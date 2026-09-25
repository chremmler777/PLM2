/**
 * Optimistic saves, one in flight at a time.
 *
 * Every ChangeSet is applied to the displayed model at once. The queue sends
 * them to the adapter in order; the next one leaves only after the previous
 * one answered. A saved ChangeSet stays applied until the host passes a new
 * model (the server's copy) so the view never flickers back; it is dropped
 * after `settleMs` in any case. On an error the whole queue is dropped (later
 * edits may build on the failed one), the view falls back to the host model
 * and `onError` is told (the adapter refetches).
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { applyAll, remapChangeSet, touchedTaskIds } from './engine/changes'
import type { ApplyResult, ChangeSet, GanttId, GanttModel } from './engine/types'

type Status = 'queued' | 'inflight' | 'settled'
interface Item { seq: number; cs: ChangeSet; status: Status; at: number }

export interface SaveQueueOptions {
  onChange?: (cs: ChangeSet) => Promise<ApplyResult | void> | ApplyResult | void
  onError?: (error: unknown) => void
  /** Told about temp id -> real id mappings (history remap). */
  onIdMap?: (idMap: Record<string, GanttId>) => void
  settleMs?: number
}

export function useSaveQueue(base: GanttModel, opts: SaveQueueOptions) {
  const [items, setItems] = useState<Item[]>([])
  const seq = useRef(0)
  const optsRef = useRef(opts)
  optsRef.current = opts
  const running = useRef(false)
  // The ref is the source of truth (updated synchronously), the state only renders it:
  // a pump running in a microtask must never see a stale "queued" item and send it twice.
  const itemsRef = useRef(items)
  const update = useCallback((fn: (list: Item[]) => Item[]) => {
    const next = fn(itemsRef.current)
    if (next === itemsRef.current) return
    itemsRef.current = next
    setItems(next)
  }, [])

  // A new host model replaces every settled ChangeSet.
  useEffect(() => {
    update((list) => (list.some((i) => i.status === 'settled') ? list.filter((i) => i.status !== 'settled') : list))
  }, [base.tasks, base.links, update])

  const settleMs = opts.settleMs ?? 1500
  useEffect(() => {
    if (!items.some((i) => i.status === 'settled')) return
    const t = setTimeout(() => {
      update((list) => {
        const keep = list.filter((i) => i.status !== 'settled' || Date.now() - i.at < settleMs)
        return keep.length === list.length ? list : keep
      })
    }, settleMs)
    return () => clearTimeout(t)
  }, [items, settleMs, update])

  const pump = useCallback(async () => {
    if (running.current) return
    const next = itemsRef.current.find((i) => i.status === 'queued')
    if (!next) return
    running.current = true
    update((list) => list.map((i) => (i.seq === next.seq ? { ...i, status: 'inflight' } : i)))
    try {
      const res = await optsRef.current.onChange?.(next.cs)
      const idMap = res && typeof res === 'object' ? res.idMap : undefined
      if (idMap && Object.keys(idMap).length) optsRef.current.onIdMap?.(idMap)
      update((list) => list.map((i) => {
        if (i.seq === next.seq) return { ...i, cs: idMap ? remapChangeSet(i.cs, idMap) : i.cs, status: 'settled' as Status, at: Date.now() }
        return idMap && i.status === 'queued' ? { ...i, cs: remapChangeSet(i.cs, idMap) } : i
      }))
      running.current = false
      // Continue with the next queued item.
      queueMicrotask(() => { void pumpRef.current() })
    } catch (e) {
      running.current = false
      update(() => [])
      optsRef.current.onError?.(e)
    }
  }, [update])
  const pumpRef = useRef(pump)
  pumpRef.current = pump

  const enqueue = useCallback((cs: ChangeSet) => {
    const item: Item = { seq: ++seq.current, cs, status: 'queued', at: Date.now() }
    update((list) => [...list, item])
    queueMicrotask(() => { void pumpRef.current() })
  }, [update])

  const display = useMemo(() => (items.length ? applyAll(base, items.map((i) => i.cs)) : base), [base, items])
  const saving = items.some((i) => i.status !== 'settled')
  const pendingIds = useMemo(() => new Set(items.filter((i) => i.status !== 'settled').flatMap((i) => touchedTaskIds(i.cs))), [items])
  return { display, enqueue, saving, pendingIds, queueLength: items.filter((i) => i.status !== 'settled').length }
}
