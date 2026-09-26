/**
 * Stage 9 — did the change actually work?
 *
 * Implementation says the work was done. Validation says it holds: every
 * implementing department answers a fixed, small list of checks, and two of
 * them carry a number the rest of the system already assumed something about.
 * The cycle time (measured by the Tool Engineer) sits next to what costing
 * planned; the weight sits next to what the Tool Engineer estimated, and the difference between the two is a
 * commercial event, not a footnote — a part that came out heavier than quoted
 * means the price is wrong until Sales says otherwise.
 *
 * Scoped like the costing, assessment and tracking boards: an ordinary member
 * gets their own department's block; PM, Sales, the change lead and admins see
 * every block. Writes are open only while the change sits at `in_validation`;
 * afterwards the panel is the record of what was checked and by whom.
 *
 * The one way out that is not forward: checks that did not pass send the change
 * back to implementation, with a written reason, because that move costs
 * somebody a replanned date and possibly a renegotiated price.
 *
 * A check its department no longer owes (e.g. a cycle time Manufacturing or
 * Process Engineer measured before the Tool Engineer alone measured it) stays
 * readable, marked "No longer asked", and cannot be answered or raised on.
 */
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { changesApi } from '../../api/changes'
import { validationIssuesKey } from '../../api/validationIssues'
import { t } from '../../i18n/cmLabels'
import ReasonDialog from './ReasonDialog'
import type {
  ValidationCheck, ValidationDepartmentState, ValidationState,
} from '../../types/change'
import {
  NUMBER_INPUT_HINT, NUMBER_INPUT_INVALID, formatDate, numberEditText, readNumberInput,
} from '../../lib/format'
import type { IssueOut } from '../../types/validationIssue'
import { isIssueOpen, issueCode } from '../../types/validationIssue'
import RaiseIssueDialog, { type RaisePrefill } from './validation/RaiseIssueDialog'
import { RAISE_STATUSES, useValidationIssues } from './validation/IssuesPanel'
import { toastError } from '../../lib/apiError'
import { Check, X } from 'lucide-react'
import { btnSm } from '../common/buttonStyles'

const onDay = (iso?: string | null) => formatDate(iso)

/** 12 not 12.0; 12.5 stays 12.5. */
const num = (n: number) => String(Math.round(n * 100) / 100)

/** A delta only means something with its sign on it. */
const signed = (n: number) => (n > 0 ? `+${num(n)}` : num(n))

const fieldCls =
  'bg-slate-900 border border-slate-600 rounded px-2 py-1 text-xs text-slate-100'

/** The two checks that are a measurement rather than a yes/no. */
const VALUE_CHECKS = new Set(['cycle_time', 'weight'])

/** The backend's own label first (it owns the catalog), then ours, then the key. */
const checkLabel = (key: string, given?: string | null): string => {
  if (given) return given
  const label = t(`validation.check.${key}`)
  return label === `validation.check.${key}` ? key : label
}

/** The checks still asked: a retired row is on the record, never owed. */
const liveChecks = (d: ValidationDepartmentState): ValidationDepartmentState['checks'] =>
  d.checks.filter((c) => !c.retired)

/** Anything that is not an explicit pass is still owed. */
export const departmentOpenChecks = (d: ValidationDepartmentState): number =>
  liveChecks(d).filter((c) => c.status !== 'passed').length

/**
 * Is the commercial side of validation settled? A delta of zero (or none yet)
 * needs no acknowledgement; anything else does, until Sales has given one.
 * Exported because the wait banner asks the same question of the same payload.
 */
export const weightAckOutstanding = (state?: ValidationState | null): boolean =>
  !!state && (state.weight_delta_g ?? 0) !== 0 && !state.weight_ack_at

/** The open issue raised from this failed check, if any (one per check). */
export const openIssueForCheck = (issues: IssueOut[], deptId: number, key: string): IssueOut | undefined =>
  issues.find((i) => isIssueOpen(i) && i.check_key === key
    && (i.check_department_id ?? i.department_id) === deptId)

