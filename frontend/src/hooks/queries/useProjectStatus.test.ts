import { describe, it, expect } from 'vitest'
import { changesChip, lessonsChip, lopChip } from './useProjectStatus'
import { lopLine, lopProject, pdbTopic } from '../../components/lop/lop.fixtures'
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

describe('lopChip', () => {
  it('nav chip counts a late pinned topic and turns amber', () => {
    const pin = pdbTopic({ id: 44, project_id: 2, pinned: true, group: 'overdue', late: true, days_late: 2 })
    const chip = lopChip(lopProject({ lines: [lopLine(), pin] }))
    expect(chip?.label).toBe('LOP 2')
    expect(chip?.tone).toBe('amber')
    expect(lopChip(lopProject({ lines: [lopLine(), { ...pin, late: false }] }))?.tone).toBe('neutral')
  })
})
