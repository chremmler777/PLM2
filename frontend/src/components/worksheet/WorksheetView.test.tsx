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
})
