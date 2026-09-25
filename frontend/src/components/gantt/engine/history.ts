/**
 * Undo/redo over ChangeSets. Each entry keeps the forward ChangeSet and its
 * inverse (computed against the model before it ran). Undo hands back the
 * inverse to apply and persist, redo the forward one. When the server maps
 * temporary ids to real ones, `remap` rewrites every stored entry.
 */
import { invertChangeSet, isEmptyChangeSet, remapChangeSet } from './changes'
import type { ChangeSet, GanttId, GanttModel } from './types'

export interface HistoryEntry {
  id: number
  forward: ChangeSet
  backward: ChangeSet
  /** What last happened to it: recorded, undone or redone (for `revert`). */
  last?: 'push' | 'undo' | 'redo'
}

export class History {
  private past: HistoryEntry[] = []
  private future: HistoryEntry[] = []
  private seq = 0
  constructor(private limit = 100) {}

  /** Record a ChangeSet about to be applied to `before`; returns the entry id (0 when nothing was recorded). */
  push(before: GanttModel, cs: ChangeSet): number {
    if (isEmptyChangeSet(cs)) return 0
    const id = ++this.seq
    this.past.push({ id, forward: cs, backward: invertChangeSet(before, cs), last: 'push' })
    if (this.past.length > this.limit) this.past.shift()
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

  /** The undo of entry `id` went through: move it to the redo stack. */
  confirmUndo(id: number): void {
    const i = this.past.findIndex((e) => e.id === id)
    if (i < 0) return
    const [e] = this.past.splice(i, 1)
    this.future.push({ ...e, last: 'undo' })
  }

  confirmRedo(id: number): void {
    const i = this.future.findIndex((e) => e.id === id)
    if (i < 0) return
    const [e] = this.future.splice(i, 1)
    this.past.push({ ...e, last: 'redo' })
  }

  /**
   * The save of entry `id` was refused: a new change is forgotten, an undo
   * or redo goes back to the stack it came from (so it can be retried).
   */
  revert(id: number): void {
    const f = this.future.findIndex((e) => e.id === id)
    if (f >= 0 && this.future[f].last === 'undo') {
      const [e] = this.future.splice(f, 1)
      this.past.push({ ...e, last: 'push' })
      return
    }
    const p = this.past.findIndex((e) => e.id === id)
    if (p >= 0 && this.past[p].last === 'redo') {
      const [e] = this.past.splice(p, 1)
      this.future.push({ ...e, last: 'undo' })
      return
    }
    this.discard(id)
  }

  /** Forget one entry (its save was refused). */
  discard(id: number): void {
    this.past = this.past.filter((e) => e.id !== id)
    this.future = this.future.filter((e) => e.id !== id)
  }

  get canUndo() { return this.past.length > 0 }
  get canRedo() { return this.future.length > 0 }
  get undoLabel() { return this.past[this.past.length - 1]?.forward.label }
  get redoLabel() { return this.future[this.future.length - 1]?.forward.label }
  get size() { return { past: this.past.length, future: this.future.length } }

  /** The ChangeSet that undoes the last action, or null. */
  undo(): ChangeSet | null {
    const e = this.past.pop()
    if (!e) return null
    this.future.push(e)
    return { ...e.backward, label: `Undo ${e.forward.label ?? 'change'}`.trim() }
  }

  redo(): ChangeSet | null {
    const e = this.future.pop()
    if (!e) return null
    this.past.push(e)
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
  }

  clear(): void { this.past = []; this.future = [] }
}
