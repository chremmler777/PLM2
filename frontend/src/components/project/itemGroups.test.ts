import { describe, it, expect } from 'vitest'
import { findNode, groupNodes, groupOf, matchesSearch, visibleOrder } from './itemGroups'
import type { Part, TreeNode } from './projectTypes'

const part = (id: number, over: Partial<Part> = {}): Part => ({
  id, part_number: `P${id}`, name: `Part ${id}`, part_type: 'internal_mfg', active_revision_id: null,
  item_category: 'article', parent_part_id: null, ...over,
})
const node = (p: Part, children: TreeNode[] = []): TreeNode => ({ part: p, children })

describe('groupOf', () => {
  it('maps categories and sub-assemblies to the five groups', () => {
    expect(groupOf(part(1))).toBe('article')
    expect(groupOf(part(2, { item_category: 'tool' }))).toBe('tool')
    expect(groupOf(part(3, { item_category: 'assembly_equipment' }))).toBe('equipment')
    expect(groupOf(part(4, { item_category: 'eoat' }))).toBe('equipment')
    expect(groupOf(part(5, { item_category: 'gauge' }))).toBe('gauge')
    expect(groupOf(part(6, { part_type: 'sub_assembly' }))).toBe('assemblies')
    expect(groupOf(part(7, { item_category: 'something_new' }))).toBe('article')
  })
})

describe('groupNodes', () => {
  it('keeps the fixed group order and hides empty groups', () => {
    const groups = groupNodes([node(part(1, { item_category: 'gauge' })), node(part(2)), node(part(3, { item_category: 'tool' }))])
    expect(groups.map((g) => [g.key, g.label, g.nodes.length])).toEqual([
      ['article', 'Articles', 1], ['tool', 'Tools', 1], ['gauge', 'Gauges', 1],
    ])
  })
})

describe('matchesSearch', () => {
  const p = part(1, { part_number: '20-1994-001-0', customer_part_number: '206.882.251', tier1_part_number: 'S00H4X-110', name: 'Handle LH' })
  it('matches number, customer number, tier 1 number and name, ignoring case', () => {
    for (const q of ['1994-001', '882.251', 's00h4x', 'handle', '  HANDLE  ']) expect(matchesSearch(p, q)).toBe(true)
    expect(matchesSearch(p, 'bracket')).toBe(false)
    expect(matchesSearch(p, '')).toBe(true)
  })
})

describe('visibleOrder', () => {
  it('walks open groups and expanded children in display order', () => {
    const child = node(part(11))
    const assy = node(part(10, { part_type: 'sub_assembly' }), [child])
    const groups = groupNodes([node(part(1)), node(part(2, { item_category: 'tool' })), assy])
    expect(visibleOrder(groups, new Set(), () => true)).toEqual([1, 2, 10, 11])
    expect(visibleOrder(groups, new Set(['tool']), () => true)).toEqual([1, 10, 11])
    expect(visibleOrder(groups, new Set(), () => false)).toEqual([1, 2, 10])
  })
})

describe('findNode', () => {
  it('finds nested nodes and returns undefined for unknown ids', () => {
    const child = node(part(11))
    const tree = [node(part(1)), node(part(10), [child])]
    expect(findNode(tree, 11)).toBe(child)
    expect(findNode(tree, 99)).toBeUndefined()
  })
})
