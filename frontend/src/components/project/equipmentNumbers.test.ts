import { describe, it, expect } from 'vitest'
import { categoryOfKind, familyOfKind, noToolFamilyOfKind, suggestEquipmentNumber } from './equipmentNumbers'

describe('equipment numbers', () => {
  it('starts each family at slot 0', () => {
    expect(suggestEquipmentNumber('3345', 4, [])).toBe('3345-40')
    expect(suggestEquipmentNumber('3345', 1, [])).toBe('3345-10')
    expect(suggestEquipmentNumber('3345', 2, [])).toBe('3345-20')
    expect(suggestEquipmentNumber('3345', 3, [])).toBe('3345-30')
  })

  it('takes the next free slot of the family and fills gaps', () => {
    expect(suggestEquipmentNumber('3345', 4, ['3345-40', '3345-41', '3345-10'])).toBe('3345-42')
    expect(suggestEquipmentNumber('3345', 4, ['3345-41'])).toBe('3345-40')
    expect(suggestEquipmentNumber('3345', 4, ['3450-40'])).toBe('3345-40')
  })

  it('keeps a second tool nested: 0674-2 owns 0674-2-40', () => {
    expect(suggestEquipmentNumber('0674-2', 4, ['0674-2-40'])).toBe('0674-2-41')
  })

  it('gives nothing when all ten slots are taken', () => {
    const all = Array.from({ length: 10 }, (_, i) => `3345-4${i}`)
    expect(suggestEquipmentNumber('3345', 4, all)).toBeNull()
  })

  it('maps the kinds to families and categories', () => {
    expect(familyOfKind('eoat')).toBe(1)
    expect(familyOfKind('assembly_equipment')).toBe(2)
    expect(familyOfKind('assembly_equipment', '3')).toBe(3)
    expect(familyOfKind('gauge')).toBe(4)
    expect(familyOfKind('tool')).toBeNull()
    expect(categoryOfKind('eoat')).toBe('assembly_equipment')
    expect(categoryOfKind('gauge')).toBe('gauge')
  })

  it('numbers equipment without a tool on the project code: -6x stations and EOATs, -7x gauges', () => {
    expect(noToolFamilyOfKind('assembly_equipment')).toBe(6)
    expect(noToolFamilyOfKind('eoat')).toBe(6)
    expect(noToolFamilyOfKind('gauge')).toBe(7)
    expect(suggestEquipmentNumber('1748', 6, [])).toBe('1748-60')
    expect(suggestEquipmentNumber('1748', 6, ['1748-60'])).toBe('1748-61')
    expect(suggestEquipmentNumber('1748', 7, ['1748-60'])).toBe('1748-70')
  })
})
