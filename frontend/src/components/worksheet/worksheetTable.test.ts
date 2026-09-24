import { describe, it, expect, vi, afterEach } from 'vitest'
import {
  HIDDEN_COLUMNS_KEY, applyFilters, buildExportPayload, compareValues, enumOptions, frozenOffsets, loadHiddenColumns,
  filterOptions, offeredFilters, rowKindVisible, saveHiddenColumns, sortRows, visibleColumns,
} from './worksheetTable'
import { WORKSHEET_COLUMNS, buildContext } from './worksheetColumns'
import { row } from './worksheetFixtures'

const col = (key: string) => WORKSHEET_COLUMNS.find((c) => c.key === key)!
const ctx = buildContext([])
const a = row({ part_id: 1, part_number: '20-1994-010-0', name: 'Side shield', part_type: 'internal_mfg' })
const b = row({ part_id: 2, part_number: '20-1994-002-0', name: 'Handle RH', part_type: 'purchased', row_kind: 'purchased',
  tool: { part_id: 91, part_number: '199409', name: 't', cavities: 8, toolmaker_id: null, toolmaker_name: null, cycle_time_s: null, tonnage_class: null } })
const c = row({ part_id: 3, part_number: '199413', name: 'Tool only', row_kind: 'tool_only', tool: null, dfm: null })

