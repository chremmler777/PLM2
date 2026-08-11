import { describe, it, expect } from 'vitest'
import { itemGroup, groupItems, ITEM_GROUP_ORDER } from './itemCategory'

const part = (part_number: string, item_category = 'article') =>
  ({ part_number, item_category })

describe('itemGroup', () => {
  it('splits articles into families by part-number prefix', () => {
    // 10/11/20/22 are the physical-part families WinCarat uses.
    expect(itemGroup(part('20-3454-001-0'))).toBe('article')
    expect(itemGroup(part('10-3457-001-0'))).toBe('article')
    expect(itemGroup(part('40-9001-000-0'))).toBe('material')   // resin
    expect(itemGroup(part('65-1000-000-0'))).toBe('dunnage')    // returnables
  })

  it('keeps an unrecognised article prefix an article', () => {
    // A part nobody has classified is still a part somebody can change —
    // burying it under "Other" would hide it from the picker.
    expect(itemGroup(part('99-0000-000-0'))).toBe('article')
  })

  it('reads the equipment kind off the op code, not the stored category', () => {
    // Every one of these is stored as item_category 'assembly_equipment';
    // only the -NN suffix says which kind of equipment it actually is.
    expect(itemGroup(part('3454-10', 'assembly_equipment'))).toBe('eoat')
    expect(itemGroup(part('3454-20', 'assembly_equipment'))).toBe('in_cell_station')
    expect(itemGroup(part('3454-31', 'assembly_equipment'))).toBe('secondary_station')
    expect(itemGroup(part('3454-40', 'assembly_equipment'))).toBe('gauge')
  })

  it('leaves a bare tool number as the mold', () => {
    expect(itemGroup(part('3454', 'tool'))).toBe('tool')
  })

  it('passes an unnumbered non-article category straight through', () => {
    expect(itemGroup(part('X', 'gauge'))).toBe('gauge')
    expect(itemGroup(part('X', 'something_new'))).toBe('other')
  })
})

describe('groupItems', () => {
  it('orders groups articles-first and drops the empty ones', () => {
    const groups = groupItems([
      part('3454', 'tool'),
      part('65-1000-000-0'),
      part('20-3454-001-0'),
      part('3454-10', 'assembly_equipment'),
      part('40-9001-000-0'),
    ])
    expect(groups.map((g) => g.key)).toEqual(
      ['article', 'material', 'dunnage', 'tool', 'eoat'])
    expect(groups.map((g) => g.label)).toEqual(
      ['Articles', 'Resin & material', 'Returnables & dunnage', 'Tools & molds', 'EOAT'])
    expect(groups.every((g) => g.items.length > 0)).toBe(true)
  })

  it('keeps every item — grouping never drops one', () => {
    const items = [
      part('20-1', 'article'), part('20-2', 'article'),
      part('3454', 'tool'), part('X', 'weird'),
    ]
    const total = groupItems(items).reduce((n, g) => n + g.items.length, 0)
    expect(total).toBe(items.length)
  })

  it('returns nothing for an empty list', () => {
    expect(groupItems([])).toEqual([])
  })

  it('every group key it can emit has a place in the order', () => {
    const emitted = ['article', 'material', 'dunnage', 'tool', 'eoat',
                     'in_cell_station', 'secondary_station',
                     'assembly_equipment', 'gauge', 'other']
    expect(ITEM_GROUP_ORDER).toEqual(emitted)
  })
})
