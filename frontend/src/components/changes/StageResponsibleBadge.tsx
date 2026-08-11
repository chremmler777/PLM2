import { t } from '../../i18n/cmLabels'
import type { ChangeStatus } from '../../types/change'

/**
 * Which role owns a change while it sits in a given stage. Only capture is
 * mapped today (Sales writes the request); the map is the extension point for
 * the remaining stages once their ownership is agreed.
 */
export const STAGE_RESPONSIBLE: Partial<Record<ChangeStatus, string>> = {
  captured: 'role.sales',
}

export function StageResponsibleBadge({ status }: { status: ChangeStatus }) {
  const key = STAGE_RESPONSIBLE[status]
  if (!key) return null
  return (
    <span data-testid="stage-responsible" title={t('responsible.label')}
      className="inline-flex items-center rounded-full bg-fuchsia-900/60 text-fuchsia-200 px-2 py-0.5 text-[11px] font-medium align-middle">
      {t(key)}
    </span>
  )
}
