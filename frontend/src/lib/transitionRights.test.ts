import { describe, it, expect } from 'vitest'
import { mayTransition, endStateOf, endLabel, hasEnded, stoppedAtFrom } from './transitionRights'

const none = { isAdmin: false, isChangeLead: false, isPm: false, isSales: false }

describe('mayTransition (spec §16 P1 4)', () => {
  it('lets only lead, PM and admin reject, cancel, hold, recall and close the assessment', () => {
    for (const to of ['rejected', 'cancelled', 'on_hold', 'scoping', 'costing']) {
      expect(mayTransition({ status: 'in_assessment' }, to, none)).toBe(false)
      expect(mayTransition({ status: 'in_assessment' }, to, { ...none, isSales: true })).toBe(false)
      expect(mayTransition({ status: 'in_assessment' }, to, { ...none, isPm: true })).toBe(true)
      expect(mayTransition({ status: 'in_assessment' }, to, { ...none, isChangeLead: true })).toBe(true)
      expect(mayTransition({ status: 'in_assessment' }, to, { ...none, isAdmin: true })).toBe(true)
    }
  })
  it('lets Sales kick off and reject at capture', () => {
    expect(mayTransition({ status: 'captured' }, 'scoping', { ...none, isSales: true })).toBe(true)
    expect(mayTransition({ status: 'captured' }, 'rejected', { ...none, isSales: true })).toBe(true)
    expect(mayTransition({ status: 'captured' }, 'scoping', none)).toBe(false)
  })
  it('follows the backend list when there is one', () => {
    expect(mayTransition({ status: 'in_assessment', allowed_transitions: ['costing'] }, 'costing', none)).toBe(true)
    expect(mayTransition({ status: 'in_assessment', allowed_transitions: ['costing'] }, 'rejected',
      { ...none, isAdmin: true })).toBe(false)
  })
  it('leaves other steps to their own gates', () => {
    expect(mayTransition({ status: 'quoting' }, 'costing', none)).toBe(true)
    expect(mayTransition({ status: 'approved' }, 'in_implementation', none)).toBe(true)
  })
})

describe('end states (spec §16 P1 7)', () => {
  it('tells rejected, rejected-then-closed, cancelled and closed apart', () => {
    expect(endStateOf({ status: 'rejected' })).toBe('rejected')
    expect(endStateOf({ status: 'closed', rejected_at: '2026-09-01' })).toBe('rejected')
    expect(endStateOf({ status: 'closed' })).toBe('closed')
    expect(endStateOf({ status: 'cancelled' })).toBe('cancelled')
    expect(endStateOf({ status: 'on_hold' })).toBeNull()
    expect(endLabel({ status: 'closed', rejected_at: '2026-09-01' })).toBe('Rejected, closed')
    expect(endLabel({ status: 'cancelled' })).toBe('Canceled')
    expect(hasEnded({ status: 'costing' })).toBe(false)
  })
  it('reads the stopped stage from the backend, else the last stop in the log', () => {
    expect(stoppedAtFrom({ status: 'rejected', stopped_at: 'scoping' })).toBe('scoping')
    expect(stoppedAtFrom({ status: 'cancelled' }, [
      { old_value: 'captured', new_value: 'scoping' },
      { old_value: 'scoping', new_value: 'in_assessment' },
      { old_value: 'in_assessment', new_value: 'cancelled' },
    ])).toBe('in_assessment')
  })
})
