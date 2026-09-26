/** The "Change from KTX Weissenburg / Solingen" option of the Start change dialog (spec §14). */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import StartChangeModal from '../StartChangeModal'

const clientMocks = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }))
vi.mock('../../../api/client', () => ({ default: clientMocks, API_BASE_URL: '' }))
vi.mock('../../../api/changes', () => ({
  changesApi: {
    create: vi.fn().mockResolvedValue({ id: 42, change_number: 'CR-2026-0042' }),
    addImpactedItem: vi.fn().mockResolvedValue({}),
    uploadAttachment: vi.fn().mockResolvedValue({}),
  },
}))
vi.mock('../../../contexts/AuthContext', () => ({ useAuth: () => ({ userId: 5 }) }))
const navigate = vi.fn()
vi.mock('react-router-dom', async (orig) => ({
  ...(await orig<typeof import('react-router-dom')>()), useNavigate: () => navigate,
}))
import { changesApi } from '../../../api/changes'

let perms: Record<string, unknown> = {}
function wrap() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}><MemoryRouter>
    <StartChangeModal open onClose={() => {}} prefill={{
      projectId: 1, part: { id: 4, part_number: '20-3450-001-0', name: 'Clip', item_category: 'article' },
    }} />
  </MemoryRouter></QueryClientProvider>)
}

