/**
 * The customer's answer and the two internal sign-offs that, together, let
 * the change be approved. Acceptance starts the release phase, so it collects
 * the release deadline; accepting an offer past its validity needs a written
 * override reason. PM and Quality sign off as two different people (4-eyes,
 * enforced by the backend and mirrored here).
 *
 * ECR-solid §7 (C4, C12): "Customer answer", nothing preselected: accepted
 * (evidence: a filed mail or file, or the PO number; "PO matches vN
 * exactly?"; the total confirmed), still talking (next contact date) or
 * declined (the customer's reference; the change is rejected and the
 * rejection letter takes over). Approval follows on its own once the
 * customer said yes and both signed.
 */
import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Check } from 'lucide-react'
import { changesApi } from '../../../api/changes'
import { toastError } from '../../../lib/apiError'
import { addDaysIso, formatCalendarDate, todayIso } from '../../../lib/format'
import { buttonClass } from '../../common/buttonStyles'
import DateInput from '../../gantt/DateInput'
import { t } from '../../../i18n/cmLabels'
import type { ChangeDetail } from '../../../types/change'
import type { OfferOut } from '../../../types/changeOffer'
import { fmtMoney, inputCls, offerDaysLeft, sectionLabel } from './offerFormat'
import { offersKey } from './useOfferDraft'

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

const EVIDENCE_KINDS = new Set(['customer_email', 'customer_file', 'general'])
const fill = (k: string, v: Record<string, string | number>) =>
  Object.entries(v).reduce((acc, [kk, vv]) => acc.split(`{${kk}}`).join(String(vv)), t(k))
/** Today plus n working days (Mon-Fri), as an ISO date. */
export function addWorkingDaysIso(fromIso: string, n: number): string {
  const d = new Date(`${fromIso}T12:00:00Z`)
  let left = n
  while (left > 0) {
    d.setUTCDate(d.getUTCDate() + 1)
    const wd = d.getUTCDay()
    if (wd !== 0 && wd !== 6) left -= 1
  }
  return d.toISOString().slice(0, 10)
}

