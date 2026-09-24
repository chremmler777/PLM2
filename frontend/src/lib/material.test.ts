import { describe, it, expect } from 'vitest'
import { materialOf, materialText } from './material'

describe('material helpers', () => {
  it('reads the material fields of a part, missing fields as null', () => {
    expect(materialOf({})).toEqual({ material_source: null, materialdb_id: null, material_ktx_number: null,
      material_label: null, material_new_text: null, material_synced_at: null })
  })

  it('shows linked, new and missing material as text', () => {
    expect(materialText({ ...materialOf({}), material_source: 'materialdb', materialdb_id: 11, material_label: '40-1234 Ultramid B3WG6' })).toBe('40-1234 Ultramid B3WG6')
    expect(materialText({ ...materialOf({}), material_source: 'materialdb', materialdb_id: 11 })).toBe('MaterialDB #11')
    expect(materialText({ ...materialOf({}), material_source: 'new', material_new_text: 'PA6-GF15' })).toBe('PA6-GF15 (NEW, not in MaterialDB)')
    expect(materialText(materialOf({}))).toBeNull()
  })
})
