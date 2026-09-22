import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, cleanup, fireEvent, waitFor, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import ProjectDetailPage from './ProjectDetailPage'

const clientMocks = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() }))
vi.mock('../api/client', () => ({ default: clientMocks, API_BASE_URL: '' }))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))
const stub = vi.hoisted(() => (label: string) => ({ default: () => <div>{label}</div> }))
vi.mock('../components/Viewer3D', () => stub('viewer'))
vi.mock('../components/workflows/RevisionWorkflowSection', () => stub('workflow'))
vi.mock('../components/PartBOMSection', () => stub('bom-section'))
vi.mock('../components/PartRelationsSection', () => stub('relations'))
vi.mock('../components/ProcessFlowSection', () => stub('process-flow'))
vi.mock('../components/PPAPSection', () => stub('ppap'))
vi.mock('../components/MilestoneStrip', () => stub('milestones'))
vi.mock('../components/ProjectLessonsSection', () => stub('lessons'))
vi.mock('../components/ProjectSepSection', () => stub('sep'))
vi.mock('../components/ProjectChangesSection', () => stub('changes'))
vi.mock('../components/parts/AssemblyTreeList', () => stub('assemblies'))
vi.mock('../components/parts/UploadDialog', () => stub('upload-dialog'))

const LH = { id: 5, part_number: '20-1994-001-0', name: '206.882.251 Handle LH', part_type: 'internal_mfg', active_revision_id: 9, item_category: 'article', parent_part_id: null }
const RH = { id: 6, part_number: '20-1994-002-0', name: '206.882.252 Handle RH', part_type: 'internal_mfg', active_revision_id: 19, item_category: 'article', parent_part_id: null }
const structure = { articles: [
  { part_id: 5, part_number: LH.part_number, customer_part_number: '206.882.251', name: LH.name, lifecycle_phase: 'nominated', active_revision_id: 9,
    revisions: [{ id: 9, revision_name: 'E1', customer_index: '003', status: 'approved', phase: 'review', parent_revision_id: null, is_active: true },
                { id: 10, revision_name: 'E1.1', customer_index: null, status: 'draft', phase: 'review', parent_revision_id: 9, is_active: false }],
    related: [{ relation_type: 'produces', direction: 'incoming', label: 'produced by', part_id: 30, part_number: '199401', name: 'TOOL Handle', item_category: 'tool' }],
    mirror_of: null, mirrored_by: [{ part_id: 6, part_number: RH.part_number, customer_part_number: '206.882.252', name: RH.name }] },
  { part_id: 6, part_number: RH.part_number, customer_part_number: '206.882.252', name: RH.name, lifecycle_phase: 'nominated', active_revision_id: 19,
    revisions: [{ id: 19, revision_name: 'E1', customer_index: '003', status: 'approved', phase: 'review', parent_revision_id: null, is_active: true }],
    related: [], mirror_of: { part_id: 5, part_number: LH.part_number, customer_part_number: '206.882.251', name: LH.name }, mirrored_by: [] },
] }
const files9 = [
  { id: 101, revision_id: 9, filename: 'lh.CATPart', file_type: 'cad', mime_type: 'application/octet-stream', file_size: 1, cad_format: 'catia', has_viewer: false, uploaded_at: '2026-05-28', kind: 'PCA', note: 'PCA engineering master' },
  { id: 102, revision_id: 9, filename: 'lh.stp', file_type: 'cad', mime_type: 'application/step', file_size: 1, cad_format: 'step', has_viewer: true, uploaded_at: '2026-05-28' },
  { id: 103, revision_id: 9, filename: 'lh.pdf', file_type: 'drawing', mime_type: 'application/pdf', file_size: 1, cad_format: null, has_viewer: false, uploaded_at: '2026-05-28' },
]

