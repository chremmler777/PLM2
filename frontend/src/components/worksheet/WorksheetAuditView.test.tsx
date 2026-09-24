import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, cleanup, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Routes, Route, useLocation } from 'react-router-dom'
import type { WorksheetAuditEntry } from '../../api/worksheet'
import WorksheetAuditView from './WorksheetAuditView'

const clientMocks = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), put: vi.fn() }))
vi.mock('../../api/client', () => ({ default: clientMocks, API_BASE_URL: '/plm2/api' }))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

const part = { id: 7, part_number: '20-1994-001-0', customer_part_number: '206.882.251', item_category: 'article' }
const entry = (id: number, over: Partial<WorksheetAuditEntry> = {}): WorksheetAuditEntry => ({
  id, at: '2026-09-24T14:54:27', actor: { id: 20, name: 'Engineer' }, part, action: 'field_flag_set',
  action_group: 'flags', field_key: 'part.material', old_value: null, new_value: 'open',
  description: 'Flag on part.material: none to open', ...over,
})
const first = [
  entry(9),
  entry(8, { action: 'field_comment_added', action_group: 'comments', new_value: 'Excel says 2', description: 'Comment on tool.cavities: Excel says 2',
    field_key: 'tool.cavities', part: { ...part, id: 90, part_number: '199401', customer_part_number: null, item_category: 'tool' } }),
  entry(7, { action: 'field_updated', action_group: 'values', field_key: 'part.colour_code', new_value: 'NM0',
    description: 'Colour code set to NM0 from the 1994 Excel BOM' }),
]

function Where() {
  const loc = useLocation()
  return <div data-testid="where">{loc.pathname}{loc.search}</div>
}

function mount() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(<QueryClientProvider client={qc}><MemoryRouter initialEntries={['/projects/35']}>
    <Routes>
      <Route path="/projects/:id" element={<WorksheetAuditView projectId={35} />} />
      <Route path="/parts/:partId" element={<Where />} />
    </Routes>
  </MemoryRouter></QueryClientProvider>)
}

const calls = () => clientMocks.get.mock.calls.filter(([url]) => url === '/v1/projects/35/worksheet/audit')

describe('WorksheetAuditView', () => {
  beforeEach(() => {
    clientMocks.get.mockReset()
    clientMocks.get.mockImplementation((_url: string, cfg?: { params?: Record<string, unknown> }) => {
      if (cfg?.params?.before_id === 7) return Promise.resolve({ data: { entries: [entry(3, { new_value: 'confirmed' })], has_more: false } })
      return Promise.resolve({ data: { entries: first, has_more: true } })
    })
  })
  afterEach(cleanup)

  it('lists entries with user, part, field label, action words and value change', async () => {
    mount()
    const row = await screen.findByTestId('audit-row-9')
    expect(row.textContent).toContain('Engineer')
    expect(row.textContent).toContain('20-1994-001-0')
    expect(row.textContent).toContain('206.882.251')
    expect(row.textContent).toContain('Material')
    expect(row.textContent).toContain('Flag set to Open')
    expect(screen.getByTestId('audit-badge-9').className).toContain('bg-yellow-500/20')
    expect(screen.getByTestId('audit-row-8').textContent).toContain('Cavities')
    expect(screen.getByTestId('audit-row-8').textContent).toContain('Excel says 2')
    expect(screen.getByTestId('audit-row-7').textContent).toContain('Colour')
    expect(screen.getByTestId('audit-row-7').textContent).toContain('none -> NM0')
  })

  it('filters by group, part text and field, and the CSV link carries the filters', async () => {
    mount()
    await screen.findByTestId('audit-row-9')
    fireEvent.change(screen.getByTestId('audit-filter-group'), { target: { value: 'flags' } })
    fireEvent.change(screen.getByTestId('audit-filter-field'), { target: { value: 'part.material' } })
    fireEvent.change(screen.getByTestId('audit-filter-part'), { target: { value: '206.882' } })
    await waitFor(() => expect(calls()[calls().length - 1]?.[1].params).toMatchObject(
      { action_group: 'flags', field_key: 'part.material', part: '206.882' }))
    expect(screen.getByTestId('audit-export-csv').getAttribute('href')).toBe(
      '/plm2/api/v1/projects/35/worksheet/audit.csv?action_group=flags&part=206.882&field_key=part.material')
  })

  it('loads older entries with before_id', async () => {
    mount()
    await screen.findByTestId('audit-row-7')
    fireEvent.click(screen.getByTestId('audit-load-older'))
    await screen.findByTestId('audit-row-3')
    expect(calls()[calls().length - 1]?.[1].params.before_id).toBe(7)
    expect(screen.queryByTestId('audit-load-older')).toBeNull()
  })

  it('opens the field like the cell menu Edit', async () => {
    mount()
    fireEvent.click(await screen.findByTestId('audit-row-8'))
    expect((await screen.findByTestId('where')).textContent).toBe('/parts/90?focus=tool.cavities')
  })

  it('shows the API error', async () => {
    clientMocks.get.mockRejectedValue({ response: { status: 500, data: { detail: 'Database down' } } })
    mount()
    expect((await screen.findByTestId('audit-error')).textContent).toContain('Database down')
  })
})
