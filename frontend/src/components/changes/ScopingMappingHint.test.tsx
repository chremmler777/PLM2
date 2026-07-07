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
  { id: 1, name: 'R&D' },
  { id: 2, name: 'Sales' },
  { id: 3, name: 'Tool Engineer' },
]

const assessment = (department_id: number): Assessment => ({
  id: department_id, department_id, verdict: 'pending', stage_order: 1,
  rasic_letter: 'R', status: 'active', owner_id: null, owner_name: null,
  accepted_at: null, due_date: null, overdue: false,
})

const meeting = (over: Partial<ChangeMeeting> = {}): ChangeMeeting => ({
  id: 1, change_id: 7, meeting_date: '2026-07-01T00:00:00', participants: [],
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
    expect(screen.getByText(/R&D ✓/)).toBeDefined()
    expect(screen.getByText(/Sales ✓/)).toBeDefined()
    expect(screen.getByText(/Tool Engineer has no blocking role in the routing template — no assessment task/)).toBeDefined()
  })

  it('renders nothing when there is no proceed meeting', () => {
    vi.mocked(changesApi.listMeetings).mockResolvedValue([meeting({ decision: null })])
    render(wrap(<ScopingMappingHint changeId={7} assessments={[]} departments={departments} />))
    expect(screen.queryByText(/From scoping:/)).toBeNull()
  })
})
