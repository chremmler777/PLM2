import { describe, expect, it, vi } from 'vitest'
import type { PlanOut, TaskOut } from '../../../types/changePlan'
import {
  ECR_KINDS, hasDateChanges, patchToEcr, persistLegacy, planToModel, serialized, sortOrders, supportOf,
  taskToGantt, toLegacyCalls, toPlanChangeSet,
} from './ecrAdapter'

const task = (over: Partial<TaskOut> & { id: number }): TaskOut => ({
  change_id: 7, plan: 'detailed', name: `T${over.id}`, lane: 'Tool Engineer', department_id: 11,
  department_name: 'Tool Engineer', kind: 'work', is_idea: false, start_date: '2026-10-05', duration_days: 5,
  end_date: '2026-10-10', predecessors: [], sort_order: over.id, progress_pct: 0, actual_start: null,
  actual_finish: null, baseline_start: null, baseline_finish: null, notes: null, ...over,
})

const planOut = (over: Partial<PlanOut> = {}): PlanOut => ({
  plan: 'detailed',
  tasks: [task({ id: 1 }), task({ id: 2, predecessors: [1], sort_order: 5 }), task({ id: 3, sort_order: 2, lane: null, department_name: 'APQP' })],
  revision: 1, baseline_set: false, can_edit: true, can_edit_dates: true, progress_department_ids: [],
  summary: { start: null, finish: null, duration_days: 0, buffer_days: 0, critical_ids: [], ideas: 0 },
  validation: { errors: [], warnings: [] }, deadlines: [], ...over,
})

describe('PlanOut -> generic model', () => {
  it('detects the 088 server by the links array', () => {
    expect(supportOf(planOut()).modern).toBe(false)
    expect(supportOf(planOut({ links: [] })).modern).toBe(true)
  })

  it('orders tasks by sort_order then id', () => {
    const m = planToModel(planOut())
    expect(m.tasks.map((t) => t.id)).toEqual([1, 3, 2])
  })

  it('degrades to finish-to-start links from predecessors on a legacy server', () => {
    const m = planToModel(planOut())
    expect(m.links).toEqual([{ id: 'p1-2', from: 1, to: 2, type: 'FS', lagDays: 0 }])
    expect(m.calendar.mode).toBe('calendar')
    expect(m.support.modern).toBe(false)
  })

  it('drops predecessors that point outside the plan', () => {
    const m = planToModel(planOut({ tasks: [task({ id: 2, predecessors: [99] })] }))
    expect(m.links).toEqual([])
  })

  it('uses typed links with lag and the plan calendar on a 088 server', () => {
    const m = planToModel(planOut({
      links: [{ id: 40, from_task_id: 1, to_task_id: 2, type: 'SS', lag_days: -2 }, { id: 41, from_task_id: 1, to_task_id: 77, type: 'FS', lag_days: 0 }],
      calendar: { mode: 'working', workdays: [1, 2, 3, 4, 5], holidays: ['2026-12-25'] },
    }))
    expect(m.links).toEqual([{ id: 40, from: 1, to: 2, type: 'SS', lagDays: -2 }])
    expect(m.calendar).toEqual({ mode: 'working', workdays: [1, 2, 3, 4, 5], holidays: ['2026-12-25'] })
  })

  it('maps every task field', () => {
    const g = taskToGantt(task({
      id: 9, parent_id: 4, constraint_type: 'snet', constraint_date: '2026-11-01', progress_pct: 40,
      baseline_start: '2026-10-01', baseline_finish: '2026-10-06', actual_start: '2026-10-02', actual_finish: '2026-10-07',
      is_idea: true, notes: 'n', kind: 'buffer', source_position_id: 3,
    }))
    expect(g).toMatchObject({
      id: 9, parentId: 4, name: 'T9', start: '2026-10-05', duration: 5, kind: 'buffer', lane: 'Tool Engineer', isIdea: true,
      progress: 40, baselineStart: '2026-10-01', baselineEnd: '2026-10-06', actualStart: '2026-10-02', actualEnd: '2026-10-07',
      constraint: { type: 'snet', date: '2026-11-01' }, notes: 'n',
    })
    expect(g.meta).toMatchObject({ department_id: 11, own_lane: 'Tool Engineer', sort_order: 9, source_position_id: 3 })
  })

  it('shows the department as the lane when the task has none, asap as no constraint', () => {
    expect(taskToGantt(task({ id: 1, lane: '  ', department_name: 'APQP' })).lane).toBe('APQP')
    expect(taskToGantt(task({ id: 1, lane: null, department_name: null })).lane).toBeNull()
    expect(taskToGantt(task({ id: 1, constraint_type: 'asap' })).constraint).toBeNull()
  })

  it('has a style per ECR kind: buffers hatched, milestones as diamonds', () => {
    expect(ECR_KINDS.buffer.pattern).toBe('hatch')
    expect(ECR_KINDS.milestone.milestone).toBe(true)
    expect(Object.keys(ECR_KINDS)).toHaveLength(9)
  })
})

