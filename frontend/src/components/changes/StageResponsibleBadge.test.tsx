import { describe, it, expect } from 'vitest'
import { stageResponsibleKey } from './StageResponsibleBadge'

describe('stageResponsibleKey', () => {
  it('gives the capture of an internal change to its lead, not Sales (P3)', () => {
    expect(stageResponsibleKey('captured', 'internal')).toBe('role.lead')
    expect(stageResponsibleKey('captured', 'internal', 7)).toBe('role.lead')
    // nobody leads it yet: Project Management picks one
    expect(stageResponsibleKey('captured', 'internal', null)).toBe('role.pmShort')
    expect(stageResponsibleKey('captured', 'customer')).toBe('role.sales')
    expect(stageResponsibleKey('captured', 'mother_plant')).toBe('role.pmShort')
    expect(stageResponsibleKey('in_assessment', 'internal')).toBe('role.team')
  })
})
