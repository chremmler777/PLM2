import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import StartChangeModal, { composeTitle } from './StartChangeModal'

const clientMocks = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }))
vi.mock('../../api/client', () => ({ default: clientMocks, API_BASE_URL: '' }))
vi.mock('../../api/changes', () => ({
  changesApi: {
    create: vi.fn().mockResolvedValue({ id: 42, change_number: 'CR-2026-0042' }),
    addImpactedItem: vi.fn().mockResolvedValue({}),
  },
}))
vi.mock('../../contexts/AuthContext', () => ({
  useAuth: () => ({ userId: 5 }),
}))
const navigate = vi.fn()
vi.mock('react-router-dom', async (orig) => ({
  ...(await orig<typeof import('react-router-dom')>()), useNavigate: () => navigate,
}))
import { changesApi } from '../../api/changes'

function wrap(ui: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}><MemoryRouter>{ui}</MemoryRouter></QueryClientProvider>)
}

describe('StartChangeModal', () => {
  beforeEach(() => {
    navigate.mockClear()
    vi.mocked(changesApi.create).mockClear()
    vi.mocked(changesApi.addImpactedItem).mockClear()
    clientMocks.get.mockImplementation((url: string) => {
      if (url.includes('/plants/projects'))
        return Promise.resolve({ data: [{ id: 1, code: '1864', name: 'VW426 Atlas' }] })
      if (url.includes('/parts/project/'))
        return Promise.resolve({ data: [
          { id: 4, part_number: '20-3450-001-0', name: 'Clip', item_category: 'article' },
          { id: 9, part_number: '3450', name: 'Tool 3450', item_category: 'tool' },
        ] })
      return Promise.resolve({ data: [] })
    })
  })
  afterEach(cleanup)

  it('starts a physical-part change and creates change + lead item', async () => {
    wrap(<StartChangeModal open onClose={() => {}} prefill={{
      projectId: 1,
      part: { id: 4, part_number: '20-3450-001-0', name: 'Clip', item_category: 'article' },
    }} />)
    await screen.findByText('20-3450-001-0 - Clip')
    // Only physical-part changes are enabled today; the type picker sits below project.
    expect((screen.getByLabelText(/Change type/) as HTMLSelectElement).value).toBe('physical_part')
    fireEvent.change(screen.getByLabelText(/Short description/), { target: { value: 'Rattle at clip' } })
    fireEvent.click(screen.getByRole('radio', { name: /^Internal change/ }))
    fireEvent.click(screen.getByRole('button', { name: /Create change/ }))
    await waitFor(() => expect(changesApi.create).toHaveBeenCalledWith(
      expect.objectContaining({ project_id: 1, change_type: 'physical_part', lead_id: 5, customer_relevant: false })))
    await waitFor(() => expect(changesApi.addImpactedItem).toHaveBeenCalledWith(
      42, { part_id: 4, is_lead: true }))
    expect(navigate).toHaveBeenCalledWith('/changes/42')
  })

  it('sends customer_relevant: true when the Yes option is picked', async () => {
    wrap(<StartChangeModal open onClose={() => {}} prefill={{
      projectId: 1,
      part: { id: 9, part_number: '3450', name: 'Tool 3450', item_category: 'tool' },
    }} />)
    await screen.findByText('3450 - Tool 3450')
    fireEvent.change(screen.getByLabelText(/Short description/), { target: { value: 'Customer requested change' } })
    fireEvent.click(screen.getByRole('radio', { name: /^Customer change/ }))
    fireEvent.click(screen.getByRole('button', { name: /Create change/ }))
    await waitFor(() => expect(changesApi.create).toHaveBeenCalledWith(
      expect.objectContaining({ customer_relevant: true })))
  })

  it('disables Create and lists what is missing until every required field is filled', async () => {
    wrap(<StartChangeModal open onClose={() => {}} prefill={{ projectId: 1 }} />)
    expect(screen.getByRole('button', { name: /Create change/ })).toHaveProperty('disabled', true)
    expect(screen.getByText(/affected item/)).toBeDefined()
    expect(screen.getByText(/reason/)).toBeDefined()
    expect(screen.getByText(/cost carrier/)).toBeDefined()
  })

  it('shows the locked project number-first instead of a raw id when prefilled', async () => {
    wrap(<StartChangeModal open onClose={() => {}} prefill={{ projectId: 1 }} />)
    expect(await screen.findByText('1864 · VW426 Atlas')).toBeTruthy()
    expect(screen.queryByText('#1')).toBeNull()
  })

  it('takes several affected items on one request, first picked is the lead', async () => {
    clientMocks.get.mockImplementation((url: string) => {
      if (url.includes('/plants/projects'))
        return Promise.resolve({ data: [{ id: 1, code: '1864', name: 'VW426 Atlas' }] })
      if (url.includes('/parts/project/'))
        return Promise.resolve({ data: [
          { id: 4, part_number: '20-3457-001-0', name: 'Bracket LH', item_category: 'article' },
          { id: 5, part_number: '20-3457-002-0', name: 'Bracket RH', item_category: 'article' },
          { id: 6, part_number: '20-3457-003-0', name: 'Cover', item_category: 'article' },
        ] })
      return Promise.resolve({ data: [] })
    })
    wrap(<StartChangeModal open onClose={() => {}} prefill={{ projectId: 1 }} />)
    // All three parts of tool 3457 ride on one change request.
    fireEvent.click(await screen.findByText('20-3457-001-0'))
    fireEvent.click(await screen.findByText('20-3457-002-0'))
    fireEvent.click(await screen.findByText('20-3457-003-0'))
    expect(screen.getByText(/3 selected/)).toBeTruthy()
    fireEvent.change(screen.getByLabelText(/Short description/), { target: { value: 'Warpage' } })
    fireEvent.click(screen.getByRole('radio', { name: /^Internal change/ }))
    fireEvent.click(screen.getByRole('button', { name: /Create change/ }))
    // One change, three impacted items, exactly one of them flagged lead.
    await waitFor(() => expect(changesApi.create).toHaveBeenCalledTimes(1))
    await waitFor(() => expect(changesApi.addImpactedItem).toHaveBeenCalledTimes(3))
    expect(vi.mocked(changesApi.addImpactedItem).mock.calls.map((c) => c[1])).toEqual([
      { part_id: 4, is_lead: true },
      { part_id: 5, is_lead: false },
      { part_id: 6, is_lead: false },
    ])
  })

  it('names the change from project, customer number and lead item', async () => {
    clientMocks.get.mockImplementation((url: string) => {
      if (url.includes('/plants/projects'))
        return Promise.resolve({ data: [{ id: 1, code: '1864', name: 'VW426 Atlas' }] })
      if (url.includes('/parts/project/'))
        return Promise.resolve({ data: [
          { id: 4, part_number: '20-3454-001-0', customer_part_number: '3CR.807.425',
            name: 'RR Cladding (Basis)', item_category: 'article' },
          { id: 5, part_number: '20-3455-001-0', customer_part_number: '3CR.807.425.B',
            name: 'RR Cladding (Peak)', item_category: 'article' },
        ] })
      return Promise.resolve({ data: [] })
    })
    wrap(<StartChangeModal open onClose={() => {}} prefill={{ projectId: 1 }} />)
    fireEvent.click(await screen.findByText('20-3454-001-0'))
    // The name follows the DMS file-name scheme, and there is no field to type it in.
    expect(screen.getByText('20-3454-001-0 - 3CR.807.425 - RR Cladding (Basis)')).toBeTruthy()
    expect(screen.queryByRole('textbox', { name: /^Title/ })).toBeNull()
    // A second item rides along and is counted, not spelled out.
    fireEvent.click(await screen.findByText('20-3455-001-0'))
    expect(screen.getByText('20-3454-001-0 +1 - 3CR.807.425 - RR Cladding (Basis)')).toBeTruthy()
    fireEvent.change(screen.getByLabelText(/Short description/), { target: { value: 'Warpage' } })
    fireEvent.click(screen.getByRole('radio', { name: /^Internal change/ }))
    fireEvent.click(screen.getByRole('button', { name: /Create change/ }))
    await waitFor(() => expect(changesApi.create).toHaveBeenCalledWith(expect.objectContaining({
      title: '20-3454-001-0 +1 - 3CR.807.425 - RR Cladding (Basis)',
    })))
  })

  it('falls back to our own number when the lead item has no customer number', () => {
    expect(composeTitle([
      { id: 1, part_number: '3457', name: 'PDC Brackets', item_category: 'tool' },
    ])).toBe('3457 - PDC Brackets')
    // Nothing to name it after yet.
    expect(composeTitle([])).toBe('')
    expect(composeTitle([])).toBe('')
  })

  it('holds the short description to one line and counts it down', async () => {
    wrap(<StartChangeModal open onClose={() => {}} prefill={{
      projectId: 1,
      part: { id: 4, part_number: '20-3450-001-0', name: 'Clip', item_category: 'article' },
    }} />)
    await screen.findByText('20-3450-001-0 - Clip')
    const reason = screen.getByLabelText(/Short description/) as HTMLInputElement
    expect(reason.maxLength).toBe(100)
    fireEvent.change(reason, { target: { value: 'x'.repeat(140) } })
    expect(reason.value).toHaveLength(100)
    expect(screen.getByText('100/100')).toBeTruthy()
    fireEvent.click(screen.getByRole('radio', { name: /^Internal change/ }))
    fireEvent.click(screen.getByRole('button', { name: /Create change/ }))
    await waitFor(() => expect(changesApi.create).toHaveBeenCalledWith(
      expect.objectContaining({ reason: 'x'.repeat(100) })))
  })

  it('promotes another picked item to lead', async () => {
    clientMocks.get.mockImplementation((url: string) => {
      if (url.includes('/plants/projects'))
        return Promise.resolve({ data: [{ id: 1, code: '1864', name: 'VW426 Atlas' }] })
      if (url.includes('/parts/project/'))
        return Promise.resolve({ data: [
          { id: 4, part_number: '20-3450-001-0', name: 'Clip', item_category: 'article' },
          { id: 9, part_number: '20-3451-001-0', name: 'Cover LH', item_category: 'article' },
        ] })
      return Promise.resolve({ data: [] })
    })
    wrap(<StartChangeModal open onClose={() => {}} prefill={{
      projectId: 1,
      part: { id: 4, part_number: '20-3450-001-0', name: 'Clip', item_category: 'article' },
    }} />)
    fireEvent.click(await screen.findByText('20-3451-001-0'))
    fireEvent.click(screen.getByRole('button', { name: /Make lead item: 20-3451-001-0/ }))
    fireEvent.change(screen.getByLabelText(/Short description/), { target: { value: 'Because' } })
    fireEvent.click(screen.getByRole('radio', { name: /^Internal change/ }))
    fireEvent.click(screen.getByRole('button', { name: /Create change/ }))
    await waitFor(() => expect(changesApi.addImpactedItem).toHaveBeenCalledTimes(2))
    expect(vi.mocked(changesApi.addImpactedItem).mock.calls.map((c) => c[1])).toEqual([
      { part_id: 9, is_lead: true },
      { part_id: 4, is_lead: false },
    ])
  })

  it('drops a picked item back out of the selection', async () => {
    wrap(<StartChangeModal open onClose={() => {}} prefill={{
      projectId: 1,
      part: { id: 4, part_number: '20-3450-001-0', name: 'Clip', item_category: 'article' },
    }} />)
    await screen.findByText('20-3450-001-0 - Clip')
    fireEvent.change(screen.getByLabelText(/Short description/), { target: { value: 'Because' } })
    fireEvent.click(screen.getByRole('radio', { name: /^Internal change/ }))
    expect(screen.getByRole('button', { name: /Create change/ })).toHaveProperty('disabled', false)
    fireEvent.click(screen.getByRole('button', { name: /Remove selected item: 20-3450-001-0/ }))
    expect(screen.getByRole('button', { name: /Create change/ })).toHaveProperty('disabled', true)
    expect(screen.getByText(/affected item/)).toBeDefined()
  })

  it('offers no tools or equipment at all under a physical-part change', async () => {
    wrap(<StartChangeModal open onClose={() => {}} prefill={{ projectId: 1 }} />)
    expect(await screen.findByText('20-3450-001-0')).toBeTruthy()
    // The tool 3450 exists in the project but a physical-part change never
    // targets it — no row, and not even a collapsed group to expand.
    expect(screen.queryByText('3450')).toBeNull()
    expect(screen.queryByText(/Tools & equipment/)).toBeNull()
  })

  it('shows the customer number alongside our own and searches on it', async () => {
    clientMocks.get.mockImplementation((url: string) => {
      if (url.includes('/plants/projects'))
        return Promise.resolve({ data: [{ id: 1, code: '1864', name: 'VW426 Atlas' }] })
      if (url.includes('/parts/project/'))
        return Promise.resolve({ data: [
          { id: 4, part_number: '20-3454-001-0', customer_part_number: '3CR.807.425',
            name: 'RR Cladding (Basis)', item_category: 'article' },
          { id: 5, part_number: '20-3456-001-0', customer_part_number: '3CS.807.425',
            name: 'RR Undertray (Cross)', item_category: 'article' },
        ] })
      return Promise.resolve({ data: [] })
    })
    wrap(<StartChangeModal open onClose={() => {}} prefill={{ projectId: 1 }} />)
    expect(await screen.findByText('3CR.807.425')).toBeTruthy()
    // Searching the customer's number finds the part — that is the number the
    // customer quotes when they raise the change.
    fireEvent.change(screen.getByPlaceholderText(/Search item/), { target: { value: '3CS.807' } })
    expect(await screen.findByText('3CS.807.425')).toBeTruthy()
    expect(screen.queryByText('3CR.807.425')).toBeNull()
    // It stays visible once picked, so the selection reads in the customer's terms.
    fireEvent.click(screen.getByText('20-3456-001-0'))
    expect(screen.getByText('3CS.807.425')).toBeTruthy()
  })

  it('requires picking an item when not prefilled', async () => {
    wrap(<StartChangeModal open onClose={() => {}} prefill={{ projectId: 1 }} />)
    fireEvent.change(screen.getByLabelText(/Short description/), { target: { value: 'Because' } })
    fireEvent.click(screen.getByRole('radio', { name: /^Internal change/ }))
    expect(screen.getByRole('button', { name: /Create change/ })).toHaveProperty('disabled', true)
    fireEvent.change(screen.getByPlaceholderText(/Search item/), { target: { value: 'clip' } })
    fireEvent.click(await screen.findByText(/20-3450-001-0/))
    expect(screen.getByRole('button', { name: /Create change/ })).toHaveProperty('disabled', false)
  })

  it('hides non-physical articles (packaging/material prefixes) under a physical-part change', async () => {
    clientMocks.get.mockImplementation((url: string) => {
      if (url.includes('/plants/projects'))
        return Promise.resolve({ data: [{ id: 1, code: '1864', name: 'VW426 Atlas' }] })
      if (url.includes('/parts/project/'))
        return Promise.resolve({ data: [
          { id: 4, part_number: '20-3450-001-0', name: 'Clip', item_category: 'article' },
          { id: 7, part_number: '40-9001-000-0', name: 'Box', item_category: 'article' },
          { id: 8, part_number: '65-1000-000-0', name: 'Resin', item_category: 'article' },
        ] })
      return Promise.resolve({ data: [] })
    })
    wrap(<StartChangeModal open onClose={() => {}} prefill={{ projectId: 1 }} />)
    // Physical part (20-) is offered; packaging (40-) and material (65-) are not.
    expect(await screen.findByText('20-3450-001-0')).toBeTruthy()
    expect(screen.queryByText('40-9001-000-0')).toBeNull()
    expect(screen.queryByText('65-1000-000-0')).toBeNull()
    // The two hidden ones are counted, not silently dropped.
    expect(screen.getByText(/2 non-physical items hidden/)).toBeTruthy()
  })

  it('shows the API refusal (403 detail) in the modal instead of swallowing it', async () => {
    vi.mocked(changesApi.create).mockRejectedValueOnce({
      response: { status: 403, data: { detail: 'Only Sales may start a change' } },
    })
    wrap(<StartChangeModal open onClose={() => {}} prefill={{
      projectId: 1,
      part: { id: 4, part_number: '20-3450-001-0', name: 'Clip', item_category: 'article' },
    }} />)
    await screen.findByText('20-3450-001-0 - Clip')
    fireEvent.change(screen.getByLabelText(/Short description/), { target: { value: 'Rattle' } })
    fireEvent.click(screen.getByRole('radio', { name: /^Internal change/ }))
    fireEvent.click(screen.getByRole('button', { name: /Create change/ }))
    const alert = await screen.findByTestId('start-error')
    expect(alert.textContent).toContain('Only Sales may start a change')
    expect(navigate).not.toHaveBeenCalled()
  })
})