describe('generic patch -> ECR fields', () => {
  it('maps names, dates, flags, progress, actuals, parent and constraints', () => {
    expect(patchToEcr({
      name: 'x', start: '2026-10-06', duration: 3, kind: 'supplier', isIdea: true, progress: 55.4, notes: null,
      actualStart: '2026-10-06', actualEnd: null, parentId: 3, constraint: { type: 'fnlt', date: '2026-11-10' },
    })).toEqual({
      name: 'x', start_date: '2026-10-06', duration_days: 3, kind: 'supplier', is_idea: true, progress_pct: 55, notes: null,
      actual_start: '2026-10-06', actual_finish: null, parent_id: 3, constraint_type: 'fnlt', constraint_date: '2026-11-10',
    })
  })

  it('clears a constraint with asap and moves a task to top level with parentId null', () => {
    expect(patchToEcr({ constraint: { type: 'asap' }, parentId: null })).toEqual({ constraint_type: null, constraint_date: null, parent_id: null })
  })

  it('writes a lane only when it really changes', () => {
    const before = taskToGantt(task({ id: 1, lane: null, department_name: 'APQP' }))
    expect(patchToEcr({ lane: 'APQP' }, before)).toEqual({})
    expect(patchToEcr({ lane: 'Customer' }, before)).toEqual({ lane: 'Customer' })
    expect(patchToEcr({ lane: '' }, taskToGantt(task({ id: 1 })))).toEqual({ lane: null })
  })

  it('maps the owner department from meta', () => {
    expect(patchToEcr({ meta: { department_id: 12 } })).toEqual({ department_id: 12 })
  })

  it('knows date changes', () => {
    expect(hasDateChanges({ updateTasks: [{ id: 1, patch: { start: '2026-10-06' } }] })).toBe(true)
    expect(hasDateChanges({ updateTasks: [{ id: 1, patch: { duration: 2 } }] })).toBe(true)
    expect(hasDateChanges({ updateTasks: [{ id: 1, patch: { notes: 'x' } }] })).toBe(false)
    expect(hasDateChanges({ addTasks: [] })).toBe(false)
  })
})

describe('sort orders', () => {
  it('keeps increasing values and renumbers only what breaks the order', () => {
    const cur = new Map([['1', 1], ['2', 2], ['3', 3], ['4', 4]])
    expect([...sortOrders([1, 4, 2, 3], cur)]).toEqual([['2', 5], ['3', 6]])
    expect([...sortOrders([1, 2, 3, 4], cur)]).toEqual([])
  })

  it('numbers new tasks after their predecessor row', () => {
    const cur = new Map([['1', 10], ['2', 20]])
    expect([...sortOrders([1, 'tmp', 2], cur)]).toEqual([['tmp', 11]])
  })

  it('starts at 1 when the first task has no value', () => {
    expect([...sortOrders(['a', 'b'], new Map())]).toEqual([['a', 1], ['b', 2]])
  })
})

