import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { actualCostsApi } from '../../../api/actualCosts'
import { formatDate, formatMoney, todayIso } from '../../../lib/format'
import type { ActualCostCategory } from '../../../types/pnl'

const CATEGORY_LABEL: Record<ActualCostCategory, string> = {
  external: 'Supplier invoice',
  scrap: 'Scrap',
  other: 'Other',
}

const input = 'bg-slate-900 border border-slate-700 rounded px-2 py-1 text-xs text-slate-200'

function errorText(e: unknown): string {
  const d = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail
  if (typeof d === 'string') return d
  return 'Could not save the cost'
}

/**
 * The actual costs that are not hours: supplier invoice lines, scrap, other.
 * Anyone with a cost role adds for any department; a department member adds
 * for their own. Whoever entered a line (or a cost role) may delete it.
 */
export default function ActualCostsPanel({ changeId, departments = [] }: {
  changeId: number
  departments?: { id: number; name: string }[]
}) {
  const qc = useQueryClient()
  const { data } = useQuery({
    queryKey: ['actual-costs', changeId],
    queryFn: () => actualCostsApi.list(changeId),
    retry: false,
  })
  const [open, setOpen] = useState(false)
  const [category, setCategory] = useState<ActualCostCategory>('external')
  const [amount, setAmount] = useState('')
  const [costDate, setCostDate] = useState(todayIso())
  const [vendor, setVendor] = useState('')
  const [dept, setDept] = useState<number | ''>('')
  const [note, setNote] = useState('')
  const [error, setError] = useState<string | null>(null)

  const refresh = () => {
    qc.invalidateQueries({ queryKey: ['actual-costs', changeId] })
    qc.invalidateQueries({ queryKey: ['offer-vs-actual', changeId] })
  }
  const add = useMutation({
    mutationFn: () => actualCostsApi.add(changeId, {
      category, amount: Number(amount.replace(',', '.')), cost_date: costDate,
      vendor_name: vendor || null, department_id: dept === '' ? null : dept,
      note: note || null,
    }),
    onSuccess: () => {
      setAmount(''); setVendor(''); setNote(''); setError(null); setOpen(false)
      refresh()
    },
    onError: (e) => setError(errorText(e)),
  })
  const remove = useMutation({
    mutationFn: (id: number) => actualCostsApi.remove(changeId, id),
    onSuccess: refresh,
  })

  if (!data) return null
  const allowed = data.writable_department_ids
  const deptOptions = allowed === null ? departments : departments.filter((d) => allowed.includes(d.id))
  const amountOk = Number(amount.replace(',', '.')) > 0
  const deptOk = allowed === null || dept !== ''

  return (
    <div data-testid="pnl-actual-costs" className="md:col-span-3 border-t border-slate-700 pt-3">
      <div className="flex items-center gap-2">
        <span className="text-xs text-slate-400 uppercase tracking-wide">Actual costs</span>
        <span className="text-xs text-slate-500 tabular-nums">{formatMoney(data.total)}</span>
        {data.can_write && !open && (
          <button type="button" data-testid="actual-cost-open"
            className="ml-auto border border-slate-600 text-slate-200 hover:bg-slate-700 px-2.5 py-1 rounded-lg text-xs"
            onClick={() => setOpen(true)}>
            Add actual cost
          </button>
        )}
      </div>

      {open && (
        <form data-testid="actual-cost-form"
          className="mt-2 grid grid-cols-2 md:grid-cols-6 gap-2 items-end"
          onSubmit={(e) => { e.preventDefault(); if (amountOk && deptOk) add.mutate() }}>
          <label className="flex flex-col gap-0.5 text-[11px] text-slate-400">Category
            <select className={input} value={category}
              onChange={(e) => setCategory(e.target.value as ActualCostCategory)}>
              {(Object.keys(CATEGORY_LABEL) as ActualCostCategory[]).map((c) => (
                <option key={c} value={c}>{CATEGORY_LABEL[c]}</option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-0.5 text-[11px] text-slate-400">Amount (EUR)
            <input aria-label="Amount" className={input} inputMode="decimal" value={amount}
              onChange={(e) => setAmount(e.target.value)} />
          </label>
          <label className="flex flex-col gap-0.5 text-[11px] text-slate-400">Date
            <input aria-label="Cost date" type="date" className={input} value={costDate}
              onChange={(e) => setCostDate(e.target.value)} />
          </label>
          <label className="flex flex-col gap-0.5 text-[11px] text-slate-400">Vendor
            <input aria-label="Vendor" className={input} maxLength={120} value={vendor}
              onChange={(e) => setVendor(e.target.value)} />
          </label>
          <label className="flex flex-col gap-0.5 text-[11px] text-slate-400">Department
            <select aria-label="Department" className={input} value={dept}
              onChange={(e) => setDept(e.target.value ? Number(e.target.value) : '')}>
              {allowed === null && <option value="">None</option>}
              {allowed !== null && <option value="">Choose</option>}
              {deptOptions.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
            </select>
          </label>
          <label className="flex flex-col gap-0.5 text-[11px] text-slate-400 col-span-2 md:col-span-6">Note
            <input aria-label="Note" className={input} value={note} placeholder="Invoice number, what it was for"
              onChange={(e) => setNote(e.target.value)} />
          </label>
          <div className="col-span-2 md:col-span-6 flex items-center gap-2">
            <button type="submit" data-testid="actual-cost-save"
              disabled={!amountOk || !deptOk || add.isPending}
              className="bg-sky-600 hover:bg-sky-500 disabled:opacity-40 text-white px-3 py-1 rounded-lg text-xs">
              Save
            </button>
            <button type="button" className="text-xs text-slate-400 hover:text-slate-200"
              onClick={() => { setOpen(false); setError(null) }}>
              Cancel
            </button>
            {error && <span className="text-[11px] text-rose-300">{error}</span>}
          </div>
        </form>
      )}

      {data.items.length > 0 ? (
        <ul className="mt-2 space-y-0.5">
          {data.items.map((c) => (
            <li key={c.id} data-testid={`actual-cost-${c.id}`}
              className="flex items-baseline gap-2 text-xs text-slate-300">
              <span className="text-slate-500 w-20 shrink-0">{formatDate(c.cost_date)}</span>
              <span className="rounded bg-slate-700 px-1.5 text-[10px] text-slate-300">{CATEGORY_LABEL[c.category] ?? c.category}</span>
              <span className="min-w-0 flex-1 truncate">
                {[c.vendor_name, c.department_name, c.note].filter(Boolean).join(', ') || '-'}
                {c.created_by_name && <span className="text-slate-500"> ({c.created_by_name})</span>}
              </span>
              <span className="tabular-nums text-slate-100">{formatMoney(c.amount)}</span>
              {c.can_delete && (
                <button type="button" data-testid={`actual-cost-delete-${c.id}`}
                  className="text-[11px] text-slate-500 hover:text-rose-300"
                  disabled={remove.isPending}
                  onClick={() => { if (window.confirm('Delete this cost line?')) remove.mutate(c.id) }}>
                  Delete
                </button>
              )}
            </li>
          ))}
        </ul>
      ) : (
        <p className="mt-1 text-[11px] text-slate-500">No supplier invoice or other cost entered yet.</p>
      )}
    </div>
  )
}
