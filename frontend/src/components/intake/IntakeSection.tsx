/**
 * My Tasks: new customer indexes waiting for Development's triage, and the
 * engineering reviews the caller's departments still have to answer
 * (spec 2026-09-25 §17, GET /v1/intakes/my).
 */
import { useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { intakeKeys, intakesApi, ROUTE_LABELS } from '../../api/intakes'
import { formatDate } from '../../lib/format'
import { isBackup } from '../../lib/myTasks'
import { t } from '../../i18n/cmLabels'
import BackupChip from '../common/BackupChip'

export default function IntakeSection() {
  const navigate = useNavigate()
  const { data } = useQuery({ queryKey: intakeKeys.my, queryFn: intakesApi.my, refetchInterval: 60_000 })
  // Project team (spec §18): main rows first, backup rows after them, muted.
  const order = <T extends { role?: string | null }>(xs: T[]) =>
    [...xs.filter((x) => !isBackup(x)), ...xs.filter(isBackup)]
  const triage = order(data?.triage ?? [])
  const review = order(data?.review ?? [])
  if (triage.length === 0 && review.length === 0) return null
  const backupCount = [...triage, ...review].filter(isBackup).length
  return (
    <div data-testid="intake-section">
      <h2 className="text-sm font-semibold text-slate-300 uppercase tracking-wide mb-2">
        New indexes ({triage.length + review.length - backupCount})
        {backupCount > 0 && (
          <span className="ml-2 normal-case tracking-normal font-normal text-slate-500">
            {t('tasks.asBackup').replace('{n}', String(backupCount))}
          </span>
        )}
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
              <tr key={`t-${i.id}`} data-testid={`intake-task-${i.id}`}
                className={`border-b border-slate-700 last:border-0${isBackup(i) ? ' opacity-60' : ''}`}>
                <td className="px-4 py-3 text-slate-100">
                  Triage index {i.revision_name} of {i.part_number}
                  <span className="block text-xs text-slate-400">
                    {i.source_label}{i.suggested_route ? `, suggested: ${ROUTE_LABELS[i.suggested_route]}` : ''}
                  </span>
                  {isBackup(i) && <BackupChip mainName={i.main_name} className="mt-0.5" />}
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
                className={`border-b border-slate-700 last:border-0${isBackup(r) ? ' opacity-60' : ''}`}>
                <td className="px-4 py-3 text-slate-100">
                  Engineering review: impact or no impact?
                  <span className="block text-xs text-slate-400">for {r.department_name}</span>
                  {isBackup(r) && <BackupChip mainName={r.main_name} className="mt-0.5" />}
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
