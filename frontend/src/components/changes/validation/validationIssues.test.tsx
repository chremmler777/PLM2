import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, cleanup, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import type { IssueOut } from '../../../types/validationIssue'
import { validationIssuesApi } from '../../../api/validationIssues'
import { changesApi } from '../../../api/changes'
import { issueActs, issueSteps, primaryAct, workingDaysBetween, categoryForCheck } from './issueModel'
import IssueCard from './IssueCard'
import RouteDialog, { routeConsequences } from './RouteDialog'
import CustomerDecisionForm from './CustomerDecisionForm'
import EscalationBadge from './EscalationBadge'
import RecoverySummary, { recoverySentence } from './RecoverySummary'
import { issueBlockers } from './IssuesPanel'
import ValidationPanel from '../ValidationPanel'
import { releaseBlockers } from '../release/ReleaseTab'
import { issueWaits, resolveWaitStates } from '../../../lib/waitStates'

vi.mock('../../../api/validationIssues', () => ({
  validationIssuesKey: (id: number) => ['change', id, 'validation-issues'],
  validationIssuesApi: {
    list: vi.fn(), create: vi.fn(), update: vi.fn(), contain: vi.fn(), rootCause: vi.fn(),
    route: vi.fn(), customer: vi.fn(), cost: vi.fn(), addAction: vi.fn(), actionDone: vi.fn(),
    close: vi.fn(), escalate: vi.fn(), acknowledge: vi.fn(),
  },
}))
vi.mock('../../../api/changes', () => ({
  changesApi: {
    validationState: vi.fn(), setValidationCheck: vi.fn(), acknowledgeWeightDelta: vi.fn(),
    transition: vi.fn(), uploadAttachment: vi.fn(),
  },
}))
vi.mock('../../../api/changePlan', () => ({ planApi: { get: vi.fn().mockResolvedValue({ tasks: [] }) } }))
vi.mock('sonner', () => ({ toast: { error: vi.fn(), success: vi.fn() } }))

const departments = [{ id: 2, name: 'Development' }, { id: 4, name: 'Tool Shop' }]

const issue = (over: Partial<IssueOut> = {}): IssueOut => ({
  id: 11, change_id: 7, number: 2, title: 'Tool cannot run', category: 'tool', severity: 2,
  department_id: 4, department_name: 'Tool Shop', description: 'Slide jams at 40 strokes',
  status: 'open', created_by: 5, created_by_name: 'Rita Raiser', created_at: '2026-09-24T08:00:00',
  actions: [], attachments: [], escalation_level: 1, escalations: [], ...over,
})

const wrap = (ui: React.ReactElement) => render(
  <MemoryRouter>
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>{ui}</QueryClientProvider>
  </MemoryRouter>)

afterEach(cleanup)
beforeEach(() => {
  vi.clearAllMocks()
  for (const fn of Object.values(validationIssuesApi)) vi.mocked(fn).mockResolvedValue({} as never)
  vi.mocked(validationIssuesApi.list).mockResolvedValue([])
})

