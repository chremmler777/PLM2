import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest'
import { render, screen, cleanup, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import ReleaseTab, { closingFigures } from './ReleaseTab'
import ReleaseChecklist from './ReleaseChecklist'
import LessonsStep from './LessonsStep'
import { changeReleaseApi } from '../../../api/changeRelease'
import { changesApi } from '../../../api/changes'
import { validationIssuesApi } from '../../../api/validationIssues'
import type { ChangeDetail } from '../../../types/change'
import type { ReleaseCheck, ReleaseState } from '../../../types/changeRelease'
import { NUMBER_INPUT_HINT, NUMBER_INPUT_INVALID } from '../../../lib/format'

vi.mock('../../../api/changeRelease', () => ({
  changeReleaseApi: {
    get: vi.fn(), setCheck: vi.fn().mockResolvedValue({}),
    addLesson: vi.fn().mockResolvedValue({}), completeLessons: vi.fn().mockResolvedValue({}),
  },
}))
vi.mock('../../../api/changes', () => ({
  changesApi: { validationState: vi.fn().mockResolvedValue({ departments: [] }) },
}))
vi.mock('../../../api/changePlan', () => ({
  planApi: {
    get: vi.fn().mockResolvedValue({
      tasks: [
        { id: 1, is_idea: false, start_date: '2026-10-01', duration_days: 14, end_date: '2026-10-15', progress_pct: 100,
          baseline_start: '2026-10-01', baseline_finish: '2026-10-11', actual_finish: '2026-10-14' },
        { id: 2, is_idea: false, start_date: '2026-09-25', duration_days: 7, end_date: '2026-10-02', progress_pct: 100,
          baseline_start: '2026-09-25', baseline_finish: '2026-10-02', actual_finish: '2026-10-02' },
      ],
      summary: { finish: '2026-10-14' },
    }),
  },
}))
vi.mock('../../../api/validationIssues', () => ({
  validationIssuesKey: (id: number) => ['change', id, 'validation-issues'],
  validationIssuesApi: { list: vi.fn().mockResolvedValue([]) },
}))
vi.mock('../ValidationPanel', () => ({ default: () => <div>mock-validation</div> }))
vi.mock('../ImplementationPanel', () => ({ default: () => <div>mock-ecn</div> }))
vi.mock('../PnlCard', () => ({ default: () => <div>mock-pnl</div> }))
vi.mock('sonner', () => ({ toast: { error: vi.fn(), success: vi.fn() } }))

const check = (over: Partial<ReleaseCheck> = {}): ReleaseCheck => ({
  key: 'weight_measured', label: 'Part weight measured and recorded', department_id: 4,
  department_name: 'Tool Engineer', status: 'open', note: null, hint: 'Validated weight exists: 412 g', ...over,
})

const state = (over: Partial<ReleaseState> = {}): ReleaseState => ({
  checks: [check(), check({ key: 'erp_updated', label: 'ERP updated', department_id: 11, department_name: 'Scheduling' })],
  open_count: 2,
  lessons: { items: [] },
  can_release: false,
  blockers: ['Release checklist incomplete: 2 open'],
  ...over,
})

const change = (over: Partial<ChangeDetail> = {}): ChangeDetail => ({
  id: 7, change_number: 'CR-7', project_id: 1, title: 'x', change_type: 'tooling',
  priority: 'medium', status: 'in_validation', raised_by: 1, customer_response: 'accepted',
  created_at: '2026-07-01T00:00:00', updated_at: '2026-07-01T00:00:00',
  impacted_items: [], assessments: [], attachments: [], ...over,
} as ChangeDetail)

const wrap = (ui: React.ReactElement) => render(
  <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>{ui}</QueryClientProvider>)

describe('ReleaseChecklist', () => {
  afterEach(cleanup)
  beforeEach(() => { vi.clearAllMocks() })

  it('n.a. needs a note before it saves', async () => {
    wrap(<ReleaseChecklist changeId={7} checks={[check()]} myDepartmentIds={[4]} canManage={false} editable />)
    fireEvent.click(screen.getByTestId('release-check-weight_measured-na'))
    const confirm = screen.getByTestId('release-check-weight_measured-confirm') as HTMLButtonElement
    expect(confirm.disabled).toBe(true)
    fireEvent.change(screen.getByTestId('release-check-weight_measured-note'), { target: { value: 'Weight unchanged' } })
    fireEvent.click(confirm)
    await waitFor(() => expect(changeReleaseApi.setCheck).toHaveBeenCalledWith(7, 'weight_measured',
      { status: 'na', note: 'Weight unchanged' }))
  })

  it('done saves without a note', async () => {
    wrap(<ReleaseChecklist changeId={7} checks={[check()]} myDepartmentIds={[4]} canManage={false} editable />)
    fireEvent.click(screen.getByTestId('release-check-weight_measured-done'))
    const confirm = screen.getByTestId('release-check-weight_measured-confirm') as HTMLButtonElement
    expect(confirm.disabled).toBe(false)
    fireEvent.click(confirm)
    await waitFor(() => expect(changeReleaseApi.setCheck).toHaveBeenCalledWith(7, 'weight_measured', { status: 'done' }))
  })

  it('gives controls only to the owner department, and to PM/lead/admin', () => {
    wrap(<ReleaseChecklist changeId={7} myDepartmentIds={[4]} canManage={false} editable
      checks={[check(), check({ key: 'erp_updated', department_id: 11, department_name: 'Scheduling' })]} />)
    expect(screen.getByTestId('release-check-weight_measured-done')).toBeDefined()
    expect(screen.queryByTestId('release-check-erp_updated-done')).toBeNull()
    cleanup()
    wrap(<ReleaseChecklist changeId={7} myDepartmentIds={[]} canManage editable
      checks={[check({ key: 'erp_updated', department_id: 11, department_name: 'Scheduling' })]} />)
    expect(screen.getByTestId('release-check-erp_updated-done')).toBeDefined()
  })

  it('renders the Tool Engineer cycle time and the APQP rows under their department, for their members', () => {
    const apqp = (key: string, label: string, over: Partial<ReleaseCheck> = {}) =>
      check({ key, label, department_id: 20, department_name: 'APQP', hint: null, ...over })
    wrap(<ReleaseChecklist changeId={7} myDepartmentIds={[20]} canManage={false} editable checks={[
      check({ key: 'cycle_time_tool', label: 'Cycle time: changed (new value entered) or confirmed unchanged',
        value_kind: 'cycle_time', hint: 'Measured in validation by the Tool Engineer: 39.5 s' }),
      apqp('process_stable_apqp', 'Process stable: SPC Cm > 1.67', { value_kind: 'cm' }),
      apqp('surface_quality', 'Surface quality confirmed'),
    ]} />)
    expect(screen.getByText('APQP')).toBeDefined()
    expect(screen.getByText('Tool Engineer')).toBeDefined()
    expect(screen.queryByText('Process Engineer')).toBeNull()
    expect(screen.getByText('Process stable: SPC Cm > 1.67')).toBeDefined()
    expect(screen.getByText('Measured in validation by the Tool Engineer: 39.5 s')).toBeDefined()
    // an APQP member answers the APQP rows only
    expect(screen.getByTestId('release-check-process_stable_apqp-done')).toBeDefined()
    expect(screen.getByTestId('release-check-surface_quality-done')).toBeDefined()
    expect(screen.queryByTestId('release-check-cycle_time_tool-done')).toBeNull()
  })

  it('cycle time: unchanged saves the outcome, changed needs the new seconds', async () => {
    const ct = check({ key: 'cycle_time_tool', label: 'Cycle time', value_kind: 'cycle_time', hint: null })
    wrap(<ReleaseChecklist changeId={7} checks={[ct]} myDepartmentIds={[4]} canManage={false} editable />)
    fireEvent.click(screen.getByTestId('release-check-cycle_time_tool-done'))
    const confirm = screen.getByTestId('release-check-cycle_time_tool-confirm') as HTMLButtonElement
    expect(confirm.disabled).toBe(true)
    fireEvent.click(screen.getByTestId('release-check-cycle_time_tool-changed'))
    expect(confirm.disabled).toBe(true)
    const input = screen.getByTestId('release-check-cycle_time_tool-value') as HTMLInputElement
    expect(input.type).toBe('text')
    // a German decimal comma is refused and named, never saved without the value
    fireEvent.change(input, { target: { value: '38,5' } })
    expect(confirm.disabled).toBe(true)
    expect(screen.getByTestId('release-check-cycle_time_tool-value-hint').textContent).toBe(NUMBER_INPUT_HINT)
    fireEvent.change(input, { target: { value: 'abc' } })
    expect(screen.getByTestId('release-check-cycle_time_tool-value-hint').textContent).toBe(NUMBER_INPUT_INVALID)
    expect(confirm.disabled).toBe(true)
    fireEvent.change(input, { target: { value: '38.5' } })
    expect(screen.queryByTestId('release-check-cycle_time_tool-value-hint')).toBeNull()
    expect(confirm.disabled).toBe(false)
    expect(confirm.textContent).toBe('Save new cycle time')
    fireEvent.click(confirm)
    await waitFor(() => expect(changeReleaseApi.setCheck).toHaveBeenCalledWith(7, 'cycle_time_tool',
      { status: 'done', outcome: 'changed', value: 38.5 }))
    cleanup()
    wrap(<ReleaseChecklist changeId={7} checks={[ct]} myDepartmentIds={[4]} canManage={false} editable />)
    fireEvent.click(screen.getByTestId('release-check-cycle_time_tool-done'))
    fireEvent.click(screen.getByTestId('release-check-cycle_time_tool-unchanged'))
    expect(screen.queryByTestId('release-check-cycle_time_tool-value')).toBeNull()
    fireEvent.click(screen.getByTestId('release-check-cycle_time_tool-confirm'))
    await waitFor(() => expect(changeReleaseApi.setCheck).toHaveBeenCalledWith(7, 'cycle_time_tool',
      { status: 'done', outcome: 'unchanged' }))
  })

  it('process stable: Cm is optional but must be above 1.67', async () => {
    const cm = check({ key: 'process_stable_apqp', label: 'Process stable: SPC Cm > 1.67', department_id: 20,
      department_name: 'APQP', value_kind: 'cm', hint: null })
    wrap(<ReleaseChecklist changeId={7} checks={[cm]} myDepartmentIds={[20]} canManage={false} editable />)
    fireEvent.click(screen.getByTestId('release-check-process_stable_apqp-done'))
    const confirm = screen.getByTestId('release-check-process_stable_apqp-confirm') as HTMLButtonElement
    expect(confirm.disabled).toBe(false)
    const input = screen.getByTestId('release-check-process_stable_apqp-value')
    fireEvent.change(input, { target: { value: '1.5' } })
    expect(confirm.disabled).toBe(true)
    expect(screen.getByText('Cm must be above 1.67')).toBeDefined()
    // kept to 2 decimals like the backend: 1.6700001 is 1.67, not above
    fireEvent.change(input, { target: { value: '1.6700001' } })
    expect(confirm.disabled).toBe(true)
    // unreadable: named, and the answer is blocked (not saved without the Cm)
    fireEvent.change(input, { target: { value: '1,8' } })
    expect(confirm.disabled).toBe(true)
    expect(screen.getByTestId('release-check-process_stable_apqp-value-hint').textContent).toBe(NUMBER_INPUT_HINT)
    fireEvent.change(input, { target: { value: '1.9' } })
    fireEvent.click(confirm)
    await waitFor(() => expect(changeReleaseApi.setCheck).toHaveBeenCalledWith(7, 'process_stable_apqp',
      { status: 'done', value: 1.9 }))
  })

  it('shows a retired answer read-only and does not count it', () => {
    wrap(<ReleaseChecklist changeId={7} myDepartmentIds={[]} canManage editable checks={[
      check({ key: 'cycle_time_tool', label: 'Cycle time', value_kind: 'cycle_time', hint: null }),
      check({ key: 'cycle_time', label: 'Cycle time', department_id: 21,
        department_name: 'Process Engineer', status: 'done', by_name: 'Pat', note: 'Confirmed unchanged',
        value_kind: 'cycle_time', retired: true, hint: null }),
    ]} />)
    expect(screen.getByTestId('release-check-cycle_time-retired').textContent).toBe('No longer asked')
    expect(screen.queryByTestId('release-check-cycle_time-done')).toBeNull()
    expect(screen.getByText('earlier answers, no longer asked')).toBeDefined()
    expect(screen.getByTestId('release-check-cycle_time_tool-done')).toBeDefined()
    expect(screen.getByText('1 open')).toBeDefined()
  })

  it('shows the hint and no controls once the stage has moved on', () => {
    wrap(<ReleaseChecklist changeId={7} checks={[check()]} myDepartmentIds={[4]} canManage editable={false} />)
    expect(screen.getByText('Validated weight exists: 412 g')).toBeDefined()
    expect(screen.queryByTestId('release-check-weight_measured-done')).toBeNull()
  })
})

describe('LessonsStep', () => {
  afterEach(cleanup)
  beforeEach(() => { vi.clearAllMocks() })

  it('completing without lessons requires a reason', async () => {
    wrap(<LessonsStep changeId={7} lessons={{ items: [] }} canAdd canComplete />)
    const btn = screen.getByTestId('lessons-complete') as HTMLButtonElement
    expect(btn.disabled).toBe(true)
    fireEvent.change(screen.getByTestId('lessons-none-reason'), { target: { value: 'Routine index change' } })
    fireEvent.click(btn)
    await waitFor(() => expect(changeReleaseApi.completeLessons).toHaveBeenCalledWith(7, 'Routine index change'))
  })

  it('completing with a lesson needs no reason', async () => {
    wrap(<LessonsStep changeId={7} canAdd canComplete lessons={{ items: [
      { id: 1, title: 'Order steel earlier', category: 'tooling', lesson_type: 'problem', severity: 'high', status: 'in_review' },
    ] }} />)
    expect(screen.queryByTestId('lessons-none-reason')).toBeNull()
    fireEvent.click(screen.getByTestId('lessons-complete'))
    await waitFor(() => expect(changeReleaseApi.completeLessons).toHaveBeenCalledWith(7, undefined))
  })

  it('adds a lesson through the inline form', async () => {
    wrap(<LessonsStep changeId={7} lessons={{ items: [] }} canAdd canComplete={false} />)
    fireEvent.click(screen.getByTestId('lesson-add'))
    const submit = screen.getByTestId('lesson-submit') as HTMLButtonElement
    expect(submit.disabled).toBe(true)
    fireEvent.change(screen.getByTestId('lesson-title'), { target: { value: 'Steel lead time' } })
    fireEvent.change(screen.getByTestId('lesson-description'), { target: { value: 'Supplier took 6 weeks' } })
    fireEvent.click(submit)
    await waitFor(() => expect(changeReleaseApi.addLesson).toHaveBeenCalledWith(7, expect.objectContaining({
      title: 'Steel lead time', description: 'Supplier took 6 weeks', category: 'other',
    })))
    expect(screen.queryByTestId('lessons-complete')).toBeNull()
  })
})

describe('ReleaseTab', () => {
  afterEach(cleanup)
  beforeEach(() => { vi.clearAllMocks() })

  it('lists the blockers as info and keeps Release clickable (soft guard via deviation)', async () => {
    vi.mocked(changeReleaseApi.get).mockResolvedValue(state())
    const onAdvance = vi.fn()
    wrap(<ReleaseTab change={change()} departments={[]} myDepartmentIds={[]} canSeeAll canAcknowledge
      canManage onAdvance={onAdvance} advancing={false} />)
    expect((await screen.findByTestId('release-blockers')).textContent).toContain('2 open')
    expect(screen.getByTestId('release-blockers-info').textContent).toContain('deviation')
    const btn = screen.getByTestId('release-change') as HTMLButtonElement
    expect(btn.disabled).toBe(false)
    // The page's advance runs the transition; a refusal opens its DeviationBanner.
    fireEvent.click(btn)
    expect(onAdvance).toHaveBeenCalledWith('released')
  })

  it('open validation issues join the release blockers and hold the validation step', async () => {
    vi.mocked(changeReleaseApi.get).mockResolvedValue(state())
    vi.mocked(changesApi.validationState).mockResolvedValue({ departments: [{ department_id: 4, checks: [
      { check_key: 'sampled', status: 'passed' }] }] } as never)
    vi.mocked(validationIssuesApi.list).mockResolvedValueOnce([{
      id: 11, change_id: 7, number: 2, title: 'Tool cannot run', category: 'tool', severity: 3,
      description: 'x', status: 'fixing', created_by: 1, created_at: '2026-09-24T08:00:00',
      actions: [], attachments: [], escalation_level: 2,
    }] as never)
    wrap(<ReleaseTab change={change()} departments={[]} myDepartmentIds={[]} canSeeAll canAcknowledge
      canManage onAdvance={vi.fn()} advancing={false} />)
    await waitFor(() => expect(screen.getByTestId('release-blockers').textContent)
      .toContain('VI-2 open: Tool cannot run (fixing)'))
    expect(screen.getByTestId('release-blockers').textContent).toContain('Release checklist incomplete')
    expect(screen.getByTestId('release-validation-issues').textContent).toBe('1 issue open')
    expect(screen.getByTestId('issue-card-11')).toBeDefined()
    expect(screen.getByRole('link', { name: /Validation checks/ }).className).not.toContain('border-emerald-800')
  })

  it('counts validation done with only a retired row still open', async () => {
    vi.mocked(changeReleaseApi.get).mockResolvedValue(state())
    vi.mocked(changesApi.validationState).mockResolvedValue({ departments: [{ department_id: 4, checks: [
      { check_key: 'sampled', status: 'passed' },
      { check_key: 'old_check', status: 'open', retired: true },
    ] }] } as never)
    wrap(<ReleaseTab change={change()} departments={[]} myDepartmentIds={[]} canSeeAll canAcknowledge
      canManage onAdvance={vi.fn()} advancing={false} />)
    await waitFor(() => expect(screen.getByRole('link', { name: /Validation checks/ }).className)
      .toContain('border-emerald-800'))
  })

  it('disables Release only while a transition runs', async () => {
    vi.mocked(changeReleaseApi.get).mockResolvedValue(state())
    wrap(<ReleaseTab change={change()} departments={[]} myDepartmentIds={[]} canSeeAll canAcknowledge
      canManage onAdvance={vi.fn()} advancing />)
    await screen.findByTestId('release-blockers')
    expect((screen.getByTestId('release-change') as HTMLButtonElement).disabled).toBe(true)
  })

  it('releases once the server says it can', async () => {
    vi.mocked(changeReleaseApi.get).mockResolvedValue(state({
      checks: [check({ status: 'done' })], open_count: 0, can_release: true, blockers: [],
      lessons: { items: [], done_at: '2026-09-20', none_reason: 'none' },
    }))
    const onAdvance = vi.fn()
    wrap(<ReleaseTab change={change()} departments={[]} myDepartmentIds={[]} canSeeAll canAcknowledge
      canManage onAdvance={onAdvance} advancing={false} />)
    await waitFor(() => expect((screen.getByTestId('release-change') as HTMLButtonElement).disabled).toBe(false))
    fireEvent.click(screen.getByTestId('release-change'))
    expect(onAdvance).toHaveBeenCalledWith('released')
  })

  it('after release shows plan against actual and the close action', async () => {
    vi.mocked(changeReleaseApi.get).mockResolvedValue(state({ open_count: 0, can_release: false, blockers: [] }))
    const onAdvance = vi.fn()
    wrap(<ReleaseTab change={change({ status: 'released' })} departments={[]} myDepartmentIds={[]} canSeeAll
      canAcknowledge canManage onAdvance={onAdvance} advancing={false} />)
    // Baseline finish is exclusive 2026-10-11 -> last day 10 Oct 2026; actual 14 Oct 2026.
    expect((await screen.findByTestId('summary-baseline-finish')).textContent).toBe('10 Oct 2026')
    await waitFor(() => expect(screen.getByTestId('summary-actual-finish').textContent).toBe('14 Oct 2026'))
    expect(screen.getByTestId('summary-against-baseline').textContent).toBe('4 d late')
    expect(screen.getByTestId('summary-against-baseline-detail').textContent).toBe('1 task slipped')
    fireEvent.click(screen.getByTestId('close-change'))
    expect(onAdvance).toHaveBeenCalledWith('closed')
  })
})

describe('closingFigures', () => {
  const task = (over: Record<string, unknown>) => ({
    id: 1, is_idea: false, start_date: '2026-12-14', duration_days: 7, end_date: '2026-12-21', progress_pct: 0,
    baseline_start: null, baseline_finish: null, actual_finish: null, ...over,
  }) as never

  it('reads finishes like the Timing tab: a milestone sits on its day, open tasks are counted', () => {
    const f = closingFigures([
      task({ id: 1, start_date: '2026-12-14', duration_days: 7, end_date: '2026-12-21',
        baseline_start: '2026-12-07', baseline_finish: '2026-12-14', actual_finish: null }),
      // SOP milestone on 21.12: the finish is 21.12, not 20.12.
      task({ id: 2, start_date: '2026-12-21', duration_days: 0, end_date: '2026-12-21',
        baseline_start: '2026-12-21', baseline_finish: '2026-12-21' }),
      task({ id: 3, is_idea: true, start_date: '2027-01-10', duration_days: 5, end_date: '2027-01-15' }),
    ])
    expect(f.planned).toBe('2026-12-21')
    expect(f.baseline).toBe('2026-12-21')
    expect(f.actual).toBeNull()
    expect(f.open).toBe(2)
    expect(f.slipped).toBe(1)
    expect(f.slip).toBe(0)
  })

  it('reads the server end_date, not start_date + duration_days', () => {
    // A calendar-aware server can land end_date somewhere plain day-count
    // arithmetic would not (weekends, holidays); the server's figure wins.
    const f = closingFigures([
      task({ id: 1, start_date: '2026-12-14', duration_days: 5, end_date: '2026-12-23',
        baseline_start: '2026-12-14', baseline_finish: '2026-12-21' }),
    ])
    // end_date 2026-12-23 exclusive -> last day 22.12, not 2026-12-14+5=19.12.
    expect(f.planned).toBe('2026-12-22')
    expect(f.slipped).toBe(1)
  })

  it('slipped compares end_date to baseline_finish, not the recomputed span', () => {
    const f = closingFigures([
      // start+duration would land exactly on baseline_finish (no slip); the
      // server's end_date says otherwise.
      task({ id: 1, start_date: '2026-12-14', duration_days: 7, end_date: '2026-12-23',
        baseline_start: '2026-12-14', baseline_finish: '2026-12-21' }),
    ])
    expect(f.slipped).toBe(1)
  })
})
