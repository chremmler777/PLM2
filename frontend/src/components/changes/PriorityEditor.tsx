import { useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { changesApi } from '../../api/changes'
import { apiErrorMessage } from '../../lib/apiError'
import type { ChangeRequest } from '../../types/change'

type Priority = ChangeRequest['priority']

export const PRIORITIES: { value: Priority; label: string; pill: string }[] = [
  { value: 'low', label: 'Low', pill: 'bg-slate-700 text-slate-200' },
  { value: 'medium', label: 'Medium', pill: 'bg-sky-900 text-sky-200' },
  { value: 'high', label: 'High', pill: 'bg-amber-900 text-amber-200' },
  { value: 'critical', label: 'Critical', pill: 'bg-red-900 text-red-200' },
]

/**
 * Priority display + inline edit. Priority steers scheduling, not the audited
 * lifecycle gates, so it stays editable throughout the change (not frozen after
 * scoping) — but only for the change lead or an admin.
 */
export function PriorityEditor({ change, canEdit }: {
  change: ChangeRequest; canEdit: boolean
}) {
  const qc = useQueryClient()
  const current = PRIORITIES.find((p) => p.value === change.priority) ?? PRIORITIES[1]

  const save = useMutation({
    mutationFn: (priority: Priority) => changesApi.update(change.id, { priority }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['change', change.id] })
      toast.success('Priority updated')
    },
    onError: (e: unknown) => toast.error(apiErrorMessage(e, 'Failed to update priority')),
  })

  if (!canEdit) {
    return (
      <span className={`text-xs px-2 py-0.5 rounded-full ${current.pill}`}>{current.label}</span>
    )
  }

  return (
    <select
      aria-label="Priority"
      className={`text-xs rounded-full px-2 py-0.5 border-0 cursor-pointer ${current.pill}`}
      value={change.priority}
      disabled={save.isPending}
      onChange={(e) => save.mutate(e.target.value as Priority)}
    >
      {PRIORITIES.map((p) => (
        <option key={p.value} value={p.value} className="bg-slate-800 text-slate-100">
          {p.label}
        </option>
      ))}
    </select>
  )
}
