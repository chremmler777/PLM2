/**
 * ECR-solid §2 capture and the §3 urgent proceed, on the change.
 *
 * - UrgentFields: an urgent change names its need-by date, a reason pick and
 *   the evidence (StartChangeModal, PriorityEditor).
 * - NeedByLine: the header line "Urgent · Need-by 24 Oct, 8 wd left, now:
 *   Scoping" (plus what the proceed said about it).
 * - ProblemTargetEditor: an internal change says what is wrong today (a
 *   number with its unit) and the target.
 * - NeedByCheck: the proceed dialog's "Need-by realistic?" (urgent only).
 * - NeedByTellCard: Sales tells the customer: new date or start at risk.
 */
import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { btnSm } from '../common/buttonStyles'
import { toastError } from '../../lib/apiError'
import { changesApi } from '../../api/changes'
import { t } from '../../i18n/cmLabels'
import { formatDate } from '../../lib/format'
import { STATUS_LABELS } from '../../lib/changeStatus'
import DateInput from '../gantt/DateInput'
import type { Attachment, ChangeRequest, ChangeStatus } from '../../types/change'

const input = 'bg-slate-900 border border-slate-600 rounded px-2 py-1 text-xs text-slate-100'
export const URGENT_REASONS = ['line_stop', 'safety', 'quality_escape', 'launch_date', 'customer_demand', 'other'] as const

/** A reference that names something (>= 5 characters, not "ok"/"tbd"). */
export const okRef = (v: string) => v.trim().length >= 5 && !['ok', 'tbd', 'n/a', 'na', 'done'].includes(v.trim().toLowerCase())

/** Our own customer or internal change (not a mother-plant one, not a review). */
export const plainChange = (c: Pick<ChangeRequest, 'origin'>) =>
  c.origin !== 'mother_plant' && c.origin !== 'engineering_review'

export interface UrgentDraft { needBy: string; reason: string; evidence: string }
export const emptyUrgent: UrgentDraft = { needBy: '', reason: '', evidence: '' }
export const urgentMissing = (d: UrgentDraft): string[] => [
  ...(d.needBy ? [] : [t('next.item.need_by')]),
  ...(d.reason ? [] : [t('urgent.missingReason')]),
  ...(okRef(d.evidence) ? [] : [t('urgent.missingEvidence')]),
]

export function UrgentFields({ value, onChange, idPrefix = 'urgent' }: {
  value: UrgentDraft; onChange: (v: UrgentDraft) => void; idPrefix?: string
}) {
  return (
    <div className="grid gap-2 sm:grid-cols-3" data-testid="urgent-fields">
      <label className="text-xs text-slate-300">
        {t('next.item.need_by')}
        <DateInput id={`${idPrefix}-need-by`} aria-label={t('next.item.need_by')} value={value.needBy}
          onChange={(v) => onChange({ ...value, needBy: v })} commitOnChange
          className={`${input} mt-1 w-full`} />
      </label>
      <label className="text-xs text-slate-300">
        {t('urgent.reasonPick')}
        <select value={value.reason} data-testid={`${idPrefix}-reason`}
          onChange={(e) => onChange({ ...value, reason: e.target.value })} className={`${input} mt-1 w-full`}>
          <option value="">{t('urgent.reasonPick')}…</option>
          {URGENT_REASONS.map((r) => <option key={r} value={r}>{t(`urgent.reason.${r}`)}</option>)}
        </select>
      </label>
      <label className="text-xs text-slate-300">
        {t('urgent.evidence')}
        <input value={value.evidence} data-testid={`${idPrefix}-evidence`}
          placeholder={t('urgent.evidencePlaceholder')}
          onChange={(e) => onChange({ ...value, evidence: e.target.value })} className={`${input} mt-1 w-full`} />
      </label>
    </div>
  )
}

/** Working days from today to `iso` (Mon-Fri); negative when past. */
export function workingDaysLeft(iso: string, now = new Date()): number {
  const end = new Date(iso)
  const a = new Date(now.getFullYear(), now.getMonth(), now.getDate())
  const b = new Date(end.getFullYear(), end.getMonth(), end.getDate())
  const sign = b >= a ? 1 : -1
  let n = 0
  const d = new Date(a)
  while (sign > 0 ? d < b : d > b) {
    d.setDate(d.getDate() + sign)
    if (d.getDay() !== 0 && d.getDay() !== 6) n += sign
  }
  return n
}

