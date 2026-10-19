/**
 * The release checklist: what has to be true before a change is live, each
 * point owned by a department. Members of the owner department tick it done
 * or not applicable (C7, RELEASE_V2: PM, the lead or an admin only for a
 * department with no member here, shown on its group; the backend's
 * can_answer decides); n.a. needs a note, the customer's approval a
 * reference (on a customer change its n.a. too: the customer's waiver).
 * The cycle time (Tool Engineer) is answered changed (with the new seconds)
 * or unchanged; the process-stable row (APQP) takes an optional Cm above
 * 1.67. Numbers are typed en-US ("." decimals); an unreadable number is
 * named and blocks the answer instead of being dropped. Rows answered
 * before an item left the checklist show read-only as "No longer asked".
 */
import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { changeReleaseApi } from '../../../api/changeRelease'
import type { ReleaseCheck, ReleaseCheckAnswer, ReleaseCheckStatus } from '../../../types/changeRelease'
import { fmtDate, inputCls, sectionLabel } from '../offer/offerFormat'
import { releaseKey } from './releaseKeys'
import { Check } from 'lucide-react'
import { btnSm } from '../../common/buttonStyles'
import { toastError } from '../../../lib/apiError'
import { NUMBER_INPUT_HINT, NUMBER_INPUT_INVALID, readNumberInput } from '../../../lib/format'
import { t } from '../../../i18n/cmLabels'
import { refOk as isRef } from '../../../lib/evidence'

const CHIP: Record<ReleaseCheckStatus, { label: string; on: string }> = {
  open: { label: 'Open', on: 'bg-slate-700 text-slate-100' },
  done: { label: 'Done', on: 'bg-emerald-700 text-white' },
  na: { label: 'N.a.', on: 'bg-slate-600 text-slate-100' },
}

const CM_MIN = 1.67

/** Kept as the backend keeps them: Cm to 2 decimals, seconds to 1. The
 *  limit is checked on the rounded Cm, like the backend does. */
const round = (n: number, decimals: number) => Math.round(n * 10 ** decimals) / 10 ** decimals

/** The value half of a "done" answer, per value kind. Returns null while
 *  the answer is not complete yet, or the typed number cannot be read. */
function valueAnswer(kind: ReleaseCheck['value_kind'], outcome: '' | 'changed' | 'unchanged', raw: string):
  null | Pick<ReleaseCheckAnswer, 'outcome' | 'value'> {
  const read = readNumberInput(raw)
  const num = read.value
  if (kind === 'cycle_time') {
    if (outcome === 'unchanged') return { outcome }
    if (outcome === 'changed' && num != null && round(num, 1) > 0) return { outcome, value: num }
    return null
  }
  if (kind === 'cm') {
    if (read.error) return null
    if (num == null) return {}
    return round(num, 2) > CM_MIN ? { value: num } : null
  }
  return {}
}

