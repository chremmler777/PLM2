import { Check, ChevronRight } from 'lucide-react'
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

/**
 * The change's path, quiet by default: past stages are a check and a muted
 * name, the current stage is the one filled pill (with its owner and a
 * plain-language hint), future stages are plain text.
 */
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
  // A closed change finished its path: every stage, Closed included, is done.
  const allDone = !end && status === 'closed'
  const endLabel = end
    ? (end.kind === 'cancelled' ? t('stepper.endCancelled')
      : end.closed ? t('stepper.endRejectedClosed') : t('stepper.endRejected'))
    : null
  return (
    <ol className={`flex flex-wrap items-center gap-x-0.5 gap-y-2 text-xs ${
      !offPath && !end && !allDone ? 'pb-5' : ''}`} data-testid="lifecycle-stepper"
      aria-label="Lifecycle">
      {offPath && !end && (
        <li className={`px-2 py-1 rounded-full font-semibold mr-2 ${STATUS_PILL[status]}`}>
          {STATUS_LABELS[status]}
        </li>
      )}
      {visible.map((s, i) => {
        // At capture, the scoping node says who takes over next rather than
        // repeating its generic hint.
        const hint = status === 'captured' && s === 'scoping'
          ? t('tab.scopingHandoff')
          // Mother plant: no meeting decides, the PM informs the team.
          : origin === 'mother_plant' && s === 'scoping' ? 'Lock the impact, inform the team'
          // Engineering review (spec §17): lock the impact, departments answer.
          : origin === 'engineering_review' && s === 'scoping' ? 'Lock the impact, departments answer'
          : origin === 'engineering_review' && s === 'released' ? 'Every answer "no impact": index active'
          : t(`stepper.hint.${s}`)
        const stoppedHere = !!end && i === stopIdx
        const current = !offPath && !end && !allDone && i === idx
        const past = end ? i < stopIdx : !offPath && (allDone || i < idx)
        const cls = end
          ? (past ? 'text-emerald-300/80'
            : stoppedHere ? 'bg-red-950 text-red-200 ring-1 ring-red-700 rounded-full'
            : 'text-slate-600')
          : offPath ? 'text-slate-600'
          : past ? 'text-emerald-300'
          : current ? 'bg-sky-500/15 text-sky-100 ring-1 ring-sky-500/60 font-semibold rounded-full'
          : 'text-slate-500'
        const label = origin === 'engineering_review' && s === 'scoping' ? 'Impact and review' : stepperLabel(s)
        return (
          <li key={s} className="flex items-center gap-0.5" aria-current={current ? 'step' : undefined}>
            <div className="relative flex items-center gap-1">
              <span title={hint} data-testid={`step-${s}`}
                className={`inline-flex items-center gap-1 whitespace-nowrap px-1.5 py-1 ${current ? 'px-2.5' : ''} ${cls}`}>
                {past && <Check aria-hidden="true" size={12} strokeWidth={2.5} className="shrink-0" />}
                {label}
              </span>
              {/* Who owns the stage: only on the stage that is running now. */}
              {current && <StageResponsibleBadge status={s} origin={origin} />}
              {/* The hint hangs under the pill so it never widens the path. */}
              {current && (
                <span className="absolute left-1/2 top-full mt-1 -translate-x-1/2 whitespace-nowrap text-[11px] text-slate-400">{hint}</span>
              )}
              {stoppedHere && (
                <span data-testid="stepper-stopped-at" className="whitespace-nowrap text-[11px] text-red-300">
                  {t('stepper.stoppedHere')}
                </span>
              )}
            </div>
            {(i < visible.length - 1 || end) && (
              <ChevronRight aria-hidden="true" size={13} className="shrink-0 text-slate-600" />
            )}
          </li>
        )
      })}
      {end && (
        <li data-testid="stepper-end"
          className="px-2.5 py-1 rounded-full font-semibold bg-red-900 text-red-100">
          {endLabel}
          {end.stoppedAt && (
            <span className="ml-1 font-normal text-red-200/80">
              {t('stepper.stoppedAt').replace('{x}', STATUS_LABELS[end.stoppedAt])}
            </span>
          )}
        </li>
      )}
    </ol>
  )
}
