/**
 * Internal changes are not offered: PM approves the costs, which starts the
 * release phase and therefore collects the release deadline. Same behaviour
 * as before the Approval tab existed.
 */
import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { CircleCheck } from 'lucide-react'
import { changesApi } from '../../../api/changes'
import { toastError } from '../../../lib/apiError'
import { buttonClass } from '../../common/buttonStyles'
import DateInput from '../../gantt/DateInput'
import { t } from '../../../i18n/cmLabels'
import type { ChangeDetail } from '../../../types/change'
import { inputCls } from './offerFormat'
import { formatDate, formatMoney } from '../../../lib/format'

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
    onError: (e: unknown) => toastError(e, 'Could not approve the internal costs'),
  })

  if (change.internal_approved_at) {
    return (
      <div data-testid="internal-approved" className="rounded-lg border border-emerald-800 bg-emerald-950/40 p-3">
        <p className="flex items-center gap-1.5 font-medium text-emerald-300">
          <CircleCheck aria-hidden="true" size={16} />{t('internal.approved')}
        </p>
        <p className="mt-1 text-xs text-slate-400 tabular-nums">
          {t('internal.amount')}: {formatMoney(change.internal_approved_amount)}
          {' · '}{formatDate(change.internal_approved_at)}
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
        className={buttonClass(open ? 'secondary' : 'primary')} aria-expanded={open}
        disabled={change.status !== 'costing' || approve.isPending}
        onClick={() => setOpen((o) => !o)}>
        {t('internal.approve')}
      </button>
      {change.status !== 'costing' && (
        <p className="text-[11px] text-slate-500">Internal costs are approved while the change is in costing.</p>
      )}
      {open && (
        <div className="flex flex-wrap items-center gap-2">
          <label htmlFor={`internal-release-due-${change.id}`} className="text-xs text-slate-400">{t('customer.releaseDue')}</label>
          <DateInput id={`internal-release-due-${change.id}`} value={due} commitOnChange
            onChange={setDue} className={`${inputCls} w-44`} />
          <button type="button" data-testid="internal-approve-confirm"
            className={buttonClass('primary', 'sm')}
            disabled={!due || approve.isPending}
            onClick={() => approve.mutate(`${due}T23:59:59Z`)}>
            {t('internal.approve')}
          </button>
        </div>
      )}
    </div>
  )
}