function CheckRow({
  changeId, deptId, check, editable, mine, plannedCycleMin, weightEstimateG, openIssue, onRaise, hasCosting = true,
}: {
  changeId: number
  deptId: number
  check: ValidationCheck
  editable: boolean
  mine: boolean
  plannedCycleMin?: number | null
  weightEstimateG?: number | null
  /** The open issue this failed check already has. */
  openIssue?: IssueOut
  /** Offered on a failed check without an open issue, to those who may raise. */
  onRaise?: () => void
  /** False on a change without a costing (mother plant): no planned figure to compare with. */
  hasCosting?: boolean
}) {
  const qc = useQueryClient()
  const key = String(check.check_key)
  const id = `${deptId}-${key}`
  const [failing, setFailing] = useState(false)
  const [note, setNote] = useState('')
  const [value, setValue] = useState(numberEditText(check.value))
  const needsValue = VALUE_CHECKS.has(key)
  const retired = !!check.retired

  const post = useMutation({
    mutationFn: (vars: { status: 'passed' | 'failed' }) => changesApi.setValidationCheck(
      changeId, {
        department_id: deptId, check_key: key, status: vars.status,
        ...(needsValue && valueRead.value !== null ? { value: valueRead.value } : {}),
        ...(note.trim() !== '' ? { note: note.trim() } : {}),
      }),
    onSuccess: () => {
      setFailing(false); setNote('')
      qc.invalidateQueries({ queryKey: ['change', changeId, 'validation'] })
      qc.invalidateQueries({ queryKey: ['change-my-actions', changeId] })
      qc.invalidateQueries({ queryKey: ['change', changeId, 'release'] })
      // a re-check closes (pass) or reopens (fail) the issues linked to it
      qc.invalidateQueries({ queryKey: validationIssuesKey(changeId) })
    },
    onError: (e: unknown) => toastError(e, 'Could not record the check'),
  })

  // Read en-US like it is shown: "12,5" is refused as ambiguous, never
  // silently dropped from the answer.
  const valueRead = readNumberInput(value)
  const valueOk = valueRead.value !== null && valueRead.value >= 0
  const valueHint = !needsValue ? null
    : valueRead.error === 'invalid' ? NUMBER_INPUT_INVALID
    : valueRead.error === 'ambiguous' ? NUMBER_INPUT_HINT
    : null
  // A measurement without the measurement is not a pass; a fail without a
  // reason is not a check; a typed number nobody can read is neither.
  const mayPass = !needsValue || valueOk
  const mayFail = !valueHint
  const mayWrite = editable && mine && !retired

  const chip = check.status === 'passed'
    ? 'bg-emerald-900/70 text-emerald-200'
    : check.status === 'failed'
      ? 'bg-red-900/80 text-red-100'
      : 'bg-slate-700 text-slate-300'

  return (
    <li data-testid={`validation-check-${id}`}
      className="rounded border border-slate-700 bg-slate-900/40 px-2 py-1.5 space-y-1">
      <div className="flex items-center gap-2 flex-wrap">
        <span className={`text-sm ${retired ? 'text-slate-400' : 'text-slate-200'}`}>{checkLabel(key, check.label_en)}</span>
        {retired && (
          <span data-testid={`validation-retired-${id}`}
            className="rounded border border-slate-700 px-1.5 py-px text-[10px] uppercase tracking-wide text-slate-400">
            No longer asked
          </span>
        )}
        <span data-testid={`validation-status-${id}`}
          className={`rounded px-1.5 py-0 text-[11px] leading-tight font-semibold ${chip}`}>
          {t(`validation.status.${check.status}`)}
        </span>
        {check.checked_at && (
          <span data-testid={`validation-checkedby-${id}`} className="text-xs text-slate-400">
            {t('validation.checkedBy')
              .replace('{who}', check.checked_by_name ?? '-')
              .replace('{d}', onDay(check.checked_at))}
          </span>
        )}
        {check.status === 'failed' && openIssue && (
          <a href={`#issue-${openIssue.id}`} data-testid={`validation-issue-link-${id}`}
            onClick={(e) => {
              e.preventDefault()
              document.querySelector(`[data-testid="issue-card-${openIssue.id}"]`)?.scrollIntoView?.({ behavior: 'smooth', block: 'center' })
            }}
            className="ml-auto rounded border border-amber-800 bg-amber-950/40 px-1.5 py-0 text-[11px] leading-tight text-amber-200 hover:bg-amber-950/70">
            {issueCode(openIssue)} open
          </a>
        )}
        {check.status === 'failed' && !openIssue && onRaise && !retired && (
          <button type="button" data-testid={`validation-raise-${id}`} onClick={onRaise}
            className="ml-auto rounded border border-rose-800 px-2 py-0.5 text-[11px] text-rose-200 hover:bg-rose-950/50">
            Raise issue
          </button>
        )}
      </div>

      {/* Development's row says what "raised" is supposed to mean, so the box is
          not ticked against somebody's private definition of it. */}
      {key === 'revision_bump' && checkLabel(key, check.label_en) !== t('validation.hint.revision_bump') && (
        <p data-testid={`validation-hint-${id}`} className="text-xs text-slate-400">
          {t('validation.hint.revision_bump')}
        </p>
      )}

      {/* The measurement, against what was planned. Both are shown whether or
          not this viewer may write — the assumption is the point. */}
      {key === 'cycle_time' && (
        <div className="flex items-center gap-2 flex-wrap">
          {mayWrite && (
            <input type="text" inputMode="decimal" value={value} aria-invalid={!!valueHint || undefined}
              data-testid={`validation-value-${id}`} aria-label={t('validation.cycleValue')}
              placeholder={t('validation.cycleValue')}
              onChange={(e) => setValue(e.target.value)} className={`w-32 ${fieldCls}`} />
          )}
          {!mayWrite && check.value != null && (
            <span className="text-xs text-slate-200 tabular-nums">
              {num(check.value)} s
            </span>
          )}
          {!retired && (hasCosting || plannedCycleMin != null) && (
            <span data-testid={`validation-assumption-${id}`} className="text-xs text-slate-400">
              {plannedCycleMin != null
                ? t('validation.cycleAssumption').replace('{x}', num(plannedCycleMin))
                : t('validation.cycleNoAssumption')}
            </span>
          )}
        </div>
      )}
      {key === 'weight' && (
        <div className="flex items-center gap-2 flex-wrap">
          {mayWrite && (
            <input type="text" inputMode="decimal" value={value} aria-invalid={!!valueHint || undefined}
              data-testid={`validation-value-${id}`} aria-label={t('validation.weightValue')}
              placeholder={t('validation.weightValue')}
              onChange={(e) => setValue(e.target.value)} className={`w-32 ${fieldCls}`} />
          )}
          {!mayWrite && check.value != null && (
            <span className="text-xs text-slate-200 tabular-nums">{num(check.value)} g</span>
          )}
          {(hasCosting || weightEstimateG != null) && (
            <span data-testid={`validation-estimate-${id}`} className="text-xs text-slate-400">
              {weightEstimateG != null
                ? t('validation.weightEstimate').replace('{x}', num(weightEstimateG))
                : t('validation.weightNoEstimate')}
            </span>
          )}
        </div>
      )}

      {mayWrite && valueHint && (
        <p data-testid={`validation-value-hint-${id}`} className="text-[11px] text-amber-300">
          {valueHint}
        </p>
      )}

      {/* The note says why a check failed; once it passes the old reason is history. */}
      {check.note && check.status === 'failed' && (
        <p data-testid={`validation-note-text-${id}`} className="text-xs text-slate-300">
          {check.note}
        </p>
      )}

      {mayWrite && (failing ? (
        <div className="space-y-1">
          <textarea rows={2} value={note} onChange={(e) => setNote(e.target.value)}
            data-testid={`validation-note-${id}`} aria-label={t('validation.failNote')}
            placeholder={t('validation.failNote')} className={`w-full ${fieldCls}`} />
          {note.trim() === '' && (
            <p data-testid={`validation-note-required-${id}`} className="text-[11px] text-amber-300">
              {t('validation.failNoteRequired')}
            </p>
          )}
          <div className="flex items-center gap-2">
            <button type="button" data-testid={`validation-fail-confirm-${id}`}
              disabled={note.trim() === '' || !mayFail || post.isPending}
              onClick={() => post.mutate({ status: 'failed' })}
              className={btnSm.danger}>
              {t('validation.fail')}
            </button>
            <button type="button" className={btnSm.ghost}
              onClick={() => { setFailing(false); setNote('') }}>
              {t('common.cancel')}
            </button>
          </div>
        </div>
      ) : (
        <div className="flex items-center gap-2">
          <button type="button" data-testid={`validation-pass-${id}`}
            disabled={!mayPass || post.isPending}
            onClick={() => post.mutate({ status: 'passed' })}
            className={btnSm.secondary}>
            <Check aria-hidden="true" size={14} className="text-emerald-400" />
            {t('validation.pass')}
          </button>
          <button type="button" data-testid={`validation-fail-${id}`}
            onClick={() => setFailing(true)}
            className={btnSm.secondary}>
            <X aria-hidden="true" size={14} className="text-red-400" />
            {t('validation.fail')}
          </button>
        </div>
      ))}
    </li>
  )
}

