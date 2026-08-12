/**
 * Stage 9 — did the change actually work?
 *
 * Implementation says the work was done. Validation says it holds: every
 * implementing department answers a fixed, small list of checks, and two of
 * them carry a number the rest of the system already assumed something about.
 * The cycle time sits next to what costing planned; the weight sits next to
 * what the Tool Engineer estimated, and the difference between the two is a
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
 */
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { changesApi } from '../../api/changes'
import { t } from '../../i18n/cmLabels'
import ReasonDialog from './ReasonDialog'
import type {
  ValidationCheck, ValidationDepartmentState, ValidationState,
} from '../../types/change'

const errDetail = (e: unknown): string | undefined =>
  (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail

const onDay = (iso?: string | null) => (iso ? new Date(iso).toLocaleDateString() : '—')

/** 12 not 12.0; 12.5 stays 12.5. */
const num = (n: number) => String(Math.round(n * 100) / 100)

/** A delta only means something with its sign on it. */
const signed = (n: number) => (n > 0 ? `+${num(n)}` : num(n))

const fieldCls =
  'bg-slate-900 border border-slate-600 rounded px-2 py-1 text-xs text-slate-100'

/** The two checks that are a measurement rather than a yes/no. */
const VALUE_CHECKS = new Set(['cycle_time', 'weight'])

const checkLabel = (key: string): string => {
  const label = t(`validation.check.${key}`)
  return label === `validation.check.${key}` ? key : label
}

/** Anything that is not an explicit pass is still owed. */
export const departmentOpenChecks = (d: ValidationDepartmentState): number =>
  d.checks.filter((c) => c.status !== 'passed').length

/**
 * Is the commercial side of validation settled? A delta of zero (or none yet)
 * needs no acknowledgement; anything else does, until Sales has given one.
 * Exported because the wait banner asks the same question of the same payload.
 */
export const weightAckOutstanding = (state?: ValidationState | null): boolean =>
  !!state && (state.weight_delta_g ?? 0) !== 0 && !state.weight_ack_at

function CheckRow({
  changeId, deptId, check, editable, mine, plannedCycleMin, weightEstimateG,
}: {
  changeId: number
  deptId: number
  check: ValidationCheck
  editable: boolean
  mine: boolean
  plannedCycleMin?: number | null
  weightEstimateG?: number | null
}) {
  const qc = useQueryClient()
  const key = String(check.check_key)
  const id = `${deptId}-${key}`
  const [failing, setFailing] = useState(false)
  const [note, setNote] = useState('')
  const [value, setValue] = useState(check.value != null ? String(check.value) : '')
  const needsValue = VALUE_CHECKS.has(key)

  const post = useMutation({
    mutationFn: (vars: { status: 'passed' | 'failed' }) => changesApi.setValidationCheck(
      changeId, {
        department_id: deptId, check_key: key, status: vars.status,
        ...(needsValue && value.trim() !== '' ? { value: Number(value) } : {}),
        ...(note.trim() !== '' ? { note: note.trim() } : {}),
      }),
    onSuccess: () => {
      setFailing(false); setNote('')
      qc.invalidateQueries({ queryKey: ['change', changeId, 'validation'] })
    },
    onError: (e: unknown) => toast.error(errDetail(e) ?? 'Could not record the check'),
  })

  const valueNumber = Number(value)
  const valueOk = value.trim() !== '' && !Number.isNaN(valueNumber) && valueNumber >= 0
  // A measurement without the measurement is not a pass; a fail without a
  // reason is not a check.
  const mayPass = !needsValue || valueOk
  const mayWrite = editable && mine

  const chip = check.status === 'passed'
    ? 'bg-emerald-900/70 text-emerald-200'
    : check.status === 'failed'
      ? 'bg-red-900/80 text-red-100'
      : 'bg-slate-700 text-slate-300'

  return (
    <li data-testid={`validation-check-${id}`}
      className="rounded border border-slate-700 bg-slate-900/40 px-2 py-1.5 space-y-1">
      <div className="flex items-center gap-2 flex-wrap">
        <span className="text-slate-200 text-sm">{checkLabel(key)}</span>
        <span data-testid={`validation-status-${id}`}
          className={`rounded px-1.5 py-0 text-[10px] leading-tight font-semibold ${chip}`}>
          {t(`validation.status.${check.status}`)}
        </span>
        {check.checked_at && (
          <span data-testid={`validation-checkedby-${id}`} className="text-xs text-slate-500">
            {t('validation.checkedBy')
              .replace('{who}', check.checked_by_name ?? '—')
              .replace('{d}', onDay(check.checked_at))}
          </span>
        )}
      </div>

      {/* Development's row says what "raised" is supposed to mean, so the box is
          not ticked against somebody's private definition of it. */}
      {key === 'revision_bump' && (
        <p data-testid={`validation-hint-${id}`} className="text-xs text-slate-500">
          {t('validation.hint.revision_bump')}
        </p>
      )}

      {/* The measurement, against what was planned. Both are shown whether or
          not this viewer may write — the assumption is the point. */}
      {key === 'cycle_time' && (
        <div className="flex items-center gap-2 flex-wrap">
          {mayWrite && (
            <input type="number" min={0} step="0.1" value={value}
              data-testid={`validation-value-${id}`} aria-label={t('validation.cycleValue')}
              placeholder={t('validation.cycleValue')}
              onChange={(e) => setValue(e.target.value)} className={`w-32 ${fieldCls}`} />
          )}
          {!mayWrite && check.value != null && (
            <span className="text-xs text-slate-200 tabular-nums">
              {num(check.value)} s
            </span>
          )}
          <span data-testid={`validation-assumption-${id}`} className="text-xs text-slate-400">
            {plannedCycleMin != null
              ? t('validation.cycleAssumption').replace('{x}', num(plannedCycleMin))
              : t('validation.cycleNoAssumption')}
          </span>
        </div>
      )}
      {key === 'weight' && (
        <div className="flex items-center gap-2 flex-wrap">
          {mayWrite && (
            <input type="number" min={0} step="1" value={value}
              data-testid={`validation-value-${id}`} aria-label={t('validation.weightValue')}
              placeholder={t('validation.weightValue')}
              onChange={(e) => setValue(e.target.value)} className={`w-32 ${fieldCls}`} />
          )}
          {!mayWrite && check.value != null && (
            <span className="text-xs text-slate-200 tabular-nums">{num(check.value)} g</span>
          )}
          <span data-testid={`validation-estimate-${id}`} className="text-xs text-slate-400">
            {weightEstimateG != null
              ? t('validation.weightEstimate').replace('{x}', num(weightEstimateG))
              : t('validation.weightNoEstimate')}
          </span>
        </div>
      )}

      {check.note && (
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
              disabled={note.trim() === '' || post.isPending}
              onClick={() => post.mutate({ status: 'failed' })}
              className="bg-red-800 hover:bg-red-700 text-white px-2.5 py-1 rounded text-xs disabled:opacity-50">
              {t('validation.fail')}
            </button>
            <button type="button" className="text-xs text-slate-400 hover:text-slate-200 px-1"
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
            className="bg-emerald-700 hover:bg-emerald-600 text-white px-2.5 py-1 rounded text-xs disabled:opacity-50">
            {t('validation.pass')}
          </button>
          <button type="button" data-testid={`validation-fail-${id}`}
            onClick={() => setFailing(true)}
            className="border border-red-800 text-red-200 hover:bg-red-950/50 px-2.5 py-1 rounded text-xs">
            {t('validation.fail')}
          </button>
        </div>
      ))}
    </li>
  )
}

