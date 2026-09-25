import { describe, expect, it } from 'vitest'
import { applyChangeSet } from '../../gantt/engine/changes'
import type { GanttLink, GanttTask } from '../../gantt/engine/types'
import {
  bankBuildChangeSet, bufferChangeSet, ideasFollow, matchSelection, runParallel, snapToLinks, withSuccessorMoves,
} from './ecrActions'

let n = 0
const newId = () => `n${++n}`
const t = (id: number, start: string, duration: number, over: Partial<GanttTask> = {}): GanttTask =>
  ({ id, name: `T${id}`, start, duration, lane: 'Tool Engineer', meta: { department_id: 11 }, ...over })
const fs = (id: string, from: number, to: number, lagDays = 0): GanttLink => ({ id, from, to, type: 'FS', lagDays })

// order 5 Oct (Mon) 5d -> sampling 10 Oct 3d -> approval 13 Oct 14d -> SOP 27 Oct
const plan = () => ({
  tasks: [
    t(1, '2026-10-05', 5, { kind: 'downtime' }),
    t(2, '2026-10-10', 3, { kind: 'sampling' }),
    t(3, '2026-10-13', 14, { kind: 'customer', lane: 'Customer' }),
    t(4, '2026-10-27', 0, { kind: 'milestone', name: 'SOP', lane: 'Customer' }),
  ],
  links: [fs('a', 1, 2), fs('b', 2, 3), fs('c', 3, 4)],
  newId,
})

describe('buffer preset', () => {
  it('without a selection goes in front of the last milestone and pushes it', () => {
    const ctx = plan()
    const cs = bufferChangeSet(ctx, [], 5)
    const buf = cs.addTasks![0]
    expect(buf).toMatchObject({ name: 'Safety buffer', kind: 'buffer', duration: 5, start: '2026-10-27', lane: 'Customer' })
    expect(cs.removeLinks).toEqual(['c'])
    expect(cs.addLinks).toEqual([
      { id: expect.any(String), from: 3, to: buf.id, type: 'FS', lagDays: 0 },
      { id: expect.any(String), from: buf.id, to: 4, type: 'FS', lagDays: 0 },
    ])
    expect(cs.updateTasks).toEqual([{ id: 4, patch: { start: '2026-11-01' } }])
    expect(cs.order!.map(String)).toEqual(['1', '2', '3', String(buf.id), '4'])
  })

  it('after the selection takes over its outgoing links and pushes the chain', () => {
    const ctx = plan()
    const cs = bufferChangeSet(ctx, [2], 2)
    const buf = cs.addTasks![0]
    expect(buf).toMatchObject({ start: '2026-10-13', lane: 'Tool Engineer', meta: { department_id: 11 } })
    expect(cs.removeLinks).toEqual(['b'])
    expect(cs.addLinks!.map((l) => [l.from, l.to])).toEqual([[2, buf.id], [buf.id, 3]])
    const after = applyChangeSet(ctx, cs)
    expect(after.tasks.find((x) => x.id === 3)!.start).toBe('2026-10-15')
    expect(after.tasks.find((x) => x.id === 4)!.start).toBe('2026-10-29')
  })

  it('uses the selected task that ends last', () => {
    const cs = bufferChangeSet(plan(), [1, 3], 5)
    expect(cs.addLinks![0].from).toBe(3)
  })

  it('appends after the last task when the plan has no milestone', () => {
    const ctx = { tasks: [t(1, '2026-10-05', 5), t(2, '2026-10-05', 8)], links: [], newId }
    const cs = bufferChangeSet(ctx, [], 5)
    expect(cs.addTasks![0].start).toBe('2026-10-13')
    expect(cs.addLinks).toEqual([{ id: expect.any(String), from: 2, to: cs.addTasks![0].id, type: 'FS', lagDays: 0 }])
  })

  it('starts on a working day in working mode', () => {
    const ctx = { ...plan(), calendar: { mode: 'working' as const, workdays: [1, 2, 3, 4, 5], holidays: [] } }
    const cs = bufferChangeSet(ctx, [1], 3)
    // Task 1 Mon 5 Oct + 5 working days ends Sat 10 Oct: the buffer starts Monday 12.
    expect(cs.addTasks![0].start).toBe('2026-10-12')
  })
})

