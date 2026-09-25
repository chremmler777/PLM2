/**
 * Undo/redo over ChangeSets. Each entry keeps the forward ChangeSet and its
 * inverse (computed against the model before it ran). Undo hands back the
 * inverse to apply and persist, redo the forward one. When the server maps
 * temporary ids to real ones, `remap` rewrites every stored entry.
 *
 * Saves are asynchronous and may be refused. Every save that belongs to an
 * entry is registered with its queue sequence number (`sent`), and the entry
 * remembers the last save that changed it. A refusal is matched exactly:
 * - a refused original change ("do") is forgotten wherever the entry sits
 *   now (the caller also drops the queued undo/redo saves of that entry);
 * - a refused undo or redo only acts when it is still the entry's last save:
 *   the entry goes back to where it was before. An undo refused after a new
 *   change emptied the redo stack goes back onto the undo stack at its
 *   original position (the change stays applied and stays undoable).
 */
import { invertChangeSet, isEmptyChangeSet, remapChangeSet } from './changes'
import type { ChangeSet, GanttId, GanttModel } from './types'

export type SaveDirection = 'do' | 'undo' | 'redo'

export interface HistoryEntry {
  id: number
  forward: ChangeSet
  backward: ChangeSet
  /** Queue sequence of the last save that moved this entry, and whether it is still unanswered. */
  lastSeq?: number
  pending?: boolean
  /** What last happened to it (kept for callers that inspect it). */
  last?: 'push' | 'undo' | 'redo'
}

export class History {
  private past: HistoryEntry[] = []
  private future: HistoryEntry[] = []
  /** Undone entries whose undo is still in flight when a new change cleared the redo stack. */
  private limbo: HistoryEntry[] = []
  private seq = 0
  constructor(private limit = 100) {}

  /** Record a ChangeSet about to be applied to `before`; returns the entry id (0 when nothing was recorded). */
  push(before: GanttModel, cs: ChangeSet): number {
    if (isEmptyChangeSet(cs)) return 0
    const id = ++this.seq
    this.past.push({ id, forward: cs, backward: invertChangeSet(before, cs), last: 'push' })
    if (this.past.length > this.limit) this.past.shift()
    // A new change clears the redo stack; an entry whose undo is still in
    // flight is kept aside in case that undo is refused.
    this.limbo.push(...this.future.filter((e) => e.pending))
    this.future = []
    return id
  }

  /** The ChangeSet an undo would apply, without moving anything yet. */
  peekUndo(): { id: number; cs: ChangeSet } | null {
    const e = this.past[this.past.length - 1]
    return e ? { id: e.id, cs: { ...e.backward, label: `Undo ${e.forward.label ?? 'change'}`.trim() } } : null
  }

  peekRedo(): { id: number; cs: ChangeSet } | null {
    const e = this.future[this.future.length - 1]
    return e ? { id: e.id, cs: { ...e.forward } } : null
  }

  private find(id: number): HistoryEntry | undefined {
    return this.past.find((e) => e.id === id) ?? this.future.find((e) => e.id === id) ?? this.limbo.find((e) => e.id === id)
  }

  /** A save of entry `id` was queued with sequence `seq`. */
  sent(id: number, seq: number): void {
    const e = this.find(id)
    if (e) { e.lastSeq = seq; e.pending = true }
  }

  /** The undo of entry `id` went out (queued as `seq`): move it to the redo stack. */
  confirmUndo(id: number, seq?: number): void {
    const i = this.past.findIndex((e) => e.id === id)
    if (i < 0) return
    const [e] = this.past.splice(i, 1)
    this.future.push({ ...e, last: 'undo', ...(seq != null ? { lastSeq: seq, pending: true } : {}) })
  }

  confirmRedo(id: number, seq?: number): void {
    const i = this.future.findIndex((e) => e.id === id)
    if (i < 0) return
    const [e] = this.future.splice(i, 1)
    this.past.push({ ...e, last: 'redo', ...(seq != null ? { lastSeq: seq, pending: true } : {}) })
  }

  /** Save `seq` of entry `id` was accepted. */
  settled(id: number, seq: number): void {
    const e = this.find(id)
    if (!e || e.lastSeq !== seq) return
    e.pending = false
    this.limbo = this.limbo.filter((x) => x.id !== id)
  }

  /**
   * Save `seq` (direction `dir`) of entry `id` was refused. Returns true when
   * the entry was forgotten (the caller drops its other queued saves).
   */
  refused(id: number, seq: number | undefined, dir: SaveDirection): boolean {
    if (dir === 'do') { this.discard(id); return true }
    const e = this.find(id)
    if (!e || e.lastSeq !== seq) return false // a later undo/redo of it answers for it
    e.pending = false
    if (dir === 'undo') {
      this.future = this.future.filter((x) => x.id !== id)
      this.limbo = this.limbo.filter((x) => x.id !== id)
      const back = { ...e, last: 'push' as const }
      // Its original position: before every entry recorded after it.
      const at = this.past.findIndex((x) => x.id > id)
      if (at < 0) this.past.push(back)
      else this.past.splice(at, 0, back)
    } else {
      this.past = this.past.filter((x) => x.id !== id)
      this.future.push({ ...e, last: 'undo' })
    }
    return false
  }

  /** Older API: a refused save of `id`, its direction read from the entry's last move. */
  revert(id: number): void {
    const e = this.find(id)
    if (!e) return
    const dir: SaveDirection = e.last === 'undo' ? 'undo' : e.last === 'redo' ? 'redo' : 'do'
    this.refused(id, e.lastSeq, dir)
  }

  /** Forget one entry. */
  discard(id: number): void {
    this.past = this.past.filter((e) => e.id !== id)
    this.future = this.future.filter((e) => e.id !== id)
    this.limbo = this.limbo.filter((e) => e.id !== id)
  }

  get canUndo() { return this.past.length > 0 }
  get canRedo() { return this.future.length > 0 }
  get undoLabel() { return this.past[this.past.length - 1]?.forward.label }
  get redoLabel() { return this.future[this.future.length - 1]?.forward.label }
  get size() { return { past: this.past.length, future: this.future.length } }
  /** Stack contents by entry id (tests, debugging). */
  get stacks() { return { past: this.past.map((e) => e.id), future: this.future.map((e) => e.id), limbo: this.limbo.map((e) => e.id) } }

  /** The ChangeSet that undoes the last action, or null (moves the entry at once). */
  undo(): ChangeSet | null {
    const e = this.past.pop()
    if (!e) return null
    this.future.push({ ...e, last: 'undo' })
    return { ...e.backward, label: `Undo ${e.forward.label ?? 'change'}`.trim() }
  }

  redo(): ChangeSet | null {
    const e = this.future.pop()
    if (!e) return null
    this.past.push({ ...e, last: 'redo' })
    return { ...e.forward }
  }

  /** Drop the last undone/redone step again (its save failed). */
  dropLast(which: 'past' | 'future'): void {
    if (which === 'past') this.past.pop(); else this.future.pop()
  }

  remap(idMap: Record<string, GanttId>, linkIdMap: Record<string, GanttId> = {}): void {
    if (!Object.keys(idMap).length && !Object.keys(linkIdMap).length) return
    const r = (e: HistoryEntry): HistoryEntry => ({
      ...e, forward: remapChangeSet(e.forward, idMap, linkIdMap), backward: remapChangeSet(e.backward, idMap, linkIdMap),
    })
    this.past = this.past.map(r)
    this.future = this.future.map(r)
    this.limbo = this.limbo.map(r)
  }

  clear(): void { this.past = []; this.future = []; this.limbo = [] }
}
