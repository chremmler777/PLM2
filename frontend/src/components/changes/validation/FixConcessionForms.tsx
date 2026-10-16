/**
 * ECR-solid §10: the two answers to a FAIL, side by side.
 *
 * FixForm: Quality's Fix task. Who fixes (process parameters / tool at
 * supplier / another department) and the retest date; the check's own
 * department retests, a pass closes the issue.
 *
 * ConcessionForm: Quality requests a concession beside the fix. A customer
 * change: the Sales owner asks the customer, Quality decides once the mail
 * is filed. An internal change: the parts are not for shipment and Quality
 * decides now, for a quantity of parts or until a date.
 */
import { useState } from 'react'
import { validationIssuesApi } from '../../../api/validationIssues'
import type { FixOwner, IssueOut } from '../../../types/validationIssue'
import { issueCode } from '../../../types/validationIssue'
import { formatCalendarDate, todayIso } from '../../../lib/format'
import DateInput from '../../gantt/DateInput'
import { inputCls } from '../offer/offerFormat'
import { FIX_OWNER_LABEL } from './issueModel'
import { useIssueMutation } from './useIssueMutation'
import { btnSm } from '../../common/buttonStyles'
import { t } from '../../../i18n/cmLabels'

const OWNERS: FixOwner[] = ['process_parameters', 'tool_at_supplier', 'other']

/** Why the fix pick cannot be saved yet, or null. */
export function fixBlocked(owner: FixOwner | null, deptId: number | null, supplier: string,
  retest: string, today: string = todayIso()): string | null {
  if (!owner) return t('fix.pickOwner')
  if (owner === 'other' && deptId == null) return t('fix.pickDepartment')
  if (owner === 'tool_at_supplier' && !supplier.trim()) return t('fix.nameSupplier')
  if (!retest) return t('fix.pickDate')
  if (retest < today) return t('fix.datePast')
  return null
}

export function FixForm({ changeId, issue, departments, onDone }: {
  changeId: number
  issue: IssueOut
  departments: { id: number; name: string }[]
  onDone: () => void
}) {
  const [owner, setOwner] = useState<FixOwner | null>(issue.fix_owner_kind ?? null)
  const [deptId, setDeptId] = useState<number | null>(issue.fix_owner_kind === 'other' ? issue.fix_department_id ?? null : null)
  const [supplier, setSupplier] = useState(issue.supplier_name ?? '')
  const [retest, setRetest] = useState(issue.retest_due ?? '')
  const save = useIssueMutation(changeId, () => validationIssuesApi.fix(changeId, issue.id, {
    owner: owner!, retest_due: retest,
    ...(owner === 'other' ? { department_id: deptId } : {}),
    ...(owner === 'tool_at_supplier' ? { supplier_name: supplier.trim() } : {}),
  }), { error: t('fix.error'), onDone })
  const blocked = fixBlocked(owner, deptId, supplier, retest)
  return (
    <div data-testid={`issue-fix-form-${issue.id}`} role="group" aria-label={t('fix.title').replace('{ref}', issueCode(issue))}
      className="space-y-2 rounded-lg border border-sky-800/70 bg-sky-950/20 p-3">
      <p className="text-xs text-slate-200">{t('fix.intro')}</p>
      <div role="radiogroup" aria-label={t('fix.who')} className="flex flex-wrap gap-1.5">
        {OWNERS.map((o) => (
          <button key={o} type="button" role="radio" aria-checked={owner === o}
            data-testid={`fix-owner-${o}`} onClick={() => setOwner(o)}
            className={`rounded-md border px-2.5 py-1 text-xs ${owner === o
              ? 'border-sky-600 bg-sky-950/40 text-sky-100' : 'border-slate-700 text-slate-300 hover:border-slate-600'}`}>
            {FIX_OWNER_LABEL[o]}
          </button>
        ))}
      </div>
      {owner === 'other' && (
        <select data-testid="fix-department" aria-label={t('fix.department')} value={deptId ?? ''}
          onChange={(e) => setDeptId(e.target.value ? Number(e.target.value) : null)}
          className={`${inputCls} w-full`}>
          <option value="">{t('fix.department')}</option>
          {departments.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
        </select>
      )}
      {owner === 'tool_at_supplier' && (
        <input data-testid="fix-supplier" value={supplier} onChange={(e) => setSupplier(e.target.value)}
          aria-label={t('fix.supplier')} placeholder={t('fix.supplier')} className={`${inputCls} w-full`} />
      )}
      <div className="flex flex-wrap items-center gap-2 text-xs text-slate-400">
        <span>{t('fix.retest')}</span>
        <span data-testid="fix-retest" className="inline-block w-36">
          <DateInput aria-label={t('fix.retest')} value={retest} min={todayIso()} commitOnChange
            onChange={setRetest} className={`${inputCls} w-full`} />
        </span>
        {weekendRetest(retest) && (
          <span data-testid="fix-retest-weekend" className="text-[11px] text-amber-300">
            Not a working day: the retest moves to {formatCalendarDate(weekendRetest(retest)!)}
          </span>
        )}
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <button type="button" data-testid="fix-submit" disabled={!!blocked || save.isPending}
          onClick={() => save.mutate(undefined)} className={btnSm.primary}>
          {t('fix.submit')}
        </button>
        <button type="button" onClick={onDone} className={btnSm.ghost}>{t('common.cancel')}</button>
        {blocked && <span data-testid="fix-blocked" className="text-[11px] text-slate-400">{blocked}</span>}
      </div>
    </div>
  )
}

/** Why the concession request cannot be sent yet, or null. */
/** A5-11: a weekend retest moves to the next Monday (the backend does the
 *  same); the form says so before it is sent. */
export function weekendRetest(iso: string): string | null {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(iso)) return null
  const d = new Date(`${iso}T12:00:00Z`)
  const wd = d.getUTCDay()
  if (wd !== 0 && wd !== 6) return null
  d.setUTCDate(d.getUTCDate() + (wd === 6 ? 2 : 1))
  return d.toISOString().slice(0, 10)
}

