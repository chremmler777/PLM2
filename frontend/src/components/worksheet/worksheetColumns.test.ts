import { describe, it, expect } from 'vitest'
import { WORKSHEET_COLUMNS, buildContext, dfmLabel, noteFor, notePartId, notesSummary, rowNotes } from './worksheetColumns'
import { FIELD_KEY_RE } from '../../lib/fieldNotes'
import { row } from './worksheetFixtures'
import type { FieldNoteSummary } from '../../api/fieldNotes'

const note = (part_id: number, field_key: string, flag_status: FieldNoteSummary['flag_status'], body?: string, at = '2026-09-24T10:00:00'): FieldNoteSummary => ({
  id: part_id * 1000 + field_key.length, part_id, field_key, flag_status, flag_set_by: null, flag_set_by_name: null,
  flag_set_at: null, created_at: at, comment_count: body ? 1 : 0,
  last_comment: body ? { id: 1, body, author_id: 1, author_name: 'Eng', created_at: at } : null,
})
const col = (key: string) => WORKSHEET_COLUMNS.find((c) => c.key === key)!
const empty = buildContext([])

describe('worksheet column registry', () => {
  it('has unique keys in backend field key format and three frozen identity columns first', () => {
    const keys = WORKSHEET_COLUMNS.map((c) => c.key)
    expect(new Set(keys).size).toBe(keys.length)
    for (const k of keys) expect(FIELD_KEY_RE.test(k)).toBe(true)
    expect(WORKSHEET_COLUMNS.slice(0, 3).map((c) => c.key)).toEqual(['part.thumbnail', 'part.part_number', 'part.customer_part_number'])
    expect(WORKSHEET_COLUMNS.filter((c) => c.frozenWidth).length).toBe(3)
    // Measured in the browser: a 13 character number, flag dot, 2 digit comment count and the menu button.
    expect(WORKSHEET_COLUMNS.filter((c) => c.frozenWidth).map((c) => [c.key, c.frozenWidth]))
      .toEqual([['part.thumbnail', 44], ['part.part_number', 170], ['part.customer_part_number', 170]])
  })

  it('reads the values PLM holds', () => {
    const r = row()
    expect(col('part.part_number').value(r, empty)).toBe('20-1994-001-0')
    expect(col('part.tier1_part_number').value(r, empty)).toBe('S00H4X-110')
    expect(col('revision.level').value(r, empty)).toBe('E1 · 001')
    expect(col('part.material').value(r, empty)).toBe('PA6-GF15 (NEW, not in MaterialDB)')
    expect(col('paint.painted').value(r, empty)).toBe('yes')
    expect(col('paint.colour').value(r, empty)).toBe('VM0 Skyscraper / Base / Clear')
    expect(col('tool.number').value(r, empty)).toBe('199401, 199409')
    expect(col('tool.cavities').value(r, empty)).toBe(2)
    expect(col('tool.toolmaker').value(r, empty)).toBe('Formenbau Nord')
    expect(col('dfm.status').value(r, empty)).toBe('Waiting on KTX, Tier 1')
    expect(col('tool.cavities').value(row({ tool: null, dfm: null }), empty)).toBeNull()
    expect(col('part.mirror_of').value(row({ mirror_of: { part_id: 2, part_number: '20-1994-002-0', customer_part_number: '206.882.252' } }), empty)).toBe('206.882.252')
  })

  it('tool columns read and edit the tool, shared by rows of the same tool', () => {
    const lh = row(), rh = row({ part_id: 2, part_number: '20-1994-002-0' })
    const ctx = buildContext([note(90, 'tool.cavities', 'open', 'Excel says 4')])
    expect(notePartId(col('tool.cavities'), lh)).toBe(90)
    expect(noteFor(col('tool.cavities'), lh, ctx)?.flag_status).toBe('open')
    expect(noteFor(col('tool.cavities'), rh, ctx)?.flag_status).toBe('open')
    expect(col('tool.cavities').edit(lh)).toEqual({ partId: 90, focus: 'tool.cavities' })
    expect(col('dfm.status').edit(lh)).toEqual({ partId: 90, focus: 'dfm.status' })
    expect(col('tool.cavities').edit(row({ tool: null }))).toBeNull()
  })

  it('article columns read and edit the row part', () => {
    const r = row()
    expect(notePartId(col('part.material'), r)).toBe(1)
    expect(col('part.material').edit(r)).toEqual({ partId: 1, focus: 'part.material' })
    expect(col('paint.colour').edit(r)).toEqual({ partId: 1, focus: 'paint.colour' })
    expect(col('paint.colour').edit(row({ row_kind: 'tool_only' }))).toBeNull()
    expect(col('part.mirror_of').edit(r)).toBeNull()
    expect(notePartId(col('part.thumbnail'), r)).toBeNull()
    expect(notePartId(col('notes.summary'), r)).toBeNull()
  })

  it('summarises open flags and the latest comment of a row, tool notes included', () => {
    const ctx = buildContext([
      note(1, 'part.material', 'open', 'Resin to be nominated', '2026-09-23T09:00:00'),
      note(90, 'tool.cavities', 'open', 'Excel BOM says 4 cavities, PLM has 2 for the 1+1 tool', '2026-09-24T09:00:00'),
      note(90, 'part.name', 'open'),  // a tool's own name note is not an article row note
      note(1, 'paint.colour', 'confirmed'),
    ])
    expect(rowNotes(row(), ctx).map((n) => n.field_key).sort()).toEqual(['paint.colour', 'part.material', 'tool.cavities'])
    expect(notesSummary(row(), ctx)).toBe('2 open · Excel BOM says 4 cavities, PLM has 2...')
    expect(notesSummary(row(), empty)).toBeNull()
    expect(col('notes.summary').value(row(), ctx)).toBe(notesSummary(row(), ctx))
  })

  it('labels every DFM state', () => {
    expect(dfmLabel(null)).toBeNull()
    expect(dfmLabel({ status: 'no_topic', waiting_on: [], open_topics: 0 })).toBe('No topic')
    expect(dfmLabel({ status: 'all_answered', waiting_on: [], open_topics: 1 })).toBe('All answered')
    expect(dfmLabel({ status: 'open', waiting_on: [], open_topics: 1 })).toBe('Open')
    expect(dfmLabel({ status: 'finished', waiting_on: [], open_topics: 0 })).toBe('Finished')
  })
})


