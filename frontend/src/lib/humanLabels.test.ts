import { describe, it, expect } from 'vitest'
import { verdictLabel, changeTypeLabel, priorityLabel, taskKindLabel, auditValueLabel, humanize, plural } from './humanLabels'

describe('humanLabels (spec §16 P2)', () => {
  it('names codes in words', () => {
    expect(verdictLabel('feasible_with_conditions')).toBe('Feasible with conditions')
    expect(verdictLabel('not_feasible')).toBe('Not feasible')
    expect(changeTypeLabel('physical_part')).toBe('Physical part')
    expect(priorityLabel('critical')).toBe('Critical')
    expect(taskKindLabel('costing_input')).toBe('Enter costs')
    expect(taskKindLabel('brand_new_kind')).toBe('Brand new kind')
    expect(taskKindLabel('assessment', 'Server label')).toBe('Server label')
    expect(humanize('')).toBe('-')
  })
  it('reads audit values: statuses, verdicts, booleans, dates', () => {
    expect(auditValueLabel('status', '"in_assessment"')).toBe('In Assessment')
    expect(auditValueLabel('verdict', 'pending')).toBe('Not answered yet')
    expect(auditValueLabel('customer_relevant', 'true')).toBe('Yes')
    expect(auditValueLabel('required_by_date', '2026-10-05')).toBe('05.10.2026')
    expect(auditValueLabel('note', 'Wall 2.5 to 1.8 mm')).toBe('Wall 2.5 to 1.8 mm')
    expect(auditValueLabel(null, 'some_code_here')).toBe('Some code here')
  })
  it('pluralizes', () => {
    expect(plural(1, 'risk')).toBe('1 risk')
    expect(plural(2, 'risk')).toBe('2 risks')
  })
})
