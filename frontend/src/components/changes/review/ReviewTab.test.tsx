import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import ReviewTab from './ReviewTab'
import type { ReviewState } from '../../../api/intakes'
import type { ChangeRequest } from '../../../types/change'

const api = vi.hoisted(() => ({ list: vi.fn(), decide: vi.fn(), my: vi.fn(), review: vi.fn(), answer: vi.fn(), escalate: vi.fn() }))
vi.mock('../../../api/intakes', async (orig) => ({
  ...(await orig<typeof import('../../../api/intakes')>()), intakesApi: api,
}))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

const row = (id: number, name: string, over = {}) => ({
  id, department_id: id, department_name: name, answer: null, answer_label: null, note: null,
  answered_by_name: null, answered_at: null, objects: [], can_answer: false, ...over,
})
const state = (over: Partial<ReviewState> = {}): ReviewState => ({
  change_id: 9, is_review: true, escalated: false, escalated_at: null, impact_locked: true, open: true,
  answers: [row(2, 'Development'), row(4, 'Tool Engineer', { can_answer: true,
    objects: [{ id: 5, number: '199401', name: 'Cover tool', item_category: 'tool', via_part_id: 3 }] })],
  open_count: 2, impact_count: 0,
  revisions: [{ part_id: 3, part_number: '20-1994-001', revision_id: 40, revision_name: 'E2', status: 'in_review', active: false }],
  intake_id: 7, can_escalate: false, ...over,
})
const change = { id: 9, status: 'scoping', origin: 'engineering_review' } as unknown as ChangeRequest

let lastQc: QueryClient
function wrap(onGoImpact = vi.fn()) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  lastQc = qc
  return render(<QueryClientProvider client={qc}><MemoryRouter>
    <ReviewTab change={change} onGoImpact={onGoImpact} />
  </MemoryRouter></QueryClientProvider>)
}

describe('ReviewTab', () => {
  beforeEach(() => Object.values(api).forEach((f) => f.mockReset()))
  afterEach(cleanup)

  it('lists the departments with their objects and lets a member answer', async () => {
    api.review.mockResolvedValue(state())
    api.answer.mockResolvedValue(state({ open_count: 1 }))
    wrap()
    await screen.findByTestId('review-tab')
    expect(screen.getByTestId('review-tab').textContent).toContain('Waiting on 2 answers')
    expect(screen.getByTestId('review-row-4').textContent).toContain('199401 Cover tool')
    expect(screen.getByTestId('review-row-2').textContent).toContain('Answered by a member of Development')
    // "impact" needs a note first
    expect((screen.getByTestId('answer-impact-4') as HTMLButtonElement).disabled).toBe(true)
    fireEvent.click(screen.getByTestId('answer-no-impact-4'))
    await waitFor(() => expect(api.answer).toHaveBeenCalledWith(9, { department_id: 4, answer: 'no_impact', note: undefined }))
  })

  it('points at the impact lock before the review opens', async () => {
    api.review.mockResolvedValue(state({ impact_locked: false, open: false, answers: [] }))
    const go = vi.fn()
    wrap(go)
    fireEvent.click(await screen.findByTestId('review-go-impact'))
    expect(go).toHaveBeenCalled()
  })

  it('escalates to a full ECR when an impact is reported', async () => {
    api.review.mockResolvedValue(state({ impact_count: 1, can_escalate: true,
      answers: [row(4, 'Tool Engineer', { answer: 'impact', answer_label: 'Impact', note: 'insert change' })] }))
    api.escalate.mockResolvedValue(state({ escalated: true, escalated_at: '2026-09-25T10:00:00', is_review: false }))
    wrap()
    expect((await screen.findByTestId('review-tab')).textContent).toContain('1 impact reported')
    expect(screen.getByTestId('review-row-4').textContent).toContain('insert change')
    fireEvent.click(screen.getByTestId('review-escalate'))
    fireEvent.click(screen.getByTestId('escalate-confirm'))
    await waitFor(() => expect(api.escalate).toHaveBeenCalledWith(9, undefined))
  })

  it('escalation refreshes the change and every list naming it (new title and lead, final walk P2-8)', async () => {
    api.review.mockResolvedValue(state({ impact_count: 1, can_escalate: true, answers: [] }))
    api.escalate.mockResolvedValue(state({ escalated: true, escalated_at: '2026-09-25T10:00:00', is_review: false }))
    wrap()
    const spy = vi.spyOn(lastQc, 'invalidateQueries')
    fireEvent.click(await screen.findByTestId('review-escalate'))
    fireEvent.click(screen.getByTestId('escalate-confirm'))
    await waitFor(() => expect(spy).toHaveBeenCalledWith({ queryKey: ['changes'] }))
    expect(spy).toHaveBeenCalledWith({ queryKey: ['change', 9] })
  })

  it('needs a note to escalate without a reported impact', async () => {
    api.review.mockResolvedValue(state({ can_escalate: true }))
    wrap()
    fireEvent.click(await screen.findByTestId('review-escalate'))
    expect((screen.getByTestId('escalate-confirm') as HTMLButtonElement).disabled).toBe(true)
    fireEvent.change(screen.getByLabelText('Why escalate'), { target: { value: 'customer wants a quote' } })
    expect((screen.getByTestId('escalate-confirm') as HTMLButtonElement).disabled).toBe(false)
  })
})
