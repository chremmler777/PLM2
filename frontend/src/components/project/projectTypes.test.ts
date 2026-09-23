import { describe, it, expect } from 'vitest'
import { buildPartTree, getDescendantIds, typeColor, type Part } from './projectTypes'

const p = (id: number, part_number: string, parent_part_id: number | null = null, over: Partial<Part> = {}): Part => ({
  id, part_number, name: `P${id}`, part_type: 'internal_mfg', active_revision_id: null,
  item_category: 'article', parent_part_id, ...over,
})

describe('buildPartTree', () => {
  it('nests children under their parent and sorts by the embedded number', () => {
    const tree = buildPartTree([p(1, '1994-10'), p(2, '1994-2'), p(3, '1994-3', 1), p(4, '1994-1', 1)])
    expect(tree.map((n) => n.part.part_number)).toEqual(['1994-2', '1994-10'])
    expect(tree[1].children.map((n) => n.part.part_number)).toEqual(['1994-1', '1994-3'])
  })

  it('drops parts caught in a parent cycle instead of looping', () => {
    expect(buildPartTree([p(1, 'A', 2), p(2, 'B', 1)])).toEqual([])
  })
})

describe('getDescendantIds', () => {
  it('collects children and grandchildren', () => {
    const parts = [p(1, 'A'), p(2, 'B', 1), p(3, 'C', 2), p(4, 'D')]
    expect([...getDescendantIds(parts, 1)].sort()).toEqual([2, 3])
  })
})

describe('typeColor', () => {
  it('falls back for unknown part types', () => {
    expect(typeColor('sub_assembly')).toContain('blue')
    expect(typeColor('whatever')).toBe('bg-slate-700 text-slate-300')
  })
})
