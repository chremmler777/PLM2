import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, cleanup, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import AssessmentChecks from './AssessmentChecks'
import { changesApi } from '../../../api/changes'
import { t } from '../../../i18n/cmLabels'
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
