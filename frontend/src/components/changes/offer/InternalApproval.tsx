/**
 * Internal changes are not offered: an engineering approver (HARD #8, never
 * the raiser) approves the costs, which starts the release phase and
 * therefore collects the release deadline.
 *
 * Spec §5 (ASSESSMENT_V2) approval card: the cost (a "Tool cost ESTIMATE"
 * banner while any line is priced on an estimate), why we spend it (nothing
 * preselected), and with money the annual volume, the saving per year and
 * whether it is calculated or estimated; the payback is computed. All at no
 * cost: one click + the rationale.
 */
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { CircleCheck, TriangleAlert } from 'lucide-react'
import { changesApi } from '../../../api/changes'
import { toastError } from '../../../lib/apiError'
import { buttonClass } from '../../common/buttonStyles'
import DateInput from '../../gantt/DateInput'
import { t } from '../../../i18n/cmLabels'
import type { ChangeDetail } from '../../../types/change'
import { inputCls } from './offerFormat'
import { formatDate, formatMoney } from '../../../lib/format'

export const RATIONALES = ['saving', 'quality', 'capacity', 'safety', 'maintenance', 'other'] as const

/** Months until the saving pays the cost back; null without a saving. */
export function paybackMonths(cost: number, savingPerYear: number): number | null {
  if (!(savingPerYear > 0)) return null
  return Math.round((cost / savingPerYear) * 12 * 10) / 10
}

export default function InternalApproval({ change, canApprove, approvers, needsMoney }: {
  change: ChangeDetail
  canApprove: boolean
  /** Who approves, in words (stage-state internal_approvers). */
  approvers?: string | null
  /** stage-state internal_needs_money: the fields an approver without price
   *  view must fill, whose /summation is refused (R24). */
  needsMoney?: boolean | null
}) {
  const qc = useQueryClient()
  const v2 = !!change.assessment_v2
  const [open, setOpen] = useState(false)
  const [due, setDue] = useState('')
  const [rationale, setRationale] = useState('')
  const [volume, setVolume] = useState('')
  const [saving, setSaving] = useState('')
  const [basis, setBasis] = useState<'' | 'calculated' | 'estimate'>('')
  // The cost and its estimates: what the approver approves.
  const { data: summation } = useQuery({
    queryKey: ['change-summation', change.id],
    queryFn: () => changesApi.getSummation(change.id),
    enabled: v2 && canApprove && open, retry: false,
  })
  const { data: positions = [] } = useQuery({
    queryKey: ['costing-positions', change.id],
    queryFn: () => changesApi.listCostPositions(change.id),
    enabled: v2 && canApprove && open, retry: false,
  })
  const total = summation?.totals?.grand_total ?? null
  const withMoney = total != null ? Math.abs(total) > 0.004 : !!needsMoney
  const estimated = positions.filter((p) => p.estimated)
  const payback = withMoney ? paybackMonths(total!, Number(saving)) : null
  const approve = useMutation({
    mutationFn: (release_due_date: string) =>
      changesApi.approveInternalCosts(change.id, {
        note: null, release_due_date, release_due_reason: null,
        ...(v2 ? { rationale } : {}),
        ...(v2 && withMoney ? { volume: Number(volume), saving: Number(saving),
          saving_basis: basis || undefined } : {}),
      }),
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
        {change.internal_rationale && (
          <p className="text-xs text-slate-400" data-testid="internal-case">
            {t(`internal.rationale.${change.internal_rationale}`)}
            {change.internal_saving != null && ` · ${t('internal.saving')}: ${formatMoney(change.internal_saving)}`
              + ` (${t(`internal.basis.${change.internal_saving_basis ?? 'estimate'}`)})`}
            {change.internal_volume != null && ` · ${t('internal.volume')}: ${change.internal_volume}`}
          </p>
        )}
        {change.internal_approval_note && (
          <p className="text-xs text-slate-400">{change.internal_approval_note}</p>
        )}
      </div>
    )
  }
  if (!canApprove) {
    return (
      <p data-testid="internal-approvers" className="text-xs text-slate-400">
        {t('internal.approvedBy').replace('{who}', approvers || t('internal.approverFallback'))}
      </p>
    )
  }
  const caseReady = !v2 || (rationale !== '' && (!withMoney
    || (Number(volume) > 0 && saving !== '' && Number(saving) >= 0 && basis !== '')))
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
      {open && v2 && (
        <div className="space-y-2 rounded border border-slate-700 p-2 text-xs" data-testid="internal-card">
          {total != null && (
            <p className="text-slate-200 tabular-nums" data-testid="internal-cost">
              {t('internal.cost')}: {formatMoney(total, summation?.currency ?? undefined)}
            </p>
          )}
          {estimated.length > 0 && (
            <p data-testid="internal-estimate-banner"
              className="flex items-center gap-1 rounded bg-amber-900/50 px-2 py-1 font-semibold text-amber-100">
              <TriangleAlert aria-hidden="true" size={12} />
              {t('internal.estimateBanner').replace('{x}', estimated.map((p) => p.label).join(', '))}
            </p>
          )}
          <label className="block text-slate-400">{t('internal.why')}
            <select className={`${inputCls} ml-2`} value={rationale} data-testid="internal-rationale"
              onChange={(e) => setRationale(e.target.value)}>
              <option value="">{t('internal.pick')}</option>
              {RATIONALES.map((r) => <option key={r} value={r}>{t(`internal.rationale.${r}`)}</option>)}
            </select>
          </label>
          {withMoney && (
            <div className="flex flex-wrap items-center gap-2">
              <label className="text-slate-400">{t('internal.volume')}
                <input type="number" min={0} className={`${inputCls} ml-1 w-28`} value={volume}
                  data-testid="internal-volume" onChange={(e) => setVolume(e.target.value)} /></label>
              <label className="text-slate-400">{t('internal.saving')}
                <input type="number" min={0} className={`${inputCls} ml-1 w-28`} value={saving}
                  data-testid="internal-saving" onChange={(e) => setSaving(e.target.value)} /></label>
              {(['calculated', 'estimate'] as const).map((b) => (
                <label key={b} className="inline-flex items-center gap-1 text-slate-200">
                  <input type="radio" name={`saving-basis-${change.id}`} checked={basis === b}
                    data-testid={`internal-basis-${b}`} onChange={() => setBasis(b)} />
                  {t(`internal.basis.${b}`)}
                </label>
              ))}
              <span className="text-slate-300" data-testid="internal-payback">
                {t('internal.payback')}: {payback != null
                  ? t('internal.months').replace('{n}', String(payback)) : '-'}
              </span>
            </div>
          )}
        </div>
      )}
      {open && (
        <div className="flex flex-wrap items-center gap-2">
          <label htmlFor={`internal-release-due-${change.id}`} className="text-xs text-slate-400">{t('customer.releaseDue')}</label>
          <DateInput id={`internal-release-due-${change.id}`} value={due} commitOnChange
            onChange={setDue} className={`${inputCls} w-44`} />
          <button type="button" data-testid="internal-approve-confirm"
            className={buttonClass('primary', 'sm')}
            disabled={!due || !caseReady || approve.isPending}
            onClick={() => approve.mutate(`${due}T23:59:59Z`)}>
            {t('internal.approve')}
          </button>
        </div>
      )}
    </div>
  )
}
