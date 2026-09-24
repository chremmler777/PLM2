import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, cleanup, waitFor, fireEvent } from '@testing-library/react'
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
vi.mock('../components/dfm/DfmArchive', () => stub('dfm-archive'))

const article = { id: 5, part_number: '20-1994-005-0', customer_part_number: '206.887.233', tier1_part_number: 'S00H54-110',
  name: 'ISOFIX Cover', part_type: 'internal_mfg', data_classification: 'confidential', item_category: 'article',
  project_id: 2, active_revision_id: null, lifecycle_phase: 'rfq', revisions: [],
  material_source: 'new', material_new_text: 'PA6-GF15 acc. VW 50125', colour_code: 'NM0', grain: null }
const tool = { ...article, id: 9, part_number: '199403', item_category: 'tool', tool_cavities: 4, material_source: null }
const note = (part_id: number, field_key: string, flag_status: string | null, comment_count = 0) => ({
  id: part_id * 100, part_id, field_key, flag_status, flag_set_by: null, flag_set_by_name: null, flag_set_at: null,
  created_at: null, comment_count, last_comment: null })

function renderAt(url: string) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[url]}>
        <Routes><Route path="/parts/:partId" element={<PartDetail />} /></Routes>
      </MemoryRouter>
    </QueryClientProvider>)
}

describe('PartDetail field notes', () => {
  beforeEach(() => {
    Element.prototype.scrollIntoView = vi.fn()
    clientMocks.get.mockReset()
    clientMocks.get.mockImplementation((url: string) => {
      if (url === '/v1/parts/5') return Promise.resolve({ data: article })
      if (url === '/v1/parts/9') return Promise.resolve({ data: tool })
      if (url === '/v1/parts/5/field-notes') return Promise.resolve({ data: [note(5, 'part.material', 'rejected', 2), note(5, 'paint.colour', 'confirmed')] })
      if (url === '/v1/parts/9/field-notes') return Promise.resolve({ data: [note(9, 'tool.cavities', 'open', 1)] })
      if (url === '/v1/parts/5/paint') return Promise.resolve({ data: { paint_required: false, process: null, notes: null, layers: [] } })
      return Promise.resolve({ data: [] })
    })
  })
  afterEach(cleanup)

  it('shows worksheet flags next to the article and paint fields', async () => {
    renderAt('/parts/5')
    await waitFor(() => expect(screen.getByTestId('note-dot-part.material').className).toContain('bg-red-500'))
    expect(screen.getByTestId('note-count-part.material').textContent).toBe('2')
    // the paint card renders after its own query
    await waitFor(() => expect(screen.getByTestId('note-dot-paint.colour').className).toContain('bg-emerald-500'))
    for (const key of ['part.part_number', 'part.customer_part_number', 'part.tier1_part_number', 'part.name',
      'part.part_type', 'part.lifecycle_phase', 'revision.level', 'paint.painted']) {
      expect(screen.getByTestId(`note-marker-${key}`)).toBeTruthy()
    }
  })

  it('shows colour code and grain on the article with markers, editable inline', async () => {
    clientMocks.put.mockReset()
    clientMocks.put.mockResolvedValue({ data: {} })
    renderAt('/parts/5?focus=part.grain')
    expect((await screen.findByTestId('edit-colour_code')).textContent).toBe('NM0')
    expect(screen.getByTestId('edit-grain').textContent).toBe('+ grain')
    expect(screen.getByTestId('note-marker-part.colour_code')).toBeTruthy()
    expect(screen.getByTestId('note-marker-part.grain')).toBeTruthy()
    expect(document.querySelector('[data-field-key="part.colour_code"]')).toBeTruthy()
    await waitFor(() => expect(document.querySelector('[data-field-key="part.grain"]')!.className).toContain('ring-2'))
    fireEvent.click(screen.getByTestId('edit-grain'))
    fireEvent.change(screen.getByTestId('grain-input'), { target: { value: ' KF8 ' } })
    fireEvent.keyDown(screen.getByTestId('grain-input'), { key: 'Enter' })
    await waitFor(() => expect(clientMocks.put).toHaveBeenCalledWith('/v1/parts/5', { grain: 'KF8' }))
    fireEvent.click(screen.getByTestId('edit-colour_code'))
    fireEvent.change(screen.getByTestId('colour_code-input'), { target: { value: '' } })
    fireEvent.click(screen.getByTestId('save-colour_code'))
    await waitFor(() => expect(clientMocks.put).toHaveBeenCalledWith('/v1/parts/5', { colour_code: null }))
  })

  it('highlights the field named by ?focus=', async () => {
    renderAt('/parts/5?focus=part.material')
    await waitFor(() => expect(document.querySelector('[data-field-key="part.material"]')!.className).toContain('ring-2'))
  })

  it('shows the tool flags on the tool page', async () => {
    renderAt('/parts/9?focus=tool.cavities')
    await waitFor(() => expect(screen.getByTestId('note-dot-tool.cavities').className).toContain('bg-yellow-400'))
    for (const key of ['tool.number', 'tool.tonnage_class', 'tool.cycle_time_s', 'tool.toolmaker', 'dfm.status']) {
      expect(screen.getByTestId(`note-marker-${key}`)).toBeTruthy()
    }
    await waitFor(() => expect(document.querySelector('[data-field-key="tool.cavities"]')!.className).toContain('ring-2'))
  })
})
