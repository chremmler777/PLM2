import { t } from '../../i18n/cmLabels'
import type { ChangeStatus } from '../../types/change'

/**
 * Which role owns a change while it sits in a given stage: Sales writes the
 * request, project management runs the scoping. The badge is chip-sized, so the
 * map points at short labels ('PM', later 'Team') rather than the full role
 * names. It is the extension point for the remaining stages once their
 * ownership is agreed.
 */
export const STAGE_RESPONSIBLE: Partial<Record<ChangeStatus, string>> = {
  captured: 'role.sales',
  scoping: 'role.pmShort',
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
