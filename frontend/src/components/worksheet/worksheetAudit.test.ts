import { describe, it, expect } from 'vitest'
import type { WorksheetAuditEntry } from '../../api/worksheet'
import { auditActionText, auditEditPath, auditFieldLabel, auditValueChange, excerpt, worksheetAuditCsvUrl } from './worksheetAudit'

const entry = (over: Partial<WorksheetAuditEntry> = {}): WorksheetAuditEntry => ({
  id: 1, at: '2026-09-24T14:54:27', actor: { id: 20, name: 'Engineer' },
  part: { id: 7, part_number: '20-1994-001-0', customer_part_number: '206.882.251', item_category: 'article' },
  action: 'field_flag_set', action_group: 'flags', field_key: 'part.material', old_value: null, new_value: 'open',
  description: 'Flag on part.material: none to open', ...over,
})

describe('worksheet audit helpers', () => {
  it('labels fields from the column registry, colour keys as Colour, unknown keys as themselves', () => {
    expect(auditFieldLabel('part.material')).toBe('Material')
    expect(auditFieldLabel('tool.cavities')).toBe('Cavities')
    expect(auditFieldLabel('part.colour_code')).toBe('Colour')
    expect(auditFieldLabel('paint.colour')).toBe('Colour')
    expect(auditFieldLabel('part.unknown')).toBe('part.unknown')
    expect(auditFieldLabel(null)).toBe('')
  })

  it('says what happened in plain words', () => {
    expect(auditActionText(entry())).toBe('Flag set to Open')
    expect(auditActionText(entry({ old_value: 'open', new_value: null }))).toBe('Flag cleared')
    expect(auditActionText(entry({ action: 'field_comment_added', action_group: 'comments' }))).toBe('Commented')
    expect(auditActionText(entry({ action: 'material_set', action_group: 'material' }))).toBe('Material changed')
    expect(auditActionText(entry({ action: 'metadata_updated', action_group: 'values' }))).toBe('Value changed')
    expect(auditActionText(entry({ action: 'dfm_topic_opened', action_group: 'other' }))).toBe('DFM topic opened')
    expect(auditActionText(entry({ action: 'something_new', action_group: 'other' }))).toBe('something new')
  })

  it('shows old -> new for value changes, nothing for comments', () => {
    expect(auditValueChange(entry({ action: 'metadata_updated', old_value: '4', new_value: '2' }))).toBe('4 -> 2')
    expect(auditValueChange(entry({ action: 'field_updated', old_value: null, new_value: 'NM0' }))).toBe('none -> NM0')
    expect(auditValueChange(entry({ action: 'field_comment_added', new_value: 'text' }))).toBe('')
    expect(excerpt('a'.repeat(200), 20)).toBe(`${'a'.repeat(17)}...`)
    expect(excerpt(null, 20)).toBe('')
  })

  it('navigates like the cell menu Edit: the field on the part that holds it, else the part page', () => {
    expect(auditEditPath(entry())).toBe('/parts/7?focus=part.material')
    expect(auditEditPath(entry({ field_key: 'tool.cavities', part: { ...entry().part, id: 90, item_category: 'tool' } })))
      .toBe('/parts/90?focus=tool.cavities')
    expect(auditEditPath(entry({ field_key: 'part.colour_code' }))).toBe('/parts/7?focus=part.colour_code')
    expect(auditEditPath(entry({ field_key: 'part.mirror_of' }))).toBe('/parts/7')
    expect(auditEditPath(entry({ field_key: null }))).toBe('/parts/7')
  })

  it('builds the CSV link on the app API base with the active filters', () => {
    expect(worksheetAuditCsvUrl(35, { action_group: 'flags', part: '', field_key: 'part.material' }))
      .toBe('/plm2/api/v1/projects/35/worksheet/audit.csv?action_group=flags&field_key=part.material')
    expect(worksheetAuditCsvUrl(35, {})).toBe('/plm2/api/v1/projects/35/worksheet/audit.csv')
  })
})