function CheckRow({ changeId, check, canEdit }: {
  changeId: number; check: ReleaseCheck; canEdit: boolean
}) {
  const qc = useQueryClient()
  const [editing, setEditing] = useState<null | 'done' | 'na'>(null)
  const [note, setNote] = useState('')
  const [outcome, setOutcome] = useState<'' | 'changed' | 'unchanged'>('')
  const [value, setValue] = useState('')
  const save = useMutation({
    mutationFn: (body: ReleaseCheckAnswer) =>
      changeReleaseApi.setCheck(changeId, check.key, body),
    onSuccess: () => {
      setEditing(null); setNote(''); setOutcome(''); setValue('')
      qc.invalidateQueries({ queryKey: releaseKey(changeId) })
      qc.invalidateQueries({ queryKey: ['change-my-actions', changeId] })
      qc.invalidateQueries({ queryKey: ['change', changeId] })
    },
    onError: (e: unknown) => toastError(e, 'Could not save the check'),
  })

  const pick = (s: ReleaseCheckStatus) => {
    if (s === 'open') { save.mutate({ status: 'open' }); return }
    setEditing(s); setNote(''); setOutcome(''); setValue('')
  }

  const kind = editing === 'done' ? check.value_kind ?? null : null
  const extra = kind ? valueAnswer(kind, outcome, value) : {}
  const numberUsed = (kind === 'cycle_time' && outcome === 'changed') || kind === 'cm'
  const read = readNumberInput(value)
  const numberHint = !numberUsed ? null
    : read.error === 'invalid' ? NUMBER_INPUT_INVALID
    : read.error === 'ambiguous' ? NUMBER_INPUT_HINT
    : null
  const cmLow = kind === 'cm' && read.value !== null && extra === null
  // C7: the customer's approval is a document: 'done' names it
  // R38 (R4): the measurement report, the ERP reference, the customer mail;
  // the process-stable row takes the measured Cm instead of the SPC report
  const refNeeded = editing === 'done' && !!check.needs_ref
    && !(kind === 'cm' && read.value !== null)
  // the drawing row: no 'done' while a revision has no drawing or 3D file
  const doneRefused = editing === 'done' ? check.done_refusal ?? null : null
  // ... and on a customer change 'not applicable' is the customer's waiver
  const waiverNeeded = editing === 'na' && !!check.na_needs_ref
  // the backend's reference rule (cm_rules.reference_refusal), shared
  const refOk = isRef(note)
  // A5-09: a measured row (weight, cycle time, dimensions) answers from the
  // validation measurement: 'done' needs one on file and not outside its
  // limits ('changed' cycle time aside), 'n.a.' a reason of a few words
  const measuredRow = check.measurement !== undefined
  const measuredWhy = !measuredRow || editing === null ? null
    : editing === 'na' ? (note.trim() && !refOk ? 'Say why it does not apply in a few words' : null)
    : check.measurement == null ? 'Record the measurement in validation first: this row reads it'
    : check.measurement_failed && (check.key !== 'cycle_time_tool' || outcome === 'unchanged')
      ? `The validation measurement is outside its limits (${check.measurement}): fix and retest, or a concession (Quality)`
      : null
  const naReasonOk = !measuredRow || refOk
  const canConfirm = !save.isPending && !measuredWhy && (editing === 'na'
    ? !!note.trim() && (!waiverNeeded || refOk) && naReasonOk
    : extra !== null && (!refNeeded || refOk) && !doneRefused)
  const confirmLabel = editing === 'na' ? 'Mark not applicable'
    : kind === 'cycle_time' ? (outcome === 'changed' ? 'Save new cycle time' : 'Confirm unchanged')
    : 'Mark done'
  const retired = !!check.retired

  return (
    <li data-testid={`release-check-${check.key}`}
      className={`rounded-lg border px-3 py-2 ${check.status === 'open' && !retired ? 'border-slate-700 bg-slate-900/40' : 'border-slate-800 bg-slate-900/20'}`}>
      <div className="flex flex-wrap items-center gap-3">
        <span className={`h-2 w-2 shrink-0 rounded-full ${retired ? 'bg-slate-600' : check.status === 'done' ? 'bg-emerald-400'
          : check.status === 'na' ? 'bg-slate-500' : 'bg-amber-400'}`} />
        <div className="min-w-0 flex-1">
          <div className={`text-sm ${check.status === 'open' && !retired ? 'text-slate-100' : 'text-slate-400'}`}>
            {check.label}
            {retired && ' '}
            {retired && (
              <span data-testid={`release-check-${check.key}-retired`}
                className="ml-2 rounded border border-slate-700 px-1.5 py-px text-[10px] uppercase tracking-wide text-slate-400">
                No longer asked
              </span>
            )}
          </div>
          {check.hint && <div className="text-[11px] text-sky-300/80">{check.hint}</div>}
          {check.measurement && !check.hint?.includes(check.measurement) && (
            <div data-testid={`release-check-${check.key}-measurement`}
              className={`text-[11px] ${check.measurement_failed ? 'text-rose-300' : 'text-sky-300/80'}`}>
              Validation: {check.measurement}
            </div>
          )}
          {check.status !== 'open' && (check.by_name || check.note) && (
            <div className="text-[11px] text-slate-400">
              {check.by_name}{check.at ? `, ${fmtDate(check.at)}` : ''}{check.note ? `: ${check.note}` : ''}
            </div>
          )}
        </div>
        {canEdit && !retired ? (
          <div role="radiogroup" aria-label={`Status ${check.label}`}
            className="inline-flex rounded-lg border border-slate-700 bg-slate-900 p-0.5 text-xs">
            {(['open', 'done', 'na'] as ReleaseCheckStatus[]).map((s) => (
              <button key={s} type="button" role="radio" aria-checked={check.status === s}
                data-testid={`release-check-${check.key}-${s}`}
                disabled={save.isPending}
                onClick={() => pick(s)}
                className={`rounded-md px-2 py-0.5 ${check.status === s ? CHIP[s].on : 'text-slate-400 hover:text-slate-200'}`}>
                {CHIP[s].label}
              </button>
            ))}
          </div>
        ) : (
          <span className={`rounded-md px-2 py-0.5 text-xs ${CHIP[check.status].on}`}>{CHIP[check.status].label}</span>
        )}
      </div>
      {editing && (
        <div className="mt-2 flex flex-wrap items-center gap-2 pl-5">
          {kind === 'cycle_time' && (
            <div role="radiogroup" aria-label="Cycle time"
              className="inline-flex rounded-lg border border-slate-700 bg-slate-900 p-0.5 text-xs">
              {([['unchanged', 'Unchanged'], ['changed', 'Changed']] as const).map(([o, label]) => (
                <button key={o} type="button" role="radio" aria-checked={outcome === o}
                  data-testid={`release-check-${check.key}-${o}`}
                  onClick={() => setOutcome(o)}
                  className={`rounded-md px-2 py-0.5 ${outcome === o ? 'bg-sky-700 text-white' : 'text-slate-400 hover:text-slate-200'}`}>
                  {label}
                </button>
              ))}
            </div>
          )}
          {numberUsed && (
            <label className="inline-flex items-center gap-1 text-xs text-slate-400">
              {kind === 'cm' ? 'Cm' : 'New cycle time'}
              <input type="text" inputMode="decimal"
                data-testid={`release-check-${check.key}-value`} value={value}
                onChange={(e) => setValue(e.target.value)}
                placeholder={kind === 'cm' ? 'optional' : 'required'}
                aria-invalid={cmLow || !!numberHint || undefined}
                className={`${inputCls} w-24`} />
              {kind === 'cycle_time' && 's'}
            </label>
          )}
          {numberHint && (
            <span data-testid={`release-check-${check.key}-value-hint`} className="text-[11px] text-amber-300">
              {numberHint}
            </span>
          )}
          {cmLow && <span className="text-[11px] text-amber-300">Cm must be above {CM_MIN}</span>}
          <input autoFocus={!kind} data-testid={`release-check-${check.key}-note`} value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder={waiverNeeded ? t('release.waiverRef')
              : editing === 'na' ? 'Why does this not apply? (required)'
              : refNeeded ? `${check.ref_prompt ?? 'PSW / ISIR reference or the file name of the approval'} (required)`
              : check.measurement ? `Measured in validation: ${check.measurement}` : 'Note (optional)'}
            className={`${inputCls} min-w-0 flex-1`} />
          {doneRefused && (
            <span data-testid={`release-check-${check.key}-refused`} className="text-[11px] text-amber-300">{doneRefused}</span>
          )}
          {measuredWhy && (
            <span data-testid={`release-check-${check.key}-why`} className="text-[11px] text-amber-300">{measuredWhy}</span>
          )}
          <button type="button" data-testid={`release-check-${check.key}-confirm`}
            disabled={!canConfirm}
            onClick={() => save.mutate({ status: editing, ...(note.trim() ? { note: note.trim() } : {}), ...(extra ?? {}) })}
            className={btnSm.primary}>
            {confirmLabel}
          </button>
          <button type="button" onClick={() => setEditing(null)} className="px-1 text-xs text-slate-400 hover:text-slate-200">
            Cancel
          </button>
        </div>
      )}
    </li>
  )
}

