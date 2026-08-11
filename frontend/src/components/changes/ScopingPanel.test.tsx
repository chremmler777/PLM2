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
    recommendedDepartments: vi.fn().mockResolvedValue([{ id: 2, name: 'Quality' }]),
  },
}))
vi.mock('../../hooks/queries/useWorkflows', () => ({
  useDepartments: () => ({ data: [{ id: 2, name: 'Quality' }] }),
}))
// ConcernStrip has its own suite and its own auth/query needs; this file is
// about the meeting flow.
vi.mock('./ConcernStrip', () => ({ default: () => <div>mock-concern-strip</div> }))
vi.mock('./AttachmentDropzone', () => ({ default: () => <div>mock-attachment-dropzone</div> }))
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
  it('pre-marks the recommended assessor departments with a star', async () => {
    render(wrap(<ScopingPanel change={change()} />))
    // "Quality" is recommended → button pre-selected (sky bg) and starred.
    const qualityBtn = await screen.findByRole('button', { name: /★\s*Quality/ })
    expect(qualityBtn.className).toContain('bg-sky-600')
  })
  it('adds a picked contact as a removable chip', async () => {
    const { container } = render(wrap(<ScopingPanel change={change()} />))
    const add = await screen.findByPlaceholderText(/add attendee/i)
    // Wait for the contacts datalist to populate before "picking" one.
    await waitFor(() =>
      expect(container.querySelector('option[value="Dana Lee"]')).toBeTruthy())
    // Selecting a datalist option fires a change with the full contact name.
    fireEvent.change(add, { target: { value: 'Dana Lee' } })
    // It becomes a chip with a remove control, not free-editable text.
    const remove = await screen.findByRole('button', { name: /remove dana lee/i })
    expect(remove).toBeTruthy()
    fireEvent.click(remove)
    await waitFor(() =>
      expect(screen.queryByRole('button', { name: /remove dana lee/i })).toBeNull())
  })

  it('confirms the best-matching contact on Enter from a partial name', async () => {
    const { container } = render(wrap(<ScopingPanel change={change()} />))
    const add = await screen.findByPlaceholderText(/add attendee/i)
    await waitFor(() =>
      expect(container.querySelector('option[value="Dana Lee"]')).toBeTruthy())
    fireEvent.change(add, { target: { value: 'dana' } })
    fireEvent.keyDown(add, { key: 'Enter' })
    // "dana" resolves to the full contact name as a chip — no mouse needed.
    expect(await screen.findByRole('button', { name: /remove dana lee/i })).toBeTruthy()
  })

  it('confirms the best match on Tab too', async () => {
    const { container } = render(wrap(<ScopingPanel change={change()} />))
    const add = await screen.findByPlaceholderText(/add attendee/i)
    await waitFor(() =>
      expect(container.querySelector('option[value="Dana Lee"]')).toBeTruthy())
    fireEvent.change(add, { target: { value: 'dana' } })
    fireEvent.keyDown(add, { key: 'Tab' })
    expect(await screen.findByRole('button', { name: /remove dana lee/i })).toBeTruthy()
  })
})

describe('ScopingPanel meeting recording is scoping-only', () => {
  afterEach(cleanup)

  it('offers no meeting form or decision buttons while the change is captured', async () => {
    render(wrap(<ScopingPanel change={change({ status: 'captured' })} />))
    await screen.findByText(/PM Jane/)
    expect(screen.queryByRole('button', { name: /save meeting/i })).toBeNull()
    expect(screen.queryByRole('button', { name: /^proceed$/i })).toBeNull()
  })
})