describe('issue stepper', () => {
  const states = (i: IssueOut) => Object.fromEntries(issueSteps(i).map((s) => [s.key, s.state]))

  it('a fresh issue: raised done, containment current, the rest to do', () => {
    expect(states(issue())).toEqual({
      raised: 'done', contained: 'current', root_cause: 'todo', route: 'todo',
      fixing: 'todo', revalidation: 'todo', closed: 'todo',
    })
  })

  it('a fix route in progress: fixing current', () => {
    expect(states(issue({
      status: 'fixing', contained_at: '2026-09-24', root_cause_at: '2026-09-25', route: 'internal_rework',
      route_decided_at: '2026-09-25', actions: [{ id: 1, description: 'Rework slide', status: 'open' }],
    }))).toMatchObject({ contained: 'done', root_cause: 'done', route: 'done', fixing: 'current', revalidation: 'todo' })
  })

  it('all actions done: re-validation current', () => {
    expect(states(issue({
      status: 'revalidation', contained_at: 'x', root_cause_at: 'x', route: 'supplier_rework', route_decided_at: 'x',
      actions: [{ id: 1, description: 'a', status: 'done' }],
    }))).toMatchObject({ fixing: 'done', revalidation: 'current', closed: 'todo' })
  })

  it('an accepted concession skips root cause, fixing and re-validation', () => {
    const steps = issueSteps(issue({
      status: 'accepted', contained_at: 'x', route: 'customer_concession', route_decided_at: 'x',
    }))
    expect(Object.fromEntries(steps.map((s) => [s.key, s.state]))).toMatchObject({
      root_cause: 'skipped', fixing: 'skipped', revalidation: 'skipped', closed: 'done',
    })
    expect(steps[steps.length - 1].label).toBe('Accepted')
  })

  it('renders data-state per step', () => {
    wrap(<IssueCard changeId={7} changeStatus="in_validation" issue={issue()} viewer={{}} departments={departments} />)
    expect(screen.getByTestId('issue-step-11-contained').getAttribute('data-state')).toBe('current')
    expect(screen.getByTestId('issue-step-11-contained').getAttribute('aria-current')).toBe('step')
    expect(screen.getByTestId('issue-step-11-raised').getAttribute('aria-current')).toBeNull()
    expect(screen.getByTestId('issue-stepper-11').getAttribute('aria-label')).toMatch(/^Progress of issue VI-\d+$/)
  })
})

describe('raise from a failed check', () => {
  it('prefills category, owner department and description from the check', async () => {
    vi.mocked(changesApi.validationState).mockResolvedValue({
      departments: [{ department_id: 4, checks: [{
        check_key: 'weight', label_en: 'Weight', status: 'failed', note: '+30 g over the estimate', value: 442,
      }] }],
      weight_delta_g: null,
    } as never)
    wrap(<ValidationPanel changeId={7} status="in_validation" departments={departments}
      myDepartmentIds={[4]} canSeeAll={false} />)
    fireEvent.click(await screen.findByTestId('validation-raise-4-weight'))
    expect((screen.getByTestId('raise-title') as HTMLInputElement).value).toBe('Weight: failed')
    expect((screen.getByTestId('raise-category') as HTMLSelectElement).value).toBe('material_weight')
    expect((screen.getByTestId('raise-department') as HTMLSelectElement).value).toBe('4')
    expect((screen.getByTestId('raise-description') as HTMLTextAreaElement).value).toBe('+30 g over the estimate')
    fireEvent.click(screen.getByTestId('raise-submit'))
    await waitFor(() => expect(validationIssuesApi.create).toHaveBeenCalledWith(7, expect.objectContaining({
      category: 'material_weight', department_id: 4, check_key: 'weight', check_department_id: 4, severity: 2,
    })))
  })

  it('a failed check with an open issue links it instead of offering a second', async () => {
    vi.mocked(changesApi.validationState).mockResolvedValue({
      departments: [{ department_id: 4, checks: [{ check_key: 'sampled', status: 'failed', note: 'x' }] }],
    } as never)
    vi.mocked(validationIssuesApi.list).mockResolvedValue([issue({ check_key: 'sampled', check_department_id: 4 })])
    wrap(<ValidationPanel changeId={7} status="in_validation" departments={departments}
      myDepartmentIds={[4]} canSeeAll={false} />)
    expect((await screen.findByTestId('validation-issue-link-4-sampled')).textContent).toContain('VI-2 open')
    expect(screen.queryByTestId('validation-raise-4-sampled')).toBeNull()
  })

  it('maps check keys to categories', () => {
    expect(categoryForCheck('cycle_time')).toBe('cycle_time')
    expect(categoryForCheck('measured')).toBe('dimensional')
    expect(categoryForCheck('sampled')).toBe('tool')
    expect(categoryForCheck('packaging_validated')).toBe('packaging')
    expect(categoryForCheck('revision_bump')).toBe('documentation')
    expect(categoryForCheck('whatever')).toBe('other')
  })
})