describe('StartChangeModal: change from KTX Weissenburg / Solingen', () => {
  beforeEach(() => {
    vi.mocked(changesApi.create).mockClear()
    vi.mocked(changesApi.uploadAttachment).mockClear()
    perms = {
      can_start_change: false, can_start_mother_plant: true,
      mother_plants: ['KTX Weissenburg (WUG)', 'KTX Solingen'], default_mother_plant: 'KTX Weissenburg (WUG)',
    }
    clientMocks.get.mockImplementation((url: string) => {
      if (url.includes('/changes/permissions')) return Promise.resolve({ data: perms })
      if (url.includes('/plants/projects')) return Promise.resolve({ data: [{ id: 1, code: '1864', name: 'VW426 Atlas' }] })
      return Promise.resolve({ data: [] })
    })
  })
  afterEach(cleanup)

  it('asks for plant, reference, SOP (required), documents and their timing, and sends them', async () => {
    wrap()
    await screen.findByText('20-3450-001-0 - Clip')
    fireEvent.change(screen.getByLabelText(/Short description/), { target: { value: 'WUG insert change' } })
    fireEvent.click(await screen.findByRole('radio', { name: /^Change from KTX Weissenburg \/ Solingen/ }))
    const plant = screen.getByLabelText('Plant') as HTMLSelectElement
    expect(plant.value).toBe('KTX Weissenburg (WUG)')
    expect([...plant.options].map((o) => o.value)).toEqual(['KTX Weissenburg (WUG)', 'KTX Solingen'])
    // SOP is required
    const create = screen.getByRole('button', { name: /Create change/ }) as HTMLButtonElement
    expect(create.disabled).toBe(true)
    expect(screen.getByText(/SOP date/, { selector: 'p' })).toBeDefined()
    fireEvent.change(plant, { target: { value: 'KTX Solingen' } })
    fireEvent.change(screen.getByLabelText('Their reference'), { target: { value: 'SOL-17' } })
    const sop = screen.getByLabelText('SOP date')
    fireEvent.change(sop, { target: { value: '01.12.2026' } })
    fireEvent.blur(sop)
    const doc = new File(['pdf'], 'ecr.pdf', { type: 'application/pdf' })
    const xml = new File(['<Project/>'], 'timing.xml', { type: 'application/xml' })
    fireEvent.change(screen.getByLabelText('Their documents'), { target: { files: [doc] } })
    fireEvent.change(screen.getByLabelText(/Their timing/), { target: { files: [xml] } })
    await waitFor(() => expect(create.disabled).toBe(false))
    fireEvent.click(create)
    await waitFor(() => expect(changesApi.create).toHaveBeenCalledWith(expect.objectContaining({
      origin: 'mother_plant', customer_relevant: false, mother_plant_name: 'KTX Solingen',
      mother_plant_ref: 'SOL-17', mother_plant_sop: '2026-12-01',
    })))
    await waitFor(() => expect(changesApi.uploadAttachment).toHaveBeenCalledTimes(2))
    expect(changesApi.uploadAttachment).toHaveBeenCalledWith(42, doc, { kind: 'general' })
    expect(changesApi.uploadAttachment).toHaveBeenCalledWith(42, xml, { kind: 'mother_plant_timing' })
    await waitFor(() => expect(navigate).toHaveBeenCalledWith('/changes/42'))
  })

  it('is a labelled modal that Escape closes', async () => {
    const onClose = vi.fn()
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(<QueryClientProvider client={qc}><MemoryRouter>
      <StartChangeModal open onClose={onClose} prefill={{ projectId: 1 }} />
    </MemoryRouter></QueryClientProvider>)
    const dialog = await screen.findByRole('dialog', { name: /Start change|change/i })
    expect(dialog.getAttribute('aria-modal')).toBe('true')
    fireEvent.keyDown(document, { key: 'Escape' })
    expect(onClose).toHaveBeenCalled()
  })

  it('the SOP date commits when Tab leaves it from the calendar button', async () => {
    wrap()
    await screen.findByText('20-3450-001-0 - Clip')
    fireEvent.change(screen.getByLabelText(/Short description/), { target: { value: 'x' } })
    fireEvent.click(await screen.findByRole('radio', { name: /^Change from KTX Weissenburg \/ Solingen/ }))
    const create = screen.getByRole('button', { name: /Create change/ }) as HTMLButtonElement
    const fields = screen.getByTestId('mother-plant-fields')
    const sop = screen.getByLabelText('SOP date')
    // A two-digit year is not committed while typing, only when the field is left.
    fireEvent.change(sop, { target: { value: '01.12.26' } })
    expect(create.disabled).toBe(true)
    const calBtn = fields.querySelector('button[aria-label="Open calendar"]') as HTMLButtonElement
    fireEvent.blur(sop, { relatedTarget: calBtn })
    fireEvent.blur(calBtn, { relatedTarget: screen.getByLabelText(/Their timing/) })
    await waitFor(() => expect(create.disabled).toBe(false))
    expect((sop as HTMLInputElement).value).toBe('1 Dec 2026')
  })

  it('the customer option still sends a customer change', async () => {
    wrap()
    await screen.findByText('20-3450-001-0 - Clip')
    fireEvent.change(screen.getByLabelText(/Short description/), { target: { value: 'x' } })
    fireEvent.click(await screen.findByRole('radio', { name: /^Change from KTX Weissenburg \/ Solingen/ }))
    fireEvent.click(screen.getByRole('radio', { name: /^Customer change/ }))
    expect(screen.queryByTestId('mother-plant-fields')).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: /Create change/ }))
    await waitFor(() => expect(changesApi.create).toHaveBeenCalledWith(
      expect.objectContaining({ customer_relevant: true })))
    expect(vi.mocked(changesApi.create).mock.calls[0][0]).not.toHaveProperty('origin')
  })

  it('hides the option from users who may not start one and says PM starts it', async () => {
    perms = { can_start_change: true, can_start_mother_plant: false }
    wrap()
    await screen.findByText('20-3450-001-0 - Clip')
    await waitFor(() => expect(screen.queryByRole('radio', { name: /^Change from KTX Weissenburg \/ Solingen/ })).toBeNull())
    expect(screen.getByTestId('mother-plant-pm-only').textContent)
      .toBe('Changes from KTX Weissenburg / Solingen are started by Project Management (PM).')
  })

  it('shows the option, without the hint, to Project Management', async () => {
    wrap()
    await screen.findByText('20-3450-001-0 - Clip')
    expect(await screen.findByRole('radio', { name: /^Change from KTX Weissenburg \/ Solingen/ })).toBeDefined()
    expect(screen.queryByTestId('mother-plant-pm-only')).toBeNull()
  })
})