function DepartmentBlock({
  changeId, dept, name, mine, editable, state,
}: {
  changeId: number
  dept: ValidationDepartmentState
  name: string
  mine: boolean
  editable: boolean
  state: ValidationState
}) {
  const open = departmentOpenChecks(dept)
  return (
    <section data-testid={`validation-block-${dept.department_id}`}
      className="rounded-lg border border-slate-700 bg-slate-800 p-3 space-y-2 text-sm">
      <div className="flex items-center gap-2 flex-wrap">
        <span className="text-slate-100 font-medium">{name}</span>
        {mine && (
          <span className="rounded bg-sky-900/70 text-sky-200 px-1.5 py-0 text-[10px] leading-tight">
            {t('costing.yourBucket')}
          </span>
        )}
        <span data-testid={`validation-open-${dept.department_id}`}
          className={`ml-auto rounded px-1.5 py-0 text-[10px] leading-tight font-medium ${
            open > 0 ? 'bg-amber-900/70 text-amber-200' : 'bg-emerald-900/70 text-emerald-200'}`}>
          {`${dept.checks.length - open}/${dept.checks.length}`}
        </span>
      </div>
      <ul className="space-y-1">
        {dept.checks.map((c) => (
          <CheckRow key={String(c.check_key)} changeId={changeId}
            deptId={dept.department_id} check={c} editable={editable} mine={mine}
            plannedCycleMin={state.planned_cycle_time_min_per_part}
            weightEstimateG={state.weight_estimate_g} />
        ))}
      </ul>
    </section>
  )
}

