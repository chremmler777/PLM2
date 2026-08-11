import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import NeedsInfoCard from './NeedsInfoCard'
import { changesApi } from '../../api/changes'
import { t } from '../../i18n/cmLabels'

vi.mock('../../api/changes', () => ({
  changesApi: {
    answerConcern: vi.fn().mockResolvedValue({}),
    withdrawConcern: vi.fn().mockResolvedValue({}),
    uploadAttachment: vi.fn(),
  },
}))
vi.mock('./AttachmentDropzone', () => ({
  default: (p: { kind?: string; concernId?: number }) => (
    <div data-testid="dropzone" data-kind={p.kind ?? ''} data-concern={p.concernId ?? ''} />
  ),
}))

const concern = (over: Record<string, unknown> = {}) => ({
  id: 1, change_id: 7, kind: 'needs_info', note: 'What is the target price?',
  raised_by: 9, raised_by_name: 'PM Jane', raised_at: '2026-08-01T09:00:00',
  withdrawn_at: null, resolved_by_meeting_id: null, is_open: true,
  department_id: null, resolution_note: null, answer_note: null,
  answered_at: null, answered_by: null, answered_by_name: null, ...over,
}) as never

const doc = (over: Record<string, unknown> = {}) => ({
  id: 100, filename: 'q.msg', content_type: 'text/plain', size_bytes: 1,
  phase: 'baseline', created_at: '2026-08-01T10:00:00',
  kind: 'info_request', responds_to_id: null, concern_id: 1, ...over,
}) as never

const wrap = (ui: React.ReactElement) =>
  render(<QueryClientProvider client={new QueryClient()}>{ui}</QueryClientProvider>)

const card = (props: Record<string, unknown> = {}) =>
  wrap(<NeedsInfoCard changeId={7} concern={concern()} attachments={[]} editable
    canAnswer={false} canSettle={false} onChanged={() => {}} {...props} />)

describe('NeedsInfoCard states', () => {
  beforeEach(() => {
    vi.mocked(changesApi.answerConcern).mockClear()
    vi.mocked(changesApi.withdrawConcern).mockClear()
  })
  afterEach(cleanup)

  it('opens awaiting an answer', () => {
    card()
    expect(screen.getByTestId('needs-info-state-1').textContent).toBe(t('concern.awaitingAnswer'))
    expect(screen.queryByTestId('needs-info-answer-1')).toBeNull()
  })

  it('shows the stored answer and still asks to be closed', () => {
    card({ concern: concern({
      answer_note: 'customer confirmed 12.50', answered_at: '2026-08-02T00:00:00',
      answered_by: 5, answered_by_name: 'Sam Sales' }) })
    expect(screen.getByTestId('needs-info-state-1').textContent).toBe(t('concern.awaitingClosure'))
    const answer = screen.getByTestId('needs-info-answer-1')
    expect(answer.textContent).toContain('customer confirmed 12.50')
    expect(answer.textContent).toContain('Sam Sales')
    // Answered is not closed: the settle control is still there.
    expect(screen.getByTestId('needs-info-settle-1')).toBeTruthy()
  })

  it('reads as one settled line, expandable to its record', () => {
    card({ concern: concern({ is_open: false, withdrawn_at: '2026-08-03T00:00:00',
      answer_note: 'customer confirmed 12.50', resolution_note: 'price agreed' }) })
    fireEvent.click(screen.getByTestId('needs-info-summary-1'))
    expect(screen.getByTestId('needs-info-state-1').textContent).toBe(t('concern.solved'))
    expect(screen.getByTestId('needs-info-resolution-1').textContent).toContain('price agreed')
    expect(screen.queryByTestId('needs-info-settle-1')).toBeNull()
  })
})

