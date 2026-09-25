import { describe, expect, it } from 'vitest'
import {
  modelContains,
  applyAll, applyChangeSet, chainLinksChangeSet, duplicateChangeSet, invertChangeSet, isEmptyChangeSet,
  remapChangeSet, removeTasksChangeSet, touchedTaskIds, unlinkChangeSet,
} from './changes'
import { buildTree } from './tree'
import type { ChangeSet, GanttModel, GanttTask } from './types'

const T = (id: number | string, more: Partial<GanttTask> = {}): GanttTask =>
  ({ id, name: `T${id}`, start: '2026-10-05', duration: 2, ...more })

const model = (): GanttModel => ({
  tasks: [T(1), T(2, { parentId: 1 }), T(3, { parentId: 1 }), T(4), T(5)],
  links: [
    { id: 'a', from: 2, to: 3, type: 'FS', lagDays: 0 },
    { id: 'b', from: 3, to: 4, type: 'SS', lagDays: 1 },
    { id: 'c', from: 4, to: 5, type: 'FS', lagDays: 0 },
  ],
})

/** Apply cs, then its inverse, and expect the original model back (order-insensitive for links). */
function roundTrip(m: GanttModel, cs: ChangeSet) {
  const inv = invertChangeSet(m, cs)
  const back = applyChangeSet(applyChangeSet(m, cs), inv)
  const norm = (x: GanttModel) => ({
    // Undo clears a field that was unset with an explicit null (so adapters can persist the clear).
    tasks: x.tasks.map((t) => Object.fromEntries(Object.entries(t).filter(([, v]) => v != null))),
    links: [...x.links].sort((p, q) => String(p.id).localeCompare(String(q.id))),
  })
  expect(norm(back)).toEqual(norm(m))
}

describe('isEmptyChangeSet', () => {
  it('knows empty sets', () => {
    expect(isEmptyChangeSet(null)).toBe(true)
    expect(isEmptyChangeSet({ label: 'x', addTasks: [] })).toBe(true)
    expect(isEmptyChangeSet({ removeLinks: ['a'] })).toBe(false)
    expect(isEmptyChangeSet({ order: [1] })).toBe(false)
  })
})

describe('applyChangeSet', () => {
  it('adds tasks at the end', () => {
    const r = applyChangeSet(model(), { addTasks: [T(9)] })
    expect(r.tasks.map((t) => t.id)).toEqual([1, 2, 3, 4, 5, 9])
  })
  it('skips an add whose id already exists (idempotent reconcile)', () => {
    const r = applyChangeSet(model(), { addTasks: [T(1, { name: 'dup' })] })
    expect(r.tasks).toHaveLength(5)
    expect(r.tasks[0].name).toBe('T1')
  })
  it('patches tasks and merges several patches of one id', () => {
    const r = applyChangeSet(model(), { updateTasks: [{ id: 4, patch: { name: 'X' } }, { id: 4, patch: { duration: 7 } }] })
    expect(r.tasks[3]).toMatchObject({ id: 4, name: 'X', duration: 7 })
  })
  it('never changes an id through a patch', () => {
    const r = applyChangeSet(model(), { updateTasks: [{ id: 4, patch: { id: 99 } as Partial<GanttTask> }] })
    expect(r.tasks[3].id).toBe(4)
  })
  it('removes tasks and drops their links', () => {
    const r = applyChangeSet(model(), { removeTasks: [4] })
    expect(r.links.map((l) => l.id)).toEqual(['a'])
  })
  it('lifts children of a removed parent to top level', () => {
    const r = applyChangeSet(model(), { removeTasks: [1] })
    expect(r.tasks.find((t) => t.id === 2)!.parentId).toBeNull()
  })
  it('reorders with order, unknown ids ignored and missing ones kept last', () => {
    const r = applyChangeSet(model(), { order: [5, 99, 4, 1] })
    expect(r.tasks.map((t) => t.id)).toEqual([5, 4, 1, 2, 3])
  })
  it('adds, patches and removes links', () => {
    const r = applyChangeSet(model(), {
      addLinks: [{ id: 'd', from: 1, to: 5, type: 'FF', lagDays: 2 }],
      updateLinks: [{ id: 'b', patch: { type: 'FS', lagDays: -1 } }],
      removeLinks: ['c'],
    })
    expect(r.links.map((l) => l.id)).toEqual(['a', 'b', 'd'])
    expect(r.links[1]).toMatchObject({ type: 'FS', lagDays: -1 })
  })
  it('drops a new link to a missing task', () => {
    expect(applyChangeSet(model(), { addLinks: [{ id: 'z', from: 1, to: 77, type: 'FS', lagDays: 0 }] }).links).toHaveLength(3)
  })
  it('does not mutate the input model', () => {
    const m = model()
    const copy = JSON.parse(JSON.stringify(m))
    applyChangeSet(m, { updateTasks: [{ id: 1, patch: { name: 'Y' } }], removeTasks: [5], order: [5, 4] })
    expect(m).toEqual(copy)
  })
  it('applyAll applies in order', () => {
    const r = applyAll(model(), [{ updateTasks: [{ id: 1, patch: { name: 'A' } }] }, { updateTasks: [{ id: 1, patch: { name: 'B' } }] }])
    expect(r.tasks[0].name).toBe('B')
  })
})