export function NeedByLine({ change }: { change: ChangeRequest }) {
  if (change.priority !== 'critical' || !change.scoping_v2 || !plainChange(change)) return null
  const status = STATUS_LABELS[change.status as ChangeStatus] ?? change.status
  const due = change.release_due_date
  const left = due ? workingDaysLeft(due) : null
  return (
    <p data-testid="need-by-line" className="text-xs font-medium text-red-200">
      {t('urgent.line')}
      {due ? ` · ${t('urgent.needBy').replace('{d}', formatDate(due))
        .replace('{n}', String(left))}` : ` · ${t('urgent.noNeedBy')}`}
      {` · ${t('urgent.now').replace('{s}', status)}`}
      {change.need_by_check && change.need_by_check !== 'yes' && (
        <span className="text-amber-300">
          {' · '}{change.need_by_check === 'at_risk' ? t('urgent.checkAtRisk')
            : t('urgent.checkNo').replace('{d}', formatDate(change.need_by_proposed))}
          {change.need_by_told_at ? ` (${t('urgent.told')})` : ''}
        </span>
      )}
    </p>
  )
}

export function ProblemTargetEditor({ change, canEdit }: { change: ChangeRequest; canEdit: boolean }) {
  const qc = useQueryClient()
  const [value, setValue] = useState(change.problem_value != null ? String(change.problem_value) : '')
  const [unit, setUnit] = useState(change.problem_unit ?? '')
  const [target, setTarget] = useState(change.target_value != null ? String(change.target_value) : '')
  const save = useMutation({
    mutationFn: () => changesApi.update(change.id, {
      problem_value: Number(value), problem_unit: unit.trim(), target_value: Number(target) }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['change', change.id] }) },
    onError: (e: unknown) => { toastError(e, 'Could not save the problem and target') },
  })
  if (change.customer_relevant || !plainChange(change) || !change.scoping_v2) return null
  const editable = canEdit && (change.status === 'captured' || change.status === 'scoping')
  const isNum = (v: string) => v.trim() !== '' && !Number.isNaN(Number(v))
  if (!editable) {
    return (
      <p data-testid="problem-target">
        <span className="text-slate-400">{t('problem.label')}:</span>{' '}
        {change.problem_value != null
          ? `${change.problem_value} ${change.problem_unit ?? ''} → ${t('problem.target')} ${change.target_value ?? '-'} ${change.problem_unit ?? ''}`
          : '-'}
      </p>
    )
  }
  const ready = isNum(value) && unit.trim() !== '' && isNum(target)
  return (
    <div className="flex flex-wrap items-center gap-2 text-xs" data-testid="problem-target-editor">
      <span className="text-slate-400 text-sm">{t('problem.label')}:</span>
      <input value={value} onChange={(e) => setValue(e.target.value)} inputMode="decimal"
        aria-label={t('problem.value')} placeholder={t('problem.value')} data-testid="problem-value"
        className={`${input} w-24`} />
      <input value={unit} onChange={(e) => setUnit(e.target.value)} aria-label={t('problem.unit')}
        placeholder={t('problem.unit')} data-testid="problem-unit" className={`${input} w-24`} />
      <span className="text-slate-400">→ {t('problem.target')}</span>
      <input value={target} onChange={(e) => setTarget(e.target.value)} inputMode="decimal"
        aria-label={t('problem.target')} placeholder={t('problem.target')} data-testid="problem-target-value"
        className={`${input} w-24`} />
      <button type="button" className={btnSm.primary} data-testid="problem-save"
        disabled={!ready || save.isPending} onClick={() => save.mutate()}>{t('followup.save')}</button>
    </div>
  )
}

export interface NeedByAnswer { check: '' | 'yes' | 'at_risk' | 'no'; proposed: string }