describe('route dialog', () => {
  const ready = issue({ contained_at: 'x', root_cause_at: 'x', status: 'contained' })
  const open = (i = ready, status = 'in_validation') => wrap(
    <RouteDialog open changeId={7} changeStatus={status} issue={i} departments={departments} onClose={() => {}} />)

  it('fix routes warn about the loop back and need a fix action', async () => {
    open()
    fireEvent.click(screen.getByTestId('route-option-internal_rework'))
    expect(screen.getByTestId('route-loopback').textContent).toMatch(/goes back to implementation/)
    fireEvent.change(screen.getByTestId('route-reason'), { target: { value: 'Slide worn' } })
    expect((screen.getByTestId('route-submit') as HTMLButtonElement).disabled).toBe(true)
    expect(screen.getByTestId('route-missing').textContent).toBe('Add at least one fix action')
    fireEvent.change(screen.getByTestId('route-action-0'), { target: { value: 'Rework slide' } })
    fireEvent.click(screen.getByTestId('route-submit'))
    await waitFor(() => expect(validationIssuesApi.route).toHaveBeenCalledWith(7, 11, expect.objectContaining({
      route: 'internal_rework', reason: 'Slide worn', actions: [{ description: 'Rework slide', department_id: 4 }],
    })))
  })

  it('the fix action due date is typed dd.mm.yyyy (no native picker) and sent as ISO', async () => {
    open()
    fireEvent.click(screen.getByTestId('route-option-internal_rework'))
    fireEvent.change(screen.getByTestId('route-reason'), { target: { value: 'Slide worn' } })
    fireEvent.change(screen.getByTestId('route-action-0'), { target: { value: 'Rework slide' } })
    const due = screen.getByLabelText('Due date') as HTMLInputElement
    expect(due.type).toBe('text')
    fireEvent.change(due, { target: { value: '05.10.2030' } })
    fireEvent.click(screen.getByTestId('route-submit'))
    await waitFor(() => expect(validationIssuesApi.route).toHaveBeenCalledWith(7, 11, expect.objectContaining({
      actions: [{ description: 'Rework slide', department_id: 4, due_date: '2030-10-05' }],
    })))
  })

  it('no loop back warning when the change is already in implementation', () => {
    expect(routeConsequences('design_change', ready, 'in_implementation').loopBack).toBeNull()
    expect(routeConsequences('design_change', ready, 'in_validation').loopBack).toMatch(/VI-2: Tool cannot run/)
  })

  it('supplier rework needs the supplier', () => {
    open()
    fireEvent.click(screen.getByTestId('route-option-supplier_rework'))
    fireEvent.change(screen.getByTestId('route-reason'), { target: { value: 'r' } })
    fireEvent.change(screen.getByTestId('route-action-0'), { target: { value: 'a' } })
    expect(screen.getByTestId('route-missing').textContent).toBe('Name the supplier')
  })

  it('design change informs the customer by default', () => {
    open()
    fireEvent.click(screen.getByTestId('route-option-design_change'))
    expect(screen.getByTestId('route-inform').getAttribute('aria-checked')).toBe('true')
  })

  it('a concession says the customer mail is required and needs no action or root cause', async () => {
    open(issue({ contained_at: 'x' }))
    expect((screen.getByTestId('route-option-internal_rework') as HTMLButtonElement).disabled).toBe(true)
    fireEvent.click(screen.getByTestId('route-option-customer_concession'))
    expect(screen.getByTestId('route-consequences').textContent).toMatch(/customer mail filed into this issue/)
    expect(screen.queryByTestId('route-loopback')).toBeNull()
    expect(screen.queryByTestId('route-actions')).toBeNull()
    fireEvent.change(screen.getByTestId('route-reason'), { target: { value: 'Cosmetic only' } })
    fireEvent.click(screen.getByTestId('route-submit'))
    await waitFor(() => expect(validationIssuesApi.route).toHaveBeenCalledWith(7, 11,
      { route: 'customer_concession', reason: 'Cosmetic only', customer_inform: true }))
  })

  it('a follow-up change says the issue is transferred', () => {
    open()
    fireEvent.click(screen.getByTestId('route-option-follow_up_change'))
    expect(screen.getByTestId('route-consequences').textContent).toMatch(/transferred and no longer holds up the release/)
  })

  it('severity 3 without containment blocks every route', () => {
    open(issue({ severity: 3, root_cause_at: 'x' }))
    for (const r of ['internal_rework', 'customer_concession', 'follow_up_change']) {
      expect((screen.getByTestId(`route-option-${r}`) as HTMLButtonElement).disabled).toBe(true)
    }
  })
})