describe('invertChangeSet round trips', () => {
  it('update', () => roundTrip(model(), { updateTasks: [{ id: 4, patch: { start: '2026-11-01', duration: 9 } }] }))
  it('update of a field that was unset', () => roundTrip(model(), { updateTasks: [{ id: 4, patch: { notes: 'hi', progress: 30 } }] }))
  it('undo of a field that was unset patches it to null', () => {
    expect(invertChangeSet(model(), { updateTasks: [{ id: 4, patch: { notes: 'hi' } }] }).updateTasks).toEqual([{ id: 4, patch: { notes: null } }])
  })
  it('add task', () => roundTrip(model(), { addTasks: [T(9)] }))
  it('add task with a link', () => roundTrip(model(), { addTasks: [T(9)], addLinks: [{ id: 'n', from: 5, to: 9, type: 'FS', lagDays: 0 }] }))
  it('remove a task with its links', () => roundTrip(model(), removeTasksChangeSet(model(), [4])!))
  it('remove a summary with children and links', () => roundTrip(model(), removeTasksChangeSet(model(), [1])!))
  it('remove only a parent: children come back under it', () => roundTrip(model(), { removeTasks: [1] }))
  it('remove only a task, its links implicitly', () => roundTrip(model(), { removeTasks: [3] }))
  it('reorder', () => roundTrip(model(), { order: [5, 4, 1, 2, 3] }))
  it('reparent', () => roundTrip(model(), { updateTasks: [{ id: 4, patch: { parentId: 1 } }], order: [1, 2, 3, 4, 5] }))
  it('link update', () => roundTrip(model(), { updateLinks: [{ id: 'b', patch: { type: 'FF', lagDays: 3 } }] }))
  it('link removal', () => roundTrip(model(), { removeLinks: ['a', 'c'] }))
  it('link add', () => roundTrip(model(), { addLinks: [{ id: 'x', from: 1, to: 4, type: 'FS', lagDays: 0 }] }))
  it('duplicate', () => roundTrip(model(), duplicateChangeSet(model(), [1])!))
  it('keeps the label and meta', () => {
    const inv = invertChangeSet(model(), { label: 'Move', meta: { reason: 'r' }, updateTasks: [{ id: 1, patch: { start: '2026-10-06' } }] })
    expect(inv).toMatchObject({ label: 'Move', meta: { reason: 'r' } })
  })
})

describe('remapChangeSet', () => {
  it('replaces temporary ids everywhere', () => {
    const cs: ChangeSet = {
      addTasks: [T('tmp1', { parentId: 'tmp0' })],
      updateTasks: [{ id: 'tmp1', patch: { parentId: 'tmp0' } }],
      removeTasks: ['tmp1'],
      addLinks: [{ id: 'lt', from: 'tmp0', to: 'tmp1', type: 'FS', lagDays: 0 }],
      updateLinks: [{ id: 'lt', patch: { lagDays: 1 } }],
      removeLinks: ['lt'],
      order: ['tmp0', 'tmp1', 3],
    }
    const r = remapChangeSet(cs, { tmp0: 10, tmp1: 11, lt: 50 })
    expect(r.addTasks![0]).toMatchObject({ id: 11, parentId: 10 })
    expect(r.updateTasks![0]).toEqual({ id: 11, patch: { parentId: 10 } })
    expect(r.removeTasks).toEqual([11])
    expect(r.addLinks![0]).toMatchObject({ id: 50, from: 10, to: 11 })
    expect(r.updateLinks![0].id).toBe(50)
    expect(r.removeLinks).toEqual([50])
    expect(r.order).toEqual([10, 11, 3])
  })
  it('leaves unknown ids alone and does not add parentId to patches', () => {
    const r = remapChangeSet({ updateTasks: [{ id: 3, patch: { name: 'x' } }] }, { tmp: 1 })
    expect(r.updateTasks).toEqual([{ id: 3, patch: { name: 'x' } }])
  })
})

