import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, cleanup, fireEvent, within, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Routes, Route, useLocation } from 'react-router-dom'
import WorksheetView from './WorksheetView'
import { row } from './worksheetFixtures'

const clientMocks = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), put: vi.fn() }))
vi.mock('../../api/client', () => ({ default: clientMocks, API_BASE_URL: '' }))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

const rows = [
  row({ part_id: 1, part_number: '20-1994-010-0', name: 'Side shield' }),
  row({ part_id: 2, part_number: '20-1994-002-0', name: 'Handle RH', part_type: 'purchased', row_kind: 'purchased' }),
  row({ part_id: 3, part_number: '20-1994-005-0', name: 'ISOFIX Cover',
    tool: { part_id: 93, part_number: '199403', name: 't', cavities: 4, toolmaker_id: null, toolmaker_name: null, cycle_time_s: null, tonnage_class: null } }),
]
const notes = [{ id: 1, part_id: 93, field_key: 'tool.cavities', flag_status: 'open', flag_set_by: null, flag_set_by_name: null,
  flag_set_at: null, created_at: null, comment_count: 1, last_comment: { id: 1, body: 'Excel says 2', author_id: 1, author_name: 'E', created_at: '2026-09-24T09:00:00' } }]

function mount(onClose = vi.fn()) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(<QueryClientProvider client={qc}><MemoryRouter><WorksheetView projectId={35} onClose={onClose} /></MemoryRouter></QueryClientProvider>)
  return onClose
}

