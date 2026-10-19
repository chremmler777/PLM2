import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest'
import { render, screen, cleanup, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import ScopingFlags from './ScopingFlags'
import AnswerForm from './AnswerForm'
import ProceedFixList from './ProceedFixList'
import { changesApi } from '../../../api/changes'
import { t } from '../../../i18n/cmLabels'
import { unroutedCheckOwners } from '../../../lib/scopingRules'
import type { ChangeConcern, ChangeMeeting } from '../../../types/change'

vi.mock('../../../api/changes', () => ({
  changesApi: {
    raiseConcern: vi.fn().mockResolvedValue({}),
    joinConcern: vi.fn().mockResolvedValue({}),
    setConcernType: vi.fn().mockResolvedValue({}),
    withdrawConcern: vi.fn().mockResolvedValue({}),
    answerConcernForm: vi.fn().mockResolvedValue({}),
    confirmConcern: vi.fn().mockResolvedValue({}),
    updateMeeting: vi.fn().mockResolvedValue({}),
  },
}))
vi.mock('../AttachmentDropzone', () => ({ default: () => <div data-testid="dropzone" /> }))
vi.mock('../../../contexts/AuthContext', () => ({ useAuth: () => ({ userId: 5, isAdmin: false }) }))

const wrap = (ui: React.ReactElement) => (
  <QueryClientProvider client={new QueryClient()}>{ui}</QueryClientProvider>
)
const DEPTS = [{ id: 3, name: 'Process Engineer', is_active: true },
  { id: 4, name: 'Tool Engineer', is_active: true }, { id: 6, name: 'Quality', is_active: true }]
const concern = (over: Partial<ChangeConcern> = {}): ChangeConcern => ({
  id: 11, change_id: 7, kind: 'needs_info', note: 'Rib thickness', raised_by: 5,
  raised_at: '2026-10-14T10:00:00Z', is_open: true, flag_type: 'check',
  check_what: 'drawing', department_id: 3, owner_department_names: ['Process Engineer'],
  ...over,
})

beforeEach(() => { try { window.localStorage.clear() } catch { /* */ } })
afterEach(() => { cleanup(); vi.clearAllMocks() })

describe('ScopingFlags quick add', () => {
  const flags = (concerns: ChangeConcern[] = []) => wrap(
    <ScopingFlags changeId={7} concerns={concerns}
      impactedItems={[{ id: 1, part_id: 21, part_number: '886.197' }]}
      departments={DEPTS} myDepartmentIds={[3]} changeDepartmentIds={[3, 4]}
      editable onChanged={() => {}} />)

  it('adds a check item by default with the department preselected', async () => {
    render(flags())
    const add = screen.getByTestId('quick-add-submit') as HTMLButtonElement
    // nothing typed, nothing picked: refused with what is missing
    expect(add.disabled).toBe(true)
    expect(add.textContent).toBe(t('flag.addCheck'))
    expect((screen.getByTestId('quick-add-dept') as HTMLSelectElement).value).toBe('3')
    fireEvent.change(screen.getByTestId('quick-add-note'), { target: { value: 'Check rib' } })
    fireEvent.change(screen.getByTestId('quick-add-what'), { target: { value: 'drawing' } })
    fireEvent.change(screen.getByTestId('quick-add-part'), { target: { value: '21' } })
    expect(add.disabled).toBe(false)
    fireEvent.click(add)
    await waitFor(() => expect(changesApi.raiseConcern).toHaveBeenCalledWith(7, {
      kind: 'needs_info', note: 'Check rib', department_id: 3, flag_type: 'check',
      check_what: 'drawing', part_id: 21 }))
  })

  it('a question also needs who answers and what it changes in the scope', async () => {
    render(flags())
    fireEvent.change(screen.getByTestId('quick-add-note'), { target: { value: 'Resin lot?' } })
    fireEvent.change(screen.getByTestId('quick-add-what'), { target: { value: 'material' } })
    fireEvent.click(screen.getByTestId('quick-add-question'))
    expect(screen.getByTestId('quick-add-scope-test').textContent).toContain(t('flag.scopeTest'))
    const add = screen.getByTestId('quick-add-submit') as HTMLButtonElement
    expect(add.textContent).toBe(t('flag.addQuestion'))
    expect(add.disabled).toBe(true)
    fireEvent.click(screen.getByTestId('quick-add-from-customer'))
    expect(add.disabled).toBe(true)
    fireEvent.change(screen.getByTestId('quick-add-effect'), { target: { value: 'Adds Toolshop' } })
    expect(add.disabled).toBe(false)
    fireEvent.click(add)
    await waitFor(() => expect(changesApi.raiseConcern).toHaveBeenCalledWith(7, expect.objectContaining({
      flag_type: 'question', answer_from: 'customer', scope_effect: 'Adds Toolshop' })))
  })

  it('offers same as / add to beside an open item on the same pick', async () => {
    render(flags([concern({ id: 12, department_id: 4, owner_department_names: ['Tool Engineer'] })]))
    fireEvent.change(screen.getByTestId('quick-add-what'), { target: { value: 'drawing' } })
    expect(screen.getByTestId('quick-add-twins')).toBeTruthy()
    // no text yet: only "same as" (my department co-owns it)
    expect(screen.queryByTestId('quick-add-addto-12')).toBeNull()
    fireEvent.click(screen.getByTestId('quick-add-same-12'))
    await waitFor(() => expect(changesApi.joinConcern).toHaveBeenCalledWith(7, 12, { department_id: 3 }))
  })

  it('offers add to only where the backend allows it (can_add_to, R24)', async () => {
    render(flags([
      concern({ id: 12, department_id: 4, owner_department_names: ['Tool Engineer'], can_add_to: true }),
      concern({ id: 14, department_id: 4, owner_department_names: ['Tool Engineer'], can_add_to: false }),
    ]))
    fireEvent.change(screen.getByTestId('quick-add-note'), { target: { value: 'Rib 2 too' } })
    fireEvent.change(screen.getByTestId('quick-add-what'), { target: { value: 'drawing' } })
    expect(screen.getByTestId('quick-add-addto-12')).toBeTruthy()
    expect(screen.queryByTestId('quick-add-addto-14')).toBeNull()
    // 'same as' on #14 sends no line the caller may not add
    fireEvent.click(screen.getByTestId('quick-add-same-14'))
    await waitFor(() => expect(changesApi.joinConcern).toHaveBeenCalledWith(7, 14, { department_id: 3 }))
  })

  it('A2-03: a check item is raised only for a routable department; a question may name Management', () => {
    render(wrap(
      <ScopingFlags changeId={7} concerns={[]} impactedItems={[]}
        departments={[...DEPTS, { id: 9, name: 'Management', is_active: true },
          { id: 8, name: 'Old Lab', is_active: false }]}
        myDepartmentIds={[3]} changeDepartmentIds={[3]} editable onChanged={() => {}} />))
    const ids = () => [...(screen.getByTestId('quick-add-dept') as HTMLSelectElement).options].map((o) => o.value)
    expect(ids()).not.toContain('9')
    expect(ids()).not.toContain('8')
    fireEvent.click(screen.getByTestId('quick-add-question'))
    expect(ids()).toContain('9')
    expect(ids()).not.toContain('8')
  })

  it('A2-03: a Management member is not offered same as on a check item', () => {
    render(wrap(
      <ScopingFlags changeId={7} concerns={[concern({ id: 12, department_id: 4, owner_department_names: ['Tool Engineer'] })]}
        impactedItems={[]} departments={[...DEPTS, { id: 9, name: 'Management', is_active: true }]}
        myDepartmentIds={[9]} changeDepartmentIds={[4]} editable onChanged={() => {}} />))
    fireEvent.click(screen.getByTestId('quick-add-question'))
    fireEvent.change(screen.getByTestId('quick-add-dept'), { target: { value: '9' } })
    fireEvent.change(screen.getByTestId('quick-add-what'), { target: { value: 'drawing' } })
    expect(screen.queryByTestId('quick-add-same-12')).toBeNull()
  })

  it('does not offer same as for a department that is not mine', () => {
    render(flags([concern({ id: 12, department_id: 4, owner_department_names: ['Tool Engineer'] })]))
    fireEvent.change(screen.getByTestId('quick-add-dept'), { target: { value: '6' } })
    fireEvent.change(screen.getByTestId('quick-add-what'), { target: { value: 'drawing' } })
    expect(screen.queryByTestId('quick-add-same-12')).toBeNull()
  })

  it('groups check items by owner with their due; promote only for asker or PM', () => {
    render(flags([
      concern({ id: 11, owner_due: '2026-10-22T12:00:00Z', can_switch: true }),
      concern({ id: 13, note: 'Gate position', raised_by: 9, can_switch: false }),
    ]))
    expect(screen.getByTestId('check-group-Process Engineer').textContent).toContain('(2)')
    expect(screen.getByTestId('check-due-11').textContent).toContain('2026')
    expect(screen.getByTestId('check-due-13').textContent).toBe(t('flag.dueAtAssessment'))
    expect(screen.getByTestId('check-promote-11')).toBeTruthy()
    expect(screen.queryByTestId('check-promote-13')).toBeNull()
  })
})

describe('AnswerForm', () => {
  it('nothing preselected; a customer question is confirmed only by a filed mail', async () => {
    const q = concern({ flag_type: 'question', answer_from: 'customer' })
    render(wrap(<AnswerForm changeId={7} concern={q} onDone={() => {}}
      attachments={[{ id: 50, filename: 'mail.eml', kind: 'customer_email', created_at: '2026-10-14' } as never]} />))
    expect(screen.queryByTestId('answer-save-11')).toBeNull()
    fireEvent.click(screen.getByTestId('answer-kind-confirmed-11'))
    expect(screen.getByTestId('answer-customer-rule-11')).toBeTruthy()
    // no reference field for a customer question: the mail is the evidence
    expect(screen.queryByTestId('answer-ref-11')).toBeNull()
    const save = screen.getByTestId('answer-save-11') as HTMLButtonElement
    expect(save.disabled).toBe(true)
    fireEvent.change(screen.getByTestId('answer-mail-11'), { target: { value: '50' } })
    expect(save.disabled).toBe(false)
    fireEvent.click(save)
    await waitFor(() => expect(changesApi.answerConcernForm).toHaveBeenCalledWith(
      7, 11, { answer_kind: 'confirmed', mail_id: 50 }))
  })

  it('Assumed owes a number with its unit and the risk if wrong', async () => {
    const q = concern({ flag_type: 'question', answer_from: 'our_team' })
    render(wrap(<AnswerForm changeId={7} concern={q} attachments={[]} confirmerName="Cody"
      onDone={() => {}} />))
    fireEvent.click(screen.getByTestId('answer-kind-assumed-11'))
    const save = screen.getByTestId('answer-save-11') as HTMLButtonElement
    fireEvent.change(screen.getByTestId('answer-value-11'), { target: { value: 'lots' } })
    fireEvent.change(screen.getByTestId('answer-unit-11'), { target: { value: 'pcs/yr' } })
    fireEvent.change(screen.getByTestId('answer-risk-11'), { target: { value: 'Second cavity' } })
    expect(save.disabled).toBe(true)
    fireEvent.change(screen.getByTestId('answer-value-11'), { target: { value: '120000' } })
    expect(save.disabled).toBe(false)
    expect(screen.getByTestId('answer-confirm-by-11').textContent).toContain('Cody')
    fireEvent.click(save)
    await waitFor(() => expect(changesApi.answerConcernForm).toHaveBeenCalledWith(7, 11, {
      answer_kind: 'assumed', assumed_value: '120000', assumed_unit: 'pcs/yr',
      assumed_risk: 'Second cavity' }))
  })
})

describe('ProceedFixList', () => {
  const meeting = { id: 2, change_id: 7, selected_department_ids: [4],
    department_rasic: { 4: 'R' } } as unknown as ChangeMeeting
  it('lists questions to fix, check items by owner, and routes an unrouted owner', async () => {
    render(wrap(<ProceedFixList changeId={7} meeting={meeting} departments={DEPTS}
      attachments={[]} onChanged={() => {}}
      concerns={[
        concern({ id: 20, flag_type: 'question', can_answer: true, can_switch: true,
          asking_department_name: 'Tool Engineer', note: 'Slider?' }),
        concern({ id: 21, department_id: 3 }),
        concern({ id: 22, department_id: 6, owner_department_names: ['Quality'] }),
      ]} />))
    expect(screen.getByTestId('proceed-question-20').textContent).toContain('Slider?')
    expect(screen.getByTestId('proceed-answer-20')).toBeTruthy()
    fireEvent.click(screen.getByTestId('proceed-make-check-20'))
    await waitFor(() => expect(changesApi.setConcernType).toHaveBeenCalledWith(7, 20, { flag_type: 'check' }))
    // Process (3) and Quality (6) own check items but are not routed: C first for both
    const routeQ = screen.getByTestId('proceed-route-6-C')
    expect(screen.getByTestId('proceed-unrouted-3')).toBeTruthy()
    fireEvent.click(routeQ)
    await waitFor(() => expect(changesApi.updateMeeting).toHaveBeenCalledWith(7, 2, {
      department_rasic: { 4: 'R', 6: 'C' } }))
    expect(screen.getByTestId('proceed-checks').textContent).toContain('(2)')
    // check items grouped by their owner, each with its count
    expect(screen.getByTestId('proceed-checks-owner-Process Engineer').textContent).toContain('(1)')
    expect(screen.getByTestId('proceed-checks-owner-Quality').textContent).toContain('(1)')
    // a question is reassigned to the department that can answer it
    fireEvent.change(screen.getByTestId('proceed-reassign-20'), { target: { value: '6' } })
    await waitFor(() => expect(changesApi.setConcernType).toHaveBeenCalledWith(
      7, 20, { flag_type: 'question', department_id: 6 }))
  })

  it('an Informed department owns nothing: its check items count as not routed', () => {
    const m = { ...meeting, selected_department_ids: [4, 3], department_rasic: { 4: 'R', 3: 'I' } } as unknown as ChangeMeeting
    const got = unroutedCheckOwners(m, [concern({ id: 21, department_id: 3 }),
      concern({ id: 23, department_id: 4 })])
    expect([...got.entries()]).toEqual([[3, 1]])
  })

  it('a viewer who may neither answer nor switch gets no buttons', () => {
    render(wrap(<ProceedFixList changeId={7} meeting={meeting} departments={DEPTS}
      attachments={[]} onChanged={() => {}}
      concerns={[concern({ id: 20, flag_type: 'question', can_answer: false, can_switch: false })]} />))
    expect(screen.queryByTestId('proceed-answer-20')).toBeNull()
    expect(screen.queryByTestId('proceed-make-check-20')).toBeNull()
  })
})
