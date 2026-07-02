import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import StartChangeModal from './StartChangeModal'

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
    clientMocks.get.mockImplementation((url: string) => {
      if (url.includes('/plants/projects'))
        return Promise.resolve({ data: [{ id: 1, name: 'VW426 Atlas' }] })
      if (url.includes('/parts/project/'))
        return Promise.resolve({ data: [
          { id: 4, part_number: '20-3450-001-0', name: 'Clip', item_category: 'article' },
          { id: 9, part_number: '3450', name: 'Tool 3450', item_category: 'tool' },
        ] })
      return Promise.resolve({ data: [] })
    })
  })
  afterEach(cleanup)

  it('infers tooling type from a tool prefill and creates change + lead item', async () => {
    wrap(<StartChangeModal open onClose={() => {}} prefill={{
      projectId: 1,
      part: { id: 9, part_number: '3450', name: 'Tool 3450', item_category: 'tool' },
    }} />)
    expect((screen.getByLabelText(/Change type/) as HTMLSelectElement).value).toBe('tooling')
    fireEvent.change(screen.getByLabelText(/Title/), { target: { value: 'Fix cavity' } })
    fireEvent.click(screen.getByRole('button', { name: /Create change/ }))
    await waitFor(() => expect(changesApi.create).toHaveBeenCalledWith(
      expect.objectContaining({ project_id: 1, change_type: 'tooling', lead_id: 5 })))
    await waitFor(() => expect(changesApi.addImpactedItem).toHaveBeenCalledWith(
      42, { part_id: 9, is_lead: true }))
    expect(navigate).toHaveBeenCalledWith('/changes/42')
  })

  it('shows the locked project name instead of a raw id when prefilled', async () => {
    wrap(<StartChangeModal open onClose={() => {}} prefill={{ projectId: 1 }} />)
    expect(await screen.findByText('VW426 Atlas')).toBeTruthy()
    expect(screen.queryByText('#1')).toBeNull()
  })

  it('requires picking an item when not prefilled', async () => {
    wrap(<StartChangeModal open onClose={() => {}} prefill={{ projectId: 1 }} />)
    fireEvent.change(screen.getByLabelText(/Title/), { target: { value: 'X' } })
    expect(screen.getByRole('button', { name: /Create change/ })).toHaveProperty('disabled', true)
    fireEvent.change(screen.getByPlaceholderText(/Search item/), { target: { value: 'clip' } })
    fireEvent.click(await screen.findByText(/20-3450-001-0/))
    expect(screen.getByRole('button', { name: /Create change/ })).toHaveProperty('disabled', false)
  })
})
