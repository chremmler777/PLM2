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
    listConcerns: vi.fn().mockResolvedValue([]), withdrawConcern: vi.fn(),
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
vi.mock('../../contexts/AuthContext', () => ({ useAuth: () => ({ userId: 5, isAdmin: false }) }))
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

describe('ScopingPanel question containers', () => {
  const meeting = (over: Record<string, unknown> = {}) => ({
    id: 4, change_id: 7, meeting_date: '2026-07-04T10:00:00Z', channel: 'email',
    participants: [{ name: 'PM Jane' }], notes: null, decision: 'needs_info',
    decision_reason: 'target price', selected_department_ids: [],
    created_by: 1, created_at: '2026-07-04T10:00:00Z',
    decided_by: 1, decided_at: '2026-07-04T11:00:00Z', ...over,
  })
  const question = (over: Record<string, unknown> = {}) => ({
    id: 11, change_id: 7, kind: 'needs_info', note: 'What is the target price?',
    raised_by: 1, raised_by_name: 'PM Jane', raised_at: '2026-07-04T11:00:00',
    withdrawn_at: null, resolved_by_meeting_id: null, is_open: true,
    department_id: null, resolution_note: null, answer_note: null,
    raised_by_meeting_id: 4, ...over,
  })

  beforeEach(() => {
    vi.mocked(changesApi.listMeetings).mockResolvedValue([meeting()] as never)
  })
  afterEach(cleanup)

  it('gives a meeting-raised question the same working card as a hand-raised one', async () => {
    vi.mocked(changesApi.listConcerns).mockResolvedValue([
      question({ id: 11, raised_by_meeting_id: 4, note: 'from the meeting' }),
      question({ id: 12, raised_by_meeting_id: null, note: 'raised by hand',
        raised_at: '2026-07-05T09:00:00' }),
    ] as never)
    render(wrap(<ScopingPanel change={change()} canAnswerConcerns />))
    // Both are open work, so both sit in "Now" — neither is buried in history.
    await screen.findByTestId('needs-info-card-11')
    const now = screen.getByTestId('scoping-now')
    expect(now.textContent).toContain('from the meeting')
    expect(now.textContent).toContain('raised by hand')
    // And both carry the same answer zone for Sales.
    expect(screen.getByTestId('needs-info-answer-note-11')).toBeTruthy()
    expect(screen.getByTestId('needs-info-answer-note-12')).toBeTruthy()
    // The meeting origin still shows on the card raised by a decision.
    expect(screen.getByTestId('needs-info-card-11').textContent)
      .toContain(t('concern.fromMeeting'))
    expect(screen.getByTestId('needs-info-card-12').textContent)
      .not.toContain(t('concern.fromMeeting'))
  })

  it('gives parallel questions parallel cards', async () => {
    vi.mocked(changesApi.listConcerns).mockResolvedValue([
      question({ id: 11, note: 'price?' }),
      question({ id: 12, note: 'timing?', raised_at: '2026-07-04T12:00:00' }),
    ] as never)
    render(wrap(<ScopingPanel change={change()} />))
    await screen.findByTestId('needs-info-card-11')
    const first = screen.getByTestId('needs-info-card-11')
    expect(first.textContent).toContain('price?')
    expect(first.textContent).not.toContain('timing?')
    expect(screen.getByTestId('needs-info-card-12').textContent).toContain('timing?')
  })

  it('drops a settled question into history under its meeting', async () => {
    vi.mocked(changesApi.listConcerns).mockResolvedValue([
      question({ id: 11, is_open: false, withdrawn_at: '2026-07-06T00:00:00',
        resolution_note: 'price agreed' })] as never)
    render(wrap(<ScopingPanel change={change()} />))
    const nest = await screen.findByTestId('meeting-questions-4')
    // One quiet line in history, not a working card in "Now".
    expect(nest.textContent).toContain('What is the target price?')
    expect(screen.getByTestId('needs-info-summary-11')).toBeTruthy()
    expect(screen.getByTestId('scoping-now').textContent).not.toContain('What is the target price?')
  })

  it('keeps the latest meeting open and older ones one click away', async () => {
    vi.mocked(changesApi.listConcerns).mockResolvedValue([] as never)
    vi.mocked(changesApi.listMeetings).mockResolvedValue([
      meeting({ id: 3, meeting_date: '2026-07-01T10:00:00Z', decision: 'needs_info',
        decision_reason: 'older question' }),
      meeting({ id: 4, decision_reason: 'latest question' }),
    ] as never)
    render(wrap(<ScopingPanel change={change()} />))
    await screen.findByText(/latest question/)
    // The older record is a summary line until asked for.
    expect(screen.queryByText(/older question/)).toBeNull()
    fireEvent.click(screen.getByTestId('meeting-summary-3'))
    expect(screen.getByText(/older question/)).toBeTruthy()
  })
})