function mount() {
  clientMocks.get.mockImplementation((url: string) => {
    if (url === '/v1/plants/projects') return Promise.resolve({ data: [{ id: 2, name: 'Seat Trim', code: '1994', status: 'active' }] })
    if (url === '/v1/parts/project/2') return Promise.resolve({ data: [LH, RH] })
    if (url === '/v1/parts/project/2/structure') return Promise.resolve({ data: structure })
    if (url === '/v1/parts/5/revisions') return Promise.resolve({ data: structure.articles[0].revisions.map((r) => ({ ...r, part_id: 5, created_at: '2026-05-28' })) })
    if (url === '/v1/parts/6/revisions') return Promise.resolve({ data: structure.articles[1].revisions.map((r) => ({ ...r, part_id: 6, created_at: '2026-05-28' })) })
    if (url === '/v1/parts/revisions/9/files') return Promise.resolve({ data: files9 })
    if (url === '/v1/parts/revisions/10/files') return Promise.resolve({ data: [] })
    if (url === '/v1/parts/revisions/19/files') return Promise.resolve({ data: [] })
    if (url.includes('/bom-tree')) return Promise.resolve({ data: { part_id: 5, part_number: LH.part_number, name: LH.name, revision_name: 'E1', customer_index: '003', lines: [] } })
    return Promise.resolve({ data: [] })
  })
  return render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter initialEntries={['/projects/2']}><Routes><Route path="/projects/:projectId" element={<ProjectDetailPage />} /></Routes></MemoryRouter>
    </QueryClientProvider>)
}

