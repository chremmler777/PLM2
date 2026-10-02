import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, cleanup } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import DfmPopout from './DfmPopout'

const clientMocks = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }))
vi.mock('../api/client', () => ({ default: clientMocks, API_BASE_URL: '' }))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))
vi.mock('../components/dfm/DfmArchive', () => ({
  default: (p: { scope: { kind: string; id: number }; projectId: number | null; initialTopic: number | null; inWindow: boolean }) => (
    <div data-testid="archive">{p.scope.kind} {p.scope.id} topic {String(p.initialTopic)} window {String(p.inWindow)}
      <span data-testid="archive-project">{String(p.projectId)}</span></div>
  ),
}))

const TOOL = { id: 7, part_number: '30-1994-003-0', name: 'ISOFIX cover tool', item_category: 'tool', project_id: 35 }
const relations = [{ id: 1, relation_type: 'produces', direction: 'outgoing', other_part_id: 5, other_part_number: '20-1994-001-0',
  other_part_name: 'ISOFIX cover LH', other_item_category: 'article', other_active_revision_name: 'E1', other_active_customer_index: null, notes: null }]

function mount(path: string) {
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/parts/:partId/dfm" element={<DfmPopout />} />
          <Route path="/projects/:projectId/dfm" element={<DfmPopout />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>)
}

describe('DfmPopout', () => {
  beforeEach(() => {
    clientMocks.get.mockReset()
    clientMocks.get.mockImplementation((url: string) => {
      if (url === '/v1/parts/7') return Promise.resolve({ data: TOOL })
      if (url === '/v1/parts/7/relations') return Promise.resolve({ data: relations })
      if (url === '/v1/plants/projects') return Promise.resolve({ data: [{ id: 35, code: 'P1994', name: 'Brose door module', status: 'active' }] })
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
    expect(screen.getByTestId('archive').textContent).toBe('tool 7 topic 3 window true35')
  })

  it('opens the topic list without a topic parameter', async () => {
    mount('/parts/7/dfm')
    expect((await screen.findByTestId('archive')).textContent).toMatch(/^tool 7 topic null window true/)
  })

  it('renders the general tooling DFM of a project with the project header', async () => {
    mount('/projects/35/dfm?topic=4')
    const header = screen.getByTestId('dfm-popout-header')
    expect(header.textContent).toContain('General tooling DFM')
    await screen.findByText('P1994')
    expect(header.textContent).toContain('Brose door module')
    expect(screen.getByTestId('archive').textContent).toBe('project 35 topic 4 window truenull')
    expect(clientMocks.get).not.toHaveBeenCalledWith('/v1/parts/0')
  })
})
