/**
 * Amber banner when the rate owners (Sales, with Finance) owe a review: nothing published yet, or the
 * latest version is older than the org's review cycle. Reused by costing.
 */
import { TriangleAlert } from 'lucide-react'
import { formatCalendarDate } from '../../lib/format'
import type { StaleStatus } from '../../types/costSheet'

export default function StaleBanner({ stale, canEdit }: { stale: StaleStatus; canEdit?: boolean }) {
  if (!stale.stale) return null
  const text = stale.reason === 'no_published_version'
    ? 'No cost sheet has been published yet. Costing falls back to the old department rates.'
    : `The cost sheet was last reviewed on ${formatCalendarDate(stale.reviewed_on)} (version ${stale.latest_version}). `
      + `The review cycle is ${stale.review_months} months; it was due on ${formatCalendarDate(stale.due_on)}.`
  return (
    <div role="status" className="flex items-start gap-3 rounded-lg border border-amber-500/40 bg-amber-500/10 px-4 py-3 text-sm text-amber-200">
      <TriangleAlert aria-hidden="true" size={16} className="mt-0.5 shrink-0 text-amber-300" />
      <div>
        <p className="font-medium">Cost sheet review due</p>
        <p className="text-amber-200/80">
          {text}{canEdit ? ' Start a new draft, check the rates and publish it.' : ' Sales has been asked to review it.'}
        </p>
      </div>
    </div>
  )
}