describe('4-eyes', () => {
  it('the raiser (PM) sees the route act disabled with the reason', () => {
    const i = issue({ contained_at: 'x', root_cause_at: 'x', status: 'contained', created_by: 5 })
    const viewer = { id: 5, canManage: true, myDepartmentIds: [] }
    expect(issueActs(i, viewer)).not.toContain('route')
    wrap(<IssueCard changeId={7} changeStatus="in_validation" issue={i} viewer={viewer} departments={departments} />)
    const btn = screen.getByTestId('issue-primary-11') as HTMLButtonElement
    expect(btn.disabled).toBe(true)
    expect(btn.textContent).toBe('Decide the route')
    expect(screen.getByTestId('issue-four-eyes-11').textContent).toMatch(/another PM or the lead decides/)
  })

  it('another PM gets it as the primary act; an admin raiser too', () => {
    const i = issue({ contained_at: 'x', root_cause_at: 'x', status: 'contained', created_by: 5 })
    expect(primaryAct(issueActs(i, { id: 6, canManage: true }))).toBe('route')
    expect(primaryAct(issueActs(i, { id: 5, canManage: true, isAdmin: true }))).toBe('route')
  })

  it('the backend next_acts win and pick the primary button', () => {
    wrap(<IssueCard changeId={7} changeStatus="in_validation" viewer={{}} departments={departments}
      issue={issue({ next_acts: ['attach', 'root_cause', 'cost'] })} />)
    expect(screen.getByTestId('issue-primary-11').getAttribute('data-act')).toBe('root_cause')
  })
})

describe('customer decision', () => {
  const concession = issue({ route: 'customer_concession', customer_inform: true, status: 'route_decided' })

  it('accepting a concession needs the customer mail filed into the issue', () => {
    wrap(<CustomerDecisionForm changeId={7} issue={concession} />)
    fireEvent.click(screen.getByTestId('customer-decision-accept_deviation'))
    fireEvent.change(screen.getByTestId('customer-note'), { target: { value: 'Mr. K agreed on the phone' } })
    expect((screen.getByTestId('customer-submit') as HTMLButtonElement).disabled).toBe(true)
    expect(screen.getByTestId('customer-blocked').textContent).toBe('File the customer mail into this issue first')
  })

  it('with the mail filed it saves, with the concession end date', async () => {
    const withMail = { ...concession, attachments: [{ id: 3, filename: 'ok.msg', kind: 'customer_email', created_at: '2026-09-25T10:00:00' }] } as IssueOut
    wrap(<CustomerDecisionForm changeId={7} issue={withMail} />)
    fireEvent.click(screen.getByTestId('customer-decision-accept_deviation'))
    fireEvent.change(screen.getByTestId('customer-note'), { target: { value: 'Accepted in writing' } })
    fireEvent.change(screen.getByTestId('customer-concession-until').querySelector('input')!, { target: { value: '2026-12-31' } })
    fireEvent.click(screen.getByTestId('customer-submit'))
    await waitFor(() => expect(validationIssuesApi.customer).toHaveBeenCalledWith(7, 11, {
      decision: 'accept_deviation', note: 'Accepted in writing', concession_until: '2026-12-31',
    }))
  })

  it('new timing needs the new release date and sends it', async () => {
    wrap(<CustomerDecisionForm changeId={7} issue={issue({ customer_inform: true })} releaseDueDate="2026-11-03" />)
    fireEvent.click(screen.getByTestId('customer-decision-new_timing'))
    fireEvent.change(screen.getByTestId('customer-note'), { target: { value: 'New SOP agreed' } })
    expect(screen.getByTestId('customer-blocked').textContent).toBe('Enter the new release date')
    expect(screen.getByTestId('issue-customer-form-11').textContent).toContain('Now 3 Nov 2026')
    fireEvent.change(screen.getByTestId('customer-new-date').querySelector('input')!, { target: { value: '2026-11-20' } })
    fireEvent.click(screen.getByTestId('customer-submit'))
    await waitFor(() => expect(validationIssuesApi.customer).toHaveBeenCalledWith(7, 11, {
      decision: 'new_timing', note: 'New SOP agreed', new_release_due_date: '2026-11-20',
    }))
  })
})

