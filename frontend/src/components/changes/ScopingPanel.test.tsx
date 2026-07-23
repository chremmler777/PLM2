import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, cleanup, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import ScopingPanel from './ScopingPanel'

vi.mock('../../api/changes', () => ({
  changesApi: {
    listMeetings: vi.fn().mockResolvedValue([{
      id: 1, change_id: 7, meeting_date: '2026-07-04T10:00:00Z', channel: 'email',
      participants: [{ name: 'PM Jane' }], notes: 'scope ok',
      decision: 'needs_info', selected_department_ids: [2],
      created_by: 1, created_at: '2026-07-04T10:00:00Z',
      decided_by: 1, decided_at: '2026-07-04T11:00:00Z',
    }]),
    createMeeting: vi.fn(), decideMeeting: vi.fn(), update: vi.fn(),
  },
}))
vi.mock('../../hooks/queries/useWorkflows', () => ({
  useDepartments: () => ({ data: [{ id: 2, name: 'Quality' }] }),
}))
vi.mock('../../api/contacts', () => ({
  contactsApi: { list: vi.fn().mockResolvedValue([{ name: 'Dana Lee', email: 'dana@ktx.io' }]) },
}))

const wrap = (ui: React.ReactElement) => (
  <QueryClientProvider client={new QueryClient()}>{ui}</QueryClientProvider>
)

// Minimal change stand-in — only the fields ScopingPanel / DeadlineEditor read.
const change = (over: Record<string, unknown> = {}) => ({
  id: 7, status: 'scoping', required_by_date: null, required_by_reason: null,
  deadline_state: null, ...over,
}) as never

describe('ScopingPanel', () => {
  afterEach(cleanup)

  it('lists recorded meetings with their decision', async () => {
    render(wrap(<ScopingPanel change={change()} />))
    expect(await screen.findByText(/PM Jane/)).toBeTruthy()
    expect(screen.getByText(/needs more info/i)).toBeTruthy()
  })
  it('offers the create form while scoping is open', async () => {
    render(wrap(<ScopingPanel change={change()} />))
    expect(await screen.findByRole('button', { name: /save meeting/i })).toBeTruthy()
  })
  it('warns that a deadline is required when none is set', async () => {
    render(wrap(<ScopingPanel change={change({ required_by_date: null })} />))
    expect(await screen.findByText(/required before assessment/i)).toBeTruthy()
  })
  it('does not warn once a deadline is set', async () => {
    render(wrap(<ScopingPanel change={change({ required_by_date: '2026-09-01', deadline_state: 'on_track' })} />))
    await screen.findByText(/PM Jane/)
    expect(screen.queryByText(/required before assessment/i)).toBeNull()
  })
  it('appends a picked contact to the participants list', async () => {
    render(wrap(<ScopingPanel change={change()} />))
    const add = await screen.findByPlaceholderText(/add attendee/i)
    // Selecting a datalist option fires a change with the full contact name.
    fireEvent.change(add, { target: { value: 'Dana Lee' } })
    await waitFor(() => {
      const list = screen.getByDisplayValue('Dana Lee')
      expect(list).toBeTruthy()
    })
  })
})