describe('ChangeSet -> POST /plan/changes', () => {
  const before = planToModel(planOut({ links: [] })).tasks

  it('creates, updates, deletes tasks and links in one body with temp ids', () => {
    const body = toPlanChangeSet({
      addTasks: [{ id: 'tmp-1', name: 'New', start: '2026-10-20', duration: 2, kind: 'work', lane: 'APQP', parentId: 1, meta: { department_id: 12 } }],
      updateTasks: [{ id: 2, patch: { start: '2026-10-08', notes: 'n' } }],
      removeTasks: [3],
      addLinks: [{ id: 'l-1', from: 1, to: 'tmp-1', type: 'SS', lagDays: 2 }],
      updateLinks: [{ id: 40, patch: { lagDays: -1 } }, { id: 'tmp-x', patch: { type: 'FF' } }],
      removeLinks: [41, 'p1-2'],
    }, before)
    expect(body.tasks_upsert).toEqual([
      { id: 'tmp-1', name: 'New', kind: 'work', lane: 'APQP', department_id: 12, start_date: '2026-10-20', duration_days: 2, is_idea: false, notes: null, parent_id: 1 },
      { id: 2, start_date: '2026-10-08', notes: 'n' },
    ])
    expect(body.tasks_delete).toEqual([3])
    expect(body.links_upsert).toEqual([
      { id: 'l-1', from_task_id: 1, to_task_id: 'tmp-1', type: 'SS', lag_days: 2 },
      { id: 40, lag_days: -1 },
    ])
    expect(body.links_delete).toEqual([41])
  })

  it('turns a new order into sort_order upserts merged with other fields', () => {
    const body = toPlanChangeSet({ updateTasks: [{ id: 1, patch: { name: 'A' } }], order: [2, 1, 3] }, before)
    const byId = Object.fromEntries(body.tasks_upsert.map((u) => [String(u.id), u]))
    expect(byId['1']).toEqual({ id: 1, name: 'A', sort_order: 6 })
    expect(byId['3']).toEqual({ id: 3, sort_order: 7 })
    expect(byId['2']).toBeUndefined()
  })

  it('does not upsert a task that is deleted in the same set', () => {
    const body = toPlanChangeSet({ updateTasks: [{ id: 3, patch: { name: 'x' } }], removeTasks: [3] }, before)
    expect(body.tasks_upsert).toEqual([])
  })

  it('carries constraints of new tasks', () => {
    const body = toPlanChangeSet({ addTasks: [{ id: 't', name: 'M', start: '2026-10-05', duration: 0, constraint: { type: 'mso', date: '2026-10-05' } }] }, before)
    expect(body.tasks_upsert[0]).toMatchObject({ constraint_type: 'mso', constraint_date: '2026-10-05', kind: 'work' })
  })
})

describe('ChangeSet -> legacy REST calls', () => {
  const m = planToModel(planOut())

  it('batches date moves into one bulk patch with the reason', () => {
    const calls = toLegacyCalls({ updateTasks: [{ id: 1, patch: { start: '2026-10-06' } }, { id: 2, patch: { duration: 3 } }] }, 'detailed', m.tasks, m.links, 'late')
    expect(calls).toEqual([{ kind: 'bulk', updates: [{ id: 1, start_date: '2026-10-06' }, { id: 2, duration_days: 3 }], reason: 'late' }])
  })

  it('splits fields from dates of the same task', () => {
    const calls = toLegacyCalls({ updateTasks: [{ id: 1, patch: { start: '2026-10-06', notes: 'x' } }] }, 'detailed', m.tasks, m.links)
    expect(calls).toEqual([
      { kind: 'patch', id: 1, body: { notes: 'x' } },
      { kind: 'bulk', updates: [{ id: 1, start_date: '2026-10-06' }] },
    ])
  })

  it('rewrites the predecessor list for added and removed links', () => {
    const calls = toLegacyCalls({ addLinks: [{ id: 'n', from: 3, to: 2, type: 'FS', lagDays: 0 }], removeLinks: ['p1-2'] }, 'detailed', m.tasks, m.links)
    expect(calls).toEqual([{ kind: 'patch', id: 2, body: { predecessors: [3] } }])
  })

  it('creates a task with its predecessors (temp ones resolved later)', () => {
    const calls = toLegacyCalls({
      addTasks: [{ id: 'a', name: 'A', start: '2026-10-10', duration: 2 }, { id: 'b', name: 'B', start: '2026-10-12', duration: 1 }],
      addLinks: [{ id: 'l1', from: 1, to: 'a', type: 'FS', lagDays: 0 }, { id: 'l2', from: 'a', to: 'b', type: 'FS', lagDays: 0 }],
    }, 'quote', m.tasks, m.links)
    expect(calls[0]).toMatchObject({ kind: 'create', tempId: 'a', predTemps: [], body: { plan: 'quote', name: 'A', predecessors: [1] } })
    expect(calls[1]).toMatchObject({ kind: 'create', tempId: 'b', predTemps: ['a'], body: { predecessors: [] } })
  })

  it('refuses what a legacy server cannot store', () => {
    expect(() => toLegacyCalls({ addLinks: [{ id: 'x', from: 1, to: 2, type: 'SS', lagDays: 0 }] }, 'detailed', m.tasks, m.links)).toThrow(/finish-to-start/)
    expect(() => toLegacyCalls({ addLinks: [{ id: 'x', from: 1, to: 3, type: 'FS', lagDays: 2 }] }, 'detailed', m.tasks, m.links)).toThrow()
    expect(() => toLegacyCalls({ updateTasks: [{ id: 1, patch: { parentId: 2 } }] }, 'detailed', m.tasks, m.links)).toThrow(/subtasks/)
  })

  it('deletes last and skips temp ids', () => {
    const calls = toLegacyCalls({ removeTasks: [3, 'tmp-9'], updateTasks: [{ id: 1, patch: { name: 'Z' } }] }, 'detailed', m.tasks, m.links)
    expect(calls).toEqual([{ kind: 'patch', id: 1, body: { name: 'Z' } }, { kind: 'delete', id: 3 }])
  })

  it('patches sort_order for a reorder', () => {
    const calls = toLegacyCalls({ order: [2, 1, 3] }, 'detailed', m.tasks, m.links)
    expect(calls).toEqual([
      { kind: 'patch', id: 1, body: { sort_order: 6 } },
      { kind: 'patch', id: 3, body: { sort_order: 7 } },
    ])
  })
})

