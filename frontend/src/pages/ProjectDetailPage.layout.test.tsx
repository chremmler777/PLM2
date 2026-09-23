import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, cleanup, fireEvent, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import ProjectDetailPage from './ProjectDetailPage'

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
vi.mock('../components/MilestoneStrip', () => stub('milestones'))
vi.mock('../components/ProjectLessonsSection', () => stub('lessons-section'))
vi.mock('../components/ProjectSepSection', () => stub('sep-section'))
vi.mock('../components/ProjectChangesSection', () => stub('changes-section'))
vi.mock('../components/parts/AssemblyTreeList', () => stub('assemblies'))
vi.mock('../components/parts/UploadDialog', () => stub('upload-dialog'))

// Some tests replace these two; keep them at the jsdom defaults otherwise.
const realOpen = window.open

const LH = { id: 5, part_number: '20-1994-001-0', customer_part_number: '206.882.251', tier1_part_number: 'S00H4X-110', name: '206.882.251 Handle LH', part_type: 'internal_mfg', active_revision_id: 9, item_category: 'article', parent_part_id: null, lifecycle_phase: 'nominated' }
const RH = { id: 6, part_number: '20-1994-002-0', name: '206.882.252 Handle RH', part_type: 'internal_mfg', active_revision_id: 19, item_category: 'article', parent_part_id: null, lifecycle_phase: 'nominated' }
const TOOL = { id: 30, part_number: '199401', name: '1994 TOOL Handle', part_type: 'purchased', active_revision_id: null, item_category: 'tool', parent_part_id: null, lifecycle_phase: 'rfq' }
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

let partsData: unknown[] = [LH, RH, TOOL]

function routeGet(url: string) {
  if (url === '/v1/plants/projects') return Promise.resolve({ data: [{ id: 2, name: 'Seat Trim', code: '1994', status: 'active', customer_naming: 'vw' }] })
  if (url === '/v1/parts/project/2') return Promise.resolve({ data: partsData })
  if (url === '/v1/parts/project/2/structure') return Promise.resolve({ data: structure })
  if (url === '/v1/parts/project/2/paint-overview') return Promise.resolve({ data: [
    { part_id: 6, part_number: RH.part_number, name: RH.name, process: null, layers: [{ layer_order: 1, area: null, notes: null,
      paint: { id: 7, name: 'Black', paint_type: 'basecoat', colour_code: 'RAL 9005', colour_name: 'Black', colour_hex: '#111111', supplier_id: null, supplier_text: null, spec_reference: null, notes: null, is_active: true } }] },
  ] })
  if (url === '/v1/parts/5/revisions') return Promise.resolve({ data: structure.articles[0].revisions.map((r) => ({ ...r, part_id: 5, created_at: '2026-05-28' })) })
  if (url === '/v1/parts/6/revisions') return Promise.resolve({ data: structure.articles[1].revisions.map((r) => ({ ...r, part_id: 6, created_at: '2026-05-28' })) })
  if (url.includes('/bom-tree')) return Promise.resolve({ data: { part_id: 5, part_number: LH.part_number, name: LH.name, revision_name: 'E1', customer_index: '003', lines: [] } })
  if (url === '/v1/sep/projects/2') return Promise.resolve({ data: { active: true, gates: [
    { id: 1, code: 'K0/RG1', status: 'in_progress', color: 'green', phase_en: 'Kick-off', progress: { done: 0, open: 5, not_applicable: 0, total: 5, pct: 0 } },
  ] } })
  if (url === '/v1/lessons/projects/2/references') return Promise.resolve({ data: [] })
  return Promise.resolve({ data: [] })
}

function mount(path = '/projects/2') {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[path]}>
        <Routes><Route path="/projects/:projectId" element={<ProjectDetailPage />} /></Routes>
      </MemoryRouter>
    </QueryClientProvider>)
  return queryClient
}

beforeEach(() => {
  partsData = [LH, RH, TOOL]
  localStorage.clear()
  clientMocks.get.mockReset()
  clientMocks.get.mockImplementation(routeGet)
})
afterEach(() => {
  cleanup()
  window.open = realOpen
  vi.unstubAllGlobals()
})

describe('project header and slide-over', () => {
  it('no longer stacks the SEP, changes and lessons blocks above the items', async () => {
    mount()
    expect(await screen.findByTestId('project-header')).toBeTruthy()
    expect(screen.queryByText('sep-section')).toBeNull()
    expect(screen.queryByText('changes-section')).toBeNull()
    expect(screen.queryByText('lessons-section')).toBeNull()
  })

  it('opens each section in the slide-over and closes it with Escape or a click outside', async () => {
    mount()
    fireEvent.click(await screen.findByTestId('chip-sep'))
    expect(within(screen.getByTestId('status-slideover')).getByText('sep-section')).toBeTruthy()
    fireEvent.keyDown(document, { key: 'Escape' })
    expect(screen.queryByTestId('status-slideover')).toBeNull()

    fireEvent.click(screen.getByTestId('chip-lessons'))
    expect(screen.getByText('lessons-section')).toBeTruthy()
    fireEvent.click(screen.getByTestId('slideover-backdrop'))
    expect(screen.queryByTestId('status-slideover')).toBeNull()

    fireEvent.click(screen.getByTestId('chip-changes'))
    expect(screen.getByText('changes-section')).toBeTruthy()
  })

  it('the ⋯ menu still reaches the add-part dialog', async () => {
    mount()
    fireEvent.click(await screen.findByLabelText('Project actions'))
    fireEvent.click(screen.getByText('+ Add Part'))
    expect(screen.getByText('Add New Item')).toBeTruthy()
  })
})

describe('paint on the project page', () => {
  it('does not mount the paint section but keeps the Painted filter', async () => {
    mount()
    expect(await screen.findByText('🎨 Painted (1)')).toBeTruthy()
    expect(screen.queryByTestId('project-paint-toggle')).toBeNull()
  })
})
