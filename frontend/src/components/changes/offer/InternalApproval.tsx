/**
 * Internal changes are not offered: PM approves the costs, which starts the
 * release phase and therefore collects the release deadline. Same behaviour
 * as before the Approval tab existed.
 */
import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { changesApi } from '../../../api/changes'
import { t } from '../../../i18n/cmLabels'
import type { ChangeDetail } from '../../../types/change'
import { inputCls } from './offerFormat'

const errDetail = (e: unknown): string | undefined =>
  (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail

export default function InternalApproval({ change, canApprove }: {
  change: ChangeDetail
  canApprove: boolean
}) {
  const qc = useQueryClient()
  const [open, setOpen] = useState(false)
  const [due, setDue] = useState('')
  const approve = useMutation({
    mutationFn: (release_due_date: string) =>
      changesApi.approveInternalCosts(change.id, { note: null, release_due_date, release_due_reason: null }),
    onSuccess: () => {
      toast.success(t('internal.approved'))
      setOpen(false)
      qc.invalidateQueries({ queryKey: ['change', change.id] })
    },
    onError: (e: unknown) => toast.error(errDetail(e) ?? 'Approval failed'),
  })

  if (change.internal_approved_at) {
    return (
      <div data-testid="internal-approved" className="rounded-lg border border-emerald-800 bg-emerald-950/40 p-3">
        <p className="font-medium text-emerald-300">✓ {t('internal.approved')}</p>
        <p className="mt-1 text-xs text-slate-400 tabular-nums">
          {t('internal.amount')}: {change.internal_approved_amount?.toFixed(2) ?? '-'}
          {' · '}{new Date(change.internal_approved_at).toLocaleDateString()}
        </p>
        {change.internal_approval_note && (
          <p className="text-xs text-slate-400">{change.internal_approval_note}</p>
        )}
      </div>
    )
  }
  if (!canApprove) {
    return (
      <p className="text-xs text-slate-400">
        Only a Project Manager department member or an admin may approve internal costs.
      </p>
    )
  }
  return (
    <div className="space-y-2">
      <button type="button"
        className="rounded-lg bg-emerald-700 px-4 py-2 text-sm font-semibold text-white hover:bg-emerald-600 disabled:opacity-50"
        disabled={change.status !== 'costing' || approve.isPending}
        onClick={() => setOpen((o) => !o)}>
        {t('internal.approve')}
      </button>
      {change.status !== 'costing' && (
        <p className="text-[11px] text-slate-500">Internal costs are approved while the change is in costing.</p>
      )}
      {open && (
        <div className="flex flex-wrap items-center gap-2">
          <label className="text-xs text-slate-400">{t('customer.releaseDue')}</label>
          <input type="date" data-testid="internal-release-due" value={due}
            onChange={(e) => setDue(e.target.value)} className={inputCls} />
          <button type="button" data-testid="internal-approve-confirm"
            className="rounded-lg bg-emerald-700 px-2.5 py-1 text-xs text-white hover:bg-emerald-600 disabled:opacity-50"
            disabled={!due || approve.isPending}
            onClick={() => approve.mutate(`${due}T23:59:59Z`)}>
            {t('internal.approve')}
          </button>
        </div>
      )}
    </div>
  )
}
