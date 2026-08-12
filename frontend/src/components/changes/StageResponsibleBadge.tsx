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
  // The go/no-go at approval is the customer's — the badge keeps every
  // stage on the path owned.
  approved: 'role.customer',
  in_implementation: 'role.team',
  in_validation: 'role.team',
  released: 'role.pmShort',
}

export function StageResponsibleBadge({ status }: { status: ChangeStatus }) {
  const key = STAGE_RESPONSIBLE[status]
  if (!key) return null
  return (
    <span data-testid="stage-responsible" title={t('responsible.label')}
      className="inline-flex items-center rounded bg-fuchsia-900/60 text-fuchsia-200 px-1 py-0 text-[10px] leading-tight font-medium align-middle">
      {t(key)}
    </span>
  )
}
