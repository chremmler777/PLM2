import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { actualCostsApi } from '../../../api/actualCosts'
import { changesApi } from '../../../api/changes'
import { X } from 'lucide-react'
import {
  NUMBER_INPUT_HINT, NUMBER_INPUT_INVALID, formatCalendarDate, formatMoney, readNumberInput, todayIso,
} from '../../../lib/format'
import { apiErrorMessage } from '../../../lib/apiError'
import ConfirmDialog from '../../common/ConfirmDialog'
import { btnIcon, btnSm } from '../../common/buttonStyles'
import DateInput from '../../gantt/DateInput'
import type { ActualCost, ActualCostCategory } from '../../../types/pnl'
import { departmentLabel } from '../../../lib/departments'

const CATEGORY_LABEL: Record<ActualCostCategory, string> = {
  external: 'Supplier invoice',
  scrap: 'Scrap',
  other: 'Other',
}

/** A currency mark before or after the typed number ("$1,250", "1,250 EUR",
 *  "€ 12"): the number part is checked here, the mark is the backend's to
 *  read against the currency (actual_costs.split_amount_sign). */
const MARKED = /^(?:([A-Za-z]{3}|[€£$])\s*)?(.*?)(?:\s*([A-Za-z]{3}|[€£$]))?$/
function splitCurrencyMark(text: string): { num: string; mark: string | null } {
  const m = MARKED.exec(text.trim())
  const mark = m?.[1] ?? m?.[3] ?? null
  return m && mark ? { num: m[2], mark } : { num: text, mark: null }
}

const input = 'bg-slate-900 border border-slate-700 rounded px-2 py-1 text-xs text-slate-200'


/**
 * The actual costs that are not hours: supplier invoice lines, scrap, other.
 * Anyone with a cost role adds for any department; a department member adds
 * for their own. Whoever entered a line (or a cost role) may delete it.
 */
