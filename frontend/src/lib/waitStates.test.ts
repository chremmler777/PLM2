import { describe, it, expect } from 'vitest'
import { resolveWaitStates } from './waitStates'
import { t } from '../i18n/cmLabels'

const change = (over: Record<string, unknown> = {}) => ({
  status: 'scoping', customer_relevant: true, blocked_department_ids: [],
  costing_pending_department_ids: [], rejection_sent_at: null, ...over,
}) as never

const concern = (over: Record<string, unknown> = {}) => ({
  id: 1, change_id: 7, kind: 'needs_info', note: 'What is the target price?',
  raised_by: 9, raised_at: '2026-08-01T09:00:00', is_open: true,
  department_id: null, answer_note: null, ...over,
}) as never

const deptName = (id: number) => ({ 2: 'Development', 4: 'Tool Engineer' }[id] ?? `#${id}`)

describe('resolveWaitStates', () => {
  it('says nothing when nothing is waiting', () => {
    expect(resolveWaitStates(change(), [], deptName)).toEqual([])
  })

  it('waits on Sales while a customer question is unanswered', () => {
    const [w] = resolveWaitStates(change(), [concern()], deptName)
    expect(w.key).toBe('sales-info-1')
    expect(w.text).toContain('What is the target price?')
    expect(w.tab).toBe('scoping')
  })

  it('waits on review once the answer is in', () => {
    const [w] = resolveWaitStates(change(), [concern({ answer_note: '12.50' })], deptName)
    expect(w.key).toBe('review-1')
    expect(w.text).toContain(t('wait.onReview').split('{x}')[0].trim())
  })

  it('forgets a question that has been settled', () => {
    expect(resolveWaitStates(change(), [concern({ is_open: false })], deptName)).toEqual([])
  })

  it('names the departments an open concern is holding, in assessment', () => {
    const waits = resolveWaitStates(
      change({ status: 'in_assessment', blocked_department_ids: [2, 4] }), [], deptName)
    expect(waits[0].key).toBe('blocked-departments')
    expect(waits[0].text).toContain('Development, Tool Engineer')
    // Only while the assessment is the live phase.
    expect(resolveWaitStates(
      change({ status: 'costing', blocked_department_ids: [2] }), [], deptName)).toEqual([])
  })

  it('names the departments still owing cost input, while costing', () => {
    const waits = resolveWaitStates(
      change({ status: 'costing', costing_pending_department_ids: [2, 4] }), [], deptName)
    expect(waits[0].key).toBe('costing-input')
    expect(waits[0].text).toContain('Development, Tool Engineer')
    expect(waits[0].tab).toBe('commercial')
    // Only while costing is the live phase.
    expect(resolveWaitStates(
      change({ status: 'quoted', costing_pending_department_ids: [2] }), [], deptName)).toEqual([])
  })

  it('waits on the rejection letter until the customer has been told', () => {
    const waits = resolveWaitStates(change({ status: 'rejected' }), [], deptName)
    expect(waits[0].key).toBe('rejection-letter')
    expect(resolveWaitStates(
      change({ status: 'rejected', rejection_sent_at: '2026-08-04T00:00:00' }), [], deptName)
    ).toEqual([])
    // An internal change owes the customer nothing.
    expect(resolveWaitStates(
      change({ status: 'rejected', customer_relevant: false }), [], deptName)).toEqual([])
  })

  it('lists every wait at once', () => {
    const waits = resolveWaitStates(
      change({ status: 'in_assessment', blocked_department_ids: [2] }),
      [concern(), concern({ id: 2, note: 'timing?', answer_note: 'Q4' })], deptName)
    expect(waits.map((w) => w.key)).toEqual(['sales-info-1', 'review-2', 'blocked-departments'])
  })
})
