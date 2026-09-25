/**
 * The change lead, on the Status card (spec §16 P1 5). The lead, Project
 * Management and admins may set it; everyone else reads it. The picker offers
 * the backend's candidates (GET /changes/{id}/lead-candidates: PM members,
 * the current lead, the project's PM as the default). An older backend
 * without the endpoint (404) falls back to the user list for admins, and for
 * everyone to the people the picker can see: the current lead and the viewer.
 */
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import client from '../../api/client'
import { changesApi } from '../../api/changes'
import { apiErrorMessage } from '../../lib/apiError'
import { t } from '../../i18n/cmLabels'
import type { ChangeRequest, LeadCandidate } from '../../types/change'

export default function LeadPicker({ change, canEdit, viewer, isAdmin = false }: {
  change: Pick<ChangeRequest, 'id' | 'lead_id' | 'lead_name'>
  canEdit: boolean
  /** The viewer, offered as "Me" when the candidate list is not available. */
  viewer?: { id: number; name: string } | null
  /** Admins may read the user list as a fallback candidate source. */
  isAdmin?: boolean
}) {
  const qc = useQueryClient()
  const [editing, setEditing] = useState(false)
  const { data: candidates = [] } = useQuery({
    queryKey: ['change', change.id, 'lead-candidates', isAdmin],
    enabled: canEdit && editing,
    retry: false,
    queryFn: async (): Promise<LeadCandidate[]> => {
      try {
        return await changesApi.leadCandidates(change.id)
      } catch (e) {
        // Only a missing endpoint falls back to the user list; a refusal or
        // a failure leaves the lead and the viewer.
        const status = (e as { response?: { status?: number } })?.response?.status
        if (status !== 404 || !isAdmin) return []
        const users = (await client.get<{ id: number; full_name?: string | null; username: string; is_active?: boolean }[]>('/v1/users')).data
        return users.filter((u) => u.is_active !== false)
          // Two people may share a display name: the login tells them apart.
          .map((u) => ({ id: u.id, name: u.full_name && u.full_name !== u.username ? `${u.full_name} (${u.username})` : u.username }))
      }
    },
  })
  const options: LeadCandidate[] = [
    ...candidates,
    ...(change.lead_id != null && !candidates.some((c) => c.id === change.lead_id)
      ? [{ id: change.lead_id, name: change.lead_name ?? `#${change.lead_id}` }] : []),
    ...(viewer && !candidates.some((c) => c.id === viewer.id) && viewer.id !== change.lead_id
      ? [{ id: viewer.id, name: `${viewer.name} (${t('cockpit.leadMe')})` }] : []),
  ]
  const set = useMutation({
    mutationFn: (leadId: number) => changesApi.setLead(change.id, leadId),
    onSuccess: () => {
      toast.success(t('cockpit.leadSaved'))
      setEditing(false)
      qc.invalidateQueries({ queryKey: ['change', change.id] })
    },
    onError: (e: unknown) => toast.error(apiErrorMessage(e, 'Setting the lead failed')),
  })
  const defaultId = candidates.find((c) => c.is_default)?.id

  return (
    <div data-testid="lead-picker" className="flex flex-wrap items-center gap-2">
      <span>{t('cockpit.lead')}:</span>
      {editing ? (
        // Keyed on the default so it is preselected once the candidates arrive.
        <select key={defaultId ?? 'none'} aria-label={t('cockpit.leadPick')} data-testid="lead-select" autoFocus
          defaultValue={change.lead_id ?? defaultId ?? ''}
          disabled={set.isPending}
          onChange={(e) => { const v = Number(e.target.value); if (v) set.mutate(v) }}
          onBlur={() => { if (!set.isPending) setEditing(false) }}
          className="rounded border border-slate-600 bg-slate-900 px-2 py-0.5 text-sm text-slate-100">
          <option value="">{t('cockpit.leadPick')}</option>
          {options.map((o) => (
            <option key={o.id} value={o.id}>
              {o.name}{o.department ? ` (${o.department})` : ''}
            </option>
          ))}
        </select>
      ) : (
        // A missing lead is a warning only where someone can still fix it.
        <span className={change.lead_id == null && canEdit ? 'text-amber-300' : 'text-slate-100'}
          data-testid="lead-name">
          {change.lead_name ?? t('cockpit.noLead')}
        </span>
      )}
      {canEdit && !editing && (
        <button type="button" data-testid="lead-edit" title={t('cockpit.leadHint')}
          onClick={() => setEditing(true)}
          className="text-xs text-sky-300 hover:text-sky-200 underline decoration-dotted underline-offset-2">
          {change.lead_id == null ? t('cockpit.leadPick') : t('cockpit.leadChange')}
        </button>
      )}
    </div>
  )
}
