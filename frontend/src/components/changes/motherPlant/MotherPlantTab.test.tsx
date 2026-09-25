import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import MotherPlantTab from './MotherPlantTab'
import type { MotherPlantState } from '../../../api/motherPlant'
import type { ChangeRequest } from '../../../types/change'

const api = vi.hoisted(() => ({
  get: vi.fn(), sendInfo: vi.fn(), acknowledge: vi.fn(), inform: vi.fn(),
}))
vi.mock('../../../api/motherPlant', async (orig) => ({
  ...(await orig<typeof import('../../../api/motherPlant')>()), motherPlantApi: api,
}))
vi.mock('../../../api/changes', () => ({ changesApi: { uploadAttachment: vi.fn().mockResolvedValue({}) } }))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

const departments = [
  { id: 2, name: 'Development' }, { id: 4, name: 'Tool Engineer' },
  { id: 6, name: 'Quality' }, { id: 8, name: 'Old dept', is_active: false },
]
const state = (over: Partial<MotherPlantState> = {}): MotherPlantState => ({
  change_id: 9, mother_plant_name: 'KTX Weissenburg (WUG)', mother_plant_ref: 'WUG-4711',
  mother_plant_sop: '2026-12-01', mother_plants: ['KTX Weissenburg (WUG)', 'KTX Solingen'],
  default_department_ids: [2, 4], receipts: [], open_count: 0,
  timing_attachment: null, documents: [], informed_at: null, informed_by_name: null,
  can_send: true, can_inform: false, my_open_receipt_ids: [], ...over,
})
const change = { id: 9, status: 'scoping', release_due_date: null, origin: 'mother_plant' } as unknown as ChangeRequest

function wrap() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}>
    <MotherPlantTab change={change} departments={departments} />
  </QueryClientProvider>)
}

describe('MotherPlantTab', () => {
  beforeEach(() => { Object.values(api).forEach((f) => f.mockReset()) })
  afterEach(cleanup)

  it('shows what the mother plant sent and preselects the routing departments', async () => {
    api.get.mockResolvedValue(state({ timing_attachment: { id: 3, filename: 'wug.xml', created_at: '2026-09-01T00:00:00' } }))
    wrap()
    await screen.findByTestId('mother-plant-tab')
    expect(screen.getByText('KTX Weissenburg (WUG)')).toBeDefined()
    expect(screen.getByText('WUG-4711')).toBeDefined()
    expect(screen.getByTestId('mother-plant-sop-date').textContent).toContain('01.12.2026')
    expect(screen.getByTestId('mother-plant-timing-file').textContent).toBe('wug.xml')
    const box = (name: string) => screen.getByRole('checkbox', { name }) as HTMLInputElement
    await waitFor(() => expect(box('Development').checked).toBe(true))
    expect(box('Tool Engineer').checked).toBe(true)
    expect(box('Quality').checked).toBe(false)
    expect(screen.queryByRole('checkbox', { name: 'Old dept' })).toBeNull()
  })

  it('sends the information to the picked departments with the message', async () => {
    api.get.mockResolvedValue(state())
    api.sendInfo.mockResolvedValue(state({ receipts: [], can_send: true }))
    wrap()
    await screen.findByTestId('mother-plant-send')
    await waitFor(() => expect((screen.getByRole('checkbox', { name: 'Development' }) as HTMLInputElement).checked).toBe(true))
    fireEvent.click(screen.getByRole('checkbox', { name: 'Quality' }))
    fireEvent.change(screen.getByLabelText('Message to the team'), { target: { value: 'New insert' } })
    fireEvent.click(screen.getByTestId('mother-plant-send-button'))
    await waitFor(() => expect(api.sendInfo).toHaveBeenCalled())
    const [cid, body] = api.sendInfo.mock.calls[0]
    expect(cid).toBe(9)
    expect([...body.department_ids].sort()).toEqual([2, 4, 6])
    expect(body.message).toBe('New insert')
  })

  it('lists receipts; my department confirms "Read and understood" with a note', async () => {
    const receipt = (id: number, dept: number, name: string, ack = false) => ({
      id, department_id: dept, department_name: name, sent_by: 1, sent_by_name: 'PM',
      sent_at: '2026-09-02T08:00:00', acknowledged_by: ack ? 3 : null,
      acknowledged_by_name: ack ? 'Dora Dev' : null, acknowledged_at: ack ? '2026-09-03T09:00:00' : null,
      note: ack ? 'fine' : null,
    })
    api.get.mockResolvedValue(state({
      receipts: [receipt(1, 2, 'Development', true), receipt(2, 4, 'Tool Engineer')],
      open_count: 1, can_send: false, my_open_receipt_ids: [2],
    }))
    api.acknowledge.mockResolvedValue(state())
    wrap()
    await screen.findByTestId('mother-plant-receipts')
    expect(screen.getByTestId('mother-plant-receipt-count').textContent).toBe('1 of 2 read and understood')
    expect(screen.getByTestId('mother-plant-receipt-2').textContent).toContain('Dora Dev')
    expect(screen.queryByTestId('mother-plant-ack-2')).toBeNull()
    fireEvent.change(screen.getByLabelText('Note back from Tool Engineer'), { target: { value: 'we build the insert' } })
    fireEvent.click(screen.getByTestId('mother-plant-ack-4'))
    await waitFor(() => expect(api.acknowledge).toHaveBeenCalledWith(9, 2, 'we build the insert'))
    expect(screen.queryByTestId('mother-plant-send')).toBeNull()
  })

  it('without the right to send, says who sends', async () => {
    api.get.mockResolvedValue(state({ can_send: false }))
    wrap()
    await screen.findByText('Project Management sends the information to the team.')
  })
})
