import { describe, it, expect } from 'vitest'
import { mayTransition, mayMoveCarrier, mayEditCapture, endStateOf, endLabel, hasEnded, stoppedAtFrom } from './transitionRights'

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
    expect(mayTransition({ status: 'quoting' }, 'quoted', { ...none, isSales: true })).toBe(true)
  })
  it('keeps the C1 mid-flow hops and every resume for the run team', () => {
    const hops: [string, string][] = [
      ['quoted', 'approved'], ['costing', 'approved'], ['approved', 'in_implementation'],
      ['in_implementation', 'in_validation'], ['rejected', 'scoping'],
      ['on_hold', 'in_assessment'], ['on_hold', 'quoted'],
    ]
    for (const [from, to] of hops) {
      const c = { status: from as 'quoted' }
      expect(mayTransition(c, to, none)).toBe(false)
      expect(mayTransition(c, to, { ...none, isSales: true })).toBe(false)
      expect(mayTransition(c, to, { ...none, isPm: true })).toBe(true)
      expect(mayTransition(c, to, { ...none, isChangeLead: true })).toBe(true)
      expect(mayTransition(c, to, { ...none, isAdmin: true })).toBe(true)
    }
  })
  it('lets Sales send a change back from validation (only the start from approved is C1)', () => {
    const c = { status: 'in_validation' as const }
    expect(mayTransition(c, 'in_implementation', { ...none, isSales: true })).toBe(true)
    expect(mayTransition(c, 'in_implementation', none)).toBe(false)
    expect(mayTransition({ status: 'approved' }, 'in_implementation', { ...none, isSales: true })).toBe(false)
  })
  it('gives Sales no capture hop on an internal change that has a lead', () => {
    const internal = { status: 'captured' as const, customer_relevant: false, lead_id: 7 }
    expect(mayTransition(internal, 'scoping', { ...none, isSales: true })).toBe(false)
    expect(mayTransition(internal, 'rejected', { ...none, isSales: true })).toBe(false)
    expect(mayTransition(internal, 'scoping', { ...none, isChangeLead: true })).toBe(true)
    expect(mayTransition({ ...internal, lead_id: null }, 'scoping', { ...none, isSales: true })).toBe(true)
  })
})

describe('mayMoveCarrier (P3 / C10)', () => {
  const starter = { ...none, canStartChange: true }
  const engineer = { ...none, canStartChange: false }
  it('lets Sales and PM make an internal change a customer change without leading it', () => {
    expect(mayMoveCarrier(false, { ...starter, isSales: true })).toBe(true)
    expect(mayMoveCarrier(false, { ...starter, isPm: true })).toBe(true)
    expect(mayMoveCarrier(false, { ...none, canStartChange: false, isAdmin: true })).toBe(true)
  })
  it('refuses the engineering lead and a non-starter lead (Quality) the flip', () => {
    expect(mayMoveCarrier(false, { ...engineer, isChangeLead: true })).toBe(false)
    expect(mayMoveCarrier(false, engineer)).toBe(false)
  })
  it('keeps the way back for a starter or PM lead and the admin, not the engineering raiser', () => {
    expect(mayMoveCarrier(true, { ...engineer, isChangeLead: true })).toBe(false)
    expect(mayMoveCarrier(true, { ...starter, isChangeLead: true })).toBe(true)
    expect(mayMoveCarrier(true, { ...engineer, isChangeLead: true, isPm: true })).toBe(true)
    expect(mayMoveCarrier(true, { ...none, canStartChange: false, isAdmin: true })).toBe(true)
    expect(mayMoveCarrier(true, { ...starter, isSales: true })).toBe(false)
    expect(mayMoveCarrier(true, { ...starter, isPm: true })).toBe(false)
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

describe('mayEditCapture (PATCH rights: lead, Sales, pm_capture)', () => {
  const none = { isAdmin: false, isChangeLead: false, isPm: false, isSales: false }
  it('refuses a PM member on an internal change with a lead (the backend 403s)', () => {
    expect(mayEditCapture({ origin: 'internal', status: 'scoping', lead_id: 22 },
      { ...none, isPm: true })).toBe(false)
  })
  it('lets PM capture where nobody leads yet, or on a mother-plant change', () => {
    expect(mayEditCapture({ origin: 'internal', status: 'captured', lead_id: null },
      { ...none, isPm: true })).toBe(true)
    expect(mayEditCapture({ origin: 'mother_plant', status: 'approved', lead_id: 3 },
      { ...none, isPm: true })).toBe(true)
  })
  it('lets the lead, Sales and an admin edit', () => {
    const c = { origin: 'internal' as const, status: 'scoping' as const, lead_id: 22 }
    expect(mayEditCapture(c, { ...none, isChangeLead: true })).toBe(true)
    expect(mayEditCapture(c, { ...none, isSales: true })).toBe(true)
    expect(mayEditCapture(c, { ...none, isAdmin: true })).toBe(true)
    expect(mayEditCapture(c, none)).toBe(false)
  })
})