describe('cost visibility', () => {
  it('cost roles see the amount, others only that a cost is set', () => {
    const i = issue({ extra_cost: 1250.5, cost_bearer: 'supplier', cost_set: true, currency: 'EUR' })
    wrap(<IssueCard changeId={7} changeStatus="in_validation" issue={i} viewer={{ canSeeCosts: true }} departments={departments} />)
    expect(screen.getByTestId('issue-cost-11').textContent).toBe('1,250.50 EUR, Supplier pays')
    cleanup()
    wrap(<IssueCard changeId={7} changeStatus="in_validation" viewer={{}} departments={departments}
      issue={issue({ extra_cost: null, cost_bearer: 'supplier', cost_set: true })} />)
    expect(screen.getByTestId('issue-cost-11').textContent).toBe('Cost set, Supplier pays')
  })
})

describe('escalation', () => {
  it('badge colors per level', () => {
    const { container } = render(<><EscalationBadge level={1} /><EscalationBadge level={2} /><EscalationBadge level={3} /></>)
    expect(screen.getByTestId('escalation-badge-l1').className).toContain('slate')
    expect(screen.getByTestId('escalation-badge-l2').className).toContain('amber')
    expect(screen.getByTestId('escalation-badge-l3').className).toContain('rose')
    expect(container.textContent).toContain('Level 3 (management and customer)')
  })

  it('acknowledge from the history and as the primary act', async () => {
    const i = issue({
      escalation_level: 2, next_acts: ['acknowledge', 'contain'],
      escalations: [{ id: 91, level: 2, reason: 'Severity 3', notified: 'PM, lead, Sales', created_at: '2026-09-24T09:00:00', can_acknowledge: true }],
    })
    wrap(<IssueCard changeId={7} changeStatus="in_validation" issue={i} viewer={{}} departments={departments} />)
    expect(screen.getAllByTestId('escalation-badge-l2').length).toBeGreaterThan(0)
    expect(screen.getByTestId('issue-primary-11').textContent).toBe('Acknowledge escalation')
    fireEvent.click(screen.getByTestId('escalation-ack-91'))
    await waitFor(() => expect(validationIssuesApi.acknowledge).toHaveBeenCalledWith(7, 11, 91))
  })

  it('an acknowledged row shows who, without the button', () => {
    const i = issue({ escalation_level: 2, escalations: [{ id: 91, level: 2, reason: 'r', created_at: '2026-09-24T09:00:00',
      acknowledged_at: '2026-09-25T09:00:00', acknowledged_by_name: 'Paul PM', can_acknowledge: false }] })
    wrap(<IssueCard changeId={7} changeStatus="in_validation" issue={i} viewer={{}} departments={departments} />)
    expect(screen.getByTestId('escalation-acked-91').textContent).toContain('Paul PM')
    expect(screen.queryByTestId('escalation-ack-91')).toBeNull()
  })
})