describe('bank build preset', () => {
  it('ends where the first downtime starts, in the Scheduling lane, as an idea', () => {
    const cs = bankBuildChangeSet(plan(), [], { lane: 'Scheduling', departmentId: 30 }, 10)
    expect(cs.addTasks![0]).toMatchObject({
      name: 'Bank build (idea)', kind: 'bank_build', isIdea: true, lane: 'Scheduling', start: '2026-09-25', duration: 10,
      meta: { department_id: 30 },
    })
    // Linked FS into the downtime so it follows it.
    expect(cs.addLinks).toEqual([{ id: expect.any(String), from: cs.addTasks![0].id, to: 1, type: 'FS', lagDays: 0 }])
    expect(cs.order!.map(String)[0]).toBe(String(cs.addTasks![0].id))
    expect(cs.meta).toBeUndefined()
  })

  it('ends at the selection start when something is selected', () => {
    const cs = bankBuildChangeSet(plan(), [3], { lane: 'Scheduling', departmentId: null }, 10)
    expect(cs.addTasks![0].start).toBe('2026-10-03')
  })

  it('without a downtime or selection starts at the plan start', () => {
    const ctx = { tasks: [t(1, '2026-10-05', 5)], links: [], newId }
    const cs = bankBuildChangeSet(ctx, [], { lane: 'Scheduling', departmentId: null }, 10)
    expect(cs.addTasks![0].start).toBe('2026-10-05')
  })
})

describe('alignment', () => {
  it('snaps a task to its predecessor end, earlier or later', () => {
    const ctx = { tasks: [t(1, '2026-10-05', 5), t(2, '2026-10-20', 2), t(3, '2026-10-01', 1)], links: [fs('a', 1, 2), fs('b', 1, 3)] }
    const cs = snapToLinks(ctx, [2, 3])!
    expect(cs.updateTasks).toEqual([{ id: 2, patch: { start: '2026-10-10' } }, { id: 3, patch: { start: '2026-10-10' } }])
  })

  it('snaps a chain in dependency order and honours lag and link types', () => {
    const ctx = {
      tasks: [t(1, '2026-10-05', 5), t(2, '2026-10-01', 2), t(3, '2026-10-01', 4)],
      links: [fs('a', 1, 2, 1), { id: 'b', from: 2, to: 3, type: 'FF' as const, lagDays: 0 }],
    }
    const cs = snapToLinks(ctx, [3, 2])!
    const s = Object.fromEntries(cs.updateTasks!.map((u) => [String(u.id), u.patch.start]))
    expect(s['2']).toBe('2026-10-11')
    expect(s['3']).toBe('2026-10-09')
  })

  it('returns null when nothing moves', () => {
    const ctx = { tasks: [t(1, '2026-10-05', 5), t(2, '2026-10-10', 2)], links: [fs('a', 1, 2)] }
    expect(snapToLinks(ctx, [2])).toBeNull()
    expect(snapToLinks(ctx, [1])).toBeNull()
  })

  it('matches start or end of the first selected', () => {
    const ctx = { tasks: [t(1, '2026-10-05', 5), t(2, '2026-10-20', 2)], links: [] }
    expect(matchSelection(ctx, [1, 2], 'start')!.updateTasks).toEqual([{ id: 2, patch: { start: '2026-10-05' } }])
    expect(matchSelection(ctx, [1, 2], 'end')!.updateTasks).toEqual([{ id: 2, patch: { start: '2026-10-08' } }])
    expect(matchSelection(ctx, [], 'end')).toBeNull()
  })

  it('runs the selection in parallel: drops their links, same start', () => {
    const ctx = plan()
    const cs = runParallel(ctx, [1, 2])!
    expect(cs.removeLinks).toEqual(['a'])
    expect(cs.updateTasks).toEqual([{ id: 2, patch: { start: '2026-10-05' } }])
    expect(runParallel(ctx, [1])).toBeNull()
  })
})

describe('successor moves after the baseline', () => {
  it('adds the pushed successors and lists them', () => {
    const ctx = plan()
    const { cs, moved } = withSuccessorMoves(ctx, { updateTasks: [{ id: 1, patch: { start: '2026-10-08' } }] })
    expect(cs.updateTasks!.map((u) => [u.id, u.patch.start])).toEqual([
      [1, '2026-10-08'], [2, '2026-10-13'], [3, '2026-10-16'], [4, '2026-10-30'],
    ])
    expect(moved.map((m) => [m.name, m.days])).toEqual([['T2', 3], ['T3', 3], ['SOP', 3]])
  })

  it('does not pull successors earlier and ignores unrelated violations', () => {
    const ctx = { tasks: [t(1, '2026-10-05', 5), t(2, '2026-10-10', 2), t(8, '2026-10-01', 1), t(9, '2026-09-01', 1)], links: [fs('a', 1, 2), fs('z', 8, 9)] }
    const { moved } = withSuccessorMoves(ctx, { updateTasks: [{ id: 1, patch: { start: '2026-10-01' } }] })
    expect(moved).toEqual([])
  })

  it('leaves a ChangeSet without date changes alone', () => {
    const cs = { updateTasks: [{ id: 1, patch: { notes: 'x' } }] }
    expect(withSuccessorMoves(plan(), cs)).toEqual({ cs, moved: [] })
  })
})

