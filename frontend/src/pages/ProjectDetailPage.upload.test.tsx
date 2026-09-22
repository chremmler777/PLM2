import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, cleanup, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import ProjectDetailPage from './ProjectDetailPage'

const clientMocks = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() }))
vi.mock('../api/client', () => ({ default: clientMocks, API_BASE_URL: '' }))
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
const dialogProps = vi.hoisted(() => ({ last: null as Record<string, unknown> | null }))
vi.mock('../components/parts/UploadDialog', () => ({
  default: (props: Record<string, unknown>) => { dialogProps.last = props; return <div>upload-dialog</div> },
}))

describe('ProjectDetailPage upload entry point', () => {
  beforeEach(() => {
    dialogProps.last = null
    clientMocks.get.mockReset()
    clientMocks.get.mockImplementation((url: string) => {
      if (url === '/v1/plants/projects')
        return Promise.resolve({ data: [{ id: 2, name: 'Atlas', code: 'ATL', status: 'active', customer_naming: 'vw' }] })
      if (url === '/v1/parts/project/2')
        return Promise.resolve({ data: [{ id: 5, part_number: '20-1', name: 'Cover', part_type: 'internal_mfg',
          active_revision_id: 9, item_category: 'article', parent_part_id: null }] })
      if (url === '/v1/parts/5/revisions')
        return Promise.resolve({ data: [{ id: 9, part_id: 5, revision_name: 'E1', phase: 'review', status: 'approved',
          created_at: '2026-05-28', customer_index: '003' }] })
      if (url === '/v1/parts/revisions/9/files') return Promise.resolve({ data: [] })
      if (url.includes('/bom-tree'))
        return Promise.resolve({ data: { part_id: 5, part_number: '20-1', name: 'Cover',
          revision_name: 'E1', customer_index: '003', lines: [] } })
      return Promise.resolve({ data: [] })
    })
  })
  afterEach(cleanup)

  it('opens the upload dialog with the project convention and the selected revision when files are dropped', async () => {
    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <MemoryRouter initialEntries={['/projects/2']}>
          <Routes><Route path="/projects/:projectId" element={<ProjectDetailPage />} /></Routes>
        </MemoryRouter>
      </QueryClientProvider>)
    fireEvent.click(await screen.findByText('Cover'))
    const zone = await screen.findByTestId('upload-dropzone')
    const f = new File(['x'], '206_881_479____PCA_TM__003_____X.CATPart')
    fireEvent.drop(zone, { dataTransfer: { files: [f] } })
    await waitFor(() => expect(screen.getByText('upload-dialog')).toBeTruthy())
    expect(dialogProps.last).toEqual(expect.objectContaining({
      partId: 5, projectNaming: 'vw', officialOnly: false, revisionNames: ['E1'],
    }))
    expect((dialogProps.last as { currentRevision: { id: number } }).currentRevision.id).toBe(9)
    expect((dialogProps.last as { initialFiles: File[] }).initialFiles[0].name).toBe(f.name)
  })
})
