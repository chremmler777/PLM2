import type { ChangeStatus } from '../../types/change'
import { STATUS_LABELS, STATUS_PILL, OFF_PATH_STATUSES, branchStepOrder, stepperLabel } from '../../lib/changeStatus'
import { t } from '../../i18n/cmLabels'
import { StageResponsibleBadge } from './StageResponsibleBadge'

/** A change that stopped: how it ended and in which stage (spec §16 P1 7). */
export interface StepperEnd {
  kind: 'rejected' | 'cancelled'
  /** The stage it was in when it stopped; null when unknown. */
  stoppedAt: ChangeStatus | null
  /** Rejected and then closed (the letter went out). */
  closed?: boolean
}

export default function LifecycleStepper({
  status,
  customerRelevant,
  origin,
  end = null,
}: {
  status: ChangeStatus
  customerRelevant?: boolean
  /** 'mother_plant' shows only the stages that side track uses (spec §14). */
  origin?: string | null
  /** Rejected (also after closing) and cancelled are end states of their own. */
  end?: StepperEnd | null
}) {
  const offPath = OFF_PATH_STATUSES.includes(status)
  const order = branchStepOrder(customerRelevant, origin)
  // A stopped change reads up to where it stopped; everything after is greyed
  // and the path ends in a red pill, never in "Closed".
  const stopIdx = end?.stoppedAt ? order.indexOf(end.stoppedAt) : -1
  const idx = end ? stopIdx : order.indexOf(status)
  const visible = end ? order.filter((s) => s !== 'closed') : order
  const endLabel = end
    ? (end.kind === 'cancelled' ? t('stepper.endCancelled')
      : end.closed ? t('stepper.endRejectedClosed') : t('stepper.endRejected'))
    : null
  return (
    <div className="flex items-center gap-1 text-xs flex-wrap" data-testid="lifecycle-stepper">
      {offPath && !end && (
        <span className={`px-2 py-1 rounded-full font-semibold mr-2 ${STATUS_PILL[status]}`}>
          {STATUS_LABELS[status]}
        </span>
      )}
      {visible.map((s, i) => {
        // At capture, the scoping node says who takes over next rather than
        // repeating its generic hint.
        const hint = status === 'captured' && s === 'scoping'
          ? t('tab.scopingHandoff')
          // Mother plant: no meeting decides, the PM informs the team.
          : origin === 'mother_plant' && s === 'scoping' ? 'Lock the impact, inform the team'
          : t(`stepper.hint.${s}`)
        const stoppedHere = !!end && i === stopIdx
        const cls = end
          ? (i < stopIdx ? 'bg-emerald-900/60 text-emerald-200/80'
            : stoppedHere ? 'bg-red-950 text-red-200 ring-1 ring-red-700'
            : 'bg-slate-800/60 text-slate-600')
          : offPath ? 'bg-slate-800 text-slate-600'
          : i < idx ? 'bg-emerald-900 text-emerald-200'
          : i === idx ? 'bg-sky-600 text-white'
          : 'bg-slate-800 text-slate-500'
        return (
          <div key={s} className="flex items-center gap-1">
            <div className="flex flex-col items-center">
              <span title={hint} data-testid={`step-${s}`}
                className={`px-2 py-1 rounded-full ${cls}`}>{stepperLabel(s)}</span>
              {/* Who owns the stage, shown on the stage node itself. */}
              <StageResponsibleBadge status={s} />
              {!offPath && !end && i === idx && (
                <span className="text-[10px] text-slate-400">{hint}</span>
              )}
              {stoppedHere && (
                <span data-testid="stepper-stopped-at" className="text-[10px] text-red-300">
                  {t('stepper.stoppedHere')}
                </span>
              )}
            </div>
            {(i < visible.length - 1 || end) && <span className="text-slate-600">→</span>}
          </div>
        )
      })}
      {end && (
        <span data-testid="stepper-end"
          className="px-2.5 py-1 rounded-full font-semibold bg-red-900 text-red-100">
          {endLabel}
          {end.stoppedAt && (
            <span className="ml-1 font-normal text-red-200/80">
              {t('stepper.stoppedAt').replace('{x}', STATUS_LABELS[end.stoppedAt])}
            </span>
          )}
        </span>
      )}
    </div>
  )
}
