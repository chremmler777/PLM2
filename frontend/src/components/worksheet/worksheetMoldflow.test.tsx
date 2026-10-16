import { describe, it, expect, afterEach } from 'vitest'
import { render, screen, cleanup } from '@testing-library/react'
import WorksheetCell from './WorksheetCell'
import { WORKSHEET_COLUMNS, buildContext, moldflowLabel } from './worksheetColumns'
import { buildExportPayload } from './worksheetTable'
import { row } from './worksheetFixtures'
import type { WorksheetMoldflow } from '../../api/worksheet'
import { moldflowChip } from '../../hooks/queries/useProjectStatus'
import type { MoldflowRow, ProjectMoldflow } from '../../api/moldflow'

const col = WORKSHEET_COLUMNS.find((c) => c.key === 'moldflow.status')!
const ctx = buildContext([])
const mf = (over: Partial<WorksheetMoldflow> = {}): WorksheetMoldflow => ({
  id: 1, version: 'V1', cavity_layout: null, layouts: 1, versions: 1, status: 'sent_to_customer',
  last_step: { key: 'sent_customer_on', label: 'Sent to customer', on: '2026-10-15' }, blockers: null, ...over,
})

afterEach(cleanup)

describe('worksheet Moldflow column', () => {
  it('sits in its own group right after DFM', () => {
    const keys = WORKSHEET_COLUMNS.map((c) => c.key)
    expect(keys.indexOf('moldflow.status')).toBe(keys.indexOf('dfm.status') + 1)
    expect(col.group).toBe('Moldflow')
    expect(col.defaultVisible).toBe(true)
  })

  it('labels version, status and the last step, or the blocker instead', () => {
    expect(moldflowLabel(null)).toBeNull()
    expect(moldflowLabel(undefined)).toBeNull()
    expect(moldflowLabel(mf())).toBe('V1 · At customer · Sent to customer 2026-10-15')
    expect(moldflowLabel(mf({ version: 'V2', cavity_layout: '2+2', status: 'inputs_open', last_step: null, blockers: 'UDB' })))
      .toBe('V2 (2+2) · Inputs open · Blocker: UDB')
    expect(moldflowLabel(mf({ status: 'not_started', last_step: null }))).toBe('V1 · Not started')
  })

  it('renders a compact cell: version, status chip, date or blocker', () => {
    render(<WorksheetCell row={row({ moldflow: mf({ blockers: 'Clamp force high' }) })} col={col} ctx={ctx}
      noteOpen={false} onNoteOpenChange={() => {}} onMenu={() => {}} />)
    const cell = screen.getByTestId('ws-moldflow-1')
    expect(cell.textContent).toContain('V1')
    expect(screen.getByTestId('mf-status-chip').textContent).toBe('At customer')
    expect(cell.textContent).toContain('Clamp force high')
    expect(cell.textContent).not.toContain('2026-10-15')
  })

  it('renders nothing for a tool without Moldflow', () => {
    render(<WorksheetCell row={row({ moldflow: null })} col={col} ctx={ctx}
      noteOpen={false} onNoteOpenChange={() => {}} onMenu={() => {}} />)
    expect(screen.queryByTestId('ws-moldflow-1')).toBeNull()
  })

  it('goes into the xlsx export as text, merged over the tool group', () => {
    const rows = [row({ moldflow: mf() }), row({ part_id: 2, part_number: '20-1994-002-0', moldflow: mf() })]
    const payload = buildExportPayload([col], rows, ctx)
    expect(payload.columns).toEqual([{ key: 'moldflow.status', label: 'Moldflow', type: 'text' }])
    expect(payload.rows[0].cells[0]).toMatchObject({ value: 'V1 · At customer · Sent to customer 2026-10-15', span: 2 })
    expect(payload.rows[1].cells[0]).toMatchObject({ span: 0 })
  })
})

const r = (id: number, status: MoldflowRow['status']) => ({ id, status }) as MoldflowRow
const tool = (n: number, rows: MoldflowRow[]) => ({
  tool: { part_id: n, part_number: String(n), name: 'T', cavities: null }, articles: [], rows,
  latest_id: rows.length ? rows[rows.length - 1].id : null,
})

describe('Moldflow nav chip', () => {
  it('is plain while loading or without rows', () => {
    expect(moldflowChip(undefined).label).toBe('Moldflow')
    const none = moldflowChip({ project_id: 1, can_edit: true, tools: [tool(1, [])] })
    expect(none.label).toBe('Moldflow')
    expect(none.title).toContain('no Moldflow recorded for 1 tools')
  })

  it('counts each tool by its latest row, the two most advanced buckets in the label', () => {
    const data: ProjectMoldflow = { project_id: 1, can_edit: true, tools: [
      tool(1, [r(1, 'sent_to_customer')]), tool(2, [r(2, 'sent_to_customer')]), tool(3, [r(3, 'sent_to_customer')]),
      tool(4, [r(4, 'ready_for_mf')]), tool(5, [r(5, 'inputs_open')]), tool(6, [r(6, 'received'), r(7, 'running')]),
      tool(7, []),
    ] }
    const chip = moldflowChip(data)
    expect(chip.label).toBe('Moldflow · 3 at customer · 1 running')
    expect(chip.tone).toBe('neutral')
    expect(chip.title).toContain('1 ready, 1 inputs open; 1 tools without Moldflow')
  })

  it('turns amber while customer feedback waits on KTX', () => {
    const chip = moldflowChip({ project_id: 1, can_edit: true, tools: [tool(1, [r(1, 'customer_feedback')])] })
    expect(chip.label).toBe('Moldflow · 1 feedback')
    expect(chip.tone).toBe('amber')
  })
})