export default function ActualCostsPanel({ changeId, departments = [] }: {
  changeId: number
  departments?: { id: number; name: string; is_active?: boolean }[]
}) {
  const qc = useQueryClient()
  const { data } = useQuery({
    queryKey: ['actual-costs', changeId],
    queryFn: () => actualCostsApi.list(changeId),
    retry: false,
  })
  // The change's costing currency (its costing plant's): what a new line is
  // entered in and what the list is stated in. Same cache as the costing tab.
  const { data: ctx } = useQuery({
    queryKey: ['costing-context', changeId],
    queryFn: () => changesApi.costingContext(changeId),
    retry: false,
  })
  const [open, setOpen] = useState(false)
  const [category, setCategory] = useState<ActualCostCategory>('external')
  const [amount, setAmount] = useState('')
  const [costDate, setCostDate] = useState(todayIso())
  const [vendor, setVendor] = useState('')
  const [dept, setDept] = useState<number | ''>('')
  const [note, setNote] = useState('')
  // A two-currency plant (Silao: USD and MXN): the entry names its currency;
  // the P&L converts it at the change's cost sheet exchange rate.
  const [entryCur, setEntryCur] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const refresh = () => {
    qc.invalidateQueries({ queryKey: ['actual-costs', changeId] })
    qc.invalidateQueries({ queryKey: ['offer-vs-actual', changeId] })
  }
  const add = useMutation({
    mutationFn: () => actualCostsApi.add(changeId, {
      category,
      // with a currency mark the text goes as typed: the backend reads the
      // mark (and refuses one that contradicts the currency, shown below)
      amount: amountMark ? amount.trim() : amountRead.value as number,
      cost_date: costDate,
      vendor_name: vendor || null, department_id: dept === '' ? null : dept,
      note: note || null,
      ...(entryCur ? { currency: entryCur } : {}),
    }),
    onSuccess: () => {
      setAmount(''); setVendor(''); setNote(''); setError(null); setOpen(false)
      refresh()
    },
    onError: (e) => setError(apiErrorMessage(e, 'Could not save the cost')),
  })
  const remove = useMutation({
    mutationFn: (id: number) => actualCostsApi.remove(changeId, id),
    onSuccess: refresh,
  })
  const [removing, setRemoving] = useState<ActualCost | null>(null)
  // en-US like everything shown: "1,500" is fifteen hundred, "12,5" is refused.
  const { num: amountNum, mark: amountMark } = splitCurrencyMark(amount)
  const amountRead = readNumberInput(amountNum)

  if (!data) return null
  const allowed = data.writable_department_ids
  const deptOptions = allowed === null ? departments : departments.filter((d) => allowed.includes(d.id))
  const currency = data.currency ?? ctx?.currency ?? data.items.find((c) => c.currency)?.currency ?? 'EUR'
  const curOf = (c: { currency?: string | null }) => c.currency ?? currency
  const localCur = ctx?.local_currency && ctx.local_currency !== currency ? ctx.local_currency : null
  const shownCur = entryCur ?? currency
  // Never added across currencies: one total per currency.
  const totals = data.totals_by_currency && Object.keys(data.totals_by_currency).length > 0
    ? Object.entries(data.totals_by_currency)
    : [...data.items.reduce((m, c) => m.set(curOf(c), (m.get(curOf(c)) ?? 0) + c.amount), new Map<string, number>())]
  const amountOk = amountRead.value !== null && amountRead.value > 0
  const amountHint = amountRead.error === 'invalid' ? NUMBER_INPUT_INVALID
    : amountRead.error === 'ambiguous' ? NUMBER_INPUT_HINT
    : amountRead.value !== null && amountRead.value <= 0 ? 'The amount must be more than 0' : null
  // An actual cost is booked when it happened: never ahead of today.
  const future = !!costDate && costDate > todayIso()
  const dateOk = !!costDate && !future
  const deptOk = allowed === null || dept !== ''

  return (
    <div data-testid="pnl-actual-costs" className="md:col-span-3 border-t border-slate-700 pt-3">
      <div className="flex items-center gap-2">
        <span className="text-xs text-slate-400 uppercase tracking-wide">
          {data.cost_role ? 'Actual costs' : 'Actual costs of your department'}
        </span>
        <span data-testid="actual-cost-total" className="text-xs text-slate-500 tabular-nums">
          {totals.length === 0 ? formatMoney(data.total, currency)
            : totals.map(([cur, v]) => formatMoney(v, cur)).join(' · ')}
        </span>
        {data.can_write && !open && (
          <button type="button" data-testid="actual-cost-open"
            className={`ml-auto ${btnSm.secondary}`}
            onClick={() => setOpen(true)}>
            Add actual cost
          </button>
        )}
      </div>

      {open && (
        <form data-testid="actual-cost-form"
          className="mt-2 grid grid-cols-2 md:grid-cols-6 gap-2 items-end"
          onSubmit={(e) => { e.preventDefault(); if (amountOk && dateOk && deptOk) add.mutate() }}>
          <label className="flex flex-col gap-0.5 text-[11px] text-slate-400">Category
            <select className={input} value={category}
              onChange={(e) => setCategory(e.target.value as ActualCostCategory)}>
              {(Object.keys(CATEGORY_LABEL) as ActualCostCategory[]).map((c) => (
                <option key={c} value={c}>{CATEGORY_LABEL[c]}</option>
              ))}
            </select>
          </label>
          {localCur && (
            <label className="flex flex-col gap-0.5 text-[11px] text-slate-400"
              title={`Amounts in ${localCur} are converted to ${currency} at the exchange rate of the change's cost sheet version`}>
              Currency
              <select data-testid="actual-cost-currency" aria-label="Currency" className={input}
                value={shownCur} onChange={(e) => setEntryCur(e.target.value === currency ? null : e.target.value)}>
                <option value={currency}>{currency}</option>
                <option value={localCur}>{localCur}</option>
              </select>
            </label>
          )}
          <label className="flex flex-col gap-0.5 text-[11px] text-slate-400">Amount ({shownCur})
            <input aria-label="Amount" className={input} inputMode="decimal" value={amount}
              aria-invalid={amountHint ? true : undefined}
              aria-describedby={amountHint ? `actual-cost-amount-hint-${changeId}` : undefined}
              onChange={(e) => { setAmount(e.target.value); setError(null) }} />
            {amountHint && (
              <span id={`actual-cost-amount-hint-${changeId}`} data-testid="actual-cost-amount-hint"
                className="text-[11px] text-rose-300">{amountHint}</span>
            )}
          </label>
          <div className="flex flex-col gap-0.5 text-[11px] text-slate-400">
            <label htmlFor={`actual-cost-date-${changeId}`}>Date</label>
            <DateInput id={`actual-cost-date-${changeId}`} aria-label="Cost date" className={input}
              value={costDate} onChange={setCostDate} commitOnChange />
            {future && (
              <span data-testid="actual-cost-future" role="alert" className="text-[11px] text-rose-300">
                A cost cannot be dated in the future. Book it on or after the day it happened.
              </span>
            )}
          </div>
          <label className="flex flex-col gap-0.5 text-[11px] text-slate-400">Vendor
            <input aria-label="Vendor" className={input} maxLength={120} value={vendor}
              onChange={(e) => setVendor(e.target.value)} />
          </label>
          <label className="flex flex-col gap-0.5 text-[11px] text-slate-400">Department
            <select aria-label="Department" className={input} value={dept}
              onChange={(e) => setDept(e.target.value ? Number(e.target.value) : '')}>
              {allowed === null && <option value="">None</option>}
              {allowed !== null && <option value="">Choose</option>}
              {deptOptions.map((d) => <option key={d.id} value={d.id}>{departmentLabel(d)}</option>)}
            </select>
          </label>
          <label className="flex flex-col gap-0.5 text-[11px] text-slate-400 col-span-2 md:col-span-6">Note
            <input aria-label="Note" className={input} value={note} placeholder="Invoice number, what it was for"
              onChange={(e) => setNote(e.target.value)} />
          </label>
          <div className="col-span-2 md:col-span-6 flex items-center gap-2">
            <button type="submit" data-testid="actual-cost-save"
              disabled={!amountOk || !dateOk || !deptOk || add.isPending}
              className={btnSm.primary}>
              Save
            </button>
            <button type="button" className={btnSm.ghost}
              onClick={() => { setOpen(false); setError(null) }}>
              Cancel
            </button>
            {error && <span role="alert" className="text-[11px] text-rose-300">{error}</span>}
          </div>
        </form>
      )}

      {data.items.length > 0 ? (
        <ul className="mt-2 space-y-0.5">
          {data.items.map((c) => (
            <li key={c.id} data-testid={`actual-cost-${c.id}`}
              className="flex items-baseline gap-2 text-xs text-slate-300">
              <span className="text-slate-500 w-20 shrink-0 tabular-nums">{formatCalendarDate(c.cost_date)}</span>
              <span className="rounded bg-slate-700 px-1.5 text-[11px] text-slate-300">{CATEGORY_LABEL[c.category] ?? c.category}</span>
              <span className="min-w-0 flex-1 truncate">
                {[c.vendor_name, c.department_name, c.note].filter(Boolean).join(', ') || '-'}
                {c.created_by_name && <span className="text-slate-500"> ({c.created_by_name})</span>}
              </span>
              <span className="tabular-nums text-slate-100">{formatMoney(c.amount, curOf(c))}</span>
              {c.can_delete && (
                <button type="button" data-testid={`actual-cost-delete-${c.id}`}
                  aria-label={`Delete actual cost: ${CATEGORY_LABEL[c.category] ?? c.category}, ${formatMoney(c.amount, curOf(c))}, ${formatCalendarDate(c.cost_date)}`}
                  className={`${btnIcon} h-6 w-6 hover:text-rose-300`}
                  disabled={remove.isPending}
                  onClick={() => setRemoving(c)}>
                  <X aria-hidden="true" size={13} />
                </button>
              )}
            </li>
          ))}
        </ul>
      ) : (
        <p className="mt-1 text-xs text-slate-500">
          {data.cost_role ? 'No supplier invoice or other cost entered yet.'
            : 'Nothing booked to your department yet. Enter supplier invoices, scrap or other costs your department carried.'}
        </p>
      )}
      <ConfirmDialog open={removing !== null} danger data-testid="actual-cost-delete-confirm"
        title="Delete this actual cost?"
        body={removing ? `${CATEGORY_LABEL[removing.category] ?? removing.category}, ${formatMoney(removing.amount, curOf(removing))} on ${formatCalendarDate(removing.cost_date)} leaves the actual costs and the P&L.` : undefined}
        confirmLabel="Delete cost" errorFallback="Could not delete the cost"
        onConfirm={() => (removing ? remove.mutateAsync(removing.id) : undefined)}
        onClose={() => setRemoving(null)} />
    </div>
  )
}