/** The proceed dialog's question for an urgent change; nothing preselected. */
export function NeedByCheck({ change, value, onChange, customer = !!change.customer_relevant }: {
  change: ChangeRequest; value: NeedByAnswer; onChange: (v: NeedByAnswer) => void
  /** The change goes on as a customer change: start at risk (a customer
   *  go-ahead, §7a) and Sales' "Tell customer" exist only then. */
  customer?: boolean
}) {
  const options = customer ? (['yes', 'at_risk', 'no'] as const) : (['yes', 'no'] as const)
  return (
    <fieldset data-testid="need-by-check" className="mt-3 space-y-1 text-xs">
      <legend className="text-sm text-slate-200">
        {t('urgent.realistic').replace('{d}', formatDate(change.release_due_date))}
      </legend>
      <div className="flex flex-wrap gap-3">
        {options.map((v) => (
          <label key={v} className="flex items-center gap-1.5 cursor-pointer text-slate-200">
            <input type="radio" name="need-by-check" checked={value.check === v}
              data-testid={`need-by-${v}`} onChange={() => onChange({ ...value, check: v })} />
            {t(`urgent.realistic.${v}`)}
          </label>
        ))}
      </div>
      {value.check === 'no' && (
        <DateInput value={value.proposed} onChange={(v) => onChange({ ...value, proposed: v })}
          aria-label={t('urgent.proposed')} className={`${input} w-36`} commitOnChange />
      )}
      {value.check !== '' && value.check !== 'yes' && (
        <p className="text-[11px] text-amber-300/90">
          {t(customer ? 'urgent.salesTells' : 'urgent.leadTold')}
        </p>
      )}
    </fieldset>
  )
}

/** An urgent change of ours under SCOPING_V2: the need-by rules apply. */
export const isUrgentV2 = (change: ChangeRequest) =>
  change.priority === 'critical' && !!change.scoping_v2 && plainChange(change)

export const needByHold = (change: ChangeRequest, v: NeedByAnswer): string | undefined => {
  if (!isUrgentV2(change)) return undefined
  if (v.check === '') return t('urgent.answerFirst')
  if (v.check === 'no' && !v.proposed) return t('urgent.proposeFirst')
  return undefined
}

export function NeedByTellCard({ change, isSales, attachments }: {
  change: ChangeRequest; isSales: boolean; attachments: Attachment[]
}) {
  const qc = useQueryClient()
  const [ref, setRef] = useState('')
  const [mailId, setMailId] = useState<number | ''>('')
  const save = useMutation({
    mutationFn: () => changesApi.needByTell(change.id, mailId !== '' ? { mail_id: mailId } : { ref: ref.trim() }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['change', change.id] })
      qc.invalidateQueries({ queryKey: ['change-my-tasks'] })
    },
    onError: (e: unknown) => { toastError(e, 'Could not record it') },
  })
  if (!change.scoping_v2 || !change.need_by_check || change.need_by_check === 'yes') return null
  const mails = attachments.filter((a) => a.kind === 'customer_email')
    .sort((a, b) => b.created_at.localeCompare(a.created_at))
  const what = change.need_by_check === 'at_risk' ? t('urgent.checkAtRisk')
    : t('urgent.checkNo').replace('{d}', formatDate(change.need_by_proposed))
  return (
    <div data-testid="need-by-tell"
      className={`rounded-lg border p-3 space-y-2 ${change.need_by_told_at ? 'border-slate-700 bg-slate-800/40'
        : 'border-amber-700/60 bg-amber-950/20'}`}>
      <p className="text-sm font-medium text-slate-100">{t('urgent.tellTitle')}</p>
      <p className="text-xs text-slate-300">{what}</p>
      {change.need_by_told_at ? (
        <p className="text-xs text-slate-400">{t('urgent.toldRef').replace('{r}', change.need_by_told_ref ?? '-')}</p>
      ) : !isSales ? (
        <p className="text-[11px] text-slate-500">
          {t('urgent.salesOwes').replace('{x}', change.sales_owner_name ?? 'Sales')}
        </p>
      ) : (
        <div className="flex flex-wrap gap-2 text-xs">
          {mails.length > 0 && (
            <select value={mailId} aria-label={t('answer.mail')} className={`${input} max-w-[18rem]`}
              onChange={(e) => setMailId(e.target.value ? Number(e.target.value) : '')}>
              <option value="">{t('answer.mailPick')}</option>
              {mails.map((m) => <option key={m.id} value={m.id}>{m.filename}</option>)}
            </select>
          )}
          {mailId === '' && (
            <input value={ref} onChange={(e) => setRef(e.target.value)} data-testid="need-by-tell-ref"
              aria-label={t('answer.ref')} placeholder={t('answer.refPlaceholder')}
              className={`${input} flex-1 min-w-[12rem]`} />
          )}
          <button type="button" className={btnSm.primary} data-testid="need-by-tell-save"
            disabled={(mailId === '' && !okRef(ref)) || save.isPending} onClick={() => save.mutate()}>
            {t('urgent.toldSave')}
          </button>
        </div>
      )}
    </div>
  )
}
