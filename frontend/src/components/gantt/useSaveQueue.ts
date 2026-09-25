/**
 * Optimistic saves, one in flight at a time.
 *
 * Every ChangeSet is applied to the displayed model at once. The queue sends
 * them to the adapter in order; the next one leaves only after the previous
 * one answered. Temporary ids the server replaced are remembered: every later
 * ChangeSet is rewritten with them when it is queued and when it leaves.
 * A saved ChangeSet stays applied until the host model shows it (the
 * server's copy) or `settleMs` passed, so the view never flickers back and a
 * late, stale refetch cannot hide it. A refused save rolls back only itself;
 * the adapter refetches and `onError` is told with the item's tag (history).
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { applyAll, modelContains, remapChangeSet, touchedTaskIds } from './engine/changes'
import type { ApplyResult, ChangeSet, GanttId, GanttModel } from './engine/types'

type Status = 'queued' | 'inflight' | 'settled'
interface Item { seq: number; cs: ChangeSet; status: Status; at: number; tag?: number }

export interface SaveQueueOptions {
  onChange?: (cs: ChangeSet) => Promise<ApplyResult | void> | ApplyResult | void
  /** A save was refused: `tag` is what `enqueue` got with it. */
  onError?: (error: unknown, tag?: number) => void
  /** Told about temp id -> real id mappings (history and view state remap). */
  onIdMap?: (idMap: Record<string, GanttId>) => void
  settleMs?: number
}

export function useSaveQueue(base: GanttModel, opts: SaveQueueOptions) {
  const [items, setItems] = useState<Item[]>([])
  const seq = useRef(0)
  const optsRef = useRef(opts)
  optsRef.current = opts
  const running = useRef(false)
  /** Every temp id -> real id seen so far. */
  const idMapRef = useRef<Record<string, GanttId>>({})
  // The ref is the source of truth (updated synchronously), the state only renders it:
  // a pump running in a microtask must never see a stale "queued" item and send it twice.
  const itemsRef = useRef(items)
  const update = useCallback((fn: (list: Item[]) => Item[]) => {
    const next = fn(itemsRef.current)
    if (next === itemsRef.current) return
    itemsRef.current = next
    setItems(next)
  }, [])

  // A new host model replaces the settled ChangeSets it already shows.
  useEffect(() => {
    update((list) => {
      if (!list.some((i) => i.status === 'settled')) return list
      const keep = list.filter((i) => i.status !== 'settled' || !modelContains(base, i.cs))
      return keep.length === list.length ? list : keep
    })
  }, [base, update])

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
    const known = idMapRef.current
    const cs = Object.keys(known).length ? remapChangeSet(next.cs, known) : next.cs
    update((list) => list.map((i) => (i.seq === next.seq ? { ...i, cs, status: 'inflight' } : i)))
    try {
      const res = await optsRef.current.onChange?.(cs)
      const idMap = res && typeof res === 'object' ? res.idMap : undefined
      if (idMap && Object.keys(idMap).length) {
        idMapRef.current = { ...idMapRef.current, ...idMap }
        optsRef.current.onIdMap?.(idMap)
      }
      update((list) => list.map((i) => {
        if (i.seq === next.seq) return { ...i, cs: idMap ? remapChangeSet(i.cs, idMap) : i.cs, status: 'settled' as Status, at: Date.now() }
        return idMap && i.status === 'queued' ? { ...i, cs: remapChangeSet(i.cs, idMap) } : i
      }))
    } catch (e) {
      // Only this change is rolled back; later ones still go (the adapter refetches).
      update((list) => list.filter((i) => i.seq !== next.seq))
      optsRef.current.onError?.(e, next.tag)
    } finally {
      running.current = false
      queueMicrotask(() => { void pumpRef.current() })
    }
  }, [update])
  const pumpRef = useRef(pump)
  pumpRef.current = pump

  const enqueue = useCallback((cs: ChangeSet, tag?: number) => {
    const known = idMapRef.current
    const item: Item = { seq: ++seq.current, cs: Object.keys(known).length ? remapChangeSet(cs, known) : cs, status: 'queued', at: Date.now(), tag }
    update((list) => [...list, item])
    queueMicrotask(() => { void pumpRef.current() })
  }, [update])

  /** Rewrite an id with every mapping seen so far (for host / view state). */
  const resolveId = useCallback((id: GanttId): GanttId => idMapRef.current[String(id)] ?? id, [])

  const display = useMemo(() => (items.length ? applyAll(base, items.map((i) => i.cs)) : base), [base, items])
  const saving = items.some((i) => i.status !== 'settled')
  const pendingIds = useMemo(() => new Set(items.filter((i) => i.status !== 'settled').flatMap((i) => touchedTaskIds(i.cs))), [items])
  return { display, enqueue, saving, pendingIds, resolveId, queueLength: items.filter((i) => i.status !== 'settled').length }
}
