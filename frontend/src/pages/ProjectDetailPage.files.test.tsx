import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, cleanup, fireEvent, waitFor } from '@testing-library/react'
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

describe('ProjectDetailPage add part form', () => {
  beforeEach(() => {
    clientMocks.get.mockReset()
    clientMocks.post.mockReset()
    clientMocks.get.mockImplementation((url: string) => {
      if (url === '/v1/plants/projects')
        return Promise.resolve({ data: [{ id: 2, name: 'Atlas', code: 'ATL', status: 'active' }] })
      if (url === '/v1/parts/project/2') return Promise.resolve({ data: [] })
      return Promise.resolve({ data: [] })
    })
    clientMocks.post.mockResolvedValue({ data: { id: 11 } })
  })
  afterEach(cleanup)

  it('sends the customer part number when a part is created', async () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(
      <QueryClientProvider client={qc}>
        <MemoryRouter initialEntries={['/projects/2']}>
          <Routes><Route path="/projects/:projectId" element={<ProjectDetailPage />} /></Routes>
        </MemoryRouter>
      </QueryClientProvider>)

    fireEvent.click(await screen.findByText('+ Add Part'))
    fireEvent.change(screen.getByPlaceholderText('e.g., P-001'), { target: { value: '1994-100' } })
    fireEvent.change(screen.getByPlaceholderText('e.g., Housing'), { target: { value: 'Top' } })
    fireEvent.change(screen.getByTestId('add-part-customer-number'), { target: { value: '3CR.807.425' } })
    fireEvent.click(screen.getByText('Add Part'))

    await waitFor(() => expect(clientMocks.post).toHaveBeenCalled())
    const [url, payload] = clientMocks.post.mock.calls[0]
    expect(url).toBe('/v1/parts')
    expect(payload).toMatchObject({ part_number: '1994-100', customer_part_number: '3CR.807.425' })
  })

  it('sends no customer part number when the field is left empty', async () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(
      <QueryClientProvider client={qc}>
        <MemoryRouter initialEntries={['/projects/2']}>
          <Routes><Route path="/projects/:projectId" element={<ProjectDetailPage />} /></Routes>
        </MemoryRouter>
      </QueryClientProvider>)

    fireEvent.click(await screen.findByText('+ Add Part'))
    fireEvent.change(screen.getByPlaceholderText('e.g., P-001'), { target: { value: '1994-110' } })
    fireEvent.change(screen.getByPlaceholderText('e.g., Housing'), { target: { value: 'Sub' } })
    fireEvent.click(screen.getByText('Add Part'))

    await waitFor(() => expect(clientMocks.post).toHaveBeenCalled())
    expect(clientMocks.post.mock.calls[0][1].customer_part_number).toBe(null)
  })
})

describe('ProjectDetailPage items list', () => {
  beforeEach(() => {
    clientMocks.get.mockReset()
    clientMocks.get.mockImplementation((url: string) => {
      if (url === '/v1/plants/projects')
        return Promise.resolve({ data: [{ id: 2, name: 'Atlas', code: '1994', status: 'active' }] })
      if (url === '/v1/parts/project/2')
        return Promise.resolve({ data: [
          { id: 1, part_number: '1994-10', name: '1994 TOOL A-Bracket', part_type: 'purchased', item_category: 'tool', parent_part_id: null },
          { id: 2, part_number: '1994-1', name: '1994 TOOL Handle', part_type: 'purchased', item_category: 'tool', parent_part_id: null },
          { id: 3, part_number: '1994-2', name: '1994 - TOOL Latch', part_type: 'purchased', item_category: 'tool', parent_part_id: null },
          { id: 4, part_number: '1994-100', name: 'Top', part_type: 'internal_mfg', item_category: 'article', parent_part_id: null },
        ] })
      return Promise.resolve({ data: [] })
    })
  })
  afterEach(cleanup)

  const mount = () => render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter initialEntries={['/projects/2']}>
        <Routes><Route path="/projects/:projectId" element={<ProjectDetailPage />} /></Routes>
      </MemoryRouter>
    </QueryClientProvider>)

  it('sorts numerically, drops the project code from names, and counts the filtered rows', async () => {
    mount()
    expect(await screen.findByText('Items (4)')).toBeTruthy()
    fireEvent.click(screen.getByText(/Tool/))
    expect(await screen.findByText('Items (3 of 4)')).toBeTruthy()
    const numbers = screen.getAllByText(/^1994-\d+$/).map((el) => el.textContent)
    expect(numbers).toEqual(['1994-1', '1994-2', '1994-10'])
    expect(screen.getByText('TOOL Handle')).toBeTruthy()
    expect(screen.getByText('TOOL Latch')).toBeTruthy()
    expect(screen.queryByText('1994 TOOL Handle')).toBeNull()
  })
})

describe('ProjectDetailPage painted filter', () => {
  const paint = {
    id: 7, name: 'Atlas Black', paint_type: 'basecoat', colour_code: 'RAL 9005',
    colour_name: 'Black', colour_hex: '#111111', supplier_id: null, supplier_text: null,
    spec_reference: null, notes: null, is_active: true,
  }

  beforeEach(() => {
    clientMocks.get.mockReset()
    clientMocks.get.mockImplementation((url: string) => {
      if (url === '/v1/plants/projects')
        return Promise.resolve({ data: [{ id: 2, name: 'Atlas', code: '1994', status: 'active' }] })
      if (url === '/v1/parts/project/2')
        return Promise.resolve({ data: [
          { id: 4, part_number: '1994-100', name: 'Top', part_type: 'internal_mfg', item_category: 'article', parent_part_id: null },
          { id: 5, part_number: '1994-200', name: 'Bracket', part_type: 'internal_mfg', item_category: 'article', parent_part_id: null },
        ] })
      if (url === '/v1/parts/project/2/paint-overview')
        return Promise.resolve({ data: [
          { part_id: 5, part_number: '1994-200', name: 'Bracket', process: null,
            layers: [{ layer_order: 1, area: null, notes: null, paint }] },
        ] })
      return Promise.resolve({ data: [] })
    })
  })
  afterEach(cleanup)

  const mount = () => render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter initialEntries={['/projects/2']}>
        <Routes><Route path="/projects/:projectId" element={<ProjectDetailPage />} /></Routes>
      </MemoryRouter>
    </QueryClientProvider>)

  it('filters the tree down to the painted parts and marks them with a swatch', async () => {
    mount()
    expect(await screen.findByText('🎨 Painted (1)')).toBeTruthy()
    expect(await screen.findByTestId('paint-swatch-5')).toBeTruthy()
    expect(screen.queryByTestId('paint-swatch-4')).toBeNull()

    fireEvent.click(screen.getByText('🎨 Painted (1)'))
    expect(await screen.findByText('Items (1 of 2)')).toBeTruthy()
    expect(screen.getByText('1994-200')).toBeTruthy()
    expect(screen.queryByText('1994-100')).toBeNull()
  })
})
