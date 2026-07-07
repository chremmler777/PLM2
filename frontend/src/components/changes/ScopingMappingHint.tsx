import { useQuery } from '@tanstack/react-query'
import { changesApi } from '../../api/changes'
import type { Assessment } from '../../types/change'

interface DeptRef { id: number; name: string }

/**
 * F6: after a scoping meeting proceeds, the routing template (blocking-role
 * rules) decides which departments actually get an assessment task — this
 * can silently diverge from what was selected in the meeting. This renders a
 * short line comparing the two so the divergence is visible in place instead
 * of leaving the user wondering where a selected department's task went.
 */
export function ScopingMappingHint({ changeId, assessments, departments }: {
  changeId: number
  assessments: Assessment[]
  departments: DeptRef[]
}) {
  const { data: meetings = [] } = useQuery({
    queryKey: ['change-meetings', changeId],
    queryFn: () => changesApi.listMeetings(changeId),
  })

  const proceedMeeting = [...meetings].reverse().find((m) => m.decision === 'proceed')
  if (!proceedMeeting || proceedMeeting.selected_department_ids.length === 0) return null

  const deptName = (id: number) => departments.find((d) => d.id === id)?.name ?? `#${id}`
  const hasAssessment = (id: number) => assessments.some((a) => a.department_id === id)
  const matched = proceedMeeting.selected_department_ids.filter(hasAssessment)
  const missing = proceedMeeting.selected_department_ids.filter((id) => !hasAssessment(id))

  return (
    <p className="text-xs text-slate-400 bg-slate-800/60 border border-slate-700 rounded-lg p-3">
      From scoping: {matched.map((id) => `${deptName(id)} ✓`).join(', ')}
      {matched.length > 0 && missing.length > 0 && ' · '}
      {missing
        .map((id) => `${deptName(id)} has no blocking role in the routing template — no assessment task`)
        .join('; ')}
    </p>
  )
}
