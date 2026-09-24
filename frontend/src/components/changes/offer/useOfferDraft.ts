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
 * Local data is only re-synced from the server while nothing is pending, so a
 * save landing mid-typing never eats keystrokes.
 */
export function useOfferDraft(changeId: number, offer: OfferOut | undefined, delay = 500) {
  const qc = useQueryClient()
  const [data, setData] = useState<OfferData>(offer?.data ?? {})
  const [saveState, setSaveState] = useState<SaveState>('idle')
  const pending = useRef<Partial<OfferData>>({})
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const inflight = useRef(false)
  const offerId = offer?.id

  useEffect(() => {
    if (!offer) return
    if (Object.keys(pending.current).length === 0 && !inflight.current) setData(offer.data ?? {})
  }, [offer])

  const flush = useCallback(async () => {
    if (timer.current) { clearTimeout(timer.current); timer.current = null }
    const body = pending.current
    if (offerId == null || Object.keys(body).length === 0) return
    pending.current = {}
    inflight.current = true
    setSaveState('saving')
    try {
      const saved = await changeOfferApi.patch(changeId, offerId, { data: body })
      qc.setQueryData<OfferOut[]>(offersKey(changeId),
        (old) => (old ?? []).map((o) => (o.id === saved.id ? saved : o)))
      setSaveState(Object.keys(pending.current).length > 0 ? 'pending' : 'saved')
    } catch (e) {
      // Put the keys back so the next edit retries them.
      pending.current = { ...body, ...pending.current }
      setSaveState('error')
      toast.error(errDetail(e) ?? 'Could not save the offer')
    } finally {
      inflight.current = false
    }
  }, [changeId, offerId, qc])

  const update = useCallback(<K extends keyof OfferData>(key: K, value: OfferData[K]) => {
    setData((d) => ({ ...d, [key]: value }))
    pending.current = { ...pending.current, [key]: value }
    setSaveState('pending')
    if (timer.current) clearTimeout(timer.current)
    timer.current = setTimeout(() => { void flush() }, delay)
  }, [delay, flush])

  // Leaving the tab saves what was typed.
  useEffect(() => () => {
    if (timer.current) { clearTimeout(timer.current); void flush() }
  }, [flush])

  return { data, update, saveState, flush }
}
