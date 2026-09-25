import { useCallback, useEffect, useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { changeOfferApi } from '../../../api/changeOffer'
import type { OfferData, OfferOut } from '../../../types/changeOffer'

export type SaveState = 'idle' | 'pending' | 'saving' | 'saved' | 'error'

export const offersKey = (changeId: number) => ['change', changeId, 'offers'] as const

const errDetail = (e: unknown): string | undefined =>
  (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail

/**
 * The draft being edited: local data for instant typing, one debounced PATCH
 * (500 ms) with every top-level key touched since the last save. The server's
 * answer replaces the cached offer, so totals always come from the server.
 *
 * Saves are serialized: one PATCH in flight at a time. Keys touched while it
 * runs are coalesced into the next PATCH, which starts only after the previous
 * one answered, so answers can never land out of order (list keys replace
 * whole arrays, a stale answer would lose rows). Local data is re-synced from
 * the server only when nothing is pending or in flight, so a save landing
 * mid-typing never eats keystrokes.
 *
 * `flush()` resolves once everything typed so far is saved: true on success,
 * false when a save failed (the keys stay pending and the next edit retries).
 */
export function useOfferDraft(changeId: number, offer: OfferOut | undefined, delay = 500) {
  const qc = useQueryClient()
  const [data, setData] = useState<OfferData>(offer?.data ?? {})
  const [saveState, setSaveState] = useState<SaveState>('idle')
  const pending = useRef<Partial<OfferData>>({})
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const running = useRef<Promise<boolean> | null>(null)
  const offerId = offer?.id

  useEffect(() => {
    if (!offer) return
    if (Object.keys(pending.current).length === 0 && !running.current) setData(offer.data ?? {})
  }, [offer])

  const flush = useCallback((): Promise<boolean> => {
    if (timer.current) { clearTimeout(timer.current); timer.current = null }
    // The running loop picks up whatever is pending when its PATCH answers.
    if (running.current) return running.current
    if (offerId == null || Object.keys(pending.current).length === 0) return Promise.resolve(true)
    const loop = async (): Promise<boolean> => {
      let last: OfferOut | null = null
      try {
        while (Object.keys(pending.current).length > 0) {
          const body = pending.current
          pending.current = {}
          setSaveState('saving')
          try {
            last = await changeOfferApi.patch(changeId, offerId, { data: body })
            const saved = last
            qc.setQueryData<OfferOut[]>(offersKey(changeId),
              (old) => (old ?? []).map((o) => (o.id === saved.id ? saved : o)))
          } catch (e) {
            // Put the keys back (newer edits win) so the next edit retries them.
            pending.current = { ...body, ...pending.current }
            setSaveState('error')
            toast.error(errDetail(e) ?? 'Could not save the offer')
            return false
          }
        }
        setSaveState('saved')
        // Nothing pending and nothing in flight: the server's answer is the truth.
        if (last) setData(last.data ?? {})
        return true
      } finally {
        running.current = null
      }
    }
    running.current = loop()
    return running.current
  }, [changeId, offerId, qc])

  const update = useCallback(<K extends keyof OfferData>(key: K, value: OfferData[K]) => {
    setData((d) => ({ ...d, [key]: value }))
    pending.current = { ...pending.current, [key]: value }
    if (!running.current) setSaveState('pending')
    if (timer.current) clearTimeout(timer.current)
    timer.current = setTimeout(() => { timer.current = null; void flush() }, delay)
  }, [delay, flush])

  // Leaving the tab saves what was typed.
  useEffect(() => () => {
    if (timer.current) { clearTimeout(timer.current); timer.current = null; void flush() }
  }, [flush])

  /** Something typed is not on the server yet: totals shown may be stale. */
  const dirty = saveState === 'pending' || saveState === 'saving' || saveState === 'error'

  return { data, update, saveState, flush, dirty }
}