export default function ReleaseChecklist({
  changeId, checks, myDepartmentIds, canManage, editable,
}: {
  changeId: number
  checks: ReleaseCheck[]
  myDepartmentIds: number[]
  /** PM, the change lead, admin: every row. */
  canManage: boolean
  /** Only while the change is in validation. */
  editable: boolean
}) {
  const groups = new Map<string, ReleaseCheck[]>()
  for (const c of checks) {
    const k = c.department_name ?? 'Other'
    groups.set(k, [...(groups.get(k) ?? []), c])
  }
  if (checks.length === 0) {
    return <p className="text-xs text-slate-400">The checklist appears when the change reaches validation.</p>
  }
  return (
    <div className="space-y-4">
      {[...groups.entries()].map(([dept, rows]) => {
        const open = rows.filter((r) => r.status === 'open' && !r.retired).length
        const onlyRetired = rows.every((r) => r.retired)
        const runTeam = rows.some((r) => r.run_team_answers)
        const runTeamHint = rows.find((r) => r.no_member_hint)?.no_member_hint
        return (
          <div key={dept}>
            <div className="mb-1.5 flex items-center gap-2">
              <span className={sectionLabel}>{dept}</span>
              {runTeam && (
                <span data-testid={`release-run-team-${dept}`} className="text-[11px] text-slate-400">
                  {runTeamHint ?? t('release.runTeamAnswers')}
                </span>
              )}
              {onlyRetired ? (
                <span className="text-[11px] text-slate-400">earlier answers, no longer asked</span>
              ) : (
                <span className={`inline-flex items-center gap-1 text-[11px] ${open ? (editable ? 'text-amber-300' : 'text-slate-400') : 'text-emerald-400'}`}>
                  {open ? `${open} open` : <><Check aria-hidden="true" size={12} />complete</>}
                </span>
              )}
            </div>
            <ul className="space-y-1.5">
              {rows.map((c) => (
                <CheckRow key={c.key} changeId={changeId} check={c}
                  canEdit={editable && (c.can_answer ?? (canManage
                    || (c.department_id != null && myDepartmentIds.includes(c.department_id))))} />
              ))}
            </ul>
          </div>
        )
      })}
    </div>
  )
}