describe('ProjectDetailPage article panel', () => {
  beforeEach(() => { clientMocks.get.mockReset(); clientMocks.post.mockReset() })
  afterEach(cleanup)

  it('shows the revision strip with the proposal nested, grouped files and relation chips', async () => {
    mount()
    fireEvent.click(await screen.findByText(/Handle LH/))
    expect(await screen.findByTestId('rev-tab-10')).toBeTruthy()
    expect(screen.getByTestId('rev-tab-10').textContent).toContain('proposal')
    expect(await screen.findByText('3D (2)')).toBeTruthy()
    expect(screen.getByText('2D (1)')).toBeTruthy()
    expect(screen.getByTestId('relation-chip-30').textContent).toContain('199401')
    expect(screen.getAllByText(/mirrored by 20-1994-002-0/).length).toBeGreaterThan(0)
  })

  it('Open on the drawing switches the pane to the inline pdf, selecting a revision switches back', async () => {
    mount()
    fireEvent.click(await screen.findByText(/Handle LH/))
    await screen.findByText('3D (2)')
    fireEvent.click(screen.getByText('Open'))
    expect((await screen.findByTestId('doc-iframe') as HTMLIFrameElement).src).toContain('/v1/parts/revision-files/103/inline')
    fireEvent.click(screen.getByTestId('rev-tab-10'))
    await waitFor(() => expect(screen.queryByTestId('doc-iframe')).toBeNull())
  })

  it('a mirror with no own 3D shows the source viewer under the red banner and the mirror chip', async () => {
    mount()
    fireEvent.click(await screen.findByText(/Handle RH/))
    const banner = await screen.findByTestId('mirror-banner')
    expect(banner.textContent).toContain('Mirrored part. Showing 206.882.251')
    expect(screen.getByText('viewer')).toBeTruthy()
    expect(screen.getByTestId('mirror-chip').textContent).toContain('Mirror of 206.882.251')
    fireEvent.click(within(banner).getByText('Open source part'))
    expect(await screen.findByText('3D (2)')).toBeTruthy()
  })

  it('+ Proposal on the selected major posts a proposal', async () => {
    clientMocks.post.mockResolvedValue({ data: { id: 11, revision_name: 'E1.2' } })
    mount()
    fireEvent.click(await screen.findByText(/Handle LH/))
    await screen.findByTestId('rev-tab-9')
    fireEvent.click(screen.getByText('+ Proposal'))
    await waitFor(() => expect(clientMocks.post).toHaveBeenCalledWith('/v1/parts/5/revisions/proposals', { parent_revision_id: 9 }))
  })

  it('tree rows expand to revisions and tools, and mark mirrors', async () => {
    mount()
    const row = await screen.findByText(/Handle LH/)
    expect(screen.getByTestId('tree-mirror-of-6').textContent).toContain('mirror of 20-1994-001-0')
    const chevron = within(row.closest('button')!.parentElement!).getByLabelText('Expand')
    fireEvent.click(chevron)
    expect(await screen.findByTestId('tree-rev-10')).toBeTruthy()
    expect(screen.getByTestId('tree-rev-10').textContent).toContain('E1.1')
    expect(screen.getByTestId('tree-rel-30').textContent).toContain('199401')
    fireEvent.click(screen.getByTestId('tree-rev-10'))
    expect((await screen.findByTestId('rev-tab-10')).getAttribute('aria-selected')).toBe('true')
  })

  it('a pending revision pick abandoned by switching parts does not leak into a later re-select', async () => {
    let resolveLHRevisions!: (value: { data: unknown }) => void
    const lhRevisionsPromise = new Promise<{ data: unknown }>((resolve) => { resolveLHRevisions = resolve })
    let lhRevisionsCallCount = 0
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    clientMocks.get.mockImplementation((url: string) => {
      if (url === '/v1/plants/projects') return Promise.resolve({ data: [{ id: 2, name: 'Seat Trim', code: '1994', status: 'active' }] })
      if (url === '/v1/parts/project/2') return Promise.resolve({ data: [LH, RH] })
      if (url === '/v1/parts/project/2/structure') return Promise.resolve({ data: structure })
      if (url === '/v1/parts/5/revisions') {
        lhRevisionsCallCount++
        // First fetch (triggered by clicking the tree-rev-10 chip) stays pending until
        // resolveLHRevisions is called below, simulating the part switch racing ahead of it.
        return lhRevisionsCallCount === 1 ? lhRevisionsPromise : Promise.resolve({ data: structure.articles[0].revisions.map((r) => ({ ...r, part_id: 5, created_at: '2026-05-28' })) })
      }
      if (url === '/v1/parts/6/revisions') return Promise.resolve({ data: structure.articles[1].revisions.map((r) => ({ ...r, part_id: 6, created_at: '2026-05-28' })) })
      if (url === '/v1/parts/revisions/9/files') return Promise.resolve({ data: files9 })
      if (url === '/v1/parts/revisions/10/files') return Promise.resolve({ data: [] })
      if (url === '/v1/parts/revisions/19/files') return Promise.resolve({ data: [] })
      if (url.includes('/bom-tree')) return Promise.resolve({ data: { part_id: 5, part_number: LH.part_number, name: LH.name, revision_name: 'E1', customer_index: '003', lines: [] } })
      return Promise.resolve({ data: [] })
    })
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={['/projects/2']}><Routes><Route path="/projects/:projectId" element={<ProjectDetailPage />} /></Routes></MemoryRouter>
      </QueryClientProvider>)

    const row = await screen.findByText(/Handle LH/)
    const chevron = within(row.closest('button')!.parentElement!).getByLabelText('Expand')
    fireEvent.click(chevron)
    // Click LH's revision 10 chip: sets pendingRevisionRef = { partId: 5, revisionId: 10 } while
    // /v1/parts/5/revisions is still in flight (unresolved).
    fireEvent.click(await screen.findByTestId('tree-rev-10'))
    // Switch to RH before LH's revisions query resolves.
    fireEvent.click(screen.getAllByText(/Handle RH/)[0])
    expect((await screen.findByTestId('rev-tab-19')).getAttribute('aria-selected')).toBe('true')
    // Now let LH's original in-flight fetch resolve and land in the cache.
    resolveLHRevisions({ data: structure.articles[0].revisions.map((r) => ({ ...r, part_id: 5, created_at: '2026-05-28' })) })
    await waitFor(() => expect(queryClient.getQueryData(['part-revisions', 5])).toBeTruthy())
    // Re-select LH: the abandoned pending pick for revision 10 must not resurrect —
    // the default (active) revision 9 should be selected instead.
    fireEvent.click(screen.getAllByText(/Handle LH/)[0])
    expect((await screen.findByTestId('rev-tab-9')).getAttribute('aria-selected')).toBe('true')
  })
})