describe('legacy persistence', () => {
  it('runs calls in order, maps created ids and resolves temp predecessors', async () => {
    const withNew = (ids: number[]) => planOut({ tasks: ids.map((id) => task({ id })) })
    const api = {
      createTask: vi.fn().mockResolvedValueOnce(withNew([1, 2, 3, 10])).mockResolvedValueOnce(withNew([1, 2, 3, 10, 11])),
      patchTask: vi.fn().mockResolvedValue(withNew([1, 2, 3, 10, 11])),
      bulkPatch: vi.fn().mockResolvedValue(withNew([1, 2, 3, 10, 11])),
      deleteTask: vi.fn().mockResolvedValue(withNew([1, 2, 10, 11])),
    }
    const res = await persistLegacy([
      { kind: 'create', tempId: 'a', predTemps: [], body: { plan: 'quote', name: 'A', kind: 'work', start_date: '2026-10-10', duration_days: 1, predecessors: [1] } },
      { kind: 'create', tempId: 'b', predTemps: ['a'], body: { plan: 'quote', name: 'B', kind: 'work', start_date: '2026-10-11', duration_days: 1, predecessors: [] } },
      { kind: 'patch', id: 'a', body: { predecessors: [2] } },
      { kind: 'bulk', updates: [{ id: 'b', start_date: '2026-10-20' }] },
      { kind: 'delete', id: 3 },
    ], api, [1, 2, 3])
    expect(res.idMap).toEqual({ a: 10, b: 11 })
    expect(api.createTask.mock.calls[1][0].predecessors).toEqual([10])
    expect(api.patchTask).toHaveBeenCalledWith(10, { predecessors: [2] })
    expect(api.bulkPatch).toHaveBeenCalledWith([{ id: 11, start_date: '2026-10-20' }], undefined)
    expect(api.deleteTask).toHaveBeenCalledWith(3)
    expect(res.plan?.tasks.map((t) => t.id)).toEqual([1, 2, 10, 11])
  })

  it('stops at the first failing call (the caller refetches)', async () => {
    const api = {
      createTask: vi.fn(), patchTask: vi.fn().mockRejectedValue(new Error('no')), bulkPatch: vi.fn(), deleteTask: vi.fn(),
    }
    await expect(persistLegacy([
      { kind: 'patch', id: 1, body: { name: 'x' } }, { kind: 'delete', id: 2 },
    ], api, [1, 2])).rejects.toThrow('no')
    expect(api.deleteTask).not.toHaveBeenCalled()
  })
})

describe('save serialization per plan', () => {
  it('runs one save at a time per key and keeps going after a failure', async () => {
    const order: string[] = []
    let release!: () => void
    const first = serialized('7:quote', () => new Promise<void>((r) => { release = () => { order.push('a'); r() } }))
    const second = serialized('7:quote', async () => { order.push('b'); throw new Error('x') })
    const third = serialized('7:quote', async () => { order.push('c') })
    const other = serialized('7:detailed', async () => { order.push('other') })
    await other
    expect(order).toEqual(['other'])
    release()
    await first
    await expect(second).rejects.toThrow('x')
    await third
    expect(order).toEqual(['other', 'a', 'b', 'c'])
  })
})