describe('ScopingPanel question documents are visible where the questions are', () => {
  const meeting = {
    id: 4, change_id: 7, meeting_date: '2026-07-04T10:00:00Z', channel: 'email',
    participants: [{ name: 'PM Jane' }], notes: null, decision: 'needs_info',
    decision_reason: 'target price', selected_department_ids: [],
    created_by: 1, created_at: '2026-07-04T10:00:00Z',
    decided_by: 1, decided_at: '2026-07-04T11:00:00Z',
  }
  const question = {
    id: 11, change_id: 7, kind: 'needs_info', note: 'What is the target price?',
    raised_by: 1, raised_by_name: 'PM Jane', raised_at: '2026-07-04T11:00:00',
    withdrawn_at: null, resolved_by_meeting_id: null, is_open: true,
    department_id: null, resolution_note: null, answer_note: null,
    raised_by_meeting_id: 4,
  }
  const att = (over: Record<string, unknown>) => ({
    id: 1, filename: 'f.msg', content_type: 'text/plain', size_bytes: 1,
    phase: 'baseline', created_at: '2026-07-05T00:00:00',
    kind: 'info_request', responds_to_id: null, concern_id: null, ...over,
  })

  beforeEach(() => {
    vi.mocked(changesApi.listMeetings).mockResolvedValue([meeting] as never)
    vi.mocked(changesApi.listConcerns).mockResolvedValue([question] as never)
  })
  afterEach(cleanup)

  it('shows a scoped document inside its own card, downloadable and attributed', async () => {
    render(wrap(<ScopingPanel change={change({ attachments: [
      att({ id: 20, filename: 'questions.msg', concern_id: 11,
        uploaded_by_name: 'PM Jane' }),
      att({ id: 21, filename: 'reply.msg', kind: 'info_response', concern_id: 11,
        uploaded_by_name: 'Sam Sales' }),
    ] })} />))
    const card = await screen.findByTestId('needs-info-card-11')
    expect(card.textContent).toContain('questions.msg')
    expect(card.textContent).toContain('PM Jane')
    expect(card.textContent).toContain('reply.msg')
    expect(card.textContent).toContain('Sam Sales')
    const link = screen.getByRole('link', { name: 'questions.msg' })
    expect(link.getAttribute('href')).toContain('/v1/changes/7/attachments/20/download')
    // No empty headings on a card with only one side filled.
    expect(screen.queryByText(t('concern.noDocs'))).toBeNull()
  })

  it('surfaces legacy question documents that belong to no card', async () => {
    render(wrap(<ScopingPanel change={change({ attachments: [
      att({ id: 30, filename: 'legacy-question.msg', concern_id: null }),
      att({ id: 31, filename: 'general.pdf', kind: 'general', concern_id: null }),
    ] })} />))
    const strip = await screen.findByTestId('unassigned-question-docs')
    expect(strip.textContent).toContain('legacy-question.msg')
    // Plain documents are not question evidence and stay out of it.
    expect(strip.textContent).not.toContain('general.pdf')
    expect(screen.getByRole('link', { name: 'legacy-question.msg' })).toBeTruthy()
    expect(strip.textContent).toContain(t('concern.unassignedHint'))
  })

  it('keeps the strip away when every document is filed', async () => {
    render(wrap(<ScopingPanel change={change({ attachments: [
      att({ id: 20, filename: 'questions.msg', concern_id: 11 }),
    ] })} />))
    await screen.findByTestId('needs-info-card-11')
    expect(screen.queryByTestId('unassigned-question-docs')).toBeNull()
  })
})
