import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, cleanup } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import PartDetail from './PartDetail'

const clientMocks = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), delete: vi.fn() }))
vi.mock('../api/client', () => ({ default: clientMocks, API_BASE_URL: '' }))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => ({ isAdmin: true }) }))

const stub = vi.hoisted(() => (label: string) => ({ default: () => <div>{label}</div> }))
vi.mock('../components/changes/StartChangeModal', () => stub('start-change'))
vi.mock('../components/changes/StartChangeButton', () => stub('start-change-button'))
vi.mock('../components/parts/RevisionTimeline', () => stub('timeline'))
vi.mock('../components/parts/CustomerDataDialog', () => stub('customer-data'))
vi.mock('../components/parts/CustomerPackageDialog', () => stub('customer-package'))
vi.mock('../components/parts/BomTree', () => stub('bom-tree'))
vi.mock('../components/parts/DocumentPane', () => ({ default: () => <div data-testid="document-pane" /> }))
vi.mock('../components/Viewer3D', () => stub('viewer-3d'))
vi.mock('../components/paint/PartPaintCard', () => stub('paint-card'))
vi.mock('./ToolDetail', () => ({ default: ({ part }: { part: { part_number: string } }) => <div data-testid="tool-detail">{part.part_number}</div> }))

const part = (over: Record<string, unknown> = {}) => ({
  id: 5, part_number: '199403', customer_part_number: null, name: 'ISOFIX Cover',
  part_type: 'purchased', data_classification: 'confidential', item_category: 'tool',
  project_id: 2, active_revision_id: null, lifecycle_phase: 'nominated', revisions: [], ...over,
})

function renderPart() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={['/parts/5']}>
        <Routes><Route path="/parts/:partId" element={<PartDetail />} /></Routes>
      </MemoryRouter>
    </QueryClientProvider>)
}

describe('PartDetail on a tool', () => {
  beforeEach(() => {
    clientMocks.get.mockReset()
    clientMocks.get.mockImplementation((url: string) => {
      if (url === '/v1/parts/5') return Promise.resolve({ data: part() })
      return Promise.resolve({ data: [] })
    })
  })
  afterEach(cleanup)

  it('renders the tool page instead of the article page', async () => {
    renderPart()
    expect((await screen.findByTestId('tool-detail')).textContent).toBe('199403')
    expect(screen.queryByText('timeline')).toBeNull()
    expect(screen.queryByTestId('document-pane')).toBeNull()
    expect(screen.queryByText('customer-package')).toBeNull()
    expect(screen.queryByText('Bill of materials')).toBeNull()
  })

  it('does not fetch article-only data for a tool', async () => {
    renderPart()
    await screen.findByTestId('tool-detail')
    const urls = clientMocks.get.mock.calls.map((c) => c[0] as string)
    expect(urls).not.toContain('/v1/parts/5/bom-tree')
    expect(urls).not.toContain('/v1/parts/5/where-used')
  })

  it('still renders the article page for an article', async () => {
    clientMocks.get.mockImplementation((url: string) => {
      if (url === '/v1/parts/5') return Promise.resolve({ data: part({ item_category: 'article', part_number: '20-1994-003-0' }) })
      if (url === '/v1/parts/5/paint') return Promise.resolve({ data: { paint_required: false, process: null, notes: null, layers: [] } })
      return Promise.resolve({ data: [] })
    })
    renderPart()
    expect(await screen.findByText('timeline')).toBeTruthy()
    expect(screen.queryByTestId('tool-detail')).toBeNull()
  })
})