describe('NeedsInfoCard roles', () => {
  beforeEach(() => {
    vi.mocked(changesApi.answerConcern).mockClear()
    vi.mocked(changesApi.withdrawConcern).mockClear()
  })
  afterEach(cleanup)

  it('lets Sales write the answer without closing the question', async () => {
    card({ canAnswer: true })
    fireEvent.change(screen.getByTestId('needs-info-answer-note-1'),
      { target: { value: 'customer confirmed 12.50' } })
    fireEvent.click(screen.getByTestId('needs-info-answer-submit-1'))
    await waitFor(() => expect(changesApi.answerConcern)
      .toHaveBeenCalledWith(7, 1, 'customer confirmed 12.50'))
    expect(changesApi.withdrawConcern).not.toHaveBeenCalled()
  })

  it('lets Sales revise an answer already on the record', () => {
    card({ canAnswer: true, concern: concern({ answer_note: 'first take' }) })
    expect((screen.getByTestId('needs-info-answer-note-1') as HTMLTextAreaElement).value)
      .toBe('first take')
    expect(screen.getByTestId('needs-info-answer-submit-1').textContent)
      .toBe(t('concern.updateAnswer'))
  })

  it('greys the answer zone for anyone but Sales', () => {
    card({ canSettle: true })
    const submit = screen.getByTestId('needs-info-answer-submit-1') as HTMLButtonElement
    expect(submit.disabled).toBe(true)
    expect(submit.getAttribute('title')).toBe(t('concern.salesAnswers'))
    expect((screen.getByTestId('needs-info-answer-note-1') as HTMLTextAreaElement).disabled).toBe(true)
  })

  it('closes only for the asking side or PM, with a note', async () => {
    card({ canSettle: true, concern: concern({ answer_note: 'customer confirmed 12.50' }) })
    fireEvent.click(screen.getByTestId('needs-info-settle-1'))
    // The note starts from the answer — the usual reason it is being closed.
    const note = screen.getByTestId('needs-info-settle-note-1') as HTMLInputElement
    expect(note.value).toBe('customer confirmed 12.50')
    fireEvent.change(note, { target: { value: 'price agreed, good to proceed' } })
    fireEvent.click(screen.getByTestId('needs-info-settle-confirm-1'))
    await waitFor(() => expect(changesApi.withdrawConcern)
      .toHaveBeenCalledWith(7, 1, 'price agreed, good to proceed'))
  })

  it('greys closing for Sales and says who may do it', () => {
    card({ canAnswer: true })
    const settle = screen.getByTestId('needs-info-settle-1') as HTMLButtonElement
    expect(settle.disabled).toBe(true)
    expect(settle.getAttribute('title')).toBe(t('concern.closerOnly'))
  })
})

describe('NeedsInfoCard containment', () => {
  afterEach(cleanup)

  it('renders its documents as rows with a download link and their uploader', () => {
    card({ canAnswer: true, attachments: [
      doc({ id: 100, filename: 'questions.msg', uploaded_by_name: 'PM Jane' }),
      doc({ id: 101, filename: 'reply.msg', kind: 'info_response',
        uploaded_by_name: 'Sam Sales', created_at: '2026-08-02T00:00:00' }),
    ] })
    // Both sides of the exchange are readable on the card itself.
    expect(screen.getByText(t('concern.questionDocs'))).toBeTruthy()
    expect(screen.getByText(t('concern.answerDocs'))).toBeTruthy()
    const link = screen.getByRole('link', { name: 'questions.msg' })
    expect(link.getAttribute('href')).toContain('/v1/changes/7/attachments/100/download')
    expect(screen.getByTestId('needs-info-card-1').textContent).toContain('PM Jane')
    expect(screen.getByTestId('needs-info-card-1').textContent).toContain('Sam Sales')
    expect(screen.getByTestId('attach-kind-info_response')).toBeTruthy()
  })

  it('leaves out a document heading with nothing under it', () => {
    card({ canAnswer: true, attachments: [doc({ id: 100, filename: 'questions.msg' })] })
    expect(screen.getByText(t('concern.questionDocs'))).toBeTruthy()
    expect(screen.queryByText(t('concern.answerDocs'))).toBeNull()
  })

  it('holds only its own documents, never a sibling question’s', () => {
    card({ canAnswer: true, attachments: [
      doc({ id: 100, filename: 'ours.msg', concern_id: 1 }),
      doc({ id: 200, filename: 'theirs.msg', concern_id: 2 }),
      doc({ id: 300, filename: 'loose.pdf', concern_id: null, kind: 'general' }),
    ] })
    const el = screen.getByTestId('needs-info-card-1')
    expect(el.textContent).toContain('ours.msg')
    expect(el.textContent).not.toContain('theirs.msg')
    expect(el.textContent).not.toContain('loose.pdf')
  })

  it('scopes both upload slots to this question', () => {
    card({ canAnswer: true })
    fireEvent.click(screen.getByTestId('needs-info-add-doc-1'))
    const slots = screen.getAllByTestId('dropzone')
    expect(slots.every((s) => s.getAttribute('data-concern') === '1')).toBe(true)
    expect(slots.map((s) => s.getAttribute('data-kind')).sort())
      .toEqual(['info_request', 'info_response'])
  })

  it('names where a meeting-raised question came from', () => {
    card({ origin: 'from meeting of 04/07/2026' })
    expect(screen.getByTestId('needs-info-card-1').textContent)
      .toContain('from meeting of 04/07/2026')
  })
})
