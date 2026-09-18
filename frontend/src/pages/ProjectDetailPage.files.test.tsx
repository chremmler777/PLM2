import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, cleanup, fireEvent } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import ProjectDetailPage, { RevisionFileRow } from './ProjectDetailPage'

const clientMocks = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() }))
vi.mock('../api/client', () => ({ default: clientMocks, API_BASE_URL: '' }))

// The page hangs a lot of self-fetching sections off the selected part; none of
// them say anything about the customer-package entry point.
const stub = vi.hoisted(() => (label: string) => ({ default: () => <div>{label}</div> }))
vi.mock('../components/Viewer3D', () => stub('viewer'))
vi.mock('../components/CADUploader', () => stub('uploader'))
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

const file = (over: Record<string, unknown> = {}) => ({
  id: 3, revision_id: 9, filename: 'housing.step', file_type: 'cad_native',
  mime_type: 'application/step', file_size: 2_000_000, cad_format: 'step',
  has_viewer: true, uploaded_at: '2026-07-01T00:00:00', ...over,
}) as never

const wrap = (ui: React.ReactElement) =>
  render(<QueryClientProvider client={new QueryClient()}>{ui}</QueryClientProvider>)

describe('RevisionFileRow provenance', () => {
  afterEach(cleanup)

  it('names who uploaded the revision file and when', () => {
    wrap(<RevisionFileRow file={file({ uploaded_by: 5, uploaded_by_name: 'Eva Eng' })}
      isViewing={false} locked={false} />)
    expect(screen.getByTestId('uploaded-by').textContent)
      .toContain(`Eva Eng · ${new Date('2026-07-01T00:00:00').toLocaleDateString()}`)
  })

  it('shows the date alone for a file with no recorded uploader', () => {
    wrap(<RevisionFileRow file={file()} isViewing={false} locked={false} />)
    expect(screen.getByTestId('uploaded-by').textContent).not.toContain('·')
  })
})

describe('ProjectDetailPage customer package entry point', () => {
  beforeEach(() => {
    clientMocks.get.mockReset()
    clientMocks.get.mockImplementation((url: string) => {
      if (url === '/v1/plants/projects')
        return Promise.resolve({ data: [{ id: 2, name: 'Atlas', code: 'ATL', status: 'active' }] })
      if (url === '/v1/parts/project/2')
        return Promise.resolve({ data: [{ id: 5, part_number: '1994-100', name: 'Top', part_type: 'sub_assembly',
          active_revision_id: 9, item_category: 'part', parent_part_id: null }] })
      if (url === '/v1/parts/5/revisions')
        return Promise.resolve({ data: [{ id: 9, part_id: 5, revision_name: 'E1', phase: 'review',
          status: 'draft', created_at: '2026-07-01T00:00:00' }] })
      if (url.includes('/bom-tree'))
        return Promise.resolve({ data: { part_id: 5, part_number: '1994-100', name: 'Top',
          revision_name: 'E1', customer_index: null, lines: [] } })
      return Promise.resolve({ data: [] })
    })
  })
  afterEach(cleanup)

  it('offers the customer package dialog once, for a part that already has revisions', async () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(
      <QueryClientProvider client={qc}>
        <MemoryRouter initialEntries={['/projects/2?part=5']}>
          <Routes><Route path="/projects/:projectId" element={<ProjectDetailPage />} /></Routes>
        </MemoryRouter>
      </QueryClientProvider>)

    expect(await screen.findByText('Files & 3D Model')).toBeTruthy()
    // the revision dropdown is there, so this is the "part has revisions" state
    expect(await screen.findByText('E1 (draft)')).toBeTruthy()
    expect(screen.getAllByText('+ Customer package').length).toBe(1)
    fireEvent.click(screen.getByText('+ Customer package'))
    expect(screen.getByText('Customer package received')).toBeTruthy()
  })
})
