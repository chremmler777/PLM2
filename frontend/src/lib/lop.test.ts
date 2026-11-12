import { describe, it, expect } from 'vitest'
import { GROUP_LABEL, GROUP_ORDER, dueLabel, groupLines, shortDay, sourceLabel, sourceTone, staleLabel } from './lop'
import type { LopLine } from '../types/lop'
import { lopLine } from '../components/lop/lop.fixtures'

const ids = (groups: { group: string; lines: LopLine[] }[]) => groups.map((g) => g.group)

describe('LOP grouping and labels', () => {
  it('orders groups overdue, due this week, waiting, new, stale, other, pdb', () => {
    const lines = [
      lopLine({ id: null, ref_key: '91', group: 'pdb', kind: 'pdb_topic' }),
      lopLine({ id: 2, group: 'other' }),
      lopLine({ id: 3, group: 'stale' }),
      lopLine({ id: 4, group: 'new' }),
      lopLine({ id: 5, group: 'waiting_check' }),
      lopLine({ id: 6, group: 'due_this_week' }),
      lopLine({ id: 7, group: 'overdue' }),
    ]
    expect(ids(groupLines(lines))).toEqual(['overdue', 'due_this_week', 'waiting_check', 'new', 'stale', 'other', 'pdb'])
    expect(GROUP_ORDER.slice(0, 7)).toEqual(['overdue', 'due_this_week', 'waiting_check', 'new', 'stale', 'other', 'pdb'])
    expect(GROUP_LABEL.waiting_check).toBe('Done, waiting for PM check')
    expect(GROUP_LABEL.pdb).toBe('PDB topics')
  })

  it('drops empty groups', () => {
    const groups = groupLines([lopLine({ id: 1, group: 'other' }), lopLine({ id: 2, group: 'other' })])
    expect(groups).toHaveLength(1)
    expect(groups[0].lines.map((l) => l.id)).toEqual([1, 2])
    expect(groupLines([])).toEqual([])
  })

  it('sorts PDB topics escalated first, then oldest', () => {
    const t = (ref: string, escalated: boolean, age: number | null) =>
      lopLine({ id: null, ref_key: ref, kind: 'pdb_topic', group: 'pdb', escalated, age_days: age })
    const groups = groupLines([t('a', false, 40), t('b', true, 5), t('c', false, null), t('d', true, 30), t('e', false, 90)])
    expect(groups[0].lines.map((l) => l.ref_key)).toEqual(['d', 'b', 'e', 'a', 'c'])
  })

  it('labels a late line with days late', () => {
    const late = lopLine({ due_date: '2026-11-03', late: true, days_late: 8 })
    expect(dueLabel(late)).toBe('Nov 3 · 8 d late')
    expect(dueLabel(lopLine({ due_date: '2026-11-14' }))).toBe('Nov 14')
  })

  it('labels a line without a date', () => {
    const noDate = lopLine({ due_date: null })
    expect(dueLabel(noDate)).toBe('not set')
  })

  it('says where a line comes from in plain words', () => {
    expect(sourceLabel(lopLine({ kind: 'sep_item', source_label: 'SEP K0/RG1 item 17' }))).toBe('SEP K0/RG1 · item 17')
    expect(sourceLabel(lopLine({ kind: 'task', source_label: 'PM' }))).toBe('PM task')
    expect(sourceLabel(lopLine({ kind: 'risk', source_label: 'SEP risk' }))).toBe('SEP risk')
    expect(sourceLabel(lopLine({ kind: 'pdb_topic', source_label: 'PDB topic' }))).toBe('PDB topic')
    expect(sourceTone('pdb_topic')).not.toBe(sourceTone('sep_item'))
    expect(shortDay('2026-01-09')).toBe('Jan 9')
    expect(staleLabel()).toBe('No update for 14 days')
    expect(staleLabel(21)).toBe('No update for 21 days')
  })
})
