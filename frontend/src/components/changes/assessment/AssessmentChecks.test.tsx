import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, cleanup, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import AssessmentChecks from './AssessmentChecks'
import { changesApi } from '../../../api/changes'
import { t } from '../../../i18n/cmLabels'
import { formatDate } from '../../../lib/format'
import type { ChangeConcern } from '../../../types/change'

vi.mock('../scoping/AnswerForm', () => ({ default: () => <div data-testid="answer-form" /> }))
vi.mock('../../../api/changes', () => ({
  changesApi: {
    closeCheck: vi.fn().mockResolvedValue({}),
    reopenCheck: vi.fn().mockResolvedValue({}),
    raiseConcern: vi.fn().mockResolvedValue({}),
    withdrawConcern: vi.fn().mockResolvedValue({}),
    assessmentChecklist: vi.fn().mockResolvedValue([]),
  },
}))

const wrap = (ui: React.ReactElement) => (
  <QueryClientProvider client={new QueryClient()}>{ui}</QueryClientProvider>
)
const check = (over: Partial<ChangeConcern> = {}): ChangeConcern => ({
  id: 11, change_id: 7, kind: 'needs_info', note: 'Gate position', raised_by: 5,
  raised_by_name: 'Russ', raised_at: '2026-10-14T10:00:00Z', is_open: true,
  flag_type: 'check', check_what: 'drawing', department_id: 3, can_check: true,
  ...over,
})
const view = (concerns: ChangeConcern[], editable = true) => wrap(
  <AssessmentChecks changeId={7} departmentId={3} departmentName="Process Engineer"
    concerns={concerns} editable={editable} />)

afterEach(() => { cleanup(); vi.clearAllMocks() })

