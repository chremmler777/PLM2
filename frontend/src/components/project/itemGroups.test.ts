import { describe, it, expect } from 'vitest'
import { findNode, groupNodes, groupOf, hasToolFields, matchesSearch, tableRow, visibleOrder } from './itemGroups'
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

describe('tableRow', () => {
  const structure = { articles: [{
    part_id: 5, part_number: '20-1994-001-0', customer_part_number: '206.882.251', name: '206.882.251 Handle LH',
    lifecycle_phase: 'nominated', active_revision_id: 9,
    revisions: [{ id: 9, revision_name: 'E1', customer_index: '003', status: 'approved', phase: 'review' as const, parent_revision_id: null, is_active: true }],
    related: [{ relation_type: 'produces', direction: 'incoming' as const, label: 'produced by', part_id: 30, part_number: '199401', name: 'TOOL Handle', item_category: 'tool' }],
    mirror_of: null, mirrored_by: [],
  }] }
  const lh = part(5, { part_number: '20-1994-001-0', customer_part_number: '206.882.251', tier1_part_number: 'S00H4X-110', name: '206.882.251 Handle LH' })
  const tool = part(30, { part_number: '199401', name: '1994 TOOL Handle', item_category: 'tool', lifecycle_phase: 'rfq', tool_cavities: 2 })

  it('fills the table cells from the part, its structure and its tools', () => {
    expect(tableRow(lh, [lh, tool], structure, '1994')).toEqual({
      id: 5, customerNumber: '206.882.251', tier1: 'S00H4X-110', name: 'Handle LH', phase: 'nominated',
      revision: 'E1 · 003', tools: '199401', cavities: '2',
    })
  })

  it('uses the internal number when there is no customer number, and a tool shows its own cavities', () => {
    expect(tableRow(tool, [lh, tool], structure, '1994')).toMatchObject({ customerNumber: '199401', name: 'TOOL Handle', phase: 'rfq', cavities: '2', tools: '' })
  })

  it('knows whether the API sends tool fields at all', () => {
    expect(hasToolFields([lh])).toBe(false)
    expect(hasToolFields([lh, part(31, { item_category: 'tool', tool_cavities: null })])).toBe(true)
  })
})
