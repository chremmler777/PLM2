import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, cleanup, fireEvent, waitFor } from '@testing-library/react'
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

const part = (over: Record<string, unknown> = {}) => ({
  id: 5, part_number: '1994-100', customer_part_number: '3CR.807.425', name: 'Top',
  part_type: 'internal_mfg', data_classification: 'confidential', item_category: 'article',
  project_id: 2, active_revision_id: null, lifecycle_phase: 'rfq', revisions: [], ...over,
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

describe('PartDetail customer part number', () => {
  beforeEach(() => {
    clientMocks.get.mockReset()
    clientMocks.put.mockReset()
    clientMocks.get.mockImplementation((url: string) => {
      if (url === '/v1/parts/5') return Promise.resolve({ data: part() })
      if (url === '/v1/parts/5/paint') return Promise.resolve({ data: { paint_required: false, process: null, notes: null, layers: [] } })
      return Promise.resolve({ data: [] })
    })
    clientMocks.put.mockResolvedValue({ data: part({ customer_part_number: '3CR.807.425.B' }) })
  })
  afterEach(cleanup)

  it('saves an edited customer part number', async () => {
    renderPart()
    fireEvent.click(await screen.findByTestId('edit-customer-part-number'))
    fireEvent.change(screen.getByTestId('customer-part-number-input'), { target: { value: ' 3CR.807.425.B ' } })
    fireEvent.click(screen.getByTestId('save-customer-part-number'))

    await waitFor(() => expect(clientMocks.put).toHaveBeenCalled())
    expect(clientMocks.put.mock.calls[0][0]).toBe('/v1/parts/5')
    expect(clientMocks.put.mock.calls[0][1]).toEqual({ customer_part_number: '3CR.807.425.B' })
  })

  it('clears the customer part number when the field is emptied', async () => {
    renderPart()
    fireEvent.click(await screen.findByTestId('edit-customer-part-number'))
    fireEvent.change(screen.getByTestId('customer-part-number-input'), { target: { value: '' } })
    fireEvent.click(screen.getByTestId('save-customer-part-number'))

    await waitFor(() => expect(clientMocks.put).toHaveBeenCalled())
    expect(clientMocks.put.mock.calls[0][1]).toEqual({ customer_part_number: null })
  })

  it('offers the field on a part that has no customer part number yet', async () => {
    clientMocks.get.mockImplementation((url: string) => {
      if (url === '/v1/parts/5') return Promise.resolve({ data: part({ customer_part_number: null }) })
      if (url === '/v1/parts/5/paint') return Promise.resolve({ data: { paint_required: false, process: null, notes: null, layers: [] } })
      return Promise.resolve({ data: [] })
    })
    renderPart()
    expect((await screen.findByTestId('edit-customer-part-number')).textContent).toContain('+ customer part number')
  })
})

describe('PartDetail tier 1 part number', () => {
  beforeEach(() => {
    clientMocks.get.mockReset()
    clientMocks.put.mockReset()
    clientMocks.get.mockImplementation((url: string) => {
      if (url === '/v1/parts/5') return Promise.resolve({ data: part({ tier1_part_number: null }) })
      if (url === '/v1/parts/5/paint') return Promise.resolve({ data: { paint_required: false, process: null, notes: null, layers: [] } })
      return Promise.resolve({ data: [] })
    })
    clientMocks.put.mockResolvedValue({ data: part({ tier1_part_number: 'S00H54-110' }) })
  })
  afterEach(cleanup)

  it('saves a tier 1 part number without touching the customer number', async () => {
    renderPart()
    expect((await screen.findByTestId('edit-tier1-part-number')).textContent).toContain('+ tier 1 part number')
    fireEvent.click(screen.getByTestId('edit-tier1-part-number'))
    fireEvent.change(screen.getByTestId('tier1-part-number-input'), { target: { value: ' S00H54-110 ' } })
    fireEvent.click(screen.getByTestId('save-tier1-part-number'))

    await waitFor(() => expect(clientMocks.put).toHaveBeenCalled())
    expect(clientMocks.put.mock.calls[0][0]).toBe('/v1/parts/5')
    expect(clientMocks.put.mock.calls[0][1]).toEqual({ tier1_part_number: 'S00H54-110' })
  })

  it('shows the tier 1 number labelled next to the customer number', async () => {
    clientMocks.get.mockImplementation((url: string) => {
      if (url === '/v1/parts/5') return Promise.resolve({ data: part({ tier1_part_number: 'S00H54-110' }) })
      if (url === '/v1/parts/5/paint') return Promise.resolve({ data: { paint_required: false, process: null, notes: null, layers: [] } })
      return Promise.resolve({ data: [] })
    })
    renderPart()
    expect((await screen.findByTestId('edit-tier1-part-number')).textContent).toContain('Tier 1 S00H54-110')
    expect(screen.getByTestId('edit-customer-part-number').textContent).toContain('3CR.807.425')
  })
})
