/**
 * "Removal requested, awaiting decision": a routing deviation asks to take
 * this department off the routing. The row stays (still owed, every gate
 * keeps waiting on it) until the lead decides; see
 * ChangeRoutingService.pending_removal_ids.
 */
import { Hourglass } from 'lucide-react'
import { t } from '../../i18n/cmLabels'

export default function PendingRemovalChip({ testId }: { testId?: string }) {
  return (
    <span data-testid={testId}
      className="inline-flex items-center gap-1 rounded bg-amber-900/70 px-1.5 py-0 text-[11px] leading-tight font-medium text-amber-200 flex-shrink-0">
      <Hourglass aria-hidden="true" size={11} />
      {t('routingDev.removalPending')}
    </span>
  )
}
