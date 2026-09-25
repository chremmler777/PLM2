import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, cleanup, fireEvent, waitFor, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import TimingTab from './TimingTab'
import { planApi } from '../../../api/changePlan'
import type { PlanDeviation, PlanFeedback, PlanOut, TaskOut } from '../../../types/changePlan'

vi.mock('../../../api/changePlan', () => ({
  planApi: {
    get: vi.fn(), seed: vi.fn(), feedback: vi.fn(), postFeedback: vi.fn(), validateTiming: vi.fn(),
    deviations: vi.fn(), lockDeviation: vi.fn(), escalateDeviation: vi.fn(), publishPlan: vi.fn(),
    exportXml: vi.fn(), exportCsv: vi.fn(),
  },
}))
vi.mock('../plan/GanttPlanner', () => ({
  default: (p: { mode?: string; hideSeed?: boolean }) => <div data-testid="gantt-stub" data-mode={p.mode} data-hide-seed={String(!!p.hideSeed)} />,
}))
vi.mock('../BankBuildCard', () => ({
  default: (p: { canSetMode?: boolean; canPublish?: boolean; hidePublish?: boolean }) =>
    <div data-testid="bank-build-stub" data-set={String(p.canSetMode)} data-publish={String(p.canPublish)}
      data-hide-publish={String(p.hidePublish)} />,
}))
vi.mock('../ImplementationTracking', () => ({
  default: (p: { canEscalate?: boolean }) => <div data-testid="impl-stub" data-escalate={String(p.canEscalate)} />,
}))
vi.mock('sonner', () => ({ toast: { error: vi.fn(), success: vi.fn() } }))

const task = (over: Partial<TaskOut> & { id: number }): TaskOut => ({
  change_id: 7, plan: 'detailed', name: `Task ${over.id}`, lane: 'Tool Engineer', department_id: 11,
  kind: 'work', is_idea: false, start_date: '2026-10-05', duration_days: 5, end_date: '2026-10-10',
  predecessors: [], sort_order: over.id, progress_pct: 0, actual_start: null, actual_finish: null,
  baseline_start: null, baseline_finish: null, notes: null, ...over,
})

const plan = (over: Partial<PlanOut> = {}): PlanOut => ({
  plan: 'detailed', tasks: [task({ id: 1 }), task({ id: 2 })], revision: 2, baseline_set: false,
  can_edit: true, can_edit_dates: true, progress_department_ids: [],
  summary: { start: '2026-10-05', finish: '2026-10-10', duration_days: 5, buffer_days: 0, critical_ids: [], ideas: 0 },
  validation: { errors: [], warnings: [] }, deadlines: [], ...over,
})

const fb = (over: Partial<PlanFeedback> = {}): PlanFeedback => ({
  revision: 2, all_confirmed: false, validated_at: null, validated_by_name: null,
  required: [
    { department_id: 11, department_name: 'Tool Engineer', verdict: 'confirmed', note: null, by_name: 'Ann', at: '2026-09-20', stale: false },
    { department_id: 12, department_name: 'APQP', verdict: null, note: null, by_name: null, at: null, stale: false },
    { department_id: 13, department_name: 'Scheduling', verdict: 'confirmed', note: null, by_name: 'Bo', at: '2026-09-18', stale: true },
  ],
  ...over,
})

const change = (over: Record<string, unknown> = {}) => ({
  id: 7, status: 'approved', customer_relevant: true, plan_published_at: null, plan_published_by_name: null, ...over,
}) as never

const renderTab = (props: Partial<Parameters<typeof TimingTab>[0]> = {}) => render(
  <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <TimingTab change={change()} departments={[]} myDepartmentIds={[12]}
      canEditPlan canPublish={false} canSeeAll {...props} />
  </QueryClientProvider>)

