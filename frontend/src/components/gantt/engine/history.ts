/**
 * Undo/redo over ChangeSets. Each entry keeps the forward ChangeSet and its
 * inverse (computed against the model before it ran). Undo hands back the
 * inverse to apply and persist, redo the forward one. When the server maps
 * temporary ids to real ones, `remap` rewrites every stored entry.
 */
import { invertChangeSet, isEmptyChangeSet, remapChangeSet } from './changes'
import type { ChangeSet, GanttId, GanttModel } from './types'

export interface HistoryEntry { forward: ChangeSet; backward: ChangeSet }

export class History {
  private past: HistoryEntry[] = []
  private future: HistoryEntry[] = []
  constructor(private limit = 100) {}

  /** Record a ChangeSet about to be applied to `before`. */
  push(before: GanttModel, cs: ChangeSet): void {
    if (isEmptyChangeSet(cs)) return
    this.past.push({ forward: cs, backward: invertChangeSet(before, cs) })
    if (this.past.length > this.limit) this.past.shift()
    this.future = []
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

  remap(idMap: Record<string, GanttId>): void {
    if (!Object.keys(idMap).length) return
    const r = (e: HistoryEntry): HistoryEntry => ({
      forward: remapChangeSet(e.forward, idMap), backward: remapChangeSet(e.backward, idMap),
    })
    this.past = this.past.map(r)
    this.future = this.future.map(r)
  }

  clear(): void { this.past = []; this.future = [] }
}