export default function ValidationPanel({
  changeId, status, departments, myDepartmentIds, canSeeAll,
  canAcknowledge = false, canEscalate = false,
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
}) {
  const qc = useQueryClient()
  const editable = status === 'in_validation'
  const [ackNote, setAckNote] = useState('')
  const [escalateOpen, setEscalateOpen] = useState(false)

  const { data: state } = useQuery({
    queryKey: ['change', changeId, 'validation'],
    queryFn: () => changesApi.validationState(changeId),
  })

  const ack = useMutation({
    mutationFn: () => changesApi.acknowledgeWeightDelta(changeId, ackNote),
    onSuccess: () => {
      setAckNote('')
      qc.invalidateQueries({ queryKey: ['change', changeId, 'validation'] })
    },
    onError: (e: unknown) => toast.error(errDetail(e) ?? 'Could not acknowledge the delta'),
  })

  const escalate = useMutation({
    mutationFn: (reason: string) =>
      changesApi.transition(changeId, 'in_implementation', { reason }),
    onSuccess: () => {
      setEscalateOpen(false)
      qc.invalidateQueries({ queryKey: ['change', changeId] })
      qc.invalidateQueries({ queryKey: ['change', changeId, 'validation'] })
    },
    onError: (e: unknown) => toast.error(errDetail(e) ?? 'Could not return the change'),
  })

  if (!state) return null

  const deptName = (id: number) => departments.find((d) => d.id === id)?.name ?? `#${id}`
  const all = state.departments ?? []
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
          <p data-testid="validation-readonly" className="text-xs text-slate-500 mt-0.5">
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
                .replace('{who}', state.weight_ack_by_name ?? '—')
                .replace('{d}', onDay(state.weight_ack_at))}
              {state.weight_ack_note ? ` — ${state.weight_ack_note}` : ''}
            </p>
          ) : canAcknowledge && editable ? (
            <div className="flex flex-wrap items-center gap-2 pt-0.5">
              <input type="text" value={ackNote} onChange={(e) => setAckNote(e.target.value)}
                data-testid="validation-weight-ack-note" aria-label={t('validation.ackNote')}
                placeholder={t('validation.ackNote')}
                className={`flex-1 min-w-[10rem] ${fieldCls}`} />
              <button type="button" data-testid="validation-weight-ack"
                disabled={ack.isPending} onClick={() => ack.mutate()}
                className="bg-amber-700 hover:bg-amber-600 text-white px-2.5 py-1 rounded text-xs disabled:opacity-50">
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
          editable={editable} state={state} />
      ))}

      {!canSeeAll && others > 0 && (
        <p data-testid="validation-others" className="text-xs text-slate-400 px-1 py-1">
          {t('validation.others').replace('{n}', String(others))}
        </p>
      )}

      {/* Sending the change back is a decision with a bill attached, so it is
          made in writing and nowhere else. */}
      {canEscalate && editable && (
        <button type="button" data-testid="validation-escalate"
          onClick={() => setEscalateOpen(true)}
          className="border border-amber-700 text-amber-200 hover:bg-amber-950/40 px-2.5 py-1 rounded text-xs">
          {t('validation.escalate')}
        </button>
      )}

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
