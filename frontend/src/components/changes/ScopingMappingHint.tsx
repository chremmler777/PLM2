import { useQuery } from '@tanstack/react-query'
import { Check } from 'lucide-react'
import { changesApi } from '../../api/changes'
import type { Assessment } from '../../types/change'

interface DeptRef { id: number; name: string }

/** Letters that owe an answer; the others are kept in the loop only. */
const ASSESSING = new Set(['R', 'A'])

/**
 * F6: after a scoping meeting proceeds, the routing template (blocking-role
 * rules) decides which departments actually get an assessment task. This
 * can silently diverge from what was selected in the meeting. This renders a
 * short line comparing the two so the divergence is visible in place instead
 * of leaving the user wondering where a selected department's task went.
 *
 * The letter shown is the department's letter today: the assessment row's,
 * which an approved routing change (a decline, a reletter) has already
 * moved, and only then the room's original call.
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
  const rowsOf = (id: number) => assessments.filter((a) => a.department_id === id)
  // The earliest stage is the assessment round the meeting routed.
  const currentLetter = (id: number): string | null => {
    const rows = [...rowsOf(id)].sort((a, b) => a.stage_order - b.stage_order)
    const live = rows.find((a) => a.status !== 'waived') ?? rows[0]
    return live?.rasic_letter || proceedMeeting.department_rasic?.[String(id)] || null
  }
  const hasAssessment = (id: number) => rowsOf(id).length > 0
  const matched = proceedMeeting.selected_department_ids.filter(hasAssessment)
  const missing = proceedMeeting.selected_department_ids.filter((id) => !hasAssessment(id))

  return (
    <p data-testid="scoping-mapping-hint"
      className="text-xs text-slate-400 bg-slate-800/60 border border-slate-700 rounded-lg p-3 leading-relaxed">
      <span className="text-slate-500">From scoping:</span>{' '}
      {matched.map((id, i) => {
        const letter = currentLetter(id)
        const assesses = letter != null && ASSESSING.has(letter)
        return (
          <span key={id}>
            {i > 0 && ', '}
            <span data-testid={`scoping-mapped-${id}`}
              className={`inline-flex items-center gap-1 ${assesses ? 'text-slate-300' : 'text-slate-400'}`}>
              {deptName(id)}{letter ? ` ${letter}` : ''}
              {assesses ? (
                <>
                  <Check aria-hidden="true" size={12} className="text-emerald-400" />
                  <span className="sr-only">(assesses)</span>
                </>
              ) : (
                <span className="text-slate-500">(no answer needed)</span>
              )}
            </span>
          </span>
        )
      })}
      {matched.length > 0 && missing.length > 0 && <span aria-hidden="true"> · </span>}
      {missing
        .map((id) => `${deptName(id)} has no blocking role in the routing template, so no assessment task`)
        .join('; ')}
    </p>
  )
}