describe('TimingTab', () => {
  afterEach(cleanup)
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(planApi.get).mockResolvedValue(plan())
    vi.mocked(planApi.feedback).mockResolvedValue(fb())
    vi.mocked(planApi.deviations).mockResolvedValue([])
    vi.mocked(planApi.postFeedback).mockResolvedValue({})
    vi.mocked(planApi.validateTiming).mockResolvedValue({})
  })

  it('shows a retryable error when the confirmations fail to load', async () => {
    vi.mocked(planApi.feedback).mockRejectedValue(new Error('boom'))
    renderTab()
    const err = await screen.findByTestId('timing-feedback-error')
    expect(err.textContent).toContain('Could not load confirmations')
    vi.mocked(planApi.feedback).mockResolvedValue(fb())
    fireEvent.click(err)
    await waitFor(() => expect(screen.queryByTestId('timing-feedback-error')).toBeNull())
  })

  it('offers to create the detailed plan from the quote plan when empty', async () => {
    vi.mocked(planApi.get).mockResolvedValue(plan({ tasks: [] }))
    vi.mocked(planApi.seed).mockResolvedValue(plan())
    renderTab()
    fireEvent.click(await screen.findByTestId('timing-seed'))
    await waitFor(() => expect(planApi.seed).toHaveBeenCalledWith(7, 'detailed'))
  })

  it('keeps "Validate timing" disabled and says why', async () => {
    vi.mocked(planApi.get).mockResolvedValue(plan({
      tasks: [task({ id: 1 }), task({ id: 2, is_idea: true })],
      validation: { errors: [{ code: 'cycle', message: 'Loop', task_id: 1 }], warnings: [] },
    }))
    renderTab()
    const btn = await screen.findByTestId('timing-validate') as HTMLButtonElement
    await waitFor(() => expect(screen.getByTestId('timing-blockers').textContent).toContain('APQP'))
    expect(btn.disabled).toBe(true)
    const text = screen.getByTestId('timing-blockers').textContent ?? ''
    expect(text).toContain('Fix 1 plan error')
    expect(text).toContain('Resolve 1 idea block')
    expect(text).toContain('Waiting for confirmation from APQP, Scheduling')
    expect(screen.getByTestId('timing-step-2').textContent).toContain('1 of 3 confirmed')
  })

  it('validates the timing once every team confirmed', async () => {
    vi.mocked(planApi.feedback).mockResolvedValue(fb({
      all_confirmed: true,
      required: [{ department_id: 11, department_name: 'Tool Engineer', verdict: 'confirmed', note: null, by_name: 'Ann', at: '2026-09-20', stale: false }],
    }))
    renderTab()
    const btn = await screen.findByTestId('timing-validate') as HTMLButtonElement
    await waitFor(() => expect(btn.disabled).toBe(false))
    fireEvent.click(btn)
    await waitFor(() => expect(planApi.validateTiming).toHaveBeenCalledWith(7))
    expect(screen.getByTestId('gantt-stub').dataset.mode).toBe('plan')
  })

  it('shows feedback buttons only for the departments the user belongs to', async () => {
    renderTab()
    await screen.findByTestId('feedback-row-12')
    expect(screen.getByTestId('feedback-confirm-12')).toBeTruthy()
    expect(screen.queryByTestId('feedback-confirm-11')).toBeNull()
    expect(screen.queryByTestId('feedback-concern-13')).toBeNull()
    expect(screen.getByTestId('feedback-chip-13').textContent).toBe('Plan changed after this confirmation')
    expect(screen.getByTestId('feedback-chip-12').textContent).toBe('Waiting')

    fireEvent.click(screen.getByTestId('feedback-confirm-12'))
    await waitFor(() => expect(planApi.postFeedback).toHaveBeenCalledWith(7,
      { department_id: 12, verdict: 'confirmed' }))
  })

  it('requires a note to raise a concern and shows concerns prominently', async () => {
    renderTab()
    fireEvent.click(await screen.findByTestId('feedback-concern-12'))
    const send = screen.getByTestId('feedback-concern-submit-12') as HTMLButtonElement
    expect(send.disabled).toBe(true)
    fireEvent.change(screen.getByTestId('feedback-note-12'), { target: { value: 'Gauge needs 2 more weeks' } })
    fireEvent.click(send)
    await waitFor(() => expect(planApi.postFeedback).toHaveBeenCalledWith(7,
      { department_id: 12, verdict: 'concern', note: 'Gauge needs 2 more weeks' }))

    cleanup()
    vi.mocked(planApi.feedback).mockResolvedValue(fb({ required: [
      { department_id: 12, department_name: 'APQP', verdict: 'concern', note: 'Gauge late', by_name: 'Cy', at: '2026-09-21', stale: false },
    ] }))
    renderTab()
    expect((await screen.findByTestId('feedback-concerns')).textContent).toContain('APQP: Gauge late')
  })

  it('tracks after the baseline: deviations, publish and the stage 8 panels', async () => {
    vi.mocked(planApi.get).mockResolvedValue(plan({ baseline_set: true }))
    vi.mocked(planApi.feedback).mockResolvedValue(fb({ validated_at: '2026-09-22T10:00:00', validated_by_name: 'Pia', all_confirmed: true }))
    const dev: PlanDeviation = {
      id: 5, task_id: 1, task_name: 'Tool rework', old_start: '2026-10-05', old_end: '2026-10-10',
      new_start: '2026-10-05', new_end: '2026-10-13', slip_days: 3, finish_impact_days: 3,
      reason: 'Toolmaker late', status: 'open',
    }
    vi.mocked(planApi.deviations).mockResolvedValue([dev])
    vi.mocked(planApi.lockDeviation).mockResolvedValue({})
    vi.mocked(planApi.escalateDeviation).mockResolvedValue({})
    vi.mocked(planApi.publishPlan).mockResolvedValue({})
    renderTab({ change: change({ status: 'in_implementation' }), canPublish: true,
      canDecideDeviation: true, canSetBankBuild: true })

    const row = await screen.findByTestId('deviation-5')
    expect(row.textContent).toContain('09.10.2026')
    expect(row.textContent).toContain('12.10.2026')
    expect(screen.getByTestId('deviation-slip-5').className).toContain('text-red-300')
    expect(screen.getByTestId('gantt-stub').dataset.mode).toBe('track')
    expect(screen.getByTestId('impl-stub').dataset.escalate).toBe('true')
    expect(screen.getByTestId('bank-build-stub').dataset.set).toBe('true')
    expect(screen.queryByTestId('feedback-confirm-12')).toBeNull()

    fireEvent.click(screen.getByTestId('deviation-lock-5'))
    fireEvent.click(screen.getByTestId('deviation-lock-confirm-5'))
    await waitFor(() => expect(planApi.lockDeviation).toHaveBeenCalledWith(7, 5, undefined))

    fireEvent.click(screen.getByTestId('deviation-escalate-5'))
    const dialog = await screen.findByRole('dialog')
    fireEvent.change(within(dialog).getByRole('textbox'), { target: { value: 'SOP moves 3 days' } })
    fireEvent.click(within(dialog).getByText('Escalate'))
    await waitFor(() => expect(planApi.escalateDeviation).toHaveBeenCalledWith(7, 5, 'SOP moves 3 days'))
    // Publishing is an approved-stage act.
    expect(screen.queryByTestId('timing-publish')).toBeNull()
  })

  it('publishes only at approved, with a bank-build mode and a validated timing', async () => {
    vi.mocked(planApi.get).mockResolvedValue(plan({ baseline_set: true }))
    vi.mocked(planApi.feedback).mockResolvedValue(fb({ validated_at: '2026-09-22T10:00:00', all_confirmed: true }))
    vi.mocked(planApi.publishPlan).mockResolvedValue({})
    renderTab({
      change: change({ bank_build_mode: 'running_change', timing_validated_at: '2026-09-22T10:00:00' }),
      canPublish: true,
    })
    fireEvent.click(await screen.findByTestId('timing-publish'))
    await waitFor(() => expect(planApi.publishPlan).toHaveBeenCalledWith(7))
    // The bank-build card never shows a second publish button inside the tab.
    expect(screen.getByTestId('bank-build-stub').dataset.hidePublish).toBe('true')
  })

  it('asks for the bank-build mode before publishing', async () => {
    vi.mocked(planApi.get).mockResolvedValue(plan({ baseline_set: true }))
    vi.mocked(planApi.feedback).mockResolvedValue(fb({ validated_at: '2026-09-22T10:00:00', all_confirmed: true }))
    renderTab({ change: change({ timing_validated_at: '2026-09-22T10:00:00' }), canPublish: true })
    expect((await screen.findByTestId('timing-publish-needs-mode')).textContent)
      .toContain('Set how the change reaches the line first')
    expect(screen.queryByTestId('timing-publish')).toBeNull()
  })

  it('never offers to publish an internal change: a neutral line instead', async () => {
    vi.mocked(planApi.get).mockResolvedValue(plan({ baseline_set: true }))
    vi.mocked(planApi.feedback).mockResolvedValue(fb({ validated_at: '2026-09-22T10:00:00', all_confirmed: true }))
    renderTab({
      change: change({ customer_relevant: false, bank_build_mode: 'running_change', timing_validated_at: '2026-09-22T10:00:00' }),
      canPublish: true,
    })
    expect((await screen.findByTestId('timing-validated-internal')).textContent).toContain('Timing validated')
    expect(screen.queryByTestId('timing-publish')).toBeNull()
    cleanup()
    renderTab({ change: change({ customer_relevant: false, timing_validated_at: '2026-09-22T10:00:00' }), canPublish: true })
    const hint = (await screen.findByTestId('timing-publish-needs-mode')).textContent ?? ''
    expect(hint).toContain('before implementation starts')
    expect(hint).not.toContain('customer')
  })

  it('keeps team confirmation open while the feedback is still loading', async () => {
    vi.mocked(planApi.feedback).mockReturnValue(new Promise(() => {}))
    renderTab()
    await waitFor(() => expect(screen.getByTestId('timing-step-1').dataset.state).toBe('done'))
    expect(screen.getByTestId('timing-step-2').dataset.state).toBe('current')
    expect(screen.getByTestId('timing-step-2').textContent).toContain('Loading confirmations')
    expect(screen.getByTestId('timing-step-3').dataset.state).toBe('todo')
  })

  it('gives the bank-build mode to canSetBankBuild, not to every plan editor (Sales)', async () => {
    renderTab({ canEditPlan: true, canSetBankBuild: false })
    expect((await screen.findByTestId('bank-build-stub')).dataset.set).toBe('false')
    cleanup()
    renderTab({ canEditPlan: false, canSetBankBuild: true })
    expect((await screen.findByTestId('bank-build-stub')).dataset.set).toBe('true')
  })

  it('lets an admin answer for any department', async () => {
    renderTab({ myDepartmentIds: [], isAdmin: true })
    await screen.findByTestId('feedback-row-12')
    expect(screen.getByTestId('feedback-confirm-12')).toBeTruthy()
    expect(screen.getByTestId('feedback-concern-11')).toBeTruthy()
    cleanup()
    renderTab({ myDepartmentIds: [] })
    await screen.findByTestId('feedback-row-12')
    expect(screen.queryByTestId('feedback-confirm-12')).toBeNull()
  })

  it('marks team confirmation done when no team needs to confirm, and names step 3 by its state', async () => {
    vi.mocked(planApi.feedback).mockResolvedValue(fb({ required: [], all_confirmed: true }))
    renderTab()
    await waitFor(() => expect(screen.getByTestId('timing-step-2').dataset.state).toBe('done'))
    expect(screen.getByTestId('timing-step-3').dataset.state).toBe('current')
    expect(screen.getByTestId('timing-step-3').textContent).toContain('Validate timing')
    cleanup()
    vi.mocked(planApi.get).mockResolvedValue(plan({ baseline_set: true }))
    vi.mocked(planApi.feedback).mockResolvedValue(fb({ validated_at: '2026-09-22T10:00:00', all_confirmed: true }))
    renderTab()
    await waitFor(() => expect(screen.getByTestId('timing-step-3').dataset.state).toBe('done'))
    expect(screen.getByTestId('timing-step-3').textContent).toContain('Timing validated')
    expect(screen.getByTestId('timing-step-3').textContent).toContain('22.09.2026')
  })

  it('hides deviation decisions from plan editors who may not decide (Scheduling)', async () => {
    vi.mocked(planApi.get).mockResolvedValue(plan({ baseline_set: true }))
    vi.mocked(planApi.deviations).mockResolvedValue([{
      id: 5, task_id: 1, task_name: 'Tool rework', old_start: '2026-10-05', old_end: '2026-10-10',
      new_start: '2026-10-05', new_end: '2026-10-13', slip_days: 3, finish_impact_days: 0,
      reason: 'x', status: 'open',
    }])
    renderTab({ canEditPlan: true, canDecideDeviation: false })
    await screen.findByTestId('deviation-5')
    expect(screen.queryByTestId('deviation-lock-5')).toBeNull()
    expect(screen.queryByTestId('impl-stub')).toBeNull() // still approved
  })

  it('F18: no lock or escalate once the change is released', async () => {
    vi.mocked(planApi.get).mockResolvedValue(plan({ baseline_set: true }))
    vi.mocked(planApi.deviations).mockResolvedValue([{
      id: 5, task_id: 1, task_name: 'Tool rework', old_start: '2026-10-05', old_end: '2026-10-10',
      new_start: '2026-10-05', new_end: '2026-10-13', slip_days: 3, finish_impact_days: 0,
      reason: 'x', status: 'open',
    }])
    renderTab({ change: change({ status: 'released' }), canDecideDeviation: true })
    await screen.findByTestId('deviation-5')
    expect(screen.queryByTestId('deviation-lock-5')).toBeNull()
    expect(screen.queryByTestId('deviation-escalate-5')).toBeNull()
  })

  it('F19: the Gantt hides its own seed button (the card above creates the plan)', async () => {
    vi.mocked(planApi.get).mockResolvedValue(plan())
    renderTab({ canEditPlan: true })
    expect((await screen.findByTestId('gantt-stub')).dataset.hideSeed).toBe('true')
  })
})
