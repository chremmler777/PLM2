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
interface Item { seq: number; cs: ChangeSet; status: Status; at: number; tag?: SaveTag; server?: boolean }

/** A task the server moved on its own while saving a ChangeSet. */
/** A task the server moved by itself: only its start (the server never changes a leaf's duration on its own). */
export interface ServerMove { id: GanttId; from: { start: string }; to: { start: string } }

/**
 * Tasks the server moved on its own for this ChangeSet, leaves only (a
 * summary's dates are a roll-up; the server refuses date patches on them),
 * never a task the ChangeSet touched. `moved` (the server's own list, e.g.
 * `moved_ids`) is the only source when given. Without it: the tasks
 * reachable from what the ChangeSet touched (successors along links, the
 * tasks under and above them) whose start differs from `before` (the
 * server's previous answer). Only the start counts: a changed duration was
 * someone else's edit, never a push.
 */
export function serverMoves(before: GanttModel, cs: ChangeSet, server: GanttModel, moved?: GanttId[] | null): ServerMove[] {
  const touched = new Set(touchedTaskIds(cs).map(String))
  for (const l of [...(cs.addLinks ?? []), ...(cs.updateLinks ?? []).map((u) => u.patch)]) if (l.to != null) touched.add(String(l.to))
  const parentOf = new Map<string, string>()
  const kids = new Map<string, string[]>()
  for (const m of [server, before]) {
    for (const t of m.tasks) {
      if (t.parentId == null) continue
      const k = String(t.id), p = String(t.parentId)
      if (!parentOf.has(k)) parentOf.set(k, p)
      if (!kids.has(p)) kids.set(p, [])
      if (!kids.get(p)!.includes(k)) kids.get(p)!.push(k)
    }
  }
  const succ = new Map<string, string[]>()
  for (const l of server.links) {
    const f = String(l.from)
    if (!succ.has(f)) succ.set(f, [])
    succ.get(f)!.push(String(l.to))
  }
  const reach = new Set(touched)
  const stack = [...touched]
  const visit = (x: string | undefined) => { if (x != null && !reach.has(x)) { reach.add(x); stack.push(x) } }
  while (stack.length) {
    const x = stack.pop()!
    for (const y of succ.get(x) ?? []) visit(y)
    for (const y of kids.get(x) ?? []) visit(y)
    visit(parentOf.get(x))
  }
  const was = new Map(before.tasks.map((t) => [String(t.id), t]))
  const listed = moved ? new Set(moved.map(String)) : null
  const out: ServerMove[] = []
  for (const t of server.tasks) {
    const k = String(t.id)
    const b = was.get(k)
    if (!b || touched.has(k) || kids.has(k)) continue
    if (listed ? !listed.has(k) : !reach.has(k)) continue
    if (b.start !== t.start) out.push({ id: t.id, from: { start: b.start }, to: { start: t.start } })
  }
  return out
}

/** Does the host model already show the server's answer (dates and parents)? */
function shows(base: GanttModel, server: GanttModel): boolean {
  if (base.tasks.length !== server.tasks.length || base.links.length !== server.links.length) return false
  const m = new Map(base.tasks.map((t) => [String(t.id), t]))
  return server.tasks.every((t) => {
    const b = m.get(String(t.id))
    return !!b && b.start === t.start && b.duration === t.duration && String(b.parentId ?? '') === String(t.parentId ?? '')
  })
}

export interface SaveQueueOptions {
  onChange?: (cs: ChangeSet) => Promise<ApplyResult | void> | ApplyResult | void
  /** A save was refused: `tag` / `seq` identify it. Return an entry id to drop its other queued saves. */
  onError?: (error: unknown, tag: SaveTag | undefined, seq: number) => number | void
  /** A save was accepted. */
  onSettled?: (tag: SaveTag | undefined, seq: number) => void
  /** The server moved tasks on its own for this save (they join its undo step). */
  onServerMoves?: (tag: SaveTag | undefined, moves: ServerMove[]) => void
  /** Told about temp id -> real id mappings (history and view state remap); tasks and links apart. */
  onIdMap?: (idMap: Record<string, GanttId>, linkIdMap: Record<string, GanttId>) => void
  settleMs?: number
}

export function useSaveQueue(base: GanttModel, opts: SaveQueueOptions) {
  const [items, setItems] = useState<Item[]>([])
  const baseRef = useRef(base)
  baseRef.current = base
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
      // A save the server answered in full is shown by the next host model even
      // where the server decided differently (e.g. it pushed a task further).
      const keep = list.filter((i) => i.status !== 'settled' || (!i.server && !modelContains(base, i.cs)))
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
    // The view before this save: what "moved on its own" is measured against.
    const beforeSend = applyAll(baseRef.current, itemsRef.current.filter((i) => i.seq < next.seq).map((i) => i.cs))
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
      const server = res && typeof res === 'object' ? res.server : undefined
      if (server) {
        const was = res && typeof res === 'object' && res.serverBefore ? res.serverBefore : beforeSend
        const moved = res && typeof res === 'object' ? res.serverMoved : undefined
        const moves = serverMoves(was, any ? remapChangeSet(cs, idMap, linkIdMap) : cs, server, moved)
        if (moves.length) optsRef.current.onServerMoves?.(next.tag, moves)
      }
      // Answered in full and already shown by the host: nothing left to overlay.
      const shown = !!server && shows(baseRef.current, server)
      update((list) => list.flatMap((i) => {
        if (i.seq === next.seq) {
          return shown ? [] : [{ ...i, cs: any ? remapChangeSet(i.cs, idMap, linkIdMap) : i.cs, status: 'settled' as Status, at: Date.now(), server: !!server }]
        }
        return [any && i.status === 'queued' ? { ...i, cs: remapChangeSet(i.cs, idMap, linkIdMap) } : i]
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