export function concessionBlocked(internal: boolean, note: string, notForShipment: boolean,
  qty: string, until: string, today: string = todayIso()): string | null {
  if (note.trim().length < 5) return t('concession.noteNeeded')
  if (!internal) return null
  if (!notForShipment) return t('concession.notForShipmentNeeded')
  if (!qty.trim() && !until) return t('concession.boundNeeded')
  if (qty.trim() && !(Number(qty) >= 1 && Number.isInteger(Number(qty)))) return t('concession.qtyWhole')
  if (until && until < today) return t('concession.untilPast')
  return null
}

export function ConcessionForm({ changeId, issue, customerRelevant, onDone }: {
  changeId: number
  issue: IssueOut
  /** False: an internal change, "not for shipment", Quality decides now. */
  customerRelevant: boolean
  onDone: () => void
}) {
  const internal = !customerRelevant
  const [note, setNote] = useState('')
  const [nfs, setNfs] = useState(false)
  const [qty, setQty] = useState('')
  const [until, setUntil] = useState('')
  const save = useIssueMutation(changeId, () => validationIssuesApi.requestConcession(changeId, issue.id, {
    note: note.trim(),
    ...(internal ? {
      not_for_shipment: nfs,
      ...(qty.trim() ? { quantity: Number(qty) } : {}),
      ...(until ? { concession_until: until } : {}),
    } : {}),
  }), { error: t('concession.error'), onDone })
  const blocked = concessionBlocked(internal, note, nfs, qty, until)
  return (
    <div data-testid={`issue-concession-form-${issue.id}`} role="group"
      aria-label={t('concession.requestTitle').replace('{ref}', issueCode(issue))}
      className="space-y-2 rounded-lg border border-emerald-900/70 bg-emerald-950/10 p-3">
      <p className="text-xs text-slate-200">{t(internal ? 'concession.introInternal' : 'concession.introCustomer')}</p>
      <textarea data-testid="concession-note" rows={2} value={note} onChange={(e) => setNote(e.target.value)}
        aria-label={t('concession.note')} placeholder={t('concession.note')} className={`${inputCls} w-full`} />
      {internal && (
        <>
          <label className="flex items-center gap-2 text-xs text-slate-200">
            <input type="checkbox" data-testid="concession-nfs" checked={nfs} onChange={(e) => setNfs(e.target.checked)} />
            {t('concession.notForShipment')}
          </label>
          <ConcessionBounds qty={qty} setQty={setQty} until={until} setUntil={setUntil} />
        </>
      )}
      <div className="flex flex-wrap items-center gap-2">
        <button type="button" data-testid="concession-submit" disabled={!!blocked || save.isPending}
          onClick={() => save.mutate(undefined)} className={btnSm.primary}>
          {t(internal ? 'concession.acceptInternal' : 'concession.request')}
        </button>
        <button type="button" onClick={onDone} className={btnSm.ghost}>{t('common.cancel')}</button>
        {blocked && <span data-testid="concession-blocked" className="text-[11px] text-slate-400">{blocked}</span>}
      </div>
    </div>
  )
}

/** "For [n] parts or until [date]": a concession always has a bound. */
export function ConcessionBounds({ qty, setQty, until, setUntil }: {
  qty: string; setQty: (v: string) => void; until: string; setUntil: (v: string) => void
}) {
  return (
    <div className="flex flex-wrap items-center gap-2 text-xs text-slate-400">
      <span>{t('concession.for')}</span>
      <input data-testid="concession-qty" inputMode="numeric" value={qty} onChange={(e) => setQty(e.target.value)}
        aria-label={t('concession.qty')} placeholder={t('concession.qty')} className={`${inputCls} w-24`} />
      <span>{t('concession.orUntil')}</span>
      <span data-testid="concession-until" className="inline-block w-36">
        <DateInput aria-label={t('concession.until')} value={until} min={todayIso()} commitOnChange
          onChange={setUntil} className={`${inputCls} w-full`} />
      </span>
    </div>
  )
}