describe('WorksheetView', () => {
  beforeEach(() => {
    window.localStorage.clear()
    clientMocks.get.mockReset()
    clientMocks.get.mockImplementation((url: string) => {
      if (url === '/v1/projects/35/worksheet') return Promise.resolve({ data: { project_id: 35, rows } })
      if (url === '/v1/projects/35/field-notes') return Promise.resolve({ data: notes })
      return Promise.resolve({ data: [] })
    })
  })
  afterEach(cleanup)

  it('switches the table area to the audit log and back', async () => {
    mount()
    await screen.findByTestId('ws-row-1')
    expect(screen.getByTestId('ws-audit-toggle').getAttribute('aria-pressed')).toBe('false')
    fireEvent.click(screen.getByTestId('ws-audit-toggle'))
    expect(await screen.findByTestId('worksheet-audit')).toBeTruthy()
    expect(screen.queryByTestId('ws-row-1')).toBeNull()
    expect(screen.queryByTestId('ws-export')).toBeNull()
    expect(clientMocks.get).toHaveBeenCalledWith('/v1/projects/35/worksheet/audit', expect.anything())
    fireEvent.click(screen.getByTestId('ws-audit-toggle'))
    expect(await screen.findByTestId('ws-row-1')).toBeTruthy()
    expect(screen.queryByTestId('worksheet-audit')).toBeNull()
  })

  it('lists articles sorted by part number, purchased rows only on request', async () => {
    mount()
    await screen.findByTestId('ws-row-1')
    expect(screen.getAllByTestId(/^ws-row-/).map((r) => r.dataset.testid)).toEqual(['ws-row-3', 'ws-row-1'])
    fireEvent.click(screen.getByTestId('ws-kind-purchased'))
    expect(screen.getAllByTestId(/^ws-row-/).map((r) => r.dataset.testid)).toEqual(['ws-row-2', 'ws-row-3', 'ws-row-1'])
    expect(screen.getByTestId('ws-count').textContent).toBe('3 rows')
  })

  it('tints a flagged cell and filters to rows with open flags', async () => {
    mount()
    const cell = await screen.findByTestId('ws-cell-3-tool.cavities')
    expect(cell.dataset.flag).toBe('open')
    expect(within(cell).getByTestId('ws-tint-3-tool.cavities').className).toContain('bg-yellow-500/20')
    fireEvent.click(screen.getByTestId('ws-only-open'))
    expect(screen.getAllByTestId(/^ws-row-/).map((r) => r.dataset.testid)).toEqual(['ws-row-3'])
  })

  it('filters by column text and sorts by a column header', async () => {
    mount()
    await screen.findByTestId('ws-row-1')
    fireEvent.change(screen.getByTestId('filter-part.name'), { target: { value: 'isofix' } })
    expect(screen.getAllByTestId(/^ws-row-/).map((r) => r.dataset.testid)).toEqual(['ws-row-3'])
    fireEvent.change(screen.getByTestId('filter-part.name'), { target: { value: '' } })
    fireEvent.click(screen.getByTestId('sort-tool.cavities'))
    expect(screen.getAllByTestId(/^ws-row-/).map((r) => r.dataset.testid)).toEqual(['ws-row-1', 'ws-row-3'])
    fireEvent.click(screen.getByTestId('sort-tool.cavities'))
    expect(screen.getAllByTestId(/^ws-row-/).map((r) => r.dataset.testid)).toEqual(['ws-row-3', 'ws-row-1'])
  })

  it('offers the Type values of the rows currently included', async () => {
    const tool = row({ part_id: 4, part_number: '199413', name: 'TOOL Cover', row_kind: 'tool_only', item_category: 'tool',
      part_type: 'purchased', tool: null, dfm: null })
    clientMocks.get.mockImplementation((url: string) => {
      if (url === '/v1/projects/35/worksheet') return Promise.resolve({ data: { project_id: 35, rows: [rows[0], tool] } })
      return Promise.resolve({ data: [] })
    })
    mount()
    await screen.findByTestId('ws-row-1')
    const options = () => [...(screen.getByTestId('filter-part.part_type') as HTMLSelectElement).options].map((o) => o.value)
    expect(options()).toEqual(['', 'internal mfg'])
    fireEvent.click(screen.getByTestId('ws-kind-tool-only'))
    expect(options()).toEqual(['', 'internal mfg', 'purchased'])
    fireEvent.change(screen.getByTestId('filter-part.name'), { target: { value: 'tool' } })
    expect(options()).toEqual(['', 'purchased'])
  })

  it('a tool-only row has no comment or flag on paint and revision cells', async () => {
    const tool = row({ part_id: 4, part_number: '199413', name: 'TOOL Cover', row_kind: 'tool_only', item_category: 'tool',
      part_type: 'purchased', tool: { part_id: 4, part_number: '199413', name: 't', cavities: 2, toolmaker_id: null,
        toolmaker_name: null, cycle_time_s: null, tonnage_class: null }, dfm: null })
    clientMocks.get.mockImplementation((url: string) => {
      if (url === '/v1/projects/35/worksheet') return Promise.resolve({ data: { project_id: 35, rows: [tool] } })
      return Promise.resolve({ data: [] })
    })
    mount()
    fireEvent.click(await screen.findByTestId('ws-kind-tool-only'))
    const paint = await screen.findByTestId('ws-cell-4-paint.painted')
    expect(within(paint).queryByTestId('note-marker-paint.painted')).toBeNull()
    fireEvent.contextMenu(paint)
    expect((screen.getByTestId('ws-menu-comment') as HTMLButtonElement).disabled).toBe(true)
    expect((screen.getByTestId('ws-menu-flag-open') as HTMLButtonElement).disabled).toBe(true)
    fireEvent.keyDown(document, { key: 'Escape' })
    fireEvent.contextMenu(screen.getByTestId('ws-cell-4-tool.cavities'))
    expect((screen.getByTestId('ws-menu-comment') as HTMLButtonElement).disabled).toBe(false)
  })

  it('shows the short name with the full name as tooltip', async () => {
    clientMocks.get.mockImplementation((url: string) => {
      if (url === '/v1/projects/35/worksheet') {
        return Promise.resolve({ data: { project_id: 35, rows: [row({ part_id: 1, name: '206.882.251 Handle, manual lift, passenger' })] } })
      }
      return Promise.resolve({ data: [] })
    })
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(<QueryClientProvider client={qc}><MemoryRouter><WorksheetView projectId={35} projectCode="1994" onClose={vi.fn()} /></MemoryRouter></QueryClientProvider>)
    const cell = await screen.findByTestId('ws-cell-1-part.name')
    expect(within(cell).getByText('Handle, manual lift, passenger').closest('[title]')?.getAttribute('title'))
      .toBe('206.882.251 Handle, manual lift, passenger')
  })

  it('hides a column and remembers it', async () => {
    mount()
    await screen.findByTestId('ws-row-1')
    fireEvent.click(screen.getByTestId('ws-columns-toggle'))
    fireEvent.click(screen.getByTestId('ws-column-part.name'))
    expect(screen.queryByTestId('sort-part.name')).toBeNull()
    expect(JSON.parse(window.localStorage.getItem('plm2.worksheet.hiddenColumns')!)).toContain('part.name')
  })

  it('freezes the first identity columns', async () => {
    mount()
    const cell = await screen.findByTestId('ws-cell-1-part.part_number')
    expect(cell.className).toContain('sticky')
    expect(cell.style.left).toBe('44px')
  })

  it('goes back to the item list', async () => {
    const onClose = mount()
    fireEvent.click(await screen.findByTestId('ws-close'))
    expect(onClose).toHaveBeenCalled()
  })

  it('keeps the frozen columns at their width, truncating long values', async () => {
    mount()
    const cell = await screen.findByTestId('ws-cell-1-part.part_number')
    expect(cell.style.width).toBe('170px')
    expect(cell.style.maxWidth).toBe('170px')
    const inner = within(cell).getByTestId('ws-tint-1-part.part_number')
    expect(inner.style.width).toBe('170px')
    expect(inner.style.overflow).toBe('hidden')
    expect(within(cell).getByTitle('20-1994-010-0').className).toContain('truncate')
    const thumb = screen.getByTestId('ws-cell-1-part.thumbnail')
    expect(within(thumb).getByTestId('ws-tint-1-part.thumbnail').style.width).toBe('44px')
    expect(within(thumb).queryByTestId('cell-menu-1-part.thumbnail')).toBeNull()
  })

  it('clears an enum filter whose value is no longer offered', async () => {
    mount()
    await screen.findByTestId('ws-row-1')
    fireEvent.click(screen.getByTestId('ws-kind-purchased'))
    fireEvent.change(screen.getByTestId('filter-part.part_type'), { target: { value: 'purchased' } })
    expect(screen.getAllByTestId(/^ws-row-/).map((r) => r.dataset.testid)).toEqual(['ws-row-2'])
    fireEvent.click(screen.getByTestId('ws-kind-purchased'))
    expect(screen.getAllByTestId(/^ws-row-/).map((r) => r.dataset.testid)).toEqual(['ws-row-3', 'ws-row-1'])
    expect((screen.getByTestId('filter-part.part_type') as HTMLSelectElement).value).toBe('')
  })

  it('shows the error without a row count when the worksheet cannot load', async () => {
    clientMocks.get.mockImplementation(() => Promise.reject({ response: { status: 404 } }))
    mount()
    await screen.findByText('Could not load the worksheet')
    expect(screen.queryByTestId('ws-count')).toBeNull()
  })

  it('exports the visible rows as xlsx', async () => {
    clientMocks.post.mockResolvedValue({ data: new Blob(['x']), headers: { 'content-disposition': 'attachment; filename="1994-worksheet.xlsx"' } })
    Object.assign(URL, { createObjectURL: vi.fn(() => 'blob:x'), revokeObjectURL: vi.fn() })
    mount()
    await screen.findByTestId('ws-row-1')
    fireEvent.change(screen.getByTestId('filter-part.name'), { target: { value: 'isofix' } })
    fireEvent.click(screen.getByTestId('ws-export'))
    await waitFor(() => expect(clientMocks.post).toHaveBeenCalled())
    const [url, payload] = clientMocks.post.mock.calls[0]
    expect(url).toBe('/v1/projects/35/worksheet/export')
    expect(payload.rows).toHaveLength(1)
    expect(payload.columns.some((c: { key: string }) => c.key === 'part.thumbnail')).toBe(false)
  })
})

