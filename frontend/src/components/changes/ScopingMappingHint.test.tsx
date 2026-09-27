import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, cleanup } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { ScopingMappingHint } from './ScopingMappingHint'
import type { Assessment, ChangeMeeting } from '../../types/change'
import { changesApi } from '../../api/changes'

vi.mock('../../api/changes', () => ({
  changesApi: { listMeetings: vi.fn() },
}))

const departments = [
  { id: 1, name: 'Development' },
  { id: 2, name: 'Sales' },
  { id: 3, name: 'Tool Engineer' },
]

const assessment = (department_id: number): Assessment => ({
  id: department_id, department_id, verdict: 'pending', stage_order: 1,
  rasic_letter: 'R', status: 'active', owner_id: null, owner_name: null,
  accepted_at: null, due_date: null, overdue: false,
})

const meeting = (over: Partial<ChangeMeeting> = {}): ChangeMeeting => ({
  id: 1, change_id: 7, meeting_date: '2026-07-01T00:00:00', channel: 'meeting', participants: [],
  notes: null, decision: 'proceed', selected_department_ids: [1, 2, 3],
  created_by: 1, created_at: '2026-07-01T00:00:00', decided_by: 1, decided_at: '2026-07-01T00:00:00',
  ...over,
})

const wrap = (ui: React.ReactElement) => (
  <QueryClientProvider client={new QueryClient()}>{ui}</QueryClientProvider>
)

describe('ScopingMappingHint', () => {
  afterEach(() => {
    cleanup()
    vi.clearAllMocks()
  })

  it('shows matched departments with a check and unmatched ones with the routing explanation', async () => {
    vi.mocked(changesApi.listMeetings).mockResolvedValue([meeting()])
    render(wrap(<ScopingMappingHint changeId={7}
      assessments={[assessment(1), assessment(2)]}
      departments={departments} />))
    expect(await screen.findByText(/From scoping:/)).toBeDefined()
    expect(screen.getByTestId('scoping-mapped-1').textContent).toBe('Development R(assesses)')
    expect(screen.getByTestId('scoping-mapped-2').textContent).toBe('Sales R(assesses)')
    expect(screen.getByText(/Tool Engineer has no blocking role in the routing template, so no assessment task/)).toBeDefined()
  })

  it('says a department the room marked I is informed, not missing from the routing', async () => {
    vi.mocked(changesApi.listMeetings).mockResolvedValue([meeting({
      selected_department_ids: [1, 3], department_rasic: { '1': 'R', '3': 'I' },
    })])
    render(wrap(<ScopingMappingHint changeId={7}
      assessments={[assessment(1)]} departments={departments} />))
    expect(await screen.findByText(/Tool Engineer: Informed \(notified only\)/)).toBeDefined()
    expect(screen.queryByText(/no blocking role/)).toBeNull()
  })

  it('reads the routed row\'s letter next to the name, over the room\'s call', async () => {
    vi.mocked(changesApi.listMeetings).mockResolvedValue([meeting({
      selected_department_ids: [1, 3], department_rasic: { '1': 'R', '3': 'C' },
    })])
    render(wrap(<ScopingMappingHint changeId={7}
      assessments={[assessment(1), assessment(3)]} departments={departments} />))
    expect((await screen.findByTestId('scoping-mapped-1')).textContent).toBe('Development R(assesses)')
    expect(screen.getByTestId('scoping-mapped-3').textContent).toBe('Tool Engineer R(assesses)')
  })

  it('reads the letter an approved decline moved, not the room\'s original R', async () => {
    // Manufacturing declined: the routing change reletters its row to C.
    vi.mocked(changesApi.listMeetings).mockResolvedValue([meeting({
      selected_department_ids: [1, 3], department_rasic: { '1': 'R', '3': 'R' },
    })])
    render(wrap(<ScopingMappingHint changeId={7}
      assessments={[assessment(1), { ...assessment(3), rasic_letter: 'C' }]} departments={departments} />))
    expect((await screen.findByTestId('scoping-mapped-3')).textContent).toBe('Tool Engineer C(no answer needed)')
    expect(screen.getByTestId('scoping-mapped-1').textContent).toBe('Development R(assesses)')
  })

  it('renders nothing when there is no proceed meeting', () => {
    vi.mocked(changesApi.listMeetings).mockResolvedValue([meeting({ decision: null })])
    render(wrap(<ScopingMappingHint changeId={7} assessments={[]} departments={departments} />))
    expect(screen.queryByText(/From scoping:/)).toBeNull()
  })
})
