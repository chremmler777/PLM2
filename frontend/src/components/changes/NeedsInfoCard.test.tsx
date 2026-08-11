import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import NeedsInfoCard from './NeedsInfoCard'
import { changesApi } from '../../api/changes'
import { t } from '../../i18n/cmLabels'

vi.mock('../../api/changes', () => ({
  changesApi: { withdrawConcern: vi.fn().mockResolvedValue({}), uploadAttachment: vi.fn() },
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
  department_id: null, resolution_note: null, ...over,
}) as never

const doc = (over: Record<string, unknown> = {}) => ({
  id: 100, filename: 'q.msg', content_type: 'text/plain', size_bytes: 1,
  phase: 'baseline', created_at: '2026-08-01T10:00:00',
  kind: 'info_request', responds_to_id: null, concern_id: 1, ...over,
}) as never

const wrap = (ui: React.ReactElement) =>
  render(<QueryClientProvider client={new QueryClient()}>{ui}</QueryClientProvider>)

describe('NeedsInfoCard', () => {
  beforeEach(() => { vi.mocked(changesApi.withdrawConcern).mockClear() })
  afterEach(cleanup)

  it('holds only its own documents, never a sibling question’s', () => {
    wrap(<NeedsInfoCard changeId={7} concern={concern()} editable canAnswer isAuthor={false}
      onChanged={() => {}} attachments={[
        doc({ id: 100, filename: 'ours.msg', concern_id: 1 }),
        doc({ id: 200, filename: 'theirs.msg', concern_id: 2 }),
        doc({ id: 300, filename: 'loose.pdf', concern_id: null, kind: 'general' }),
      ]} />)
    const card = screen.getByTestId('needs-info-card-1')
    expect(card.textContent).toContain('ours.msg')
    expect(card.textContent).not.toContain('theirs.msg')
    expect(card.textContent).not.toContain('loose.pdf')
  })

  it('scopes both upload slots to this question', () => {
    wrap(<NeedsInfoCard changeId={7} concern={concern()} editable canAnswer isAuthor={false}
      onChanged={() => {}} attachments={[]} />)
    fireEvent.click(screen.getByTestId('needs-info-add-doc-1'))
    const slots = screen.getAllByTestId('dropzone')
    expect(slots.every((s) => s.getAttribute('data-concern') === '1')).toBe(true)
    expect(slots.map((s) => s.getAttribute('data-kind')).sort())
      .toEqual(['info_request', 'info_response'])
  })

  it('settles the question with the answer as its record', async () => {
    wrap(<NeedsInfoCard changeId={7} concern={concern()} editable canAnswer isAuthor={false}
      onChanged={() => {}} attachments={[]} />)
    const solve = screen.getByTestId('needs-info-solve-1') as HTMLButtonElement
    // Nothing to record yet — nothing to submit.
    expect(solve.disabled).toBe(true)
    fireEvent.change(screen.getByTestId('needs-info-answer-note-1'),
      { target: { value: 'customer confirmed 12.50' } })
    fireEvent.click(screen.getByTestId('needs-info-solve-1'))
    await waitFor(() => expect(changesApi.withdrawConcern)
      .toHaveBeenCalledWith(7, 1, 'customer confirmed 12.50'))
  })

  it('greys the answer zone for anyone who may not settle it', () => {
    wrap(<NeedsInfoCard changeId={7} concern={concern()} editable canAnswer={false} isAuthor={false}
      onChanged={() => {}} attachments={[]} />)
    const solve = screen.getByTestId('needs-info-solve-1') as HTMLButtonElement
    expect(solve.disabled).toBe(true)
    expect(solve.getAttribute('title')).toBe(t('concern.authorOrSales'))
    expect((screen.getByTestId('needs-info-answer-note-1') as HTMLTextAreaElement).disabled).toBe(true)
  })

  it('settles visibly once answered, keeping the answer and its documents', () => {
    wrap(<NeedsInfoCard changeId={7} canAnswer isAuthor={false} editable onChanged={() => {}}
      concern={concern({ is_open: false, withdrawn_at: '2026-08-03T00:00:00',
        resolution_note: 'customer confirmed 12.50' })}
      attachments={[doc({ id: 101, filename: 'reply.msg', kind: 'info_response' })]} />)
    expect(screen.getByTestId('needs-info-state-1').textContent).toBe(t('concern.solved'))
    expect(screen.getByTestId('needs-info-answer-1').textContent).toContain('customer confirmed 12.50')
    expect(screen.getByTestId('needs-info-card-1').textContent).toContain('reply.msg')
    // A settled card asks for nothing more.
    expect(screen.queryByTestId('needs-info-solve-1')).toBeNull()
    expect(screen.queryByTestId('needs-info-add-doc-1')).toBeNull()
  })
})