function DepartmentBlock({
  changeId, dept, name, mine, editable, state, issues, onRaise, hasCosting,
}: {
  changeId: number
  dept: ValidationDepartmentState
  name: string
  mine: boolean
  editable: boolean
  state: ValidationState
  issues: IssueOut[]
  onRaise?: (p: RaisePrefill) => void
  hasCosting?: boolean
}) {
  const open = departmentOpenChecks(dept)
  return (
    <section data-testid={`validation-block-${dept.department_id}`}
      className="rounded-lg border border-slate-700 bg-slate-800 p-3 space-y-2 text-sm">
      <div className="flex items-center gap-2 flex-wrap">
        <span className="text-slate-100 font-medium">{name}</span>
        {mine && (
          <span className="rounded bg-sky-900/70 text-sky-200 px-1.5 py-0 text-[11px] leading-tight">
            {t('costing.yourBucket')}
          </span>
        )}
        <span data-testid={`validation-open-${dept.department_id}`}
          title={`${liveChecks(dept).length - open} of ${liveChecks(dept).length} checks passed`}
          className={`ml-auto rounded px-1.5 py-0 text-[11px] leading-tight font-medium tabular-nums ${
            open > 0 ? 'bg-amber-900/70 text-amber-200' : 'bg-emerald-900/70 text-emerald-200'}`}>
          {`${liveChecks(dept).length - open}/${liveChecks(dept).length}`}
        </span>
      </div>
      <ul className="space-y-1">
        {dept.checks.map((c) => (
          <CheckRow key={String(c.check_key)} changeId={changeId}
            deptId={dept.department_id} check={c} editable={editable} mine={mine} hasCosting={hasCosting}
            plannedCycleMin={state.planned_cycle_time_min_per_part}
            weightEstimateG={state.weight_estimate_g}
            openIssue={openIssueForCheck(issues, dept.department_id, String(c.check_key))}
            onRaise={onRaise ? () => onRaise({
              checkKey: String(c.check_key),
              checkId: (c as ValidationCheck & { id?: number | null }).id ?? null,
              checkLabel: checkLabel(String(c.check_key), c.label_en),
              departmentId: dept.department_id,
              note: c.note,
            }) : undefined} />
        ))}
      </ul>
    </section>
  )
}

