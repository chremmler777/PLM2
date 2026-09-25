/**
 * My Tasks: new customer indexes waiting for Development's triage, and the
 * engineering reviews the caller's departments still have to answer
 * (spec 2026-09-25 §17, GET /v1/intakes/my).
 */
import { useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { intakeKeys, intakesApi, ROUTE_LABELS } from '../../api/intakes'
import { formatDate } from '../../lib/format'

export default function IntakeSection() {
  const navigate = useNavigate()
  const { data } = useQuery({ queryKey: intakeKeys.my, queryFn: intakesApi.my, refetchInterval: 60_000 })
  const triage = data?.triage ?? []
  const review = data?.review ?? []
  if (triage.length === 0 && review.length === 0) return null
  return (
    <div data-testid="intake-section">
      <h2 className="text-sm font-semibold text-slate-300 uppercase tracking-wide mb-2">
        New indexes ({triage.length + review.length})
      </h2>
      <div className="bg-slate-800 border border-slate-700 rounded-lg overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-slate-700 bg-slate-900">
              <th className="text-left px-4 py-3 text-slate-400 font-medium">Task</th>
              <th className="text-left px-4 py-3 text-slate-400 font-medium">Part / change</th>
              <th className="text-left px-4 py-3 text-slate-400 font-medium">Received</th>
              <th className="px-4 py-3" />
            </tr>
          </thead>
          <tbody>
            {triage.map((i) => (
              <tr key={`t-${i.id}`} data-testid={`intake-task-${i.id}`} className="border-b border-slate-700 last:border-0">
                <td className="px-4 py-3 text-slate-100">
                  Triage index {i.revision_name} of {i.part_number}
                  <span className="block text-xs text-slate-400">
                    {i.source_label}{i.suggested_route ? `, suggested: ${ROUTE_LABELS[i.suggested_route]}` : ''}
                  </span>
                </td>
                <td className="px-4 py-3 text-slate-300">
                  {i.part_name}
                  <span className="block text-xs text-slate-500">{i.project_name}</span>
                </td>
                <td className="px-4 py-3 text-xs text-slate-400">{formatDate(i.received_at)}</td>
                <td className="px-4 py-3 text-right">
                  <button onClick={() => navigate(`/parts/${i.part_id}`)}
                    className="text-xs px-3 py-1 rounded border border-slate-600 text-slate-200 hover:bg-slate-700 whitespace-nowrap">
                    Decide the route
                  </button>
                </td>
              </tr>
            ))}
            {review.map((r) => (
              <tr key={`r-${r.change_id}-${r.department_id}`} data-testid={`review-task-${r.change_id}`}
                className="border-b border-slate-700 last:border-0">
                <td className="px-4 py-3 text-slate-100">
                  Engineering review: impact or no impact?
                  <span className="block text-xs text-slate-400">for {r.department_name}</span>
                </td>
                <td className="px-4 py-3 text-slate-300">
                  {r.change_number}
                  <span className="block text-xs text-slate-500">{r.title}</span>
                </td>
                <td className="px-4 py-3 text-xs text-slate-400">-</td>
                <td className="px-4 py-3 text-right">
                  <button onClick={() => navigate(`/changes/${r.change_id}?tab=review`)}
                    className="text-xs px-3 py-1 rounded border border-slate-600 text-slate-200 hover:bg-slate-700 whitespace-nowrap">
                    Answer
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
