import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, cleanup, fireEvent, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
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
})
