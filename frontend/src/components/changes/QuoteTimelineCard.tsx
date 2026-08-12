/**
 * The implementation timeline, marked out but not built.
 *
 * Sequencing the work — what runs in parallel, what waits on what — is a real
 * step between costing and the offer, and Sales does it. There is no tool for it
 * yet, so the card stands empty on purpose: the step is visible in the flow
 * instead of being remembered by whoever happens to know.
 */
import { t } from '../../i18n/cmLabels'

export default function QuoteTimelineCard() {
  return (
    <div data-testid="quote-timeline-placeholder"
      className="rounded-lg border border-dashed border-slate-700 bg-slate-800/40 p-3 space-y-1">
      <p className="text-xs uppercase tracking-wide text-slate-500">{t('quote.timeline')}</p>
      <p className="text-sm text-slate-400">{t('quote.timelineBody')}</p>
    </div>
  )
}
