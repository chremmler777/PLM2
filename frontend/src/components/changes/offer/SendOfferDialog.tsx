/**
 * Sending a version: the customer's receipt date starts the 30-day validity,
 * and from v2 on Sales says in words what changed (the server's diff is shown
 * next to it, so the note can be checked against the numbers).
 */
import { useId, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { CircleAlert } from 'lucide-react'
import { changeOfferApi } from '../../../api/changeOffer'
import { toastError } from '../../../lib/apiError'
import { formatCalendarDate } from '../../../lib/format'
import Dialog from '../../common/Dialog'
import Button from '../../common/Button'
import DateInput from '../../gantt/DateInput'
import { HIGH_RISK_SEND_REASONS, NO_RATE_SEND_REASONS } from '../../../types/changeOffer'
import type { OfferDiffRow, OfferOut, OfferSendList } from '../../../types/changeOffer'
import { t } from '../../../i18n/cmLabels'
import { addDaysIso, diffLabel, diffValue, fmtMoney, inputCls, todayIso } from './offerFormat'
import { offersKey } from './useOfferDraft'

export function DiffList({ diff, testId, currency = 'EUR' }: { diff: OfferDiffRow[]; testId?: string; currency?: string }) {
  if (diff.length === 0) return null
  return (
    <ul data-testid={testId} className="space-y-0.5 text-[11px]">
      {diff.map((d) => (
        <li key={d.field} className="flex flex-wrap items-baseline gap-1.5">
          <span className="text-slate-400">{diffLabel(d.field)}</span>
          <span className="tabular-nums text-slate-500 line-through">{diffValue(d.field, d.before, currency)}</span>
          <span className="text-slate-600">→</span>
          <span className="tabular-nums text-slate-200">{diffValue(d.field, d.after, currency)}</span>
        </li>
      ))}
    </ul>
  )
}

/** Spec §6 [R3]: what goes out unconfirmed: the Assumed answers, the
 *  estimated positions and the high risks the offer does not price. */
export function SendList({ list }: { list: OfferSendList }) {
  const fill = (k: string, v: Record<string, string | number>) =>
    Object.entries(v).reduce((acc, [kk, vv]) => acc.split(`{${kk}}`).join(String(vv)), t(k))
  const carried = list.carried_risks ?? []
  if (!list.assumed.length && !list.estimates.length && !list.high_risks.length && !carried.length) return null
  return (
    <div data-testid="send-list" className="mt-3 space-y-2 rounded-lg border border-amber-900/70 bg-amber-950/20 px-3 py-2 text-xs">
      <p className="font-medium text-amber-200">{t('send.listTitle')}</p>
      {list.assumed.length > 0 && (
        <div>
          <p className="text-amber-200">{fill('send.assumed', { n: list.assumed.length })}</p>
          <ul data-testid="send-assumed" className="ml-4 list-disc text-slate-300">
            {list.assumed.map((a) => (
              <li key={a.concern_id}>{fill('send.assumedRow', {
                v: a.value || 'n/a', q: a.text, r: a.risk || '-',
                w: a.confirm_by_name || t('send.nobody'),
                d: a.confirm_due ? formatCalendarDate(a.confirm_due) : '-',
              })}</li>
            ))}
          </ul>
        </div>
      )}
      {list.estimates.length > 0 && (
        <p data-testid="send-estimates" className="text-slate-300">
          <span className="text-amber-200">{fill('send.estimates', { n: list.estimates.length })}: </span>
          {list.estimates.join(', ')}
        </p>
      )}
      {list.high_risks.length > 0 && (
        <div>
          <p className="text-rose-300">{fill('send.highRisks', { n: list.high_risks.length })}</p>
          <ul className="ml-4 list-disc text-slate-300">
            {list.high_risks.map((r) => <li key={r.concern_id}>{r.note}</li>)}
          </ul>
        </div>
      )}
      {carried.length > 0 && (
        <div data-testid="send-carried">
          <p className="text-amber-200">{fill('send.carried', { n: carried.length })}</p>
          <ul className="ml-4 list-disc text-slate-300">
            {carried.map((r) => (
              <li key={r.concern_id}>{fill('send.carriedRow', { q: r.note, v: r.version ?? '-', r: r.reason ?? '-' })}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}

export default function SendOfferDialog({
  changeId, offerId, fallback, onClose, changeStatus,
}: {
  changeId: number
  offerId: number
  /** What the send does to the status (quoting: Quoted; else it stays). */
  changeStatus?: string
  /** Shown only until the cached list has the offer. */
  fallback?: OfferOut
  onClose: () => void
}) {
  const qc = useQueryClient()
  // The offer as the server last saved it (fresh totals), straight from the
  // cache the draft hook writes every save into.
  const { data: cached } = useQuery({
    queryKey: offersKey(changeId),
    queryFn: () => changeOfferApi.list(changeId),
    staleTime: Infinity,
    select: (list: OfferOut[]) => list.find((o) => o.id === offerId),
  })
  const offer = cached ?? fallback
  const receivedId = useId()
  const noteId = useId()
  const [received, setReceived] = useState(todayIso())
  const [note, setNote] = useState('')
  // Printed on the offer; lives in the draft, so it is saved before sending.
  const [customerNote, setCustomerNote] = useState(offer?.data?.customer_note ?? '')
  const [riskCode, setRiskCode] = useState('')
  const [riskNote, setRiskNote] = useState('')
  const highRisks = offer?.send_list?.high_risks.length ?? 0
  const riskOk = highRisks === 0 || (!!riskCode && riskNote.trim().length >= 15)
  // F3 (SOFT): hours without a labour rate are not in the price; send only with a reason
  const unrated = (offer?.warnings ?? []).filter((w) => w.code === 'no_rate_department')
  const [rateCode, setRateCode] = useState('')
  const [rateNote, setRateNote] = useState('')
  const rateOk = unrated.length === 0 || (!!rateCode && rateNote.trim().length >= 15)
  const today = todayIso()
  const earliest = addDaysIso(today, -60)
  const receivedOk = !!received && received <= today && received >= earliest
  const needsNote = (offer?.version ?? 1) >= 2
  const validUntil = received ? addDaysIso(received, 30) : null

  const send = useMutation({
    mutationFn: async () => {
      if ((customerNote.trim() || null) !== ((offer?.data?.customer_note ?? '').trim() || null)) {
        const saved = await changeOfferApi.patch(changeId, offerId, { data: { customer_note: customerNote.trim() || null } })
        qc.setQueryData<OfferOut[]>(offersKey(changeId), (old) => (old ?? []).map((o) => (o.id === saved.id ? saved : o)))
      }
      return changeOfferApi.send(changeId, offerId, {
        received_at: received,
        ...(note.trim() ? { change_note: note.trim() } : {}),
        ...(highRisks ? { risk_reason_code: riskCode, risk_reason: riskNote.trim() } : {}),
        ...(unrated.length ? { rate_reason_code: rateCode, rate_reason: rateNote.trim() } : {}),
      })
    },
    onSuccess: () => {
      toast.success(`Offer v${offer?.version ?? ''} sent`)
      qc.invalidateQueries({ queryKey: offersKey(changeId) })
      qc.invalidateQueries({ queryKey: ['change', changeId] })
      qc.invalidateQueries({ queryKey: ['change-my-actions', changeId] })
      onClose()
    },
    onError: (e: unknown) => toastError(e, 'Could not send the offer'),
  })

  const blocked = !offer || !receivedOk || (needsNote && !note.trim()) || !riskOk || !rateOk || send.isPending
  if (!offer) return null

  return (
    <Dialog open onClose={onClose} busy={send.isPending} closeOnBackdrop={false} size="md"
      data-testid="send-offer-dialog"
      title={offer.kind === 'supplement' ? `${t('supp.send')} v${offer.version}` : `Send offer v${offer.version}`}
      description={<>
        Total <span className="tabular-nums text-slate-100">{fmtMoney(offer.totals.total_one_time, offer.currency)}</span>.
        {' '}{offer.kind === 'supplement' ? t('supp.sendText')
          : changeStatus === 'quoting' || changeStatus == null
            ? 'Sending sets the quoted price and moves the change to Quoted.'
            : 'Sending sets the quoted price; the change keeps its status, the customer answers this version.'}
      </>}
      footer={(
        <>
          <Button onClick={onClose} disabled={send.isPending}>Cancel</Button>
          <Button variant="primary" data-testid="send-confirm" disabled={blocked} loading={send.isPending}
            onClick={() => send.mutate()}>
            Send offer
          </Button>
        </>
      )}>
      <div>
        <label htmlFor={receivedId} className="mb-1 block text-xs text-slate-400">Received by the customer on</label>
        <DateInput id={receivedId} value={received} commitOnChange
          aria-label="Received by the customer on"
          onChange={setReceived} className={`${inputCls} w-44`} />
      </div>
      {received && !receivedOk && (
        <p data-testid="send-received-invalid" role="alert" className="mt-1 text-xs text-rose-300">
          {received > today ? 'The receipt date cannot be in the future.' : 'The receipt date cannot be more than 60 days ago.'}
        </p>
      )}
      <p data-testid="send-valid-until" className="mt-2 rounded-lg border border-sky-900 bg-sky-950/40 px-3 py-2 text-xs text-sky-200">
        The offer is valid 30 days from receipt, until {formatCalendarDate(validUntil)}.
      </p>

      {(offer.indexes ?? []).length > 0 && (
        <p data-testid="send-indexes" className="mt-3 text-xs text-slate-400">
          {t('send.goesOutOn')}:{' '}
          {(offer.indexes ?? []).map((i, n) => (
            <span key={`${i.number}-${n}`} className="mr-2 text-slate-200">
              {i.number} <span className="font-medium">{i.index || '-'}</span>
              {i.newer && <span className="text-amber-300"> ({t('send.newer').replace('{i}', i.newer.index)})</span>}
            </span>
          ))}
        </p>
      )}

      {offer.send_list && <SendList list={offer.send_list} />}
      {highRisks > 0 && (
        <div className="mt-2 space-y-1">
          <p className="text-xs text-slate-400">{t('send.highRiskHelp')}</p>
          <select data-testid="send-risk-code" aria-label={t('send.riskReason')} value={riskCode}
            onChange={(e) => setRiskCode(e.target.value)} className={`${inputCls} w-full`}>
            <option value="">{t('send.riskReason')}…</option>
            {HIGH_RISK_SEND_REASONS.map((c) => <option key={c} value={c}>{t(`send.riskReason.${c}`)}</option>)}
          </select>
          <textarea rows={2} data-testid="send-risk-note" value={riskNote} aria-label={t('send.riskNote')}
            onChange={(e) => setRiskNote(e.target.value)} placeholder={t('send.riskNote')}
            className={`${inputCls} w-full`} />
        </div>
      )}

      {unrated.length > 0 && (
        <div data-testid="send-no-rate" className="mt-3 space-y-1">
          <p className="text-xs text-rose-300">{t('send.noRateHelp')}</p>
          <select data-testid="send-rate-code" aria-label={t('send.riskReason')} value={rateCode}
            onChange={(e) => setRateCode(e.target.value)} className={`${inputCls} w-full`}>
            <option value="">{t('send.riskReason')}…</option>
            {NO_RATE_SEND_REASONS.map((c) => <option key={c} value={c}>{t(`send.rateReason.${c}`)}</option>)}
          </select>
          <textarea rows={2} data-testid="send-rate-note" value={rateNote} aria-label={t('send.riskNote')}
            onChange={(e) => setRateNote(e.target.value)} placeholder={t('send.riskNote')}
            className={`${inputCls} w-full`} />
        </div>
      )}

      {(offer.warnings ?? []).length > 0 && (
        <ul data-testid="send-warnings" className="mt-3 space-y-1">
          {(offer.warnings ?? []).map((w, i) => (
            <li key={`${w.code}-${i}`} className="flex items-start gap-1.5 text-xs text-amber-300">
              <CircleAlert aria-hidden="true" size={13} className="mt-px shrink-0" />{w.message}
            </li>
          ))}
        </ul>
      )}

      <label className="mt-4 block">
        <span className="mb-1 block text-xs text-slate-400">
          Note to the customer (optional, printed on the offer)
        </span>
        <textarea rows={2} data-testid="send-customer-note" value={customerNote}
          onChange={(e) => setCustomerNote(e.target.value)}
          placeholder="e.g. This version includes the bank build you asked for."
          className={`${inputCls} w-full`} />
      </label>

      {needsNote && (
        <div className="mt-4">
          <label htmlFor={noteId} className="mb-1 block text-xs text-slate-400">
            What changed against the last version? (internal, not printed; required)
          </label>
          {(offer.diff?.length ?? 0) > 0 && (
            <div className="mb-2 rounded-lg border border-slate-700 bg-slate-900/60 px-3 py-2">
              <DiffList diff={offer.diff ?? []} testId="send-diff" currency={offer.currency || 'EUR'} />
            </div>
          )}
          <textarea id={noteId} rows={3} data-testid="send-note" value={note} onChange={(e) => setNote(e.target.value)}
            placeholder="e.g. Margin reduced to 8%, bank build added, timing 2 weeks shorter"
            className={`${inputCls} w-full`} />
        </div>
      )}
    </Dialog>
  )
}