export default function ValidationPanel({
  changeId, status, departments, myDepartmentIds, canSeeAll,
  canAcknowledge = false, canEscalate = false, canRaiseAny = false, hasCosting = true,
}: {
  changeId: number
  status: string
  departments: { id: number; name: string }[]
  myDepartmentIds: number[]
  /** PM, Sales, the change lead and admins see every department's block. */
  canSeeAll: boolean
  /** Sales, the change lead and admins take the weight delta into the quote. */
  canAcknowledge?: boolean
  /** PM, Sales, the change lead and admins send the change back a stage. */
  canEscalate?: boolean
  /** PM, the change lead, admin raise an issue on any failed check; members on their own. */
  canRaiseAny?: boolean
  /**
   * False on a change without a costing (a mother-plant change): the cycle
   * time and weight rows then do not say "no cycle time in the costing".
   */
  hasCosting?: boolean
}) {
  const qc = useQueryClient()
  const editable = status === 'in_validation'
  const [ackNote, setAckNote] = useState('')
  const [escalateOpen, setEscalateOpen] = useState(false)
  const [raise, setRaise] = useState<RaisePrefill | null>(null)

  const { data: state } = useQuery({
    queryKey: ['change', changeId, 'validation'],
    queryFn: () => changesApi.validationState(changeId),
  })

  const ack = useMutation({
    mutationFn: () => changesApi.acknowledgeWeightDelta(changeId, ackNote),
    onSuccess: () => {
      setAckNote('')
      qc.invalidateQueries({ queryKey: ['change', changeId, 'validation'] })
      qc.invalidateQueries({ queryKey: ['change-my-actions', changeId] })
      qc.invalidateQueries({ queryKey: ['change', changeId, 'release'] })
    },
    onError: (e: unknown) => toastError(e, 'Could not acknowledge the delta'),
  })

  const escalate = useMutation({
    mutationFn: (reason: string) =>
      changesApi.transition(changeId, 'in_implementation', { reason }),
    onSuccess: () => {
      setEscalateOpen(false)
      qc.invalidateQueries({ queryKey: ['change', changeId] })
      qc.invalidateQueries({ queryKey: ['change', changeId, 'validation'] })
      qc.invalidateQueries({ queryKey: ['change-my-actions', changeId] })
      qc.invalidateQueries({ queryKey: ['change', changeId, 'release'] })
    },
    onError: (e: unknown) => toastError(e, 'Could not return the change'),
  })

  const anyFailed = (state?.departments ?? []).some((d) => d.checks.some((c) => c.status === 'failed'))
  const { data: issues = [] } = useValidationIssues(changeId, anyFailed)
  const raiseStatus = RAISE_STATUSES.includes(status)

  if (!state) return null

  const deptName = (id: number) => departments.find((d) => d.id === id)?.name ?? `#${id}`
  const all = state.departments ?? []
  // Nothing to send back once every check has passed.
  const allPassed = all.length > 0 && all.every((d) => d.checks.length > 0
    && liveChecks(d).every((c) => c.status === 'passed'))
  const visible = canSeeAll
    ? all
    : all.filter((d) => myDepartmentIds.includes(d.department_id))
  const others = all.length - visible.length
  const delta = state.weight_delta_g ?? 0

  return (
    <section data-testid="validation-panel" className="space-y-2">
      <div>
        <span className="font-medium text-slate-100">{t('validation.title')}</span>
        <p className="text-xs text-slate-400 mt-0.5">{t('validation.intro')}</p>
        {!editable && (
          <p data-testid="validation-readonly" className="text-xs text-slate-400 mt-0.5">
            {t('validation.readOnly')}
          </p>
        )}
      </div>

      {/* The weight moved: that is a price, not a measurement. Said once, at the
          top, to everybody who can read the panel — and answered by Sales. */}
      {delta !== 0 && (
        <div data-testid="validation-weight-strip"
          className="rounded-lg border border-amber-700/60 bg-amber-950/30 px-3 py-2 space-y-1">
          <p className="text-sm text-amber-100">
            {t('validation.quoteUpdate').replace('{x}', signed(delta))}
          </p>
          {state.weight_ack_at ? (
            <p data-testid="validation-weight-acked" className="text-xs text-amber-200/80">
              {t('validation.acked')
                .replace('{who}', state.weight_ack_by_name ?? '-')
                .replace('{d}', onDay(state.weight_ack_at))}
              {state.weight_ack_note ? `: ${state.weight_ack_note}` : ''}
            </p>
          ) : canAcknowledge && editable ? (
            <div className="flex flex-wrap items-center gap-2 pt-0.5">
              <input type="text" value={ackNote} onChange={(e) => setAckNote(e.target.value)}
                data-testid="validation-weight-ack-note" aria-label={t('validation.ackNote')}
                placeholder={t('validation.ackNote')}
                className={`flex-1 min-w-[10rem] ${fieldCls}`} />
              <button type="button" data-testid="validation-weight-ack"
                disabled={ack.isPending} onClick={() => ack.mutate()}
                className={btnSm.primary}>
                {t('validation.acknowledge')}
              </button>
            </div>
          ) : null}
        </div>
      )}

      {all.length === 0 && (
        <p data-testid="validation-none" className="text-sm text-slate-400">
          {t('validation.none')}
        </p>
      )}

      {visible.map((d) => (
        <DepartmentBlock key={d.department_id} changeId={changeId} dept={d}
          name={deptName(d.department_id)}
          mine={myDepartmentIds.includes(d.department_id)}
          editable={editable} state={state} issues={issues} hasCosting={hasCosting}
          onRaise={raiseStatus && (canRaiseAny || myDepartmentIds.includes(d.department_id)) ? setRaise : undefined} />
      ))}

      {!canSeeAll && others > 0 && (
        <p data-testid="validation-others" className="text-xs text-slate-400 px-1 py-1">
          {t('validation.others').replace('{n}', String(others))}
        </p>
      )}

      {/* Sending the change back is a decision with a bill attached, so it is
          made in writing and nowhere else. */}
      {canEscalate && editable && !allPassed && (
        <button type="button" data-testid="validation-escalate"
          onClick={() => setEscalateOpen(true)}
          className={btnSm.secondary}>
          {t('validation.escalate')}
        </button>
      )}

      <RaiseIssueDialog open={!!raise} changeId={changeId} departments={departments} prefill={raise}
        onClose={() => setRaise(null)} />

      <ReasonDialog open={escalateOpen}
        title={t('validation.escalateTitle')}
        label={t('validation.escalateLabel')}
        warning={t('validation.escalateWarning')}
        submitLabel={t('validation.escalateSubmit')}
        onSubmit={(reason: string) => escalate.mutate(reason)}
        onClose={() => setEscalateOpen(false)} />
    </section>
  )
}
