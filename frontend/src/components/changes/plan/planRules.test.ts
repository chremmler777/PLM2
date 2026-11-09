import { describe, expect, it } from 'vitest'
import { classify, checkRules, newViolation } from './planRules'
import type { GanttTask } from '../../gantt/engine/types'

const t = (id: number, name: string, kind: string, start: string, duration: number, over: Partial<GanttTask> = {}): GanttTask =>
  ({ id, name, kind, start, duration, ...over })

describe('planning rules (mirror of backend plan_rules)', () => {
  it('classifies like the server', () => {
    expect(classify('downtime', 'Insert rework', 'Tool Engineer', null, null)).toBe('tool_change')
    expect(classify('downtime', 'Spare insert', 'Tool Engineer', null, 'spare_part')).toBeNull()
    expect(classify('supplier', 'Gauge update', 'APQP', null, null)).toBe('gauge_change')
    expect(classify('supplier', 'Nest rework', 'Manufacturing Engineer', null, null)).toBe('line_change')
    expect(classify('bank_build', 'Assembly bank build (idea)', 'Logistics', null, null)).toBe('assembly_bank_build')
    expect(classify('bank_build', 'Bank build', 'Logistics', null, null)).toBe('mold_bank_build')
    expect(classify('sampling', 'Assembly trial', null, null, null)).toBe('assembly_trial')
    expect(classify('work', 'Tool Engineer engineering', 'Tool Engineer', null, null)).toBeNull()
  })

  it('a: tool change only after the mold bank build', () => {
    const tasks = [t(1, 'Bank build', 'bank_build', '2027-01-04', 10), t(2, 'Rework', 'downtime', '2027-01-10', 5)]
    expect(checkRules(tasks, []).map((v) => v.code)).toEqual(['tool_change_during_bank_build'])
    tasks[1] = { ...tasks[1], start: '2027-01-14' }
    expect(checkRules(tasks, [])).toEqual([])
  })

  it('b, c, d: trials after their changes, line change after the assembly bank build', () => {
    const tasks = [
      t(1, 'Rework', 'downtime', '2027-01-04', 5), t(2, 'Gauge update', 'supplier', '2027-01-04', 8),
      t(3, 'Sampling', 'sampling', '2027-01-09', 2),
      t(4, 'Assembly bank build', 'bank_build', '2027-01-04', 5), t(5, 'Line change', 'downtime', '2027-01-06', 3),
      t(6, 'Assembly trial', 'sampling', '2027-01-08', 2),
    ]
    expect(checkRules(tasks, []).map((v) => v.code).sort()).toEqual([
      'assembly_trial_before_line_done', 'line_change_during_bank_build', 'trial_before_change_done'])
  })

  it('an idea only warns; only new breaks between committed blocks are refused', () => {
    const bank = t(1, 'Bank build (idea)', 'bank_build', '2027-01-04', 10, { isIdea: true })
    const tool = t(2, 'Rework', 'downtime', '2027-01-14', 5)
    const moved = { ...tool, start: '2027-01-05' }
    expect(newViolation({ tasks: [bank, tool], links: [] }, { tasks: [bank, moved], links: [] })).toBeNull()
    const real = { ...bank, isIdea: false }
    expect(newViolation({ tasks: [real, tool], links: [] }, { tasks: [real, moved], links: [] })?.code).toBe('tool_change_during_bank_build')
    // already broken before: an unrelated edit is not blocked
    expect(newViolation({ tasks: [real, moved], links: [] }, { tasks: [real, moved], links: [] })).toBeNull()
  })
})