describe('worksheet notes on tool-only rows', () => {
  const toolOnly = row({ part_id: 95, part_number: '199413', row_kind: 'tool_only', item_category: 'tool', part_type: 'purchased',
    tool: { part_id: 95, part_number: '199413', name: 't', cavities: 2, toolmaker_id: null, toolmaker_name: null, cycle_time_s: null, tonnage_class: null } })

  it('offers no note where the backend would refuse the field key for the owner', () => {
    expect(notePartId(col('paint.painted'), toolOnly)).toBeNull()
    expect(notePartId(col('paint.colour'), toolOnly)).toBeNull()
    expect(notePartId(col('revision.level'), toolOnly)).toBeNull()
    expect(notePartId(col('part.name'), toolOnly)).toBe(95)
    expect(notePartId(col('tool.cavities'), toolOnly)).toBe(95)
    expect(notePartId(col('paint.painted'), row())).toBe(1)
    expect(notePartId(col('tool.cavities'), row())).toBe(90)
  })
})

describe('worksheet name column', () => {
  const r = row({ name: '206.882.251 Handle, manual lift, passenger', customer_part_number: '206.882.251' })

  it('shows the short name without the OEM number and project code, full name in the tooltip', () => {
    const ctx = buildContext([], '1994')
    expect(col('part.name').value(r, ctx)).toBe('Handle, manual lift, passenger')
    expect(col('part.name').value(row({ name: '1994 Isofix Cover', customer_part_number: null }), ctx)).toBe('Isofix Cover')
    expect(col('part.name').title?.(r)).toBe('206.882.251 Handle, manual lift, passenger')
  })
})
