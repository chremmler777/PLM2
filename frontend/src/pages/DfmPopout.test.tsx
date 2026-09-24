import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, cleanup } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import DfmPopout from './DfmPopout'

const clientMocks = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }))
vi.mock('../api/client', () => ({ default: clientMocks, API_BASE_URL: '' }))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))
vi.mock('../components/dfm/DfmArchive', () => ({
  default: (p: { partId: number; initialTopic: number | null; inWindow: boolean }) => (
    <div data-testid="archive">tool {p.partId} topic {String(p.initialTopic)} window {String(p.inWindow)}</div>
  ),
}))

const TOOL = { id: 7, part_number: '30-1994-003-0', name: 'ISOFIX cover tool', item_category: 'tool', project_id: 35 }
const relations = [{ id: 1, relation_type: 'produces', direction: 'outgoing', other_part_id: 5, other_part_number: '20-1994-001-0',
  other_part_name: 'ISOFIX cover LH', other_item_category: 'article', other_active_revision_name: 'E1', other_active_customer_index: null, notes: null }]

function mount(path: string) {
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter initialEntries={[path]}>
        <Routes><Route path="/parts/:partId/dfm" element={<DfmPopout />} /></Routes>
      </MemoryRouter>
    </QueryClientProvider>)
}

describe('DfmPopout', () => {
  beforeEach(() => {
    clientMocks.get.mockReset()
    clientMocks.get.mockImplementation((url: string) => {
      if (url === '/v1/parts/7') return Promise.resolve({ data: TOOL })
      if (url === '/v1/parts/7/relations') return Promise.resolve({ data: relations })
      return Promise.resolve({ data: [] })
    })
  })
  afterEach(cleanup)

  it('renders the tool header and the full archive for the tool, on the asked topic', async () => {
    mount('/parts/7/dfm?topic=3')
    await screen.findByText('30-1994-003-0')
    const header = screen.getByTestId('dfm-popout-header')
    expect(header.textContent).toContain('ISOFIX cover tool')
    expect(await screen.findByText('ISOFIX cover LH')).toBeTruthy()
    expect(screen.getByTestId('archive').textContent).toBe('tool 7 topic 3 window true')
  })

  it('opens the topic list without a topic parameter', async () => {
    mount('/parts/7/dfm')
    expect((await screen.findByTestId('archive')).textContent).toBe('tool 7 topic null window true')
  })
})
