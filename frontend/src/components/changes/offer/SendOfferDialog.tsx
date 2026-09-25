/**
 * Sending a version: the customer's receipt date starts the 30-day validity,
 * and from v2 on Sales says in words what changed (the server's diff is shown
 * next to it, so the note can be checked against the numbers).
 */
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { changeOfferApi } from '../../../api/changeOffer'
import type { OfferDiffRow, OfferOut } from '../../../types/changeOffer'
import { addDaysIso, diffLabel, diffValue, fmtDate, fmtMoney, inputCls, todayIso } from './offerFormat'
import { offersKey } from './useOfferDraft'

const errDetail = (e: unknown): string | undefined =>
  (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail

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

export default function SendOfferDialog({
  changeId, offerId, fallback, onClose,
}: {
  changeId: number
  offerId: number
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
  const [received, setReceived] = useState(todayIso())
  const [note, setNote] = useState('')
  // Printed on the offer; lives in the draft, so it is saved before sending.
  const [customerNote, setCustomerNote] = useState(offer?.data?.customer_note ?? '')
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
      })
    },
    onSuccess: () => {
      toast.success(`Offer v${offer?.version ?? ''} sent`)
      qc.invalidateQueries({ queryKey: offersKey(changeId) })
      qc.invalidateQueries({ queryKey: ['change', changeId] })
      qc.invalidateQueries({ queryKey: ['change-my-actions', changeId] })
      onClose()
    },
    onError: (e: unknown) => toast.error(errDetail(e) ?? 'Could not send the offer'),
  })

  const blocked = !offer || !receivedOk || (needsNote && !note.trim()) || send.isPending
  if (!offer) return null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" role="dialog"
      aria-label="Send offer">
      <div className="w-full max-w-lg rounded-xl border border-slate-700 bg-slate-800 p-5 shadow-2xl">
        <h3 className="text-base font-semibold text-slate-100">Send offer v{offer.version}</h3>
        <p className="mt-1 text-sm text-slate-400">
          Total <span className="tabular-nums text-slate-100">{fmtMoney(offer.totals.total_one_time, offer.currency)}</span>.
          Sending sets the quoted price and moves the change to Quoted.
        </p>

        <label className="mt-4 block">
          <span className="mb-1 block text-xs text-slate-400">Received by the customer on</span>
          <input type="date" data-testid="send-received" value={received} max={today} min={earliest}
            onChange={(e) => setReceived(e.target.value)} className={inputCls} />
        </label>
        {received && !receivedOk && (
          <p data-testid="send-received-invalid" className="mt-1 text-xs text-rose-300">
            {received > today ? 'The receipt date cannot be in the future.' : 'The receipt date cannot be more than 60 days ago.'}
          </p>
        )}
        <p data-testid="send-valid-until" className="mt-2 rounded-lg border border-sky-900 bg-sky-950/40 px-3 py-2 text-xs text-sky-200">
          The offer is valid 30 days from receipt, until {fmtDate(validUntil)}.
        </p>

        {(offer.warnings ?? []).length > 0 && (
          <ul data-testid="send-warnings" className="mt-3 space-y-1">
            {(offer.warnings ?? []).map((w, i) => (
              <li key={`${w.code}-${i}`} className="text-xs text-amber-300">⚠ {w.message}</li>
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
            <span className="mb-1 block text-xs text-slate-400">What changed against the last version? (internal, not printed; required)</span>
            {(offer.diff?.length ?? 0) > 0 && (
              <div className="mb-2 rounded-lg border border-slate-700 bg-slate-900/60 px-3 py-2">
                <DiffList diff={offer.diff ?? []} testId="send-diff" currency={offer.currency || 'EUR'} />
              </div>
            )}
            <textarea rows={3} data-testid="send-note" value={note} onChange={(e) => setNote(e.target.value)}
              placeholder="e.g. Margin reduced to 8 %, bank build added, timing 2 weeks shorter"
              className={`${inputCls} w-full`} />
          </div>
        )}

        <div className="mt-5 flex justify-end gap-2">
          <button type="button" onClick={onClose}
            className="rounded-lg border border-slate-600 px-3 py-1.5 text-sm text-slate-300 hover:bg-slate-700">Cancel</button>
          <button type="button" data-testid="send-confirm" disabled={blocked}
            onClick={() => send.mutate()}
            className="rounded-lg bg-sky-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-sky-500 disabled:opacity-50">
            Send offer
          </button>
        </div>
      </div>
    </div>
  )
}
