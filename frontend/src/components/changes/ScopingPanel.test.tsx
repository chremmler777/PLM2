import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, cleanup } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import ScopingPanel from './ScopingPanel'

vi.mock('../../api/changes', () => ({
  changesApi: {
    listMeetings: vi.fn().mockResolvedValue([{
      id: 1, change_id: 7, meeting_date: '2026-07-04T10:00:00Z',
      participants: [{ name: 'PM Jane' }], notes: 'scope ok',
      decision: 'needs_info', selected_department_ids: [2],
      created_by: 1, created_at: '2026-07-04T10:00:00Z',
      decided_by: 1, decided_at: '2026-07-04T11:00:00Z',
    }]),
    createMeeting: vi.fn(), decideMeeting: vi.fn(),
  },
}))
vi.mock('../../hooks/queries/useWorkflows', () => ({
  useDepartments: () => ({ data: [{ id: 2, name: 'Quality' }] }),
}))

const wrap = (ui: React.ReactElement) => (
  <QueryClientProvider client={new QueryClient()}>{ui}</QueryClientProvider>
)

describe('ScopingPanel', () => {
  afterEach(cleanup)

  it('lists recorded meetings with their decision', async () => {
    render(wrap(<ScopingPanel changeId={7} status="scoping" />))
    expect(await screen.findByText(/PM Jane/)).toBeTruthy()
    expect(screen.getByText(/needs more info/i)).toBeTruthy()
  })
  it('offers the create form while scoping is open', async () => {
    render(wrap(<ScopingPanel changeId={7} status="scoping" />))
    expect(await screen.findByRole('button', { name: /save meeting/i })).toBeTruthy()
  })
})
