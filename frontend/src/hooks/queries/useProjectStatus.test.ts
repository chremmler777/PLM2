import { describe, it, expect } from 'vitest'
import { changesChip, lessonsChip, sepChip } from './useProjectStatus'
import type { SepGate, SepState } from '../../types/sep'

const gate = (over: Partial<SepGate>): SepGate => ({
  id: 1, project_id: 2, code: 'K0/RG1', seq: 1, phase_de: '', phase_en: 'Kick-off', status: 'pending', color: 'green',
  target_date: null, pm_signed_name: null, pm_signed_at: null, quality_signed_name: null, quality_signed_at: null,
  progress: { done: 0, open: 10, not_applicable: 0, total: 10, pct: 0 }, open_risks: 0, items: [], ...over,
})

describe('sepChip', () => {
  it('shows the current gate and its progress', () => {
    const sep: SepState = { active: true, gates: [gate({ status: 'closed', code: 'K0' }), gate({ id: 2, code: 'K0/RG1', status: 'in_progress', color: 'yellow', progress: { done: 3, open: 7, not_applicable: 0, total: 10, pct: 30 } })] }
    expect(sepChip(sep)).toEqual({ label: 'K0/RG1 30%', tone: 'yellow', title: 'Kick-off: 3 of 10 done' })
  })
  it('says when SEP is off, done, or still loading', () => {
    expect(sepChip({ active: false, gates: [] }).label).toBe('SEP off')
    expect(sepChip({ active: true, gates: [gate({ status: 'closed' })] }).label).toBe('SEP done')
    expect(sepChip(undefined).label).toBe('SEP')
  })
})

describe('changesChip', () => {
  it('counts only open changes', () => {
    expect(changesChip([{ status: 'scoping' }, { status: 'closed' }, { status: 'rejected' }, { status: 'cancelled' }]).label).toBe('1 change')
    expect(changesChip([]).label).toBe('0 changes')
    expect(changesChip(undefined).label).toBe('Changes')
  })
})

describe('lessonsChip', () => {
  it('warns in amber when no lessons review is recorded', () => {
    expect(lessonsChip([])).toEqual({ label: 'No lessons review', tone: 'amber', title: 'Gate prep: no lessons review recorded yet' })
    expect(lessonsChip([{}, {}]).label).toBe('2 lessons reviewed')
    expect(lessonsChip([{}]).label).toBe('1 lesson reviewed')
    expect(lessonsChip(undefined).label).toBe('Lessons')
  })
})
