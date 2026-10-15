/**
 * The named Sales owner (ECR-solid C10), on the Status card under the lead.
 * Sales and Project Management (and admins) change it; everyone else reads
 * it. Only customer changes have one. Sales tasks still show to all of
 * Sales, with this name on them.
 */
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { changesApi } from '../../api/changes'
import { apiErrorMessage } from '../../lib/apiError'
import { t } from '../../i18n/cmLabels'
import type { ChangeRequest } from '../../types/change'

export default function SalesOwnerPicker({ change, canEdit }: {
  change: Pick<ChangeRequest, 'id' | 'sales_owner_id' | 'sales_owner_name'>
  canEdit: boolean
}) {
  const qc = useQueryClient()
  const [editing, setEditing] = useState(false)
  const { data: candidates = [] } = useQuery({
    queryKey: ['change', change.id, 'sales-owner-candidates'],
    enabled: canEdit && editing,
    retry: false,
    queryFn: () => changesApi.salesOwnerCandidates(change.id),
  })
  const set = useMutation({
    mutationFn: (userId: number) => changesApi.setSalesOwner(change.id, userId),
    onSuccess: () => {
      toast.success(t('cockpit.salesOwnerSaved'))
      setEditing(false)
      qc.invalidateQueries({ queryKey: ['change', change.id] })
    },
    onError: (e: unknown) => toast.error(apiErrorMessage(e, 'Could not set the Sales owner')),
  })

  return (
    <div data-testid="sales-owner-picker" className="mt-1 flex flex-wrap items-center gap-2">
      <span>{t('cockpit.salesOwner')}:</span>
      {editing ? (
        // Opens on the placeholder when nobody owns it, so picking the
        // project's Sales contact (marked) is a real change that saves.
        <select aria-label={t('cockpit.salesOwnerPick')}
          data-testid="sales-owner-select" autoFocus
          defaultValue={change.sales_owner_id ?? ''}
          disabled={set.isPending}
          onChange={(e) => { const v = Number(e.target.value); if (v) set.mutate(v) }}
          onBlur={() => { if (!set.isPending) setEditing(false) }}
          className="rounded border border-slate-600 bg-slate-900 px-2 py-0.5 text-sm text-slate-100">
          <option value="">{t('cockpit.salesOwnerPick')}</option>
          {candidates.map((o) => <option key={o.id} value={o.id}>
            {o.is_default ? `${o.name} ${t('cockpit.salesOwnerDefault')}` : o.name}</option>)}
        </select>
      ) : (
        <span className="text-slate-100" data-testid="sales-owner-name">
          {change.sales_owner_name ?? t('cockpit.noSalesOwner')}
        </span>
      )}
      {canEdit && !editing && (
        <button type="button" data-testid="sales-owner-edit" title={t('cockpit.salesOwnerHint')}
          onClick={() => setEditing(true)}
          className="text-xs text-sky-300 hover:text-sky-200 underline decoration-dotted underline-offset-2">
          {change.sales_owner_id == null ? t('cockpit.salesOwnerPick') : t('cockpit.leadChange')}
        </button>
      )}
    </div>
  )
}