export default function CustomerDecision({
  change, latestSent, canRespond, canSignPm, canSignQuality, userId, offers,
}: {
  change: ChangeDetail
  /** The newest sent (or accepted) offer version, when offers exist. */
  latestSent?: OfferOut | null
  canRespond: boolean
  canSignPm: boolean
  canSignQuality: boolean
  userId: number | null
  /** Every version, to name the one a signature was given on. */
  offers?: OfferOut[]
}) {
  const signedVersion = (oid?: number | null) => {
    const o = oid != null ? (offers ?? []).find((x) => x.id === oid) ?? (latestSent?.id === oid ? latestSent : null) : null
    return o ? `, v${o.version}` : ''
  }
  const qc = useQueryClient()
  const v2 = change.commercial_v2 !== false
  const [acceptOpen, setAcceptOpen] = useState(false)
  const [declineOpen, setDeclineOpen] = useState(false)
  const [talkOpen, setTalkOpen] = useState(false)
  // Release date from the need-by, else the offer's weeks from order (§7)
  const weeks = latestSent?.data?.timing?.weeks_from_order
  const [due, setDue] = useState(
    change.release_due_date ? change.release_due_date.slice(0, 10)
      : (v2 && weeks ? addDaysIso(todayIso(), Math.round(Number(weeks) * 7)) : ''))
  const [reason, setReason] = useState('')
  const [override, setOverride] = useState('')
  const [evidenceId, setEvidenceId] = useState('')
  const [ref, setRef] = useState('')
  const [match, setMatch] = useState<'' | 'yes' | 'no'>('')
  const [differs, setDiffers] = useState('')
  const [confirmed, setConfirmed] = useState(false)
  const [nextContact, setNextContact] = useState(addWorkingDaysIso(todayIso(), 5))
  const [talkNote, setTalkNote] = useState('')
  const mails = (change.attachments ?? [])
    .filter((a) => EVIDENCE_KINDS.has(a.kind ?? 'general'))
    .sort((a, b) => b.created_at.localeCompare(a.created_at))
  const refOk = ref.trim().length >= 5
  const evidenceOk = !!evidenceId || refOk
  const evidence = evidenceId ? { attachment_id: Number(evidenceId) } : { ref: ref.trim() }
  const total = latestSent ? fmtMoney(latestSent.totals.total_one_time, latestSent.currency) : ''
  const left = latestSent ? offerDaysLeft(latestSent) : null
  const expired = !!latestSent && latestSent.status === 'sent' && (!!latestSent.expired || (left != null && left < 0))

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ['change', change.id] })
    qc.invalidateQueries({ queryKey: offersKey(change.id) })
    qc.invalidateQueries({ queryKey: ['change-my-actions', change.id] })
  }
  const respond = useMutation({
    mutationFn: (vars: { response: string; body?: Parameters<typeof changesApi.customerResponse>[2] }) =>
      changesApi.customerResponse(change.id, vars.response, vars.body),
    onSuccess: () => { setAcceptOpen(false); setDeclineOpen(false); setTalkOpen(false); invalidate() },
    onError: (e: unknown) => toastError(e, 'Could not record the customer response'),
  })
  const signOff = useMutation({
    mutationFn: (role: 'pm' | 'quality') => changesApi.signOff(change.id, role),
    onSuccess: invalidate,
    onError: (e: unknown) => toastError(e, 'Could not record the sign-off'),
  })

  // HARD #4/#9: a signature counts for the offer it was given on; the
  // backend lists a side as owed (next_step) when it is missing or older
  // than the latest offer sent, and signing again is the way out.
  const owed = (side: 'pm' | 'quality') => change.next_step?.items
    .find((i) => i.key === `${side}_signoff` || (i.key === 'release_signoffs' && i.sides?.includes(side)))
  const again = (side: 'pm' | 'quality') => {
    const signed = side === 'pm' ? change.pm_signed_by : change.quality_signed_by
    const row = owed(side)
    return signed && row ? t('signoff.again').replace('{v}', row.detail ?? '') : null
  }
  const samePersonBlocksPm = !change.pm_signed_by
    && !!change.quality_signed_by && userId != null && userId === change.quality_signed_by
  const samePersonBlocksQuality = !change.quality_signed_by
    && !!change.pm_signed_by && userId != null && userId === change.pm_signed_by
  const decided = change.customer_response === 'accepted' || change.customer_response === 'declined'
  const acceptBlocked = !due || (expired && !override.trim()) || respond.isPending
    || (v2 && (!evidenceOk || (!!latestSent && (!match || (match === 'no' && differs.trim().length < 5) || !confirmed))))
  const pick = (which: 'accept' | 'talk' | 'decline') => {
    setAcceptOpen(which === 'accept' ? (o) => !o : false)
    setTalkOpen(which === 'talk' ? (o) => !o : false)
    setDeclineOpen(which === 'decline' ? (o) => !o : false)
  }
  const evidenceFields = (
    <>
      <label className="text-xs text-slate-400 self-center" htmlFor={`answer-mail-${change.id}`}>{t('cust.evidence')}</label>
      <div className="flex flex-wrap gap-2">
        <select id={`answer-mail-${change.id}`} data-testid="answer-mail" value={evidenceId}
          onChange={(e) => setEvidenceId(e.target.value)} className={`${inputCls} min-w-0 flex-1`}>
          <option value="">{t('cust.pickMail')}</option>
          {mails.map((m) => <option key={m.id} value={m.id}>{m.filename}</option>)}
        </select>
        <input type="text" data-testid="answer-ref" value={ref} disabled={!!evidenceId}
          onChange={(e) => setRef(e.target.value)} aria-label={t('cust.ref')}
          placeholder={t('cust.refPlaceholder')} className={`${inputCls} min-w-0 flex-1`} />
      </div>
    </>
  )
  // The backend takes the customer's answer only at quoted, and once accepted
  // nothing about it changes any more.
  const open = change.status === 'quoted'

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
            on v{latestSent.version}{latestSent.valid_until ? `, valid until ${formatCalendarDate(latestSent.valid_until)}` : ''}
          </span>
        )}
        {v2 && change.customer_response === 'negotiating' && change.customer_next_contact && (
          <span data-testid="next-contact" className="text-[11px] text-amber-200">
            {fill('cust.nextContactChip', { d: formatCalendarDate(change.customer_next_contact) })}
          </span>
        )}
        {canRespond && open && !decided && (
          <div className="ml-auto flex gap-2">
            <button type="button" data-testid="customer-accepted" onClick={() => pick('accept')}
              aria-expanded={acceptOpen}
              className={buttonClass(v2 ? 'secondary' : 'primary', 'sm')}>
              Customer accepted
            </button>
            {v2 && (
              <button type="button" data-testid="customer-talking" onClick={() => pick('talk')}
                aria-expanded={talkOpen} className={buttonClass('secondary', 'sm')}>
                {t('cust.talking')}
              </button>
            )}
            <button type="button" data-testid="customer-declined" disabled={respond.isPending}
              aria-expanded={declineOpen}
              onClick={() => pick('decline')}
              className={buttonClass('secondary', 'sm')}>
              Customer declined
            </button>
          </div>
        )}
      </div>

      {talkOpen && (
        <div data-testid="talk-box" className="grid gap-2 rounded-lg border border-amber-900/70 bg-amber-950/20 p-3 sm:grid-cols-[auto_minmax(0,1fr)]">
          <label htmlFor={`talk-next-${change.id}`} className="text-xs text-slate-400 self-center">{t('cust.nextContact')}</label>
          <DateInput id={`talk-next-${change.id}`} value={nextContact} commitOnChange
            onChange={setNextContact} className={`${inputCls} w-44`} />
          <label className="text-xs text-slate-400 self-center">{t('customer.releaseDueReason')}</label>
          <input type="text" value={talkNote} onChange={(e) => setTalkNote(e.target.value)}
            aria-label={t('cust.talkNote')} placeholder={t('cust.talkNote')} className={inputCls} />
          <p className="text-xs text-slate-400 sm:col-span-2">{t('cust.talkHelp')}</p>
          <div className="sm:col-span-2 flex justify-end">
            <button type="button" data-testid="talk-confirm" disabled={!nextContact || respond.isPending}
              onClick={() => respond.mutate({ response: 'negotiating', body: {
                next_contact: nextContact, ...(talkNote.trim() ? { note: talkNote.trim() } : {}) } })}
              className={buttonClass('primary', 'sm')}>
              {t('cust.talkConfirm')}
            </button>
          </div>
        </div>
      )}

      {declineOpen && (
        <div data-testid="decline-confirm-box" role="alertdialog" aria-label="Confirm customer declined"
          className="space-y-2 rounded-lg border border-rose-900/70 bg-rose-950/20 p-3">
          <p className="text-xs text-rose-200">
            {v2 ? t('cust.declineText')
              : 'Recording that the customer declined cannot be undone. The offer is closed and the change cannot be approved on it any more.'}
          </p>
          {v2 && <div className="grid gap-2 sm:grid-cols-[auto_minmax(0,1fr)]">{evidenceFields}</div>}
          <div className="flex justify-end gap-2">
            <button type="button" onClick={() => setDeclineOpen(false)}
              className={buttonClass('secondary', 'sm')}>
              Cancel
            </button>
            <button type="button" data-testid="decline-confirm" disabled={respond.isPending || (v2 && !evidenceOk)}
              onClick={() => respond.mutate(v2 ? { response: 'declined', body: evidence } : { response: 'declined' })}
              className={buttonClass('danger', 'sm')}>
              Yes, the customer declined
            </button>
          </div>
        </div>
      )}

      {acceptOpen && (
        <div data-testid="accept-box" className="grid gap-2 rounded-lg border border-emerald-900/70 bg-emerald-950/20 p-3 sm:grid-cols-[auto_minmax(0,1fr)]">
          {v2 && evidenceFields}
          {v2 && latestSent && (
            <>
              <span className="text-xs text-slate-400 self-center">{fill('cust.poMatch', { v: latestSent.version })}</span>
              <div role="radiogroup" aria-label={fill('cust.poMatch', { v: latestSent.version })} className="flex gap-3 text-xs text-slate-200">
                {(['yes', 'no'] as const).map((m) => (
                  <label key={m} className="flex items-center gap-1">
                    <input type="radio" name={`po-match-${change.id}`} data-testid={`po-match-${m}`}
                      checked={match === m} onChange={() => setMatch(m)} />
                    {t(`cust.poMatch.${m}`)}
                  </label>
                ))}
              </div>
              {match === 'no' && (
                <>
                  <label className="text-xs text-slate-400 self-center">{t('cust.differs')}</label>
                  <textarea rows={2} data-testid="answer-differs" value={differs}
                    onChange={(e) => setDiffers(e.target.value)} aria-label={t('cust.differs')}
                    placeholder={t('cust.differsPlaceholder')} className={inputCls} />
                </>
              )}
              {(latestSent.index_changes ?? []).length > 0 && (
                <p data-testid="accept-index-warning" className="text-xs text-amber-300 sm:col-span-2">
                  {fill('cust.indexWarn', { v: latestSent.version, list: (latestSent.index_changes ?? [])
                    .map((i) => `${i.number} ${i.offer || '-'} → ${i.now || '-'}`).join(', ') })}
                </p>
              )}
            </>
          )}
          <label htmlFor={`accept-release-due-${change.id}`} className="text-xs text-slate-400 self-center">{t('customer.releaseDue')}</label>
          <DateInput id={`accept-release-due-${change.id}`} value={due} commitOnChange
            onChange={setDue} className={`${inputCls} w-44`} />
          <label className="text-xs text-slate-400 self-center">{t('customer.releaseDueReason')}</label>
          <input type="text" value={reason} onChange={(e) => setReason(e.target.value)}
            aria-label={t('customer.releaseDueReason')} className={inputCls} />
          {expired && (
            <>
              <p data-testid="accept-expired" className="text-xs text-rose-300 sm:col-span-2">
                Offer v{latestSent?.version} expired on {formatCalendarDate(latestSent?.valid_until)}. Accepting it needs a reason on the record.
              </p>
              <label className="text-xs text-slate-400 self-center">Override reason</label>
              <input type="text" data-testid="accept-override" value={override}
                onChange={(e) => setOverride(e.target.value)} className={inputCls}
                placeholder="e.g. customer confirmed the price in writing on 2 Oct" />
            </>
          )}
          {v2 && latestSent && (
            <label className="flex items-start gap-2 text-xs text-slate-200 sm:col-span-2">
              <input type="checkbox" data-testid="accept-total" checked={confirmed}
                onChange={(e) => setConfirmed(e.target.checked)} />
              {fill('cust.confirmTotal', { v: latestSent.version, t: total })}
            </label>
          )}
          <div className="sm:col-span-2 flex justify-end">
            <button type="button" data-testid="accept-confirm"
              disabled={acceptBlocked}
              onClick={() => respond.mutate({
                response: 'accepted',
                body: {
                  release_due_date: `${due}T23:59:59Z`,
                  release_due_reason: reason || null,
                  ...(expired ? { expired_override_reason: override.trim() } : {}),
                  ...(v2 ? { ...evidence, ...(latestSent ? {
                    po_match: match || undefined, confirm_total: confirmed,
                    ...(match === 'no' ? { differs: differs.trim() } : {}) } : {}) } : {}),
                },
              })}
              className={buttonClass('primary', 'sm')}>
              {t('customer.confirmAccept')}
            </button>
          </div>
        </div>
      )}

      {(canSignPm || canSignQuality) && (
        <div className="flex flex-wrap items-center gap-2">
          {canSignPm && (
            <button type="button" data-testid="signoff-pm"
              disabled={(!!change.pm_signed_by && !again('pm')) || samePersonBlocksPm || signOff.isPending}
              onClick={() => signOff.mutate('pm')}
              className={`rounded-lg border px-3 py-1 text-xs disabled:cursor-not-allowed ${change.pm_signed_by && !again('pm')
                ? 'border-emerald-800 bg-emerald-950/40 text-emerald-200' : 'border-slate-600 text-slate-200 hover:bg-slate-700 disabled:opacity-50'}`}>
              {again('pm') ? `PM: ${again('pm')}` : 'PM sign-off'}
              {change.pm_signed_by && !again('pm') && <Check aria-label="done" size={12} strokeWidth={3} className="ml-1 inline" />}
            </button>
          )}
          {canSignQuality && (
            <button type="button" data-testid="signoff-quality"
              disabled={(!!change.quality_signed_by && !again('quality')) || samePersonBlocksQuality || signOff.isPending}
              onClick={() => signOff.mutate('quality')}
              className={`rounded-lg border px-3 py-1 text-xs disabled:cursor-not-allowed ${change.quality_signed_by && !again('quality')
                ? 'border-emerald-800 bg-emerald-950/40 text-emerald-200' : 'border-slate-600 text-slate-200 hover:bg-slate-700 disabled:opacity-50'}`}>
              {again('quality') ? `Quality: ${again('quality')}` : 'Quality sign-off'}
              {change.quality_signed_by && !again('quality') && <Check aria-label="done" size={12} strokeWidth={3} className="ml-1 inline" />}
            </button>
          )}
        </div>
      )}
      {(samePersonBlocksPm || samePersonBlocksQuality) && (
        <p className="text-xs text-amber-300">PM and Quality sign-off must be different users</p>
      )}
      <p data-testid="signers" className="text-[11px] text-slate-400">
        {t('cust.signPm')}: {change.pm_signed_by_name
          ? `${change.pm_signed_by_name}${change.pm_signed_at ? `, ${formatCalendarDate(change.pm_signed_at)}` : ''}${signedVersion(change.pm_signed_offer_id)}`
          : t('cust.signPending')}
        {' · '}
        {t('cust.signQuality')}: {change.quality_signed_by_name
          ? `${change.quality_signed_by_name}${change.quality_signed_at ? `, ${formatCalendarDate(change.quality_signed_at)}` : ''}${signedVersion(change.quality_signed_offer_id)}`
          : t('cust.signPending')}
      </p>
      <p className="text-[11px] text-slate-500">
        {v2 ? t('cust.approvalAuto')
          : "Approval needs the customer's acceptance and both sign-offs. The approve button is in the cockpit above."}
      </p>
    </div>
  )
}