function Where() {
  const loc = useLocation()
  return <div data-testid="where">{loc.pathname}{loc.search}</div>
}

function mountRouted() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(<QueryClientProvider client={qc}><MemoryRouter initialEntries={['/projects/35?view=worksheet']}>
    <Routes>
      <Route path="/projects/:id" element={<WorksheetView projectId={35} onClose={vi.fn()} />} />
      <Route path="/parts/:partId" element={<Where />} />
    </Routes>
  </MemoryRouter></QueryClientProvider>)
}

describe('WorksheetView cell menu', () => {
  beforeEach(() => {
    clientMocks.get.mockReset(); clientMocks.put.mockReset()
    clientMocks.get.mockImplementation((url: string) => {
      if (url === '/v1/projects/35/worksheet') return Promise.resolve({ data: { project_id: 35, rows } })
      if (url === '/v1/projects/35/field-notes') return Promise.resolve({ data: notes })
      return Promise.resolve({ data: { ...notes[0], comments: [] } })
    })
    clientMocks.put.mockResolvedValue({ data: {} })
  })
  afterEach(cleanup)

  it('Edit on a tool field opens the tool page with the field focused', async () => {
    mountRouted()
    fireEvent.contextMenu(await screen.findByTestId('ws-cell-3-tool.cavities'), { clientX: 10, clientY: 10 })
    fireEvent.click(screen.getByTestId('ws-menu-edit'))
    expect((await screen.findByTestId('where')).textContent).toBe('/parts/93?focus=tool.cavities')
  })

  it('Edit on the material opens the article', async () => {
    mountRouted()
    fireEvent.contextMenu(await screen.findByTestId('ws-cell-1-part.material'))
    fireEvent.click(screen.getByTestId('ws-menu-edit'))
    expect((await screen.findByTestId('where')).textContent).toBe('/parts/1?focus=part.material')
  })

  it('Edit is disabled where no page changes the value', async () => {
    mountRouted()
    fireEvent.contextMenu(await screen.findByTestId('ws-cell-1-notes.summary'))
    expect((screen.getByTestId('ws-menu-edit') as HTMLButtonElement).disabled).toBe(true)
    expect((screen.getByTestId('ws-menu-comment') as HTMLButtonElement).disabled).toBe(true)
  })

  it('Flag sets the flag on the owning part and Comment opens the popover', async () => {
    mountRouted()
    fireEvent.contextMenu(await screen.findByTestId('ws-cell-1-part.name'))
    fireEvent.click(screen.getByTestId('ws-menu-flag-rejected'))
    await waitFor(() => expect(clientMocks.put).toHaveBeenCalledWith('/v1/parts/1/field-notes/part.name/flag', { status: 'rejected' }))
    fireEvent.contextMenu(screen.getByTestId('ws-cell-3-tool.cavities'))
    expect((screen.getByTestId('ws-menu-flag-clear') as HTMLButtonElement).disabled).toBe(false)
    fireEvent.click(screen.getByTestId('ws-menu-comment'))
    expect(await screen.findByTestId('note-popover-tool.cavities')).toBeTruthy()
  })

  it('the hover button opens the same menu', async () => {
    mountRouted()
    await screen.findByTestId('ws-cell-1-part.name')
    fireEvent.click(screen.getByTestId('cell-menu-1-part.name'))
    expect(screen.getByTestId('ws-menu')).toBeTruthy()
    fireEvent.keyDown(document, { key: 'Escape' })
    expect(screen.queryByTestId('ws-menu')).toBeNull()
  })

  it('clamps the menu inside the viewport when opened near the edge', async () => {
    const rectSpy = vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockReturnValue({
      width: 180, height: 200, top: 0, left: 0, right: 180, bottom: 200, x: 0, y: 0, toJSON: () => ({}),
    } as DOMRect)
    mountRouted()
    const cell = await screen.findByTestId('ws-cell-1-part.name')
    fireEvent.contextMenu(cell, { clientX: window.innerWidth - 5, clientY: window.innerHeight - 5 })
    const menu = screen.getByTestId('ws-menu')
    const left = parseFloat(menu.style.left)
    const top = parseFloat(menu.style.top)
    expect(left).toBeGreaterThanOrEqual(0)
    expect(top).toBeGreaterThanOrEqual(0)
    expect(left + 180).toBeLessThanOrEqual(window.innerWidth)
    expect(top + 200).toBeLessThanOrEqual(window.innerHeight)
    rectSpy.mockRestore()
  })

  it('Colour shows a paint or MIC tag and flags, comments and edits where the colour lives', async () => {
    const mic = row({ part_id: 7, part_number: '20-1994-007-0', colour_code: 'NM0',
      paint: { painted: false, colour: null, colour_hex: null, paint_system: null } })
    clientMocks.get.mockImplementation((url: string) => {
      if (url === '/v1/projects/35/worksheet') return Promise.resolve({ data: { project_id: 35, rows: [rows[0], mic] } })
      return Promise.resolve({ data: [] })
    })
    mountRouted()
    const painted = await screen.findByTestId('ws-cell-1-part.colour')
    expect(within(painted).getByTestId('ws-colour-tag').textContent).toBe('paint')
    expect(within(painted).getByTestId('note-marker-paint.colour')).toBeTruthy()
    const cell = screen.getByTestId('ws-cell-7-part.colour')
    expect(cell.textContent).toContain('NM0')
    expect(within(cell).getByTestId('ws-colour-tag').textContent).toBe('MIC')
    expect(within(cell).getByTestId('note-marker-part.colour_code')).toBeTruthy()
    expect(within(screen.getByTestId('ws-cell-7-part.grain')).getByTestId('note-marker-part.grain')).toBeTruthy()
    fireEvent.contextMenu(cell)
    fireEvent.click(screen.getByTestId('ws-menu-flag-open'))
    await waitFor(() => expect(clientMocks.put).toHaveBeenCalledWith('/v1/parts/7/field-notes/part.colour_code/flag', { status: 'open' }))
    fireEvent.contextMenu(cell)
    fireEvent.click(screen.getByTestId('ws-menu-edit'))
    expect((await screen.findByTestId('where')).textContent).toBe('/parts/7?focus=part.colour_code')
  })

  it('Flag on a tool field sends the PUT to the tool part, not the row', async () => {
    mountRouted()
    fireEvent.contextMenu(await screen.findByTestId('ws-cell-3-tool.cavities'))
    fireEvent.click(screen.getByTestId('ws-menu-flag-confirmed'))
    await waitFor(() => expect(clientMocks.put).toHaveBeenCalledWith('/v1/parts/93/field-notes/tool.cavities/flag', { status: 'confirmed' }))
  })
})
