import { describe, expect, it } from 'vitest'
import { applyChangeSet } from './changes'
import { History } from './history'
import type { ChangeSet, GanttModel } from './types'

const m0 = (): GanttModel => ({
  tasks: [{ id: 1, name: 'A', start: '2026-10-05', duration: 2 }, { id: 2, name: 'B', start: '2026-10-07', duration: 2 }],
  links: [{ id: 'l', from: 1, to: 2, type: 'FS', lagDays: 0 }],
})
const move: ChangeSet = { label: 'Move', updateTasks: [{ id: 1, patch: { start: '2026-10-06' } }] }

describe('History', () => {
  it('starts empty', () => {
    const h = new History()
    expect(h.canUndo).toBe(false)
    expect(h.canRedo).toBe(false)
    expect(h.undo()).toBeNull()
    expect(h.redo()).toBeNull()
  })
  it('undo gives the inverse, redo the forward change', () => {
    const h = new History()
    const m = m0()
    h.push(m, move)
    const after = applyChangeSet(m, move)
    const u = h.undo()!
    expect(applyChangeSet(after, u).tasks[0].start).toBe('2026-10-05')
    expect(u.label).toBe('Undo Move')
    expect(h.canRedo).toBe(true)
    const r = h.redo()!
    expect(r.updateTasks).toEqual(move.updateTasks)
    expect(h.canUndo).toBe(true)
    expect(h.canRedo).toBe(false)
  })
  it('exposes labels', () => {
    const h = new History()
    h.push(m0(), move)
    expect(h.undoLabel).toBe('Move')
    h.undo()
    expect(h.redoLabel).toBe('Move')
  })
  it('ignores empty change sets', () => {
    const h = new History()
    h.push(m0(), { label: 'nothing' })
    expect(h.canUndo).toBe(false)
  })
  it('a new push clears the redo stack', () => {
    const h = new History()
    h.push(m0(), move)
    h.undo()
    h.push(m0(), { updateTasks: [{ id: 2, patch: { name: 'X' } }] })
    expect(h.canRedo).toBe(false)
  })
  it('keeps at most `limit` entries', () => {
    const h = new History(3)
    for (let i = 0; i < 5; i++) h.push(m0(), { updateTasks: [{ id: 1, patch: { duration: i } }] })
    expect(h.size).toEqual({ past: 3, future: 0 })
  })
  it('undoes several steps in reverse order', () => {
    const h = new History()
    let m = m0()
    const a: ChangeSet = { updateTasks: [{ id: 1, patch: { name: 'A1' } }] }
    const b: ChangeSet = { updateTasks: [{ id: 1, patch: { name: 'A2' } }] }
    h.push(m, a); m = applyChangeSet(m, a)
    h.push(m, b); m = applyChangeSet(m, b)
    m = applyChangeSet(m, h.undo()!)
    expect(m.tasks[0].name).toBe('A1')
    m = applyChangeSet(m, h.undo()!)
    expect(m.tasks[0].name).toBe('A')
  })
  it('undo of a delete restores the task and its link', () => {
    const h = new History()
    const m = m0()
    const del: ChangeSet = { removeTasks: [2], removeLinks: ['l'] }
    h.push(m, del)
    const back = applyChangeSet(applyChangeSet(m, del), h.undo()!)
    expect(back.tasks.map((t) => t.id)).toEqual([1, 2])
    expect(back.links).toEqual(m.links)
  })
  it('remaps temporary ids in both directions', () => {
    const h = new History()
    h.push(m0(), { addTasks: [{ id: 'tmp', name: 'N', start: '2026-10-05', duration: 1 }] })
    h.remap({ tmp: 42 })
    const u = h.undo()!
    expect(u.removeTasks).toEqual([42])
    expect(h.redo()!.addTasks![0].id).toBe(42)
  })
  it('remap with an empty map is a no-op', () => {
    const h = new History()
    h.push(m0(), move)
    h.remap({})
    expect(h.size.past).toBe(1)
  })
  it('dropLast removes a failed step', () => {
    const h = new History()
    h.push(m0(), move)
    h.undo()
    h.dropLast('future')
    expect(h.canRedo).toBe(false)
    h.push(m0(), move)
    h.dropLast('past')
    expect(h.canUndo).toBe(false)
  })
  it('clear empties both stacks', () => {
    const h = new History()
    h.push(m0(), move)
    h.push(m0(), move)
    h.undo()
    h.clear()
    expect(h.size).toEqual({ past: 0, future: 0 })
  })
})
