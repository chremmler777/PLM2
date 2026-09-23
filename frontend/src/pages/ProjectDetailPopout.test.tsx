import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, cleanup, act, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import ProjectDetailPopout from './ProjectDetailPopout'
import { FakeBroadcastChannel } from '../testing/fakeBroadcastChannel'

const clientMocks = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), delete: vi.fn() }))
vi.mock('../api/client', () => ({ default: clientMocks, API_BASE_URL: '' }))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))
const stub = vi.hoisted(() => (label: string) => ({ default: () => <div>{label}</div> }))
vi.mock('../components/Viewer3D', () => stub('viewer'))
vi.mock('../components/workflows/RevisionWorkflowSection', () => stub('workflow-section'))
vi.mock('../components/PartBOMSection', () => stub('bom-section'))
vi.mock('../components/PartRelationsSection', () => stub('relations-section'))
vi.mock('../components/ProcessFlowSection', () => stub('process-flow-section'))
vi.mock('../components/PPAPSection', () => stub('ppap-section'))
vi.mock('../components/parts/UploadDialog', () => stub('upload-dialog'))

const LH = { id: 5, part_number: '20-1994-001-0', customer_part_number: '206.882.251', name: '206.882.251 Handle LH', part_type: 'internal_mfg', active_revision_id: 9, item_category: 'article', parent_part_id: null }
const RH = { id: 6, part_number: '20-1994-002-0', name: '206.882.252 Handle RH', part_type: 'internal_mfg', active_revision_id: 19, item_category: 'article', parent_part_id: null }
const NEW = { id: 77, part_number: '20-1994-077-0', name: 'New bracket', part_type: 'internal_mfg', active_revision_id: null, item_category: 'article', parent_part_id: null }
const revs5 = [
  { id: 9, part_id: 5, revision_name: 'E1', customer_index: '003', status: 'approved', phase: 'review', parent_revision_id: null, created_at: '2026-05-28' },
  { id: 10, part_id: 5, revision_name: 'E1.1', customer_index: null, status: 'draft', phase: 'review', parent_revision_id: 9, created_at: '2026-05-28' },
]
const revs6 = [{ id: 19, part_id: 6, revision_name: 'E1', customer_index: '003', status: 'approved', phase: 'review', parent_revision_id: null, created_at: '2026-05-28' }]
let partsData: unknown[] = [LH, RH]

function mount(path = '/projects/2/detail?part=5') {
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter initialEntries={[path]}>
        <Routes><Route path="/projects/:projectId/detail" element={<ProjectDetailPopout />} /></Routes>
      </MemoryRouter>
    </QueryClientProvider>)
}

function mainWindow() {
  const got: unknown[] = []
  const channel = new FakeBroadcastChannel('plm2-project-2')
  channel.onmessage = (e) => { got.push(e.data) }
  return { channel, got }
}

describe('ProjectDetailPopout', () => {
  beforeEach(() => {
    partsData = [LH, RH]
    FakeBroadcastChannel.reset()
    vi.stubGlobal('BroadcastChannel', FakeBroadcastChannel)
    clientMocks.get.mockReset()
    clientMocks.get.mockImplementation((url: string) => {
      if (url === '/v1/plants/projects') return Promise.resolve({ data: [{ id: 2, name: 'Seat Trim', code: '1994', status: 'active' }] })
      if (url === '/v1/parts/project/2') return Promise.resolve({ data: partsData })
      if (url === '/v1/parts/5/revisions') return Promise.resolve({ data: revs5 })
      if (url === '/v1/parts/6/revisions') return Promise.resolve({ data: revs6 })
      return Promise.resolve({ data: [] })
    })
  })
  afterEach(() => {
    cleanup()
    vi.unstubAllGlobals()
  })

  it('shows only the detail of the part in the URL and says hello', async () => {
    const main = mainWindow()
    mount()
    expect((await screen.findByTestId('detail-header')).textContent).toContain('Handle LH')
    expect(screen.queryByTestId('items-pane')).toBeNull()
    expect(screen.queryByLabelText('Open detail in new window')).toBeNull()
    expect(main.got).toContainEqual({ type: 'hello' })
  })

  it('echoes the owner id of its main window in hello and bye', async () => {
    const main = mainWindow()
    mount('/projects/2/detail?part=5&owner=owner-a')
    await screen.findByTestId('detail-header')
    expect(main.got).toContainEqual({ type: 'hello', owner: 'owner-a' })
    main.got.length = 0
    act(() => main.channel.postMessage({ type: 'ping' }))
    expect(main.got).toEqual([{ type: 'hello', owner: 'owner-a' }])
    cleanup()
    expect(main.got).toContainEqual({ type: 'bye', owner: 'owner-a' })
  })

  it('opens on the revision named in the URL', async () => {
    mount('/projects/2/detail?part=5&rev=10')
    expect((await screen.findByTestId('rev-tab-10')).getAttribute('aria-selected')).toBe('true')
  })

  it('follows a selection posted by the main window', async () => {
    const main = mainWindow()
    mount()
    await screen.findByTestId('detail-header')
    act(() => main.channel.postMessage({ type: 'select', partId: 6, revisionId: 19 }))
    await waitFor(() => expect(screen.getByTestId('detail-header').textContent).toContain('Handle RH'))
    act(() => main.channel.postMessage({ type: 'select', partId: 5, revisionId: 10 }))
    expect((await screen.findByTestId('rev-tab-10')).getAttribute('aria-selected')).toBe('true')
  })

  it('answers a ping from the main window', async () => {
    const main = mainWindow()
    mount()
    await screen.findByTestId('detail-header')
    main.got.length = 0
    act(() => main.channel.postMessage({ type: 'ping' }))
    expect(main.got).toEqual([{ type: 'hello' }])
  })

  it('says bye when it goes away', async () => {
    const main = mainWindow()
    mount()
    await screen.findByTestId('detail-header')
    cleanup()
    expect(main.got).toContainEqual({ type: 'bye' })
  })

  it('waits for a part it does not know yet and shows it after refetching the parts', async () => {
    const main = mainWindow()
    mount()
    await screen.findByTestId('detail-header')
    partsData = [LH, RH, NEW] // created in the main window after the pop-out loaded
    act(() => main.channel.postMessage({ type: 'select', partId: 77, revisionId: null }))
    expect(screen.getByText('Select an item in the main window')).toBeTruthy()
    await waitFor(() => expect(screen.getByTestId('detail-header').textContent).toContain('New bracket'))
  })
})
