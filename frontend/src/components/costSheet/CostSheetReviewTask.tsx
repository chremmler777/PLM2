/**
 * My Tasks item "Review the cost sheet" (spec §15): shown to Finance when the
 * latest published version is older than the review period (or nothing is
 * published). Opens the cost sheet page; publishing a new version clears it.
 */
import { useQuery } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { costSheetApi } from '../../api/costSheet'
import { formatDate } from '../../lib/format'

export default function CostSheetReviewTask() {
  const navigate = useNavigate()
  const { data } = useQuery({
    queryKey: ['cost-sheet-review-task'],
    queryFn: () => costSheetApi.reviewTask(),
    retry: false,
    staleTime: 5 * 60 * 1000,
  })
  if (!data?.due) return null
  const s = data.stale
  return (
    <div data-testid="cost-sheet-review-task">
      <h2 className="text-sm font-semibold text-slate-300 uppercase tracking-wide mb-2">
        Finance (1)
      </h2>
      <div className="flex flex-wrap items-center gap-3 bg-slate-800 border border-amber-800/60 rounded-lg px-4 py-3">
        <div className="min-w-0 flex-1">
          <p className="text-sm text-slate-100">Review the cost sheet</p>
          <p className="text-xs text-slate-400">
            {s?.latest_version == null
              ? 'No cost sheet version is published yet: costing cannot be priced.'
              : `Cost sheet v${s.latest_version} was last reviewed ${formatDate(s.reviewed_on)}; `
                + `the ${s.review_months}-month review was due ${formatDate(s.due_on)}.`}
          </p>
        </div>
        <button type="button" onClick={() => navigate('/cost-sheet')}
          className="text-xs px-3 py-1.5 rounded bg-sky-600 hover:bg-sky-500 text-white">
          Open the cost sheet
        </button>
      </div>
    </div>
  )
}
