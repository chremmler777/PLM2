import { describe, it, expect } from 'vitest'
import { stageResponsibleKey } from './StageResponsibleBadge'

describe('stageResponsibleKey', () => {
  it('gives the capture of an internal change to its lead, not Sales (P3)', () => {
    expect(stageResponsibleKey('captured', 'internal')).toBe('role.lead')
    expect(stageResponsibleKey('captured', 'internal', 7)).toBe('role.lead')
    // nobody leads it yet: Project Management picks one
    expect(stageResponsibleKey('captured', 'internal', null)).toBe('role.pmShort')
    // D2 (2026-10-19): Project Management owns the process from capture
    // on: a customer change's capture is its lead's (the project's lead
    // PM), not Sales'; with no lead Project Management picks one
    expect(stageResponsibleKey('captured', 'customer')).toBe('role.lead')
    expect(stageResponsibleKey('captured', 'customer', 3)).toBe('role.lead')
    expect(stageResponsibleKey('captured', 'customer', null)).toBe('role.pmShort')
    expect(stageResponsibleKey('captured', 'customer')).not.toBe('role.sales')
    // Sales keeps the commercial stages
    expect(stageResponsibleKey('quoting', 'customer')).toBe('role.sales')
    expect(stageResponsibleKey('quoted', 'customer')).toBe('role.sales')
    expect(stageResponsibleKey('captured', 'mother_plant')).toBe('role.pmShort')
    expect(stageResponsibleKey('in_assessment', 'internal')).toBe('role.team')
  })
})
