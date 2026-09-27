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
import type { OfferDiffRow, OfferOut } from '../../../types/changeOffer'
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
  const receivedId = useId()
  const noteId = useId()
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
    onError: (e: unknown) => toastError(e, 'Could not send the offer'),
  })

  const blocked = !offer || !receivedOk || (needsNote && !note.trim()) || send.isPending
  if (!offer) return null

  return (
    <Dialog open onClose={onClose} busy={send.isPending} closeOnBackdrop={false} size="md"
      data-testid="send-offer-dialog"
      title={`Send offer v${offer.version}`}
      description={<>
        Total <span className="tabular-nums text-slate-100">{fmtMoney(offer.totals.total_one_time, offer.currency)}</span>.
        Sending sets the quoted price and moves the change to Quoted.
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
