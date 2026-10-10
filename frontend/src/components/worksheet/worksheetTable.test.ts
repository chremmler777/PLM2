import { describe, it, expect, vi, afterEach } from 'vitest'
import {
  HIDDEN_COLUMNS_KEY, applyFilters, buildExportPayload, compareValues, enumOptions, frozenOffsets, loadHiddenColumns,
  filterOptions, offeredFilters, rowKindVisible, saveHiddenColumns, sortRows, toolCellSpans, toolGroupStarts, visibleColumns,
} from './worksheetTable'
import { WORKSHEET_COLUMNS, buildContext } from './worksheetColumns'
import { row } from './worksheetFixtures'

const col = (key: string) => WORKSHEET_COLUMNS.find((c) => c.key === key)!
const ctx = buildContext([])
const a = row({ part_id: 1, part_number: '20-1994-010-0', name: 'Side shield', part_type: 'internal_mfg' })
const b = row({ part_id: 2, part_number: '20-1994-002-0', name: 'Handle RH', part_type: 'purchased', row_kind: 'purchased',
  tool: { part_id: 91, part_number: '199409', name: 't', cavities: '8', toolmaker_id: null, toolmaker_name: null, cycle_time_s: null, tonnage_class: null, machine: null, shrink_parallel_pct: null, shrink_normal_pct: null } })
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

  it('keeps a tool\'s articles together and shows its tool cells once', () => {
    const tool = { ...b.tool!, part_id: 90, part_number: '199401', cavities: '2+2' }
    const lh = row({ part_id: 11, part_number: '20-1994-001-0', tool })
    const rh = row({ part_id: 12, part_number: '20-1994-005-0', tool })
    const mid = row({ part_id: 13, part_number: '20-1994-003-0', tool: { ...tool, part_id: 92, part_number: '199403', cavities: '4' } })
    const shown = sortRows([rh, mid, lh], undefined, 'asc', ctx)
    expect(shown.map((r) => r.part_id)).toEqual([11, 12, 13])  // 005 moves up next to 001: same tool
    const cols = [col('part.name'), col('tool.number'), col('tool.cavities')]
    const spans = toolCellSpans(shown, cols, ctx)
    expect(spans.get('0|tool.cavities')).toBe(2)
    expect(spans.get('1|tool.cavities')).toBe(0)
    expect(spans.get('0|part.name')).toBeUndefined()  // article cells stay per row
    expect(spans.get('2|tool.cavities')).toBeUndefined()
    expect([...toolGroupStarts(shown)]).toEqual([2])
  })

  it('exports the tool groups: merged tool cells and a divider per group', () => {
    const tool = { ...b.tool!, part_id: 90, part_number: '199401', cavities: '2+2' }
    const lh = row({ part_id: 11, part_number: '1', tool })
    const rh = row({ part_id: 12, part_number: '2', tool })
    const other = row({ part_id: 13, part_number: '3', tool: { ...tool, part_id: 92, cavities: '4' } })
    const payload = buildExportPayload([col('part.name'), col('tool.cavities')], [lh, rh, other], ctx)
    expect(payload.rows.map((r) => r.cells[1].span)).toEqual([2, 0, undefined])
    expect(payload.rows.map((r) => r.cells[0].span)).toEqual([undefined, undefined, undefined])
    expect(payload.rows.map((r) => r.group_start ?? false)).toEqual([false, false, true])
  })

  it('does not merge a tool cell whose value differs between the rows', () => {
    const tool = { ...b.tool!, part_id: 90, part_number: '199401' }
    const one = row({ part_id: 11, part_number: '1', tool, other_tools: [] })
    const two = row({ part_id: 12, part_number: '2', tool, other_tools: ['199499'] })
    const spans = toolCellSpans([one, two], [col('tool.number'), col('tool.cavities')], ctx)
    expect(spans.get('0|tool.number')).toBeUndefined()
    expect(spans.get('0|tool.cavities')).toBe(2)
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

  it('builds the export from visible columns and rows with types, flags and the picture as part id', () => {
    const flagged = buildContext([{ id: 1, part_id: 90, field_key: 'tool.cavities', flag_status: 'open', flag_set_by: null,
      flag_set_by_name: null, flag_set_at: null, created_at: null, comment_count: 2, last_comment: null }])
    const cols = visibleColumns(new Set()).filter((x) => ['part.thumbnail', 'part.part_number', 'part.customer_part_number', 'tool.cavities'].includes(x.key))
    const pictured = { ...a, thumbnail_url: '/api/v1/parts/1/thumbnail' }
    const payload = buildExportPayload(cols, [pictured, b], flagged)
    expect(payload.columns).toEqual([
      { key: 'part.thumbnail', label: 'Image', type: 'image' },
      { key: 'part.part_number', label: 'KTX no.', type: 'text' },
      { key: 'part.customer_part_number', label: 'OEM no.', type: 'text' },
      { key: 'tool.cavities', label: 'Cavities', type: 'text' },
    ])
    expect(payload.frozen_columns).toBe(3)
    expect(payload.rows[0].cells).toEqual([
      { value: 1, flag: null, comments: 0 },
      { value: '20-1994-010-0', flag: null, comments: 0 },
      { value: '206.882.251', flag: null, comments: 0 },
      { value: '2', flag: 'open', comments: 2 },
    ])
    expect(payload.rows[1].cells[0]).toEqual({ value: null, flag: null, comments: 0 })
  })
})
