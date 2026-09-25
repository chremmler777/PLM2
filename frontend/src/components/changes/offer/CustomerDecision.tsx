/**
 * The customer's answer and the two internal sign-offs that, together, let
 * the change be approved. Acceptance starts the release phase, so it collects
 * the release deadline; accepting an offer past its validity needs a written
 * override reason. PM and Quality sign off as two different people (4-eyes,
 * enforced by the backend and mirrored here).
 */
import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { changesApi } from '../../../api/changes'
import { t } from '../../../i18n/cmLabels'
import type { ChangeDetail } from '../../../types/change'
import type { OfferOut } from '../../../types/changeOffer'
import { fmtDate, inputCls, sectionLabel } from './offerFormat'
import { offersKey } from './useOfferDraft'

const errDetail = (e: unknown): string | undefined =>
  (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail

const RESPONSE_CHIP: Record<string, string> = {
  pending: 'bg-slate-800 text-slate-300 border-slate-600',
  negotiating: 'bg-amber-950/60 text-amber-200 border-amber-800',
  accepted: 'bg-emerald-950/60 text-emerald-200 border-emerald-800',
  declined: 'bg-rose-950/60 text-rose-200 border-rose-800',
}

const RESPONSE_LABEL: Record<string, string> = {
  pending: 'Waiting for the customer',
  negotiating: 'In negotiation',
  accepted: 'Accepted',
  declined: 'Declined',
}

export default function CustomerDecision({
  change, latestSent, canRespond, canSignPm, canSignQuality, userId,
}: {
  change: ChangeDetail
  /** The newest sent (or accepted) offer version, when offers exist. */
  latestSent?: OfferOut | null
  canRespond: boolean
  canSignPm: boolean
  canSignQuality: boolean
  userId: number | null
}) {
  const qc = useQueryClient()
  const [acceptOpen, setAcceptOpen] = useState(false)
  const [declineOpen, setDeclineOpen] = useState(false)
  const [due, setDue] = useState('')
  const [reason, setReason] = useState('')
  const [override, setOverride] = useState('')
  const expired = !!latestSent && (latestSent.expired || (latestSent.days_left != null && latestSent.days_left < 0))

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ['change', change.id] })
    qc.invalidateQueries({ queryKey: offersKey(change.id) })
  }
  const respond = useMutation({
    mutationFn: (vars: { response: string; body?: Parameters<typeof changesApi.customerResponse>[2] }) =>
      changesApi.customerResponse(change.id, vars.response, vars.body),
    onSuccess: () => { setAcceptOpen(false); setDeclineOpen(false); invalidate() },
    onError: (e: unknown) => toast.error(errDetail(e) ?? 'Failed to record customer response'),
  })
  const signOff = useMutation({
    mutationFn: (role: 'pm' | 'quality') => changesApi.signOff(change.id, role),
    onSuccess: invalidate,
    onError: (e: unknown) => toast.error(errDetail(e) ?? 'Sign-off failed'),
  })

  const samePersonBlocksPm = !change.pm_signed_by
    && !!change.quality_signed_by && userId != null && userId === change.quality_signed_by
  const samePersonBlocksQuality = !change.quality_signed_by
    && !!change.pm_signed_by && userId != null && userId === change.pm_signed_by
  const decided = change.customer_response === 'accepted' || change.customer_response === 'declined'
  const open = change.status === 'quoted' || change.status === 'quoting'

  return (
    <div data-testid="customer-decision" className="rounded-lg border border-slate-700 bg-slate-900/50 p-3 space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className={sectionLabel}>Customer response</span>
        <span data-testid="customer-response"
          className={`rounded border px-1.5 py-0 text-[11px] ${RESPONSE_CHIP[change.customer_response] ?? RESPONSE_CHIP.pending}`}>
          {RESPONSE_LABEL[change.customer_response] ?? change.customer_response}
        </span>
        {latestSent && (
          <span className="text-[11px] text-slate-500">
            on v{latestSent.version}{latestSent.valid_until ? `, valid until ${fmtDate(latestSent.valid_until)}` : ''}
          </span>
        )}
        {canRespond && open && !decided && (
          <div className="ml-auto flex gap-2">
            <button type="button" data-testid="customer-accepted" onClick={() => { setAcceptOpen((o) => !o); setDeclineOpen(false) }}
              className="rounded-lg bg-emerald-700 px-3 py-1 text-xs font-medium text-white hover:bg-emerald-600">
              Customer accepted
            </button>
            <button type="button" data-testid="customer-declined" disabled={respond.isPending}
              onClick={() => { setDeclineOpen((o) => !o); setAcceptOpen(false) }}
              className="rounded-lg border border-slate-600 px-3 py-1 text-xs text-slate-300 hover:bg-slate-700">
              Customer declined
            </button>
          </div>
        )}
      </div>

      {declineOpen && (
        <div data-testid="decline-confirm-box" role="alertdialog" aria-label="Confirm customer declined"
          className="space-y-2 rounded-lg border border-rose-900/70 bg-rose-950/20 p-3">
          <p className="text-xs text-rose-200">
            Recording that the customer declined cannot be undone. The offer is closed and the change cannot be approved
            on it any more.
          </p>
          <div className="flex justify-end gap-2">
            <button type="button" onClick={() => setDeclineOpen(false)}
              className="rounded-lg border border-slate-600 px-3 py-1 text-xs text-slate-300 hover:bg-slate-700">
              Cancel
            </button>
            <button type="button" data-testid="decline-confirm" disabled={respond.isPending}
              onClick={() => respond.mutate({ response: 'declined' })}
              className="rounded-lg bg-rose-700 px-3 py-1 text-xs font-medium text-white hover:bg-rose-600 disabled:opacity-50">
              Yes, the customer declined
            </button>
          </div>
        </div>
      )}

      {acceptOpen && (
        <div className="grid gap-2 rounded-lg border border-emerald-900/70 bg-emerald-950/20 p-3 sm:grid-cols-[auto_minmax(0,1fr)]">
          <label className="text-xs text-slate-400 self-center">{t('customer.releaseDue')}</label>
          <input type="date" data-testid="accept-release-due" value={due}
            onChange={(e) => setDue(e.target.value)} className={`${inputCls} w-44`} />
          <label className="text-xs text-slate-400 self-center">{t('customer.releaseDueReason')}</label>
          <input type="text" value={reason} onChange={(e) => setReason(e.target.value)}
            placeholder="optional" className={inputCls} />
          {expired && (
            <>
              <p data-testid="accept-expired" className="text-xs text-rose-300 sm:col-span-2">
                Offer v{latestSent?.version} expired on {fmtDate(latestSent?.valid_until)}. Accepting it needs a reason on the record.
              </p>
              <label className="text-xs text-slate-400 self-center">Override reason</label>
              <input type="text" data-testid="accept-override" value={override}
                onChange={(e) => setOverride(e.target.value)} className={inputCls}
                placeholder="e.g. customer confirmed the price in writing on ..." />
            </>
          )}
          <div className="sm:col-span-2 flex justify-end">
            <button type="button" data-testid="accept-confirm"
              disabled={!due || (expired && !override.trim()) || respond.isPending}
              onClick={() => respond.mutate({
                response: 'accepted',
                body: {
                  release_due_date: `${due}T23:59:59Z`,
                  release_due_reason: reason || null,
                  ...(expired ? { expired_override_reason: override.trim() } : {}),
                },
              })}
              className="rounded-lg bg-emerald-700 px-3 py-1 text-xs font-medium text-white hover:bg-emerald-600 disabled:opacity-50">
              {t('customer.confirmAccept')}
            </button>
          </div>
        </div>
      )}

      {(canSignPm || canSignQuality) && (
        <div className="flex flex-wrap items-center gap-2">
          {canSignPm && (
            <button type="button" disabled={!!change.pm_signed_by || samePersonBlocksPm || signOff.isPending}
              onClick={() => signOff.mutate('pm')}
              className={`rounded-lg border px-3 py-1 text-xs disabled:cursor-not-allowed ${change.pm_signed_by
                ? 'border-emerald-800 bg-emerald-950/40 text-emerald-200' : 'border-slate-600 text-slate-200 hover:bg-slate-700 disabled:opacity-50'}`}>
              PM sign-off {change.pm_signed_by ? '✓' : ''}
            </button>
          )}
          {canSignQuality && (
            <button type="button" disabled={!!change.quality_signed_by || samePersonBlocksQuality || signOff.isPending}
              onClick={() => signOff.mutate('quality')}
              className={`rounded-lg border px-3 py-1 text-xs disabled:cursor-not-allowed ${change.quality_signed_by
                ? 'border-emerald-800 bg-emerald-950/40 text-emerald-200' : 'border-slate-600 text-slate-200 hover:bg-slate-700 disabled:opacity-50'}`}>
              Quality sign-off {change.quality_signed_by ? '✓' : ''}
            </button>
          )}
        </div>
      )}
      {(samePersonBlocksPm || samePersonBlocksQuality) && (
        <p className="text-xs text-amber-300">PM and Quality sign-off must be different users</p>
      )}
      <p className="text-[11px] text-slate-500">
        Approve requires customer acceptance + both sign-offs. The approve button is in the cockpit above.
      </p>
    </div>
  )
}
