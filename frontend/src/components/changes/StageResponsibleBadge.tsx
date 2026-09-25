import { t } from '../../i18n/cmLabels'
import type { ChangeStatus } from '../../types/change'

/**
 * Which role owns a change while it sits in a given stage (agreed 2026-08-12):
 * Sales writes the request and owns everything quote-shaped — creating it,
 * and at `quoted` the fork to rejection, negotiation or go. Assessment,
 * costing, implementation and validation belong to the team; release is PM's
 * end responsibility. Closed states are just closed — no badge.
 */
export const STAGE_RESPONSIBLE: Partial<Record<ChangeStatus, string>> = {
  captured: 'role.sales',
  scoping: 'role.pmShort',
  in_assessment: 'role.team',
  costing: 'role.team',
  quoting: 'role.sales',
  quoted: 'role.sales',
  // Once approved the open work is the detailed timing: every responsible
  // team confirms its part of the plan (spec 2026-09-25).
  approved: 'role.team',
  in_implementation: 'role.team',
  in_validation: 'role.team',
  released: 'role.pmShort',
}

/**
 * The engineering review (origin engineering_review, spec §17) is
 * Development's light track: it comes from the intake triage, Development
 * locks the impact and collects the answers, and the release is automatic
 * once every department answered "no impact".
 */
export const REVIEW_STAGE_RESPONSIBLE: Partial<Record<ChangeStatus, string>> = {
  captured: 'role.developmentIntake',
  scoping: 'role.development',
  released: 'role.development',
}

export function stageResponsibleKey(status: ChangeStatus, origin?: string | null): string | undefined {
  return (origin === 'engineering_review' ? REVIEW_STAGE_RESPONSIBLE : STAGE_RESPONSIBLE)[status]
}

export function StageResponsibleBadge({ status, origin }: { status: ChangeStatus; origin?: string | null }) {
  const key = stageResponsibleKey(status, origin)
  if (!key) return null
  return (
    <span data-testid="stage-responsible" title={`${t('responsible.label')}: ${t(key)}`}
      className="inline-flex items-center rounded bg-fuchsia-900/60 text-fuchsia-200 px-1.5 py-px text-[11px] leading-tight font-medium align-middle">
      <span className="sr-only">{t('responsible.label')}: </span>{t(key)}
    </span>
  )
}