describe('builders', () => {
  it('touchedTaskIds lists tasks and link targets', () => {
    expect(touchedTaskIds({ updateTasks: [{ id: 1, patch: {} }], addLinks: [{ id: 'x', from: 2, to: 3, type: 'FS', lagDays: 0 }] }).sort()).toEqual(['1', '3'])
  })
  it('removeTasksChangeSet includes the subtree and touching links', () => {
    const cs = removeTasksChangeSet(model(), [1])!
    expect(cs.removeTasks).toEqual([1, 2, 3])
    expect(cs.removeLinks).toEqual(['a', 'b'])
    expect(cs.label).toBe('Delete 3 tasks')
  })
  it('removeTasksChangeSet of one leaf', () => {
    expect(removeTasksChangeSet(model(), [5])).toEqual({ label: 'Delete task', removeTasks: [5], removeLinks: ['c'] })
  })
  it('removeTasksChangeSet with nothing', () => expect(removeTasksChangeSet(model(), [])).toBeNull())
  it('duplicate copies a subtree with its internal links right after it', () => {
    let k = 0
    const cs = duplicateChangeSet(model(), [1], () => `d${k++}`)!
    expect(cs.addTasks!.map((t) => t.id)).toEqual(['d0', 'd1', 'd2'])
    expect(cs.addTasks![0].name).toBe('T1 (copy)')
    expect(cs.addTasks![1]).toMatchObject({ parentId: 'd0', name: 'T2' })
    expect(cs.addLinks).toEqual([{ id: 'd3', from: 'd1', to: 'd2', type: 'FS', lagDays: 0 }])
    const after = applyChangeSet(model(), cs)
    expect(buildTree(after.tasks).order.map((t) => t.id)).toEqual([1, 2, 3, 'd0', 'd1', 'd2', 4, 5])
  })
  it('duplicate clears baselines, actuals and progress', () => {
    const m: GanttModel = { tasks: [T(1, { baselineStart: '2026-10-01', baselineEnd: '2026-10-03', actualStart: '2026-10-01', progress: 50 })], links: [] }
    expect(duplicateChangeSet(m, [1])!.addTasks![0]).toMatchObject({ baselineStart: null, baselineEnd: null, actualStart: null, progress: 0 })
  })
  it('chain links the selection in display order and skips existing links', () => {
    let k = 0
    const cs = chainLinksChangeSet(model(), [5, 2, 4, 3], () => `c${k++}`)!
    // Display order 2, 3, 4, 5: 2->3, 3->4 and 4->5 all exist already.
    expect(cs).toBeNull()
    const cs2 = chainLinksChangeSet(model(), [5, 1], () => `c${k++}`)!
    expect(cs2.addLinks).toEqual([{ id: 'c0', from: 1, to: 5, type: 'FS', lagDays: 0 }])
  })
  it('chain returns null when every link exists', () => {
    expect(chainLinksChangeSet(model(), [4, 5])).toBeNull()
  })
  it('chain adds FS links', () => {
    const cs = chainLinksChangeSet(model(), [1, 5, 4], () => 'n')!
    expect(cs.addLinks).toEqual([{ id: 'n', from: 1, to: 4, type: 'FS', lagDays: 0 }])
  })
  it('unlink removes links among the selection', () => {
    expect(unlinkChangeSet(model(), [2, 3, 4])!.removeLinks).toEqual(['a', 'b'])
  })
  it('unlink of a single task removes every link touching it', () => {
    expect(unlinkChangeSet(model(), [4])!.removeLinks).toEqual(['b', 'c'])
  })
  it('unlink with nothing to remove is null', () => expect(unlinkChangeSet(model(), [1, 5])).toBeNull())
})

describe('remap and reconcile (review)', () => {
  it('remaps link update ends and id values in meta', () => {
    const cs = remapChangeSet({ updateLinks: [{ id: 'l', patch: { from: 'tmp', to: 3 } }], meta: { focus: 'tmp', reason: 'why' } }, { tmp: 9, l: 5 })
    expect(cs.updateLinks).toEqual([{ id: 5, patch: { from: 9, to: 3 } }])
    expect(cs.meta).toEqual({ focus: 9, reason: 'why' })
  })
  it('modelContains tells whether a model already shows a ChangeSet', () => {
    const m: GanttModel = { tasks: [{ id: 1, name: 'A', start: '2026-10-05', duration: 2 }], links: [{ id: 'l', from: 1, to: 1, type: 'FS', lagDays: 0 }] }
    expect(modelContains(m, { updateTasks: [{ id: 1, patch: { name: 'A' } }] })).toBe(true)
    expect(modelContains(m, { updateTasks: [{ id: 1, patch: { name: 'B' } }] })).toBe(false)
    expect(modelContains(m, { addTasks: [{ id: 2, name: 'N', start: '2026-10-05', duration: 1 }] })).toBe(false)
    expect(modelContains(m, { removeTasks: [2], removeLinks: ['x'] })).toBe(true)
    expect(modelContains(m, { updateLinks: [{ id: 'l', patch: { lagDays: 1 } }] })).toBe(false)
  })
})