describe('recovery summary', () => {
  it('counts working days itself when the server sends none', () => {
    // Fri 13.11 -> Wed 25.11: 8 working days; Thu 19.11 -> Wed 25.11: 4.
    expect(workingDaysBetween('2026-11-13', '2026-11-25')).toBe(8)
    expect(workingDaysBetween('2026-11-25', '2026-11-13')).toBe(-8)
    expect(workingDaysBetween('2026-11-14', '2026-11-16')).toBe(1)
    const r = { summary_task_id: 501, finish: '2026-11-14', plan_finish: '2026-11-25',
      baseline_finish: '2026-11-13', release_due_date: '2026-11-19' }
    expect(recoverySentence(r)).toBe('Recovery ends 14 Nov, the plan finish moves +8 wd, 4 wd after the release deadline')
  })

  it('shows the server figures and links the recovery in the plan', () => {
    wrap(<RecoverySummary changeId={7} recovery={{ summary_task_id: 501, finish: '2026-11-14', plan_finish: '2026-11-25',
      baseline_finish: '2026-11-12', release_due_date: '2026-11-30', slip_baseline_wd: 9, slip_deadline_wd: -3 }} />)
    expect(screen.getByTestId('recovery-plan-finish-sub').textContent).toBe('+9 wd vs baseline 12 Nov')
    expect(screen.getByTestId('recovery-deadline-sub').textContent).toBe('3 wd to spare')
    expect(screen.getByTestId('recovery-sentence').textContent).toBe(
      'Recovery ends 14 Nov, the plan finish moves +9 wd, 3 wd before the release deadline.')
    expect(screen.getByTestId('recovery-open-plan').getAttribute('href')).toBe('/changes/7?tab=timing&task=501')
  })
})

describe('release blockers and waits', () => {
  const open2 = issue({ status: 'fixing' })
  const closed = issue({ id: 12, number: 3, status: 'closed', title: 'Label' })

  it('release blockers list each open issue unless the guard names them', () => {
    expect(issueBlockers([open2, closed])).toEqual(['VI-2 open: Tool cannot run (fixing)'])
    expect(releaseBlockers(['Release checklist incomplete: 2 open'], [open2, closed]))
      .toEqual(['VI-2 open: Tool cannot run (fixing)', 'Release checklist incomplete: 2 open'])
    expect(releaseBlockers(['1 validation issue open'], [open2])).toEqual(['1 validation issue open'])
  })

  it('the cockpit names the highest escalation and each open issue', () => {
    const l3 = issue({
      id: 13, number: 4, title: 'Tool cannot run', status: 'fixing', escalation_level: 3, customer_inform: true,
      attachments: [{ id: 1, filename: 'm.msg', kind: 'customer_email', created_at: '2026-09-25T10:00:00' }] as IssueOut['attachments'],
    })
    const waits = issueWaits([open2, l3, closed])
    expect(waits[0]).toMatchObject({ key: 'issue-escalation', level: 3, tab: 'release',
      text: 'Escalation L3: VI-4 Tool cannot run, customer informed 25 Sep' })
    expect(waits.slice(1).map((w) => w.text)).toEqual(['VI-2 open: Tool cannot run (fixing)', 'VI-4 open: Tool cannot run (fixing)'])
  })

  it('level 1 only: no escalation line; the guard\'s own issue line is not repeated', () => {
    const waits = resolveWaitStates({ status: 'in_validation', customer_relevant: true } as never, [], String, [], {}, null, null,
      { releaseBlockers: ['1 validation issue open', 'Release checklist incomplete: 2 open'], validationIssues: [open2] })
    expect(waits.map((w) => w.text)).toEqual(['VI-2 open: Tool cannot run (fixing)', 'Release checklist incomplete: 2 open'])
  })

  it('open issues still wait during the loop back to implementation', () => {
    const waits = resolveWaitStates({ status: 'in_implementation', customer_relevant: true } as never, [], String, [], {}, null, null,
      { validationIssues: [issue({ status: 'fixing', escalation_level: 2,
        escalations: [{ id: 1, level: 2, reason: 'overdue', created_at: '2026-09-23T08:00:00' }] })] })
    expect(waits[0].text).toBe('Escalation L2: VI-2 Tool cannot run, since 23 Sep, not acknowledged')
  })
})