describe('worksheet table helpers', () => {
  afterEach(() => { window.localStorage.clear(); vi.restoreAllMocks() })

  it('filters text case-insensitively and enums exactly, on visible columns only', () => {
    const cols = [col('part.name'), col('part.part_type')]
    expect(applyFilters([a, b], cols, { 'part.name': 'HANDLE' }, ctx, false)).toEqual([b])
    expect(applyFilters([a, b], cols, { 'part.part_type': 'purchased' }, ctx, false)).toEqual([b])
    expect(applyFilters([a, b], [col('part.name')], { 'part.part_type': 'purchased' }, ctx, false)).toEqual([a, b])
    expect(applyFilters([a, b], cols, { 'part.name': '   ' }, ctx, false)).toEqual([a, b])
  })

  it('keeps only rows with an open flag, tool flags included', () => {
    const flagged = buildContext([{ id: 1, part_id: 91, field_key: 'tool.cavities', flag_status: 'open', flag_set_by: null,
      flag_set_by_name: null, flag_set_at: null, created_at: null, comment_count: 0, last_comment: null }])
    expect(applyFilters([a, b], [col('part.name')], {}, flagged, true)).toEqual([b])
  })

  it('sorts numbers numerically with empty values last, and part numbers by default', () => {
    const none = row({ part_id: 4, tool: null })
    expect(sortRows([b, none, a], col('tool.cavities'), 'asc', ctx).map((r) => r.part_id)).toEqual([1, 2, 4])
    expect(sortRows([b, none, a], col('tool.cavities'), 'desc', ctx).map((r) => r.part_id)).toEqual([2, 1, 4])
    expect(sortRows([a, b], undefined, 'asc', ctx).map((r) => r.part_id)).toEqual([2, 1])
    expect(compareValues('E10', 'E9')).toBeGreaterThan(0)
  })

  it('shows purchased and tool-only rows only when asked', () => {
    const none = { purchased: false, toolOnly: false }
    expect([a, b, c].filter((r) => rowKindVisible(r, none))).toEqual([a])
    expect([a, b, c].filter((r) => rowKindVisible(r, { purchased: true, toolOnly: true }))).toEqual([a, b, c])
  })

  it('lists enum options from the rows', () => {
    expect(enumOptions(col('part.part_type'), [a, b, a], ctx)).toEqual(['internal mfg', 'purchased'])
  })

  it('offers the enum values of the rows the other filters leave, never narrowed by its own choice', () => {
    const tool = row({ part_id: 4, part_number: '199413', name: 'TOOL Cover', row_kind: 'tool_only', item_category: 'tool',
      part_type: 'purchased' })
    const cols = [col('part.name'), col('part.part_type')]
    expect(filterOptions(col('part.part_type'), [a, tool], cols, {}, ctx, false)).toEqual(['internal mfg', 'purchased'])
    expect(filterOptions(col('part.part_type'), [a, tool], cols, { 'part.name': 'tool' }, ctx, false)).toEqual(['purchased'])
    expect(filterOptions(col('part.part_type'), [a, tool], cols, { 'part.part_type': 'purchased' }, ctx, false))
      .toEqual(['internal mfg', 'purchased'])
    // the chosen value stays selectable even when another filter leaves no row with it
    expect(filterOptions(col('part.part_type'), [a, tool], cols, { 'part.name': 'side', 'part.part_type': 'purchased' }, ctx, false))
      .toEqual(['internal mfg', 'purchased'])
  })

  it('remembers hidden columns and falls back to the defaults', () => {
    expect(loadHiddenColumns()).toEqual(new Set(['part.mirror_of', 'tool.tonnage_class']))
    saveHiddenColumns(new Set(['part.name']))
    expect(window.localStorage.getItem(HIDDEN_COLUMNS_KEY)).toBe('["part.name"]')
    expect(loadHiddenColumns()).toEqual(new Set(['part.name']))
    expect(visibleColumns(new Set(['part.name'])).some((x) => x.key === 'part.name')).toBe(false)
  })

  it('hidden columns fall back to defaults on bad storage', () => {
    window.localStorage.setItem(HIDDEN_COLUMNS_KEY, '{not json')
    expect(loadHiddenColumns()).toEqual(new Set(['part.mirror_of', 'tool.tonnage_class']))
    window.localStorage.setItem(HIDDEN_COLUMNS_KEY, '{"a":1}')
    expect(loadHiddenColumns()).toEqual(new Set(['part.mirror_of', 'tool.tonnage_class']))
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw new Error('blocked') })
    expect(loadHiddenColumns()).toEqual(new Set(['part.mirror_of', 'tool.tonnage_class']))
  })

  it('stacks the frozen columns from the left', () => {
    const offsets = frozenOffsets(visibleColumns(new Set()))
    expect([...offsets.entries()]).toEqual([['part.thumbnail', 0], ['part.part_number', 44], ['part.customer_part_number', 214]])
    expect([...frozenOffsets(visibleColumns(new Set(['part.thumbnail']))).entries()]).toEqual([['part.part_number', 0], ['part.customer_part_number', 170]])
  })

  it('drops enum filters whose value is no longer offered, keeps text filters', () => {
    const cols = [col('part.name'), col('part.part_type')]
    const filters = { 'part.name': 'side', 'part.part_type': 'purchased' }
    expect(offeredFilters(filters, cols, [a, b], ctx)).toEqual(filters)
    expect(offeredFilters(filters, cols, [a], ctx)).toEqual({ 'part.name': 'side' })
  })

  it('builds the export from visible columns and rows with types and flags', () => {
    const flagged = buildContext([{ id: 1, part_id: 90, field_key: 'tool.cavities', flag_status: 'open', flag_set_by: null,
      flag_set_by_name: null, flag_set_at: null, created_at: null, comment_count: 2, last_comment: null }])
    const cols = visibleColumns(new Set()).filter((x) => ['part.thumbnail', 'part.part_number', 'part.customer_part_number', 'tool.cavities'].includes(x.key))
    const payload = buildExportPayload(cols, [a], flagged)
    expect(payload.columns).toEqual([
      { key: 'part.part_number', label: 'KTX no.', type: 'text' },
      { key: 'part.customer_part_number', label: 'OEM no.', type: 'text' },
      { key: 'tool.cavities', label: 'Cavities', type: 'number' },
    ])
    expect(payload.frozen_columns).toBe(2)
    expect(payload.rows[0].cells).toEqual([
      { value: '20-1994-010-0', flag: null, comments: 0 },
      { value: '206.882.251', flag: null, comments: 0 },
      { value: 2, flag: 'open', comments: 2 },
    ])
  })
})
