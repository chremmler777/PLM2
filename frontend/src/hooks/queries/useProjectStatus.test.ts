import { describe, it, expect } from 'vitest'
import { changesChip, lessonsChip } from './useProjectStatus'
describe('changesChip', () => {
  it('counts only open changes', () => {
    expect(changesChip([{ status: 'scoping' }, { status: 'closed' }, { status: 'rejected' }, { status: 'cancelled' }]).label).toBe('Changes (1)')
    expect(changesChip([]).label).toBe('Changes (0)')
    expect(changesChip(undefined).label).toBe('Changes')
  })
})

describe('lessonsChip', () => {
  it('warns in amber when no lessons review is recorded', () => {
    expect(lessonsChip([])).toEqual({ label: 'Lessons · no review', tone: 'amber', title: 'Gate prep: no lessons review recorded yet' })
    expect(lessonsChip([{}, {}]).label).toBe('Lessons (2)')
    expect(lessonsChip([{}]).label).toBe('Lessons (1)')
    expect(lessonsChip(undefined).label).toBe('Lessons')
  })
})
