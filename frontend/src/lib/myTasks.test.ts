import { describe, it, expect } from 'vitest'
import { byUrgency, foldChangeTasks, foldWorkflowTasks } from './myTasks'
import type { ChangeTask } from '../types/change'
import type { MyTask } from '../types/workflow'

const ct = (over: Partial<ChangeTask>): ChangeTask => ({
  kind: 'assessment', change_id: 1, change_number: 'CR-1', title: 'T',
  due_date: null, overdue: false, department_id: 2, ...over,
})

describe('foldChangeTasks', () => {
  it('folds R and A rows of one department into one, earliest due and both letters', () => {
    const out = foldChangeTasks([
      ct({ rasic_letters: ['A'], due_date: '2026-10-05' }),
      ct({ rasic_letters: ['R'], due_date: '2026-10-01', overdue: true }),
    ])
    expect(out).toHaveLength(1)
    expect(out[0].rasic_letters).toEqual(['R', 'A'])
    expect(out[0].due_date).toBe('2026-10-01')
    expect(out[0].overdue).toBe(true)
  })

  it('keeps different departments and kinds apart, survives a non-array', () => {
    expect(foldChangeTasks([ct({}), ct({ department_id: 3 }), ct({ kind: 'kickoff' })])).toHaveLength(3)
    expect(foldChangeTasks(undefined)).toEqual([])
  })
})

describe('foldWorkflowTasks', () => {
  it('folds the same step of one department into one row', () => {
    const base = { task_id: 1, instance_id: 5, stage_order: 1, step_name: 'Check',
      department_name: 'Quality', rasic_letter: 'A', overdue: false, due_date: null, mine: false } as unknown as MyTask
    const out = foldWorkflowTasks([base, { ...base, task_id: 2, rasic_letter: 'R' } as MyTask])
    expect(out).toHaveLength(1)
    expect(out[0].letters).toEqual(['R', 'A'])
  })
})

describe('byUrgency', () => {
  it('puts overdue first, then the nearest date, undated last', () => {
    const rows = [
      { id: 'undated', overdue: false, due_date: null },
      { id: 'later', overdue: false, due_date: '2026-12-01' },
      { id: 'late', overdue: true, due_date: '2026-09-01' },
      { id: 'soon', overdue: false, due_date: '2026-10-01' },
    ]
    expect([...rows].sort(byUrgency).map((r) => r.id)).toEqual(['late', 'soon', 'later', 'undated'])
  })
})
