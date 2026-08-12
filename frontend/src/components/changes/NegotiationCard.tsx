/**
 * What happened to the price after the offer went out.
 *
 * Between `quoted` and the customer's go-ahead there is a conversation nobody
 * records: a call here, a meeting there, a mail with a number in it. This card
 * is that conversation in order — each round with its channel, what came out of
 * it and the price the customer countered with — ending in the one entry Sales
 * marks as the final result.
 *
 * It deliberately decides nothing. The go-ahead stays where it already lives,
 * in customer acceptance with its release deadline; once a final result is on
 * the card, the hint points there rather than growing a second decision button.
 */
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { changesApi } from '../../api/changes'
import { useAuth } from '../../contexts/AuthContext'
import { t } from '../../i18n/cmLabels'
import type { ChangeNegotiation, NegotiationChannel } from '../../types/change'

const errDetail = (e: unknown): string | undefined =>
  (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail

const CHANNELS: NegotiationChannel[] = ['meeting', 'call', 'email']

const channelLabel = (c: string) => t(`negotiation.channel.${c}`)

export default function NegotiationCard({
  changeId, status, canWrite = false,
}: {
  changeId: number
  /** The change's status: entries may only be added or dropped while quoted. */
  status: string
  /** Sales, the change lead or an admin — the page derives it, mirroring the
   *  backend's POST gate. */
  canWrite?: boolean
}) {
  const qc = useQueryClient()
  const { userId, username } = useAuth()
  const [adding, setAdding] = useState(false)
  const [channel, setChannel] = useState<NegotiationChannel>('meeting')
  const [note, setNote] = useState('')
  const [counter, setCounter] = useState('')
  const [isFinal, setIsFinal] = useState(false)
  // A refused round says why in place: the typed note must survive the error.
  const [failure, setFailure] = useState<string | null>(null)

  const { data: rounds = [] } = useQuery({
    queryKey: ['change', changeId, 'negotiations'],
    queryFn: () => changesApi.listNegotiations(changeId),
  })

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ['change', changeId, 'negotiations'] })
    qc.invalidateQueries({ queryKey: ['change', changeId] })
  }

  // Negotiating is only open while the offer is out. Later the log is history.
  const open = status === 'quoted'
  const editable = canWrite && open

  const add = useMutation({
    mutationFn: () => {
      const price = counter.trim()
      return changesApi.addNegotiation(changeId, {
        channel,
        note: note.trim(),
        ...(price !== '' && !Number.isNaN(Number(price)) ? { counter_price: Number(price) } : {}),
        ...(isFinal ? { is_final: true } : {}),
      })
    },
    onSuccess: () => {
      setNote(''); setCounter(''); setIsFinal(false)
      setAdding(false); setFailure(null); invalidate()
    },
    onError: (e: unknown) => {
      const detail = errDetail(e) ?? 'Could not save the round'
      setFailure(detail)
      toast.error(detail)
    },
  })

  const drop = useMutation({
    mutationFn: (negotiationId: number) => changesApi.deleteNegotiation(changeId, negotiationId),
    onSuccess: () => { setFailure(null); invalidate() },
    onError: (e: unknown) => {
      const detail = errDetail(e) ?? 'Could not delete the round'
      setFailure(detail)
      toast.error(detail)
    },
  })

  // Only your own round is yours to drop. `userId != null` matters: without it
  // an unloaded session and a payload with a null author compare equal and the
  // control unlocks for everyone.
  const isMine = (r: ChangeNegotiation) =>
    (r.created_by != null && userId != null && r.created_by === userId)
    || (r.created_by == null && !!username && r.created_by_name === username)

  // A negotiation reads forward: oldest round first, the result at the end.
  const ordered = [...rounds].sort((a, b) => a.created_at.localeCompare(b.created_at))
  const final = ordered.find((r) => r.is_final)

  return (
    <section data-testid="negotiation-card"
      className="rounded-lg border border-slate-700 bg-slate-800 p-3 space-y-2">
      <div className="flex items-center gap-2 flex-wrap">
        <span className="font-medium text-slate-100">{t('negotiation.title')}</span>
        {ordered.length > 0 && (
          <span data-testid="negotiation-count"
            className="text-[10px] leading-tight rounded bg-slate-700 text-slate-300 px-1.5 py-0">
            {ordered.length}
          </span>
        )}
        {editable && !adding && (
          <button type="button" data-testid="negotiation-add"
            className="ml-auto text-xs text-sky-300 hover:text-sky-200"
            onClick={() => { setFailure(null); setAdding(true) }}>
            + {t('negotiation.add')}
          </button>
        )}
      </div>
      <p className="text-[11px] text-slate-500">{t('negotiation.hint')}</p>

      {ordered.length === 0 ? (
        <p className="text-xs text-slate-500" data-testid="negotiation-none">
          {t('negotiation.none')}
        </p>
      ) : (
        <ol className="space-y-1">
          {ordered.map((r) => (
            <li key={r.id} data-testid={`negotiation-round-${r.id}`}
              className={`rounded border px-2 py-1.5 text-sm ${
                r.is_final
                  ? 'border-emerald-700 bg-emerald-950/30 text-emerald-50'
                  : 'border-slate-700 bg-slate-900/40 text-slate-200'}`}>
              <div className="flex items-center gap-2 flex-wrap">
                <span className="text-xs text-slate-400 tabular-nums">
                  {r.created_at.slice(0, 10)}
                </span>
                <span data-testid={`negotiation-channel-${r.id}`}
                  className="inline-flex items-center rounded border border-slate-600 bg-slate-800 px-1.5 py-0 text-[10px] leading-tight text-slate-200">
                  {channelLabel(r.channel)}
                </span>
                {r.is_final && (
                  <span data-testid={`negotiation-final-badge-${r.id}`}
                    className="inline-flex items-center rounded border border-emerald-700 bg-emerald-900/80 px-1.5 py-0 text-[10px] leading-tight font-semibold text-emerald-100">
                    {t('negotiation.final')}
                  </span>
                )}
                {r.counter_price != null && (
                  <span data-testid={`negotiation-price-${r.id}`}
                    className={r.is_final
                      ? 'ml-auto tabular-nums text-base font-semibold text-emerald-100'
                      : 'ml-auto tabular-nums text-slate-300'}>
                    {r.counter_price.toFixed(2)}
                  </span>
                )}
              </div>
              <p className="mt-0.5">{r.note}</p>
              <div className="flex items-center gap-2 flex-wrap">
                <span className="text-xs text-slate-400">{r.created_by_name ?? '—'}</span>
                {editable && isMine(r) && (
                  <button type="button" data-testid={`negotiation-delete-${r.id}`}
                    className="text-xs text-slate-400 hover:text-slate-200 underline decoration-dotted disabled:opacity-50"
                    disabled={drop.isPending}
                    onClick={() => drop.mutate(r.id)}>
                    {t('negotiation.delete')}
                  </button>
                )}
              </div>
            </li>
          ))}
        </ol>
      )}

      {/* The result is stated once, on its own line, and then hands over to the
          acceptance controls that already carry the release deadline. */}
      {final && (
        <div data-testid="negotiation-outcome"
          className="rounded border border-emerald-800/60 bg-emerald-950/20 px-2 py-1.5">
          {final.counter_price != null && (
            <p className="flex items-baseline gap-2">
              <span className="text-slate-400 text-xs">{t('negotiation.finalPrice')}:</span>
              <span className="tabular-nums text-emerald-100 font-semibold"
                data-testid="negotiation-final-price">
                {final.counter_price.toFixed(2)}
              </span>
            </p>
          )}
          <p className="text-[11px] text-emerald-200/80" data-testid="negotiation-goahead-hint">
            {t('negotiation.goAheadHint')}
          </p>
        </div>
      )}

      {failure && (
        <p role="alert" data-testid="negotiation-error"
          className="rounded border border-red-800/60 bg-red-950/40 px-2 py-1 text-xs text-red-200">
          {failure}
        </p>
      )}

      {adding && (
        <div className="space-y-2" data-testid="negotiation-form">
          <div className="flex gap-2 items-center flex-wrap">
            <select value={channel} aria-label={t('negotiation.channel')}
              data-testid="negotiation-channel-select"
              onChange={(e) => setChannel(e.target.value as NegotiationChannel)}
              className="bg-slate-900 border border-slate-600 rounded px-2 py-1 text-xs text-slate-100">
              {CHANNELS.map((c) => (
                <option key={c} value={c}>{channelLabel(c)}</option>
              ))}
            </select>
            <input type="number" step="0.01" value={counter}
              aria-label={t('negotiation.counterPrice')}
              placeholder={t('negotiation.counterPrice')}
              data-testid="negotiation-counter-price"
              onChange={(e) => setCounter(e.target.value)}
              className="bg-slate-900 border border-slate-600 rounded px-2 py-1 text-xs text-slate-100 w-32" />
          </div>
          <textarea value={note} rows={2} onChange={(e) => setNote(e.target.value)}
            placeholder={t('negotiation.notePlaceholder')} aria-label={t('negotiation.note')}
            data-testid="negotiation-note"
            className="w-full bg-slate-900 border border-slate-600 rounded px-2 py-1 text-xs text-slate-100" />
          <label className="flex items-center gap-2 text-xs cursor-pointer">
            <input type="checkbox" data-testid="negotiation-final-check"
              checked={isFinal} onChange={(e) => setIsFinal(e.target.checked)} />
            <span className="text-slate-300">{t('negotiation.isFinal')}</span>
          </label>
          <div className="flex gap-2 items-center">
            <button type="button" data-testid="negotiation-submit"
              className="bg-sky-600 hover:bg-sky-500 text-white px-2.5 py-1 rounded text-xs disabled:opacity-50 disabled:cursor-not-allowed"
              disabled={!note.trim() || add.isPending}
              onClick={() => add.mutate()}>
              {t('negotiation.submit')}
            </button>
            <button type="button" className="text-xs text-slate-400 hover:text-slate-200 px-1"
              onClick={() => { setAdding(false); setNote(''); setCounter(''); setFailure(null) }}>
              {t('common.cancel')}
            </button>
          </div>
        </div>
      )}
    </section>
  )
}
