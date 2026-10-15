import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { changesApi } from '../../api/changes'
import { apiErrorMessage } from '../../lib/apiError'
import { t } from '../../i18n/cmLabels'
import { btnSm } from '../common/buttonStyles'
import type { ChangeRequest } from '../../types/change'
import { UrgentFields, emptyUrgent, plainChange, urgentMissing, type UrgentDraft } from './CaptureV2'

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

  // §2 (SCOPING_V2): urgent names its need-by, reason and evidence first
  const askUrgent = !!change.scoping_v2 && plainChange(change)
  const [urgent, setUrgent] = useState<UrgentDraft | null>(null)
  const save = useMutation({
    mutationFn: (priority: Priority) => changesApi.update(change.id, {
      priority,
      ...(priority === 'critical' && urgent ? {
        ...(change.release_due_date ? {} : { release_due_date: `${urgent.needBy}T12:00:00` }),
        urgent_reason: urgent.reason, urgent_evidence: urgent.evidence.trim() } : {}),
    }),
    onSuccess: (_data, priority) => {
      setUrgent(null)
      qc.invalidateQueries({ queryKey: ['change', change.id] })
      toast.success(`Priority set to ${PRIORITIES.find((p) => p.value === priority)?.label ?? priority}`)
    },
    onError: (e: unknown) => toast.error(apiErrorMessage(e, 'Could not update the priority')),
  })
  const pick = (p: Priority) => {
    if (p === 'critical' && askUrgent) {
      setUrgent({ ...emptyUrgent, needBy: change.release_due_date?.slice(0, 10) ?? '',
        reason: change.urgent_reason ?? '', evidence: change.urgent_evidence ?? '' })
      return
    }
    save.mutate(p)
  }

  if (!canEdit) {
    return (
      <span className={`text-xs px-2 py-0.5 rounded-full ${current.pill}`}>{current.label}</span>
    )
  }

  const missing = urgent ? urgentMissing(urgent) : []
  return (
    <span className="inline-flex flex-col gap-2">
      <select
        aria-label="Priority"
        className={`text-xs rounded-full px-2 py-0.5 border-0 cursor-pointer self-start ${current.pill}`}
        value={urgent ? 'critical' : change.priority}
        disabled={save.isPending}
        onChange={(e) => pick(e.target.value as Priority)}
      >
        {PRIORITIES.map((p) => (
          <option key={p.value} value={p.value} className="bg-slate-800 text-slate-100">
            {p.label}
          </option>
        ))}
      </select>
      {urgent && (
        <span className="block rounded-lg border border-red-800/60 bg-red-950/20 p-2 space-y-2" data-testid="urgent-form">
          <span className="block text-xs text-slate-300">{t('urgent.toggleHint')}</span>
          <UrgentFields value={urgent} onChange={setUrgent} idPrefix="prio-urgent" />
          <span className="flex items-center gap-2">
            <button type="button" className={btnSm.primary} data-testid="urgent-save"
              disabled={missing.length > 0 || save.isPending} onClick={() => save.mutate('critical')}>
              {t('followup.save')}
            </button>
            <button type="button" className={btnSm.secondary} onClick={() => setUrgent(null)}>
              {t('common.cancel')}
            </button>
            {missing.length > 0 && (
              <span className="text-[11px] text-slate-500">{t('flag.missing').replace('{x}', missing.join(', '))}</span>
            )}
          </span>
        </span>
      )}
    </span>
  )
}
