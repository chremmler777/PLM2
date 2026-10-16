import { describe, it, expect } from 'vitest'
import { askingSide, canAnswerQuestion, openFlagLines } from './scopingRules'
import type { ChangeConcern } from '../types/change'

const q = (over: Partial<ChangeConcern> = {}): ChangeConcern => ({
  id: 1, change_id: 7, kind: 'needs_info', note: 'Tolerance?', raised_by: 9,
  raised_by_name: 'Ann', raised_at: '2026-10-14T09:00:00Z', is_open: true,
  department_id: null, ...over,
}) as ChangeConcern

describe('canAnswerQuestion (2026-10-14: the asking side, Sales, PM)', () => {
  it('trusts the served verdict', () => {
    expect(canAnswerQuestion(q({ can_answer: false }), { isSales: true })).toBe(false)
    expect(canAnswerQuestion(q({ can_answer: true }), {})).toBe(true)
  })
  it('falls back to the rule: asking department, Sales, PM', () => {
    const dept = q({ department_id: 4 })
    expect(canAnswerQuestion(dept, { myDepartmentIds: [4] })).toBe(true)
    expect(canAnswerQuestion(dept, { myDepartmentIds: [5] })).toBe(false)
    expect(canAnswerQuestion(dept, { isSales: true })).toBe(true)
    expect(canAnswerQuestion(dept, { isPm: true })).toBe(true)
    // the author of a department question answers as a member, not as author
    expect(canAnswerQuestion(dept, { userId: 9 })).toBe(false)
  })
  it('without a department the author answers, but not while acting as one', () => {
    expect(canAnswerQuestion(q(), { userId: 9 })).toBe(true)
    expect(canAnswerQuestion(q(), { userId: 9, actingAs: true })).toBe(false)
    expect(canAnswerQuestion(q(), { userId: 3 })).toBe(false)
  })
  it('never for a closed question', () => {
    expect(canAnswerQuestion(q({ is_open: false }), { isSales: true })).toBe(false)
  })
})

describe('askingSide / openFlagLines', () => {
  it('names the department, else the author', () => {
    expect(askingSide(q({ asking_department_name: 'APQP', department_id: 4 }))).toBe('APQP')
    expect(askingSide(q({ department_id: 4 }), () => 'Quality')).toBe('Quality')
    expect(askingSide(q())).toBe('Ann')
  })
  it('lists the open flags that block proceed, risks and closed ones left out', () => {
    expect(openFlagLines([
      q({ id: 2, kind: 'reject_proposal', note: 'Too costly', raised_by_name: 'Ben' }),
      q({ id: 1, department_id: 4 }),
      q({ id: 3, kind: 'risk' as never }),
      q({ id: 4, is_open: false }),
    ], () => 'APQP')).toEqual(['Question · Ann (APQP): Tolerance?', 'Cancel vote · Ben: Too costly'])
  })
  it('A2-04: an answered question says its asker settles it', () => {
    expect(openFlagLines([q({ department_id: 4, answered_at: '2026-10-15T09:00:00Z' })], () => 'APQP'))
      .toEqual(['Question · Ann (APQP): Tolerance? (answered, APQP settles)'])
  })
})
