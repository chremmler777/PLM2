import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, cleanup, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import ScopingPanel from './ScopingPanel'
import { t } from '../../i18n/cmLabels'
import { changesApi } from '../../api/changes'

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
    markRejectionSent: vi.fn().mockResolvedValue({}),
    recommendedDepartments: vi.fn().mockResolvedValue([{ id: 2, name: 'Quality' }]),
  },
}))
vi.mock('../../hooks/queries/useWorkflows', () => ({
  useDepartments: () => ({ data: [
    { id: 2, name: 'Quality', is_active: true },
    { id: 8, name: 'Logistics', is_active: false },
  ] }),
}))
// ConcernStrip has its own suite and its own auth/query needs; this file is
// about the meeting flow.
vi.mock('./ConcernStrip', () => ({ default: () => <div>mock-concern-strip</div> }))
vi.mock('./AttachmentDropzone', () => ({
  default: (props: { kind?: string }) => (
    <div data-testid="dropzone" data-kind={props.kind ?? ''}>mock-attachment-dropzone</div>
  ),
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
  it('leaves the deadline to the cockpit — no second editor here', async () => {
    render(wrap(<ScopingPanel change={change({ required_by_date: null, customer_relevant: true })} />))
    await screen.findByText(/PM Jane/)
    // The date is demanded at kickoff and lives in the cockpit banner; the
    // scoping panel no longer carries its own copy.
    expect(screen.queryByTestId('deadline-edit')).toBeNull()
    expect(screen.queryByTestId('deadline-chip')).toBeNull()
    expect(screen.queryByText(/required before assessment/i)).toBeNull()
  })
  it('pre-selects the recommended assessor departments', async () => {
    render(wrap(<ScopingPanel change={change()} />))
    // "Quality" is recommended → button pre-selected (sky bg), no star marker.
    const qualityBtn = await screen.findByRole('button', { name: /Quality/ })
    // The recommendation arrives with its query, then seeds the selection.
    await waitFor(() => expect(qualityBtn.className).toContain('bg-sky-600'))
    expect(qualityBtn.textContent).toBe('Quality')
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

describe('ScopingPanel keeps the discussion out of the record', () => {
  afterEach(cleanup)

  it('neither renders meeting notes nor offers a notes field', async () => {
    render(wrap(<ScopingPanel change={change()} />))
    await screen.findByText(/PM Jane/)
    // The fixture meeting carries notes; they are not shown any more.
    expect(screen.queryByText('scope ok')).toBeNull()
    expect(document.querySelector('textarea')).toBeNull()
    expect(screen.getByText(t('scoping.discussionByEmail'))).toBeTruthy()
  })

  it('records a meeting without sending notes', async () => {
    render(wrap(<ScopingPanel change={change()} />))
    fireEvent.click(await screen.findByRole('button', { name: /save meeting/i }))
    await waitFor(() => expect(changesApi.createMeeting).toHaveBeenCalled())
    const body = vi.mocked(changesApi.createMeeting).mock.calls[0][1]
    expect(body).not.toHaveProperty('notes')
  })
})

describe('ScopingPanel department picker', () => {
  afterEach(cleanup)

  it('offers only active departments', async () => {
    render(wrap(<ScopingPanel change={change()} />))
    expect(await screen.findByRole('button', { name: /Quality/ })).toBeTruthy()
    expect(screen.queryByRole('button', { name: /Logistics/ })).toBeNull()
  })
})

describe('ScopingPanel refused decision', () => {
  afterEach(cleanup)

  it('names the open concerns that blocked proceed', async () => {
    vi.mocked(changesApi.listMeetings).mockResolvedValue([{
      id: 2, change_id: 7, meeting_date: '2026-07-04T10:00:00Z', channel: 'meeting',
      participants: [{ name: 'PM Jane' }], notes: null, decision: null,
      selected_department_ids: [], created_by: 1, created_at: '2026-07-04T10:00:00Z',
      decided_by: null, decided_at: null,
    }] as never)
    vi.mocked(changesApi.decideMeeting).mockRejectedValueOnce({
      response: { status: 400, data: { detail:
        'Open concerns block proceed: Rita RD (would reject): tool cannot hold tolerance' } },
    })
    render(wrap(<ScopingPanel change={change()} />))
    fireEvent.click(await screen.findByRole('button', { name: t('meeting.proceed') }))
    const alert = await screen.findByTestId('decide-error')
    expect(alert.textContent).toContain('Rita RD')
    expect(alert.textContent).toContain('tool cannot hold tolerance')
  })

  it('reads the needs-info line as an open question to the customer', async () => {
    vi.mocked(changesApi.listMeetings).mockResolvedValue([{
      id: 3, change_id: 7, meeting_date: '2026-07-04T10:00:00Z', channel: 'email',
      participants: [{ name: 'PM Jane' }], notes: null, decision: 'needs_info',
      decision_reason: 'target price for the new gauge', selected_department_ids: [],
      created_by: 1, created_at: '2026-07-04T10:00:00Z',
      decided_by: 1, decided_at: '2026-07-04T11:00:00Z',
    }] as never)
    render(wrap(<ScopingPanel change={change()} />))
    const line = await screen.findByText(/target price for the new gauge/)
    // It names the mechanism — Sales asking the customer — not a form complaint.
    expect(line.textContent).toContain(t('meeting.missingInfo'))
    expect(line.textContent).not.toMatch(/Missing \(Sales\)/)
  })
})

describe('ScopingPanel needs-info upload slot', () => {
  afterEach(cleanup)

  it('files what goes out to the customer as the info request', async () => {
    vi.mocked(changesApi.listMeetings).mockResolvedValue([{
      id: 4, change_id: 7, meeting_date: '2026-07-04T10:00:00Z', channel: 'email',
      participants: [{ name: 'PM Jane' }], notes: null, decision: 'needs_info',
      decision_reason: 'target price', selected_department_ids: [],
      created_by: 1, created_at: '2026-07-04T10:00:00Z',
      decided_by: 1, decided_at: '2026-07-04T11:00:00Z',
    }] as never)
    render(wrap(<ScopingPanel change={change()} />))
    const slot = await screen.findByTestId('dropzone')
    expect(slot.getAttribute('data-kind')).toBe('info_request')
  })
})

describe('ScopingPanel needs-info loop is reachable where Sales lands', () => {
  const pendingNeedsInfo = [{
    id: 4, change_id: 7, meeting_date: '2026-07-04T10:00:00Z', channel: 'email',
    participants: [{ name: 'PM Jane' }], notes: null, decision: 'needs_info',
    decision_reason: 'target price for the new gauge', selected_department_ids: [],
    created_by: 1, created_at: '2026-07-04T10:00:00Z',
    decided_by: 1, decided_at: '2026-07-04T11:00:00Z',
  }]
  const att = (over: Record<string, unknown>) => ({
    id: 1, filename: 'questions.msg', content_type: 'application/vnd.ms-outlook',
    size_bytes: 10, phase: 'baseline', created_at: '2026-07-05T00:00:00',
    kind: 'info_request', responds_to_id: null, ...over,
  })

  beforeEach(() => {
    vi.mocked(changesApi.listMeetings).mockResolvedValue(pendingNeedsInfo as never)
  })
  afterEach(cleanup)

  it('shows the question document, downloadable, with a slot for the answer', async () => {
    render(wrap(<ScopingPanel change={change({ attachments: [att({})] })} />))
    // The reason is already there; now the document is too — no hunt on another tab.
    expect(await screen.findByText(/target price for the new gauge/)).toBeTruthy()
    const link = screen.getByRole('link', { name: 'questions.msg' })
    expect(link.getAttribute('href')).toContain('/v1/changes/7/attachments/1/download')
    expect(screen.getByTestId('attach-response-1')).toBeTruthy()
  })

  it('reads the answer beneath its question once it lands', async () => {
    render(wrap(<ScopingPanel change={change({ attachments: [
      att({}),
      att({ id: 2, filename: 'customer-reply.msg', kind: 'info_response', responds_to_id: 1 }),
    ] })} />))
    const loop = await screen.findByTestId('scoping-info-loop')
    expect(loop.textContent).toContain('customer-reply.msg')
    // Answered: it stops asking for one.
    expect(screen.queryByTestId('attach-response-1')).toBeNull()
  })

  it('offers the request slot while no question has been sent yet', async () => {
    render(wrap(<ScopingPanel change={change({ attachments: [] })} />))
    const slot = await screen.findByTestId('dropzone')
    expect(slot.getAttribute('data-kind')).toBe('info_request')
    expect(screen.queryByTestId('scoping-info-loop')).toBeNull()
  })
})

describe('ScopingPanel rejection closure', () => {
  const rejected = [{
    id: 5, change_id: 7, meeting_date: '2026-07-04T10:00:00Z', channel: 'meeting',
    participants: [{ name: 'PM Jane' }], notes: null, decision: 'reject',
    decision_reason: 'customer withdrew', selected_department_ids: [],
    created_by: 1, created_at: '2026-07-04T10:00:00Z',
    decided_by: 1, decided_at: '2026-07-04T11:00:00Z',
  }]
  const letter = {
    id: 9, filename: 'rejection.pdf', content_type: 'application/pdf', size_bytes: 10,
    phase: 'post_scoping', created_at: '2026-07-06T00:00:00',
    kind: 'rejection_letter', responds_to_id: null,
  }

  beforeEach(() => {
    vi.mocked(changesApi.listMeetings).mockResolvedValue(rejected as never)
    vi.mocked(changesApi.markRejectionSent).mockClear()
  })
  afterEach(cleanup)

  it('offers the letter slot and refuses to close before one exists', async () => {
    render(wrap(<ScopingPanel change={change({
      status: 'rejected', customer_relevant: true, attachments: [] })} />))
    const slot = await screen.findByTestId('dropzone')
    expect(slot.getAttribute('data-kind')).toBe('rejection_letter')
    const close = screen.getByTestId('rejection-sent') as HTMLButtonElement
    expect(close.disabled).toBe(true)
    expect(close.getAttribute('title')).toBe(t('reject.needLetter'))
  })

  it('closes the ECR once the letter is attached and the send is confirmed', async () => {
    render(wrap(<ScopingPanel change={change({
      status: 'rejected', customer_relevant: true, attachments: [letter] })} />))
    expect(await screen.findByRole('link', { name: 'rejection.pdf' })).toBeTruthy()
    const close = screen.getByTestId('rejection-sent') as HTMLButtonElement
    expect(close.disabled).toBe(false)
    fireEvent.click(close)
    await waitFor(() => expect(changesApi.markRejectionSent).toHaveBeenCalledWith(7))
  })

  it('greys the confirmation for anyone outside Sales and says why', async () => {
    render(wrap(<ScopingPanel canSendRejection={false} change={change({
      status: 'rejected', customer_relevant: true, attachments: [letter] })} />))
    const close = await screen.findByTestId('rejection-sent') as HTMLButtonElement
    expect(close.disabled).toBe(true)
    expect(close.getAttribute('title')).toBe(t('reject.salesOnly'))
    fireEvent.click(close)
    expect(changesApi.markRejectionSent).not.toHaveBeenCalled()
  })

  it('states the send instead of the button once it has gone out', async () => {
    render(wrap(<ScopingPanel change={change({
      status: 'rejected', customer_relevant: true, attachments: [letter],
      rejection_sent_at: '2026-07-07T00:00:00' })} />))
    expect(await screen.findByText(new RegExp(t('reject.sent')))).toBeTruthy()
    expect(screen.queryByTestId('rejection-sent')).toBeNull()
  })

  it('leaves an internal rejected change its plain slot, no closure block', async () => {
    render(wrap(<ScopingPanel change={change({
      status: 'rejected', customer_relevant: false, attachments: [] })} />))
    await screen.findByText(/customer withdrew/)
    expect(screen.queryByTestId('rejection-closure')).toBeNull()
    expect(screen.queryByTestId('rejection-sent')).toBeNull()
  })
})