describe('AssessmentChecks (spec §4)', () => {
  it('lists the department check items on top with the open count', () => {
    render(view([check(), check({ id: 12, department_id: 4 })]))
    expect(screen.getByTestId('achk-title-3').textContent)
      .toBe(t('achk.title').replace('{d}', 'Process Engineer').replace('{n}', '1'))
    expect(screen.queryByTestId('achk-item-12')).toBeNull()
  })

  it('closes nothing without a pick and evidence, then sends value and unit', async () => {
    render(view([check()]))
    const save = screen.getByTestId('achk-save-11') as HTMLButtonElement
    expect(save.disabled).toBe(true)                       // nothing preselected
    fireEvent.click(screen.getByTestId('achk-outcome-11-answered'))
    fireEvent.change(screen.getByTestId('achk-value-11'), { target: { value: '2.4' } })
    expect(save.disabled).toBe(true)                       // no unit, no ref
    fireEvent.change(screen.getByTestId('achk-unit-11'), { target: { value: 'mm' } })
    expect(save.disabled).toBe(false)
    fireEvent.click(save)
    await waitFor(() => expect(changesApi.closeCheck).toHaveBeenCalledWith(7, 11, {
      outcome: 'answered', value: '2.4', unit: 'mm' }))
  })

  it('names the due of an open check item (R5)', () => {
    render(view([check({ owner_due: '2026-10-22T12:00:00' })]))
    expect(screen.getByTestId('achk-item-11').textContent)
      .toContain(t('flag.due').replace('{d}', formatDate('2026-10-22T12:00:00')))
  })

  it('an assumed check item with can_confirm shows the confirm form (A3-01)', () => {
    const closed = check({ is_open: false, check_outcome: 'assumed', answer_kind: 'assumed',
      assumed_value: '2.4', assumed_unit: 'mm', confirm_by_name: 'Sam Sales',
      confirm_due: '2026-10-22', can_confirm: true })
    render(view([closed], false))
    expect(screen.getByTestId('achk-confirm-11').querySelector('[data-testid="answer-form"]'))
      .toBeTruthy()
    expect(screen.getByTestId('achk-confirmline-11').textContent).toContain('Sam Sales')
  })

  it('no confirm form without can_confirm or once confirmed (A3-01)', () => {
    render(view([check({ is_open: false, answer_kind: 'assumed', can_confirm: false }),
      check({ id: 13, is_open: false, answer_kind: 'confirmed', can_confirm: true,
        confirmed_at: '2026-10-15T10:00:00Z' })], false))
    expect(screen.queryByTestId('achk-confirm-11')).toBeNull()
    expect(screen.queryByTestId('achk-confirm-13')).toBeNull()
  })

  it('words a question by viewer: asker, answerer, reader (A3-13)', () => {
    const q = check({ id: 21, flag_type: 'question', answer_from: 'customer',
      asking_department_name: 'Development', answer_due: '2026-10-20T12:00:00' })
    render(view([q], true))
    expect(screen.getByTestId('achk-qhead-21').textContent)
      .toBe(t('achk.question').replace('{who}', t('flag.from.customer')))
    expect(screen.getByText(t('achk.waiting'))).toBeTruthy()
    cleanup()
    render(view([{ ...q, can_answer: true }], false))
    expect(screen.getByTestId('achk-qhead-21').textContent).toBe(
      `Question for the customer: `
      + t('achk.answerBy').replace('{d}', formatDate('2026-10-20T12:00:00')))
    // the step line says what to do; no 'Waiting for the answer.' for the one who gets it
    expect(screen.getByTestId('achk-qstep-21').textContent)
      .toBe('Development needs this from the customer. Copy the mail text, send it to the customer, then enter the answer here.')
    expect(screen.queryByText(t('achk.waitingOther'))).toBeNull()
    cleanup()
    render(view([{ ...q, can_answer: true, answer_from: 'supplier' }], false))
    expect(screen.getByTestId('achk-qhead-21').textContent).toContain('Question for the supplier')
    cleanup()
    // a question for our team: the answerer is asked directly
    render(view([{ ...q, can_answer: true, answer_from: 'our_team' }], false))
    expect(screen.getByTestId('achk-qhead-21').textContent)
      .toContain(t('achk.asksYou').replace('{d}', 'Development'))
    // negative: the answerer is not told it holds "your submit"
    expect(screen.queryByText(t('achk.waiting'))).toBeNull()
    expect(screen.getByText(t('achk.waitingOther'))).toBeTruthy()
  })

  it('a viewer who may not check sees the item without the form', () => {
    render(view([check({ can_check: false })]))
    expect(screen.getByTestId('achk-item-11')).toBeTruthy()
    expect(screen.queryByTestId('achk-save-11')).toBeNull()
  })

  it('asks a question only with what it is about and who answers', async () => {
    render(view([]))
    fireEvent.click(screen.getByTestId('achk-ask-3'))
    const send = screen.getByTestId('achk-asksend-3') as HTMLButtonElement
    fireEvent.change(screen.getByTestId('achk-asknote-3'), { target: { value: 'Volume 2027?' } })
    expect(send.disabled).toBe(true)
    fireEvent.change(screen.getByTestId('achk-askwhat-3'), { target: { value: 'volume' } })
    fireEvent.change(screen.getByTestId('achk-askfrom-3'), { target: { value: 'customer' } })
    expect(send.disabled).toBe(false)
    fireEvent.click(send)
    await waitFor(() => expect(changesApi.raiseConcern).toHaveBeenCalledWith(7, {
      kind: 'needs_info', note: 'Volume 2027?', department_id: 3, flag_type: 'question',
      check_what: 'volume', answer_from: 'customer' }))
  })

  it('shows the reopen link only where the backend allows it', () => {
    render(view([check({ is_open: false, check_outcome: 'answered',
      resolution_note: '2.4 mm', can_reopen: false, can_check: false })], false))
    expect(screen.getByTestId('achk-closed-11')).toBeTruthy()
    expect(screen.queryByTestId('achk-reopen-11')).toBeNull()
  })
})

describe('AssessmentChecks questions (C8)', () => {
  const q = (over: Partial<ChangeConcern> = {}): ChangeConcern => ({
    id: 21, change_id: 7, kind: 'needs_info', note: 'Volume 2027?', raised_by: 5,
    raised_at: '2026-10-15T10:00:00Z', is_open: true, flag_type: 'question',
    check_what: 'volume', answer_from: 'customer', department_id: 3, ...over,
  })

  it('who may answer gets the answer form in the bucket', () => {
    render(view([q({ can_answer: true })], false))
    expect(screen.getByTestId('achk-answer-21')).toBeTruthy()
  })

  it('who may not answer only reads it', () => {
    render(view([q({ can_answer: false })], false))
    expect(screen.getByTestId('achk-q-21')).toBeTruthy()
    expect(screen.queryByTestId('achk-answer-21')).toBeNull()
  })
})
