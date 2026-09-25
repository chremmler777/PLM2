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
import { applyAll, isEmptyChangeSet, modelContains, remapChangeSet, touchedTaskIds } from './engine/changes'
import type { SaveDirection } from './engine/history'
import type { ApplyResult, ChangeSet, GanttId, GanttModel } from './engine/types'

type Status = 'queued' | 'inflight' | 'settled'
/** Which history entry a save belongs to and what it does to it. */
export interface SaveTag { entry: number; dir: SaveDirection }
interface Item { seq: number; cs: ChangeSet; status: Status; at: number; tag?: SaveTag }

export interface SaveQueueOptions {
  onChange?: (cs: ChangeSet) => Promise<ApplyResult | void> | ApplyResult | void
  /** A save was refused: `tag` / `seq` identify it. Return an entry id to drop its other queued saves. */
  onError?: (error: unknown, tag: SaveTag | undefined, seq: number) => number | void
  /** A save was accepted. */
  onSettled?: (tag: SaveTag | undefined, seq: number) => void
  /** Told about temp id -> real id mappings (history and view state remap); tasks and links apart. */
  onIdMap?: (idMap: Record<string, GanttId>, linkIdMap: Record<string, GanttId>) => void
  settleMs?: number
}

export function useSaveQueue(base: GanttModel, opts: SaveQueueOptions) {
  const [items, setItems] = useState<Item[]>([])
  const seq = useRef(0)
  const optsRef = useRef(opts)
  optsRef.current = opts
  const running = useRef(false)
  /**
   * Every temporary (string) id -> real id seen so far, tasks and links apart.
   * Numeric keys (an old id that came back under a new one) are not kept:
   * the old number may be reused for something else later.
   */
  const idMapRef = useRef<Record<string, GanttId>>({})
  const linkMapRef = useRef<Record<string, GanttId>>({})
  const tempOnly = (m: Record<string, GanttId>) => Object.fromEntries(Object.entries(m).filter(([k]) => !/^-?\d+$/.test(k)))
  const remapKnown = (cs: ChangeSet) => (Object.keys(idMapRef.current).length || Object.keys(linkMapRef.current).length
    ? remapChangeSet(cs, idMapRef.current, linkMapRef.current) : cs)
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
    const cs = remapKnown(next.cs)
    if (isEmptyChangeSet(cs)) {
      // Nothing left to send (e.g. it only touched a task whose create was refused).
      update((list) => list.filter((i) => i.seq !== next.seq))
      optsRef.current.onSettled?.(next.tag, next.seq)
      running.current = false
      queueMicrotask(() => { void pumpRef.current() })
      return
    }
    update((list) => list.map((i) => (i.seq === next.seq ? { ...i, cs, status: 'inflight' } : i)))
    try {
      const res = await optsRef.current.onChange?.(cs)
      const idMap = (res && typeof res === 'object' ? res.idMap : undefined) ?? {}
      const linkIdMap = (res && typeof res === 'object' ? res.linkIdMap : undefined) ?? {}
      const any = Object.keys(idMap).length > 0 || Object.keys(linkIdMap).length > 0
      if (any) {
        idMapRef.current = { ...idMapRef.current, ...tempOnly(idMap) }
        linkMapRef.current = { ...linkMapRef.current, ...tempOnly(linkIdMap) }
        optsRef.current.onIdMap?.(idMap, linkIdMap)
      }
      update((list) => list.map((i) => {
        if (i.seq === next.seq) return { ...i, cs: any ? remapChangeSet(i.cs, idMap, linkIdMap) : i.cs, status: 'settled' as Status, at: Date.now() }
        return any && i.status === 'queued' ? { ...i, cs: remapChangeSet(i.cs, idMap, linkIdMap) } : i
      }))
      optsRef.current.onSettled?.(next.tag, next.seq)
    } catch (e) {
      // Only this change is rolled back; later ones still go (the adapter refetches).
      update((list) => list.filter((i) => i.seq !== next.seq))
      const forgotten = optsRef.current.onError?.(e, next.tag, next.seq)
      // A refused original change: its queued undo / redo saves go too.
      if (typeof forgotten === 'number') update((list) => list.filter((i) => i.status !== 'queued' || i.tag?.entry !== forgotten))
    } finally {
      running.current = false
      queueMicrotask(() => { void pumpRef.current() })
    }
  }, [update])
  const pumpRef = useRef(pump)
  pumpRef.current = pump

  /** Queue a ChangeSet; returns its sequence number. */
  const enqueue = useCallback((cs: ChangeSet, tag?: SaveTag): number => {
    const item: Item = { seq: ++seq.current, cs: remapKnown(cs), status: 'queued', at: Date.now(), tag }
    update((list) => [...list, item])
    queueMicrotask(() => { void pumpRef.current() })
    return item.seq
  }, [update])

  /** Rewrite an id with every mapping seen so far (for host / view state). */
  const resolveId = useCallback((id: GanttId): GanttId => idMapRef.current[String(id)] ?? id, [])

  const display = useMemo(() => (items.length ? applyAll(base, items.map((i) => i.cs)) : base), [base, items])
  const saving = items.some((i) => i.status !== 'settled')
  const pendingIds = useMemo(() => new Set(items.filter((i) => i.status !== 'settled').flatMap((i) => touchedTaskIds(i.cs))), [items])
  return { display, enqueue, saving, pendingIds, resolveId, queueLength: items.filter((i) => i.status !== 'settled').length }
}