describe('successor moves follow summaries (backend cascade)', () => {
  it('a moved leaf pushes the successors of its summary', () => {
    const ctx = {
      tasks: [t(1, '2026-10-05', 0, { name: 'S' }), t(2, '2026-10-05', 3, { parentId: 1 }), t(3, '2026-10-08', 2)],
      links: [fs('s', 1, 3)],
    }
    const { moved } = withSuccessorMoves(ctx, { updateTasks: [{ id: 2, patch: { start: '2026-10-07' } }] })
    expect(moved.map((m) => [m.id, m.to])).toEqual([[3, '2026-10-10']])
  })

  it('a link into a summary pushes every leaf below it', () => {
    const ctx = {
      tasks: [t(1, '2026-10-05', 3), t(2, '2026-10-05', 0, { name: 'S' }), t(3, '2026-10-08', 2, { parentId: 2 }), t(4, '2026-10-09', 1, { parentId: 2 })],
      links: [fs('a', 1, 2)],
    }
    const { moved } = withSuccessorMoves(ctx, { updateTasks: [{ id: 1, patch: { start: '2026-10-08' } }] })
    expect(moved.map((m) => [m.id, m.to]).sort()).toEqual([[3, '2026-10-11'], [4, '2026-10-11']])
  })

  it('a pinned successor stays and nothing is pulled earlier', () => {
    const ctx = {
      tasks: [t(1, '2026-10-05', 3), t(2, '2026-10-08', 2, { constraint: { type: 'mso', date: '2026-10-08' } }), t(3, '2026-10-20', 1)],
      links: [fs('a', 1, 2), fs('b', 1, 3)],
    }
    const { moved } = withSuccessorMoves(ctx, { updateTasks: [{ id: 1, patch: { start: '2026-10-07' } }] })
    expect(moved).toEqual([])
  })

  it('counts slip in working days in working mode', () => {
    const ctx = {
      tasks: [t(1, '2026-10-05', 5), t(2, '2026-10-12', 2)], links: [fs('a', 1, 2)],
      calendar: { mode: 'working' as const, workdays: [1, 2, 3, 4, 5], holidays: [] },
    }
    // A moves Mon 5 -> Mon 12 (5 working days): B moves Mon 12 -> Mon 19, 5 working days.
    const { moved } = withSuccessorMoves(ctx, { updateTasks: [{ id: 1, patch: { start: '2026-10-12' } }] })
    expect(moved).toEqual([expect.objectContaining({ id: 2, to: '2026-10-19', days: 5 })])
  })
})

describe('bank build ideas follow their anchor (G15)', () => {
  it('warns about a second bank build on the same downtime', () => {
    const ctx = plan()
    const first = bankBuildChangeSet(ctx, [], { lane: 'Scheduling', departmentId: null })
    const after = applyChangeSet(ctx, first)
    const second = bankBuildChangeSet({ ...ctx, tasks: after.tasks, links: after.links }, [], { lane: 'Scheduling', departmentId: null })
    expect(second.meta?.warning).toContain('already has a bank build idea')
  })
  it('moves a linked idea along with its anchor', () => {
    const ctx = { tasks: [t(1, '2026-09-25', 10, { isIdea: true, kind: 'bank_build' }), t(2, '2026-10-05', 5, { kind: 'downtime' })], links: [fs('a', 1, 2)] }
    const cs = ideasFollow(ctx, { updateTasks: [{ id: 2, patch: { start: '2026-10-12' } }] })
    expect(cs.updateTasks).toEqual([{ id: 2, patch: { start: '2026-10-12' } }, { id: 1, patch: { start: '2026-10-02' } }])
  })
  it('leaves a non-idea predecessor alone', () => {
    const ctx = { tasks: [t(1, '2026-09-25', 10), t(2, '2026-10-05', 5)], links: [fs('a', 1, 2)] }
    const cs = { updateTasks: [{ id: 2, patch: { start: '2026-10-12' } }] }
    expect(ideasFollow(ctx, cs)).toBe(cs)
  })
})
