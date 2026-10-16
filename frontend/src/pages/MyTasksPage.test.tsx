import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import MyTasksPage from './MyTasksPage'
import { changesApi } from '../api/changes'
import { t } from '../i18n/cmLabels'

// MyTasksPage fetches workflow tasks via useMyTasks -> workflowApi.getMyTasks ->
// client.get('/v1/workflow-instances/my-tasks'); departments + SEP + lessons all
// go through the same axios client (default export). changesApi is a separate module.
const clientMocks = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  patch: vi.fn(),
}))
vi.mock('../api/client', () => ({ default: clientMocks, API_BASE_URL: '' }))
vi.mock('../api/changes', () => ({
  changesApi: { myTasks: vi.fn().mockResolvedValue([]), acceptAssessment: vi.fn() },
}))

const myTask = (over: Record<string, unknown>) => ({
  task_id: 1, instance_id: 9, status: 'active', is_actionable: true,
  rasic_letter: 'R', department_name: 'IE', step_name: 'do it',
  stage_order: 1, stage_name: 'S1', part_id: 4, part_number: 'P-1',
  part_name: 'Housing', project_id: 2, revision_id: 7, revision_name: 'ECR1.1',
  instance_started_at: '2026-07-01T00:00:00',
  owner_id: null, owner_name: null, accepted_at: null,
  due_date: '2026-06-30T00:00:00', overdue: true, mine: false,
  ...over,
})

function wrap(ui: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}><MemoryRouter>{ui}</MemoryRouter></QueryClientProvider>)
}

describe('MyTasksPage ownership', () => {
  beforeEach(() => {
    clientMocks.get.mockImplementation((url: string) => {
      if (url.includes('/workflow-instances/my-tasks'))
        return Promise.resolve({ data: [
          myTask({ task_id: 1, mine: true, owner_id: 5, owner_name: 'Eva Eng' }),
          myTask({ task_id: 2, step_name: 'unclaimed step', overdue: false,
                   due_date: '2026-07-30T00:00:00' }),
        ] })
      return Promise.resolve({ data: [] })
    })
    clientMocks.post.mockResolvedValue({ data: {} })
  })
  afterEach(cleanup)

  it('shows owner and overdue flag, and never offers to accept a task', async () => {
    // Workflow tasks are mandatory too: the row is owed whether or not anyone
    // has claimed it, so there is no "I take this one" — only a name once
    // somebody has worked it.
    wrap(<MyTasksPage />)
    expect(await screen.findByText('Eva Eng')).toBeDefined()
    expect(screen.getAllByText(/overdue/).length).toBeGreaterThan(0)
    expect(screen.queryByRole('button', { name: /accept/i })).toBeNull()
    expect(screen.getByText('unclaimed step')).toBeDefined()
    await waitFor(() => expect(clientMocks.post).not.toHaveBeenCalledWith(
      '/v1/workflow-instances/9/tasks/2/accept'))
  })
})

const navigate = vi.fn()
vi.mock('react-router-dom', async (orig) => ({
  ...(await orig<typeof import('react-router-dom')>()), useNavigate: () => navigate,
}))

/** Where the last click went, without the task card's own parameters
 *  (task=<kind>, dept=<id>), which every row link carries (L3). */
const opened = (): string => {
  const calls = navigate.mock.calls
  const url = String(calls[calls.length - 1]?.[0] ?? '')
  const [path, query = ''] = url.split('?')
  const params = new URLSearchParams(query)
  params.delete('task'); params.delete('dept')
  const rest = params.toString()
  return rest ? `${path}?${rest}` : path
}

const changeTask = (over: Record<string, unknown>) => ({
  change_id: 7, change_number: 'GB-CM-0007', title: 'Clip rattles',
  due_date: null, overdue: false, ...over,
})

describe('MyTasksPage change tasks by kind', () => {
  beforeEach(() => {
    navigate.mockClear()
    clientMocks.get.mockResolvedValue({ data: [] })
  })
  afterEach(cleanup)

  const renderWith = async (task: Record<string, unknown>) => {
    vi.mocked(changesApi.myTasks).mockResolvedValue([task] as never)
    wrap(<MyTasksPage />)
    return screen.findByText('GB-CM-0007')
  }

  it('names the project on the row, number first', async () => {
    await renderWith(changeTask({
      kind: 'impact_confirm', project_number: '1864', project_name: 'VW426 Atlas',
    }))
    expect(screen.getByTestId('task-project').textContent).toBe('1864 · VW426 Atlas')
  })

  it('names the missing capture pieces on a kickoff row and opens the overview', async () => {
    await renderWith(changeTask({ kind: 'kickoff', missing: ['description', 'attachment'] }))
    expect(screen.getByText(t('tasks.kind.kickoff'))).toBeDefined()
    const hint = screen.getByText(/Kickoff pending/)
    expect(hint.textContent).toContain(t('kickoff.description'))
    expect(hint.textContent).toContain(t('kickoff.attachment'))
    fireEvent.click(screen.getByRole('button', { name: t('tasks.open') }))
    expect(opened()).toBe('/changes/7')
  })

  it('names why a held change waits and opens its overview (C1 hold)', async () => {
    await renderWith(changeTask({ kind: 'hold_resume', status: 'on_hold', reason: 'No PO until 30 Oct' }))
    expect(screen.getByText(t('tasks.kind.hold_resume'))).toBeDefined()
    expect(screen.getByText('On hold because: No PO until 30 Oct')).toBeDefined()
    fireEvent.click(screen.getByRole('button', { name: t('tasks.open') }))
    expect(opened()).toBe('/changes/7')
  })

  it('says what scoping still owes and opens the scoping tab', async () => {
    await renderWith(changeTask({
      kind: 'scoping_wrapup', impact_confirmed: false, has_decision: false,
    }))
    const hint = screen.getByText(new RegExp(t('tasks.hint.impactOpen')))
    expect(hint.textContent).toContain(t('tasks.hint.decisionOpen'))
    fireEvent.click(screen.getByRole('button', { name: t('tasks.open') }))
    expect(opened()).toBe('/changes/7?tab=scoping')
  })

  it('reads Ready: proceed only when nothing holds proceed (HARD #7 names its owner)', async () => {
    await renderWith(changeTask({
      kind: 'scoping_wrapup', impact_confirmed: null, has_decision: false,
      open_questions: 0, waiting_on: [], holds: [{ key: 'ppap_decision', owner: 'Quality, due Thu' }],
    }))
    const hint = screen.getByText(new RegExp(t('tasks.hint.scopingHeld').replace('{x}', '')))
    expect(hint.textContent).toContain('PPAP decision (Quality, due Thu)')
    expect(hint.textContent).not.toContain(t('tasks.hint.scopingReady'))
  })

  it('A2-04: an answered question reads as the asker\'s to settle, not as waiting', async () => {
    await renderWith(changeTask({
      kind: 'scoping_wrapup', impact_confirmed: null, has_decision: false,
      open_questions: 1, waiting_on: ['Process Fri'], answered_questions: 1,
      settle_by: ['Quality'], holds: [],
    }))
    const hint = screen.getByText(/Not yet: waiting for 1 answer/)
    expect(hint.textContent).toContain('(Process Fri)')
    expect(hint.textContent).toContain('1 answered, Quality settles')
    expect(hint.textContent).not.toContain('Quality Fri')
  })

  it('reads Ready: proceed once nothing holds it', async () => {
    await renderWith(changeTask({
      kind: 'scoping_wrapup', impact_confirmed: null, has_decision: false,
      open_questions: 0, waiting_on: [], holds: [],
    }))
    expect(screen.getByText(t('tasks.hint.scopingReady'))).toBeDefined()
  })

  it('drops the settled half of a scoping wrap-up hint', async () => {
    await renderWith(changeTask({
      kind: 'scoping_wrapup', impact_confirmed: true, has_decision: false,
    }))
    const hint = screen.getByText(new RegExp(t('tasks.hint.decisionOpen')))
    expect(hint.textContent).not.toContain(t('tasks.hint.impactOpen'))
  })

  it('opens the impacted tab for an impact confirmation, with its due date and overdue mark', async () => {
    await renderWith(changeTask({
      kind: 'impact_confirm', due_date: '2026-06-01T23:59:59', overdue: true,
    }))
    expect(screen.getByText(t('tasks.hint.impact_confirm'))).toBeDefined()
    // The due cell reads like the changes list: a red "n d overdue" chip, the date under it.
    const chip = screen.getByTestId('task-due').querySelector('[data-testid="deadline-chip"]')
    expect(chip?.className).toContain('red')
    expect(chip?.textContent).toMatch(/\d+ d overdue/)
    expect(screen.getByTestId('task-due').textContent).toContain('1 Jun 2026')
    fireEvent.click(screen.getByRole('button', { name: t('tasks.open') }))
    expect(opened()).toBe('/changes/7?tab=impacted')
  })

  it('quotes the open question on an obtain-info row and opens scoping', async () => {
    await renderWith(changeTask({
      kind: 'obtain_info', reason: 'target price for the new gauge',
    }))
    expect(screen.getByText(t('tasks.kind.obtain_info'))).toBeDefined()
    expect(screen.getByText('target price for the new gauge')).toBeDefined()
    fireEvent.click(screen.getByRole('button', { name: t('tasks.open') }))
    expect(opened()).toBe('/changes/7?tab=scoping')
  })

  it('names the asking department that owns an obtain-info row (2026-10-14)', async () => {
    await renderWith(changeTask({
      kind: 'obtain_info', reason: 'tolerance class', asking_side: 'APQP',
    }))
    expect(screen.getByTestId('task-asking-side').textContent)
      .toBe(t('tasks.hint.askedBy').replace('{x}', 'APQP'))
  })

  it('owes no impact confirm on a wrap-up row while the confirm is switched off', async () => {
    await renderWith(changeTask({
      kind: 'scoping_wrapup', impact_confirmed: null, has_decision: false,
    }))
    const hint = screen.getByText(new RegExp(t('tasks.hint.decisionOpen')))
    expect(hint.textContent).not.toContain(t('tasks.hint.impactOpen'))
  })

  it('says how many questions are open when the row stands for several', async () => {
    await renderWith(changeTask({
      kind: 'obtain_info', reason: 'target price for the new gauge',
      question_count: 2, concern_id: 11,
    }))
    const hint = screen.getByText(/questions open/)
    expect(hint.textContent).toContain('2')
    expect(hint.textContent).toContain('target price for the new gauge')
  })

  it('falls back to a generic hint when the obtain-info row carries no reason', async () => {
    await renderWith(changeTask({ kind: 'obtain_info', reason: null }))
    expect(screen.getByText(t('tasks.hint.obtain_info'))).toBeDefined()
  })

  it('asks for the rejection letter first, then for the send', async () => {
    await renderWith(changeTask({ kind: 'send_rejection', has_letter: false }))
    expect(screen.getByText(t('tasks.kind.send_rejection'))).toBeDefined()
    expect(screen.getByText(t('tasks.hint.send_rejection_letter'))).toBeDefined()
    cleanup()
    await renderWith(changeTask({ kind: 'send_rejection', has_letter: true }))
    expect(screen.getByText(t('tasks.hint.send_rejection_send'))).toBeDefined()
  })

  it('sends a close-question row to scoping, quoting the answer', async () => {
    await renderWith(changeTask({
      kind: 'close_question', reason: 'customer confirmed 12.50', concern_id: 11,
    }))
    expect(screen.getByText(t('tasks.kind.close_question'))).toBeDefined()
    expect(screen.getByText('customer confirmed 12.50')).toBeDefined()
    fireEvent.click(screen.getByRole('button', { name: t('tasks.open') }))
    expect(opened()).toBe('/changes/7?tab=scoping')
  })

  it('counts several answers awaiting closure in one row', async () => {
    await renderWith(changeTask({
      kind: 'close_question', reason: 'customer confirmed 12.50', question_count: 3,
    }))
    const hint = screen.getByText(/questions open/)
    expect(hint.textContent).toContain('3')
    expect(hint.textContent).toContain('customer confirmed 12.50')
  })

  it('falls back to a generic hint on a close-question row with no answer text', async () => {
    await renderWith(changeTask({ kind: 'close_question', reason: null }))
    expect(screen.getByText(t('tasks.hint.close_question'))).toBeDefined()
  })

  it('sends a create-quote row to the commercial tab', async () => {
    await renderWith(changeTask({ kind: 'create_quote' }))
    expect(screen.getByText(t('tasks.kind.create_quote'))).toBeDefined()
    expect(screen.getByText(t('tasks.hint.create_quote'))).toBeDefined()
    fireEvent.click(screen.getByRole('button', { name: t('tasks.open') }))
    expect(opened()).toBe('/changes/7?tab=commercial')
  })

  it('sends a costing-input row to the costing tab', async () => {
    await renderWith(changeTask({ kind: 'costing_input' }))
    expect(screen.getByText(t('tasks.kind.costing_input'))).toBeDefined()
    expect(screen.getByText(t('tasks.hint.costing_input'))).toBeDefined()
    fireEvent.click(screen.getByRole('button', { name: t('tasks.open') }))
    expect(opened()).toBe('/changes/7?tab=costing')
  })

  it('sends a bank-build row to the implementation tab', async () => {
    await renderWith(changeTask({ kind: 'bank_build' }))
    expect(screen.getByText(t('tasks.kind.bank_build'))).toBeDefined()
    expect(screen.getByText(t('tasks.hint.bank_build'))).toBeDefined()
    fireEvent.click(screen.getByRole('button', { name: t('tasks.open') }))
    expect(opened()).toBe('/changes/7?tab=implementation')
  })

  it('sends a publish-plan row to the implementation tab', async () => {
    await renderWith(changeTask({ kind: 'publish_plan' }))
    expect(screen.getByText(t('tasks.kind.publish_plan'))).toBeDefined()
    expect(screen.getByText(t('tasks.hint.publish_plan'))).toBeDefined()
    fireEvent.click(screen.getByRole('button', { name: t('tasks.open') }))
    expect(opened()).toBe('/changes/7?tab=implementation')
  })

  it('sends a progress-report row to the implementation tab', async () => {
    await renderWith(changeTask({ kind: 'progress_report', department_id: 2, mine: true }))
    expect(screen.getByText(t('tasks.kind.progress_report'))).toBeDefined()
    expect(screen.getByText(t('tasks.hint.progress_report'))).toBeDefined()
    fireEvent.click(screen.getByRole('button', { name: t('tasks.open') }))
    expect(opened()).toBe('/changes/7?tab=implementation')
  })

  it('sends an escalate-risk row to the implementation tab', async () => {
    await renderWith(changeTask({ kind: 'escalate_risk' }))
    expect(screen.getByText(t('tasks.kind.escalate_risk'))).toBeDefined()
    expect(screen.getByText(t('tasks.hint.escalate_risk'))).toBeDefined()
    fireEvent.click(screen.getByRole('button', { name: t('tasks.open') }))
    expect(opened()).toBe('/changes/7?tab=implementation')
  })

  it('sends a validation-check row to the release tab, where the checks live (C3)', async () => {
    await renderWith(changeTask({ kind: 'validation_check', department_id: 2, mine: true }))
    expect(screen.getByText(t('tasks.kind.validation_check'))).toBeDefined()
    expect(screen.getByText(t('tasks.hint.validation_check'))).toBeDefined()
    fireEvent.click(screen.getByRole('button', { name: t('tasks.open') }))
    expect(opened()).toBe('/changes/7?tab=release')
  })

  it('sends an update-quote row to the implementation tab, where the delta is stated', async () => {
    await renderWith(changeTask({ kind: 'update_quote' }))
    expect(screen.getByText(t('tasks.kind.update_quote'))).toBeDefined()
    expect(screen.getByText(t('tasks.hint.update_quote'))).toBeDefined()
    fireEvent.click(screen.getByRole('button', { name: t('tasks.open') }))
    expect(opened()).toBe('/changes/7?tab=implementation')
  })

  it('chases the customer on a quoted change', async () => {
    await renderWith(changeTask({ kind: 'customer_response' }))
    expect(screen.getByText(t('tasks.kind.customer_response'))).toBeDefined()
    expect(screen.getByText(t('tasks.hint.customer_response'))).toBeDefined()
    fireEvent.click(screen.getByRole('button', { name: t('tasks.open') }))
    expect(opened()).toBe('/changes/7')
  })

  it('renders an unknown kind as a plain, readable row instead of crashing', async () => {
    await renderWith(changeTask({ kind: 'something_new' }))
    expect(screen.getByText('Something new')).toBeDefined()
    expect(screen.queryByText('something_new')).toBeNull()
    expect(screen.getByText('Clip rattles')).toBeDefined()
  })

  it('shows the assessment task without an accept step — tasks are mandatory', async () => {
    // The department owes the answer either way; a name appears only once
    // somebody has submitted.
    await renderWith(changeTask({
      kind: 'assessment', department_id: 2, assessment_id: 3,
      owner_id: null, owner_name: null, mine: true,
    }))
    expect(screen.queryByRole('button', { name: /accept/i })).toBeNull()
    expect(screen.getByText(t('tasks.kind.assessment'))).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Assess' }))
    expect(opened()).toBe('/changes/7')
  })

  it('tells a consulted department its row is its check items, with owner and due (R5)', async () => {
    await renderWith(changeTask({
      kind: 'assessment', department_id: 2, assessment_id: 3, rasic_letters: ['C'],
      owner_id: null, owner_name: null, mine: false, checks_open: 2,
      department_name: 'Toolshop', hint: 'Close your check items (2)',
      due_date: '2026-10-22T12:00:00',
    }))
    expect(screen.getByText(t('tasks.hint.checkItems').replace('{n}', '2')
      .replace('{x}', 'Toolshop'))).toBeTruthy()
    // it owes no submit: the button opens, it does not say Assess
    expect(screen.queryByRole('button', { name: 'Assess' })).toBeNull()
    expect(screen.getByRole('button', { name: t('tasks.open') })).toBeTruthy()
  })

  it('shows the backend brief on quote-vs-estimate rows (C25)', async () => {
    await renderWith(changeTask({
      kind: 'estimate_low', hint: 'Estimate low by 4200.00: send a supplement or absorb',
      target_tab: 'offer',
    }))
    expect(screen.getByText('Estimate low by 4200.00: send a supplement or absorb')).toBeTruthy()
  })

  it('names the owner on an assessment row: the first editor (L3)', async () => {
    await renderWith(changeTask({
      kind: 'assessment', department_id: 2, assessment_id: 3,
      owner_id: 9, owner_name: 'Toola Engineer', mine: false,
    }))
    expect(screen.getByText('Toola Engineer is working on this')).toBeTruthy()
  })
})

describe('MyTasksPage one list (spec §16)', () => {
  beforeEach(() => {
    navigate.mockClear()
    clientMocks.get.mockImplementation((url: string) => {
      if (url.includes('/workflow-instances/my-tasks'))
        return Promise.resolve({ data: [
          myTask({ task_id: 1, rasic_letter: 'R', step_name: 'Update 3D data', overdue: false,
                   due_date: '2026-10-02T00:00:00' }),
          myTask({ task_id: 2, rasic_letter: 'A', step_name: 'Update 3D data', overdue: false,
                   due_date: '2026-10-02T00:00:00' }),
        ] })
      return Promise.resolve({ data: [] })
    })
  })
  afterEach(cleanup)

  it('lists change and workflow tasks in one table, counted in the title', async () => {
    vi.mocked(changesApi.myTasks).mockResolvedValue([
      changeTask({ kind: 'kickoff', status: 'captured' })] as never)
    wrap(<MyTasksPage />)
    await screen.findByText('GB-CM-0007')
    await screen.findByText('Update 3D data')
    expect(screen.getAllByRole('table')).toHaveLength(1)
    expect(screen.getAllByTestId('task-row')).toHaveLength(2)
    expect(screen.getByTestId('task-list-title').textContent).toContain('(2)')
  })

  it('folds the R and A row of the same step into one row carrying both letters', async () => {
    vi.mocked(changesApi.myTasks).mockResolvedValue([] as never)
    wrap(<MyTasksPage />)
    await screen.findByText('Update 3D data')
    expect(screen.getAllByText('Update 3D data')).toHaveLength(1)
    expect(screen.getAllByTestId('task-rasic').map((e) => e.textContent)).toEqual(['R', 'A'])
  })

  it('folds a department\'s duplicate change-task rows into one', async () => {
    vi.mocked(changesApi.myTasks).mockResolvedValue([
      changeTask({ kind: 'assessment', department_id: 2, assessment_id: 3, rasic_letters: ['R'] }),
      changeTask({ kind: 'assessment', department_id: 2, assessment_id: 4, rasic_letters: ['A'],
                   due_date: '2026-09-01', overdue: true }),
    ] as never)
    wrap(<MyTasksPage />)
    await screen.findByText('GB-CM-0007')
    expect(screen.getAllByText('GB-CM-0007')).toHaveLength(1)
    // The earlier, overdue date wins.
    expect(screen.getByText('1 Sep 2026')).toBeDefined()
  })

  it('reads the stage from stage_label, then stage, then status', async () => {
    vi.mocked(changesApi.myTasks).mockResolvedValue([
      changeTask({ kind: 'costing_input', status: 'costing', stage: 'assessment', stage_label: 'Feasibility check' }),
      changeTask({ change_id: 8, change_number: 'GB-CM-0008', kind: 'kickoff', status: 'costing', stage: 'captured' }),
      changeTask({ change_id: 9, change_number: 'GB-CM-0009', kind: 'kickoff', status: 'quote_creation' }),
    ] as never)
    wrap(<MyTasksPage />)
    await screen.findByText('GB-CM-0009')
    const stages = screen.getAllByTestId('task-stage').map((e) => e.textContent)
    expect(stages).toContain('Feasibility check')
    expect(stages).toContain('Captured')
    expect(stages).not.toContain('Costing')
    expect(stages.length).toBe(3)
  })

  it('shows the change stage and dates as 25 Sep 2026, overdue first', async () => {
    vi.mocked(changesApi.myTasks).mockResolvedValue([
      changeTask({ kind: 'costing_input', status: 'costing', due_date: '2026-11-20' }),
      changeTask({ change_id: 8, change_number: 'GB-CM-0008', kind: 'kickoff', status: 'captured',
                   due_date: '2026-09-23', overdue: true }),
    ] as never)
    wrap(<MyTasksPage />)
    await screen.findByText('GB-CM-0008')
    const stages = screen.getAllByTestId('task-stage').map((e) => e.textContent)
    expect(stages[0]).toBe('Captured')
    expect(stages).toContain('Costing')
    expect(screen.getByText('20 Nov 2026')).toBeDefined()
    expect(screen.getByText('2 Oct 2026')).toBeDefined()
    const rows = screen.getAllByTestId('task-row')
    expect(rows[0].textContent).toContain('GB-CM-0008')
  })

  it('uses the server kind label when one is sent', async () => {
    vi.mocked(changesApi.myTasks).mockResolvedValue([
      changeTask({ kind: 'release_check', kind_label: 'Release checklist' })] as never)
    wrap(<MyTasksPage />)
    expect(await screen.findByText('Release checklist')).toBeDefined()
  })
})

describe('MyTasksPage project team (spec §18)', () => {
  beforeEach(() => {
    clientMocks.get.mockResolvedValue({ data: [] })
  })
  afterEach(cleanup)

  it('counts main rows only, lists backup rows muted with the main name', async () => {
    vi.mocked(changesApi.myTasks).mockResolvedValue([
      changeTask({ kind: 'scoping_wrapup', role: 'main' }),
      changeTask({ change_id: 8, change_number: 'GB-CM-0008', kind: 'impact_confirm',
                   role: 'backup', main_name: 'Cody Hrtyanski' }),
    ] as never)
    wrap(<MyTasksPage />)
    await screen.findByText('GB-CM-0008')
    expect(screen.getByTestId('task-list-title').textContent).toContain('(1)')
    expect(screen.getByTestId('task-list-backup-count').textContent).toBe(
      t('tasks.asBackup').replace('{n}', '1'))
    const rows = screen.getAllByTestId('task-row')
    expect(rows.map((r) => r.getAttribute('data-role'))).toEqual(['main', 'backup'])
    expect(rows[1].className).toContain('opacity-60')
    expect(screen.getByTestId('backup-chip').textContent).toContain('Cody Hrtyanski')
  })
})

describe('MyTasksPage total: the badge number', () => {
  afterEach(cleanup)

  it('counts the main task rows, the main index rows and the Finance review, never backups', async () => {
    navigate.mockClear()
    clientMocks.get.mockImplementation((url: string) => {
      if (url.includes('/intakes/my'))
        return Promise.resolve({ data: {
          triage: [
            { id: 1, part_id: 4, revision_name: 'B', part_number: 'P-1', part_name: 'Housing',
              project_name: 'X', source_label: 'Customer', received_at: '2026-09-20', role: 'main' },
            { id: 2, part_id: 5, revision_name: 'C', part_number: 'P-2', part_name: 'Cover',
              project_name: 'X', source_label: 'Customer', received_at: '2026-09-20',
              role: 'backup', main_name: 'Dev One' },
          ],
          review: [],
        } })
      if (url.includes('/cost-sheet/review-task'))
        return Promise.resolve({ data: { due: true, is_finance: true, stale: null } })
      return Promise.resolve({ data: [] })
    })
    vi.mocked(changesApi.myTasks).mockResolvedValue([
      changeTask({ kind: 'kickoff', status: 'captured' })] as never)
    wrap(<MyTasksPage />)
    await screen.findByText('GB-CM-0007')
    await screen.findByTestId('intake-task-1')
    await screen.findByTestId('cost-sheet-review-task')
    // 1 change task + 1 main index row + the Finance review; the backup index is not counted
    await waitFor(() => expect(screen.getByTestId('my-tasks-total').textContent).toBe('(3)'))
    expect(screen.getByTestId('task-list-title').textContent).toContain('(1)')
  })
})

describe('MyTasksPage: Needs you, due rules, task links (L3)', () => {
  beforeEach(() => {
    navigate.mockClear()
    clientMocks.get.mockResolvedValue({ data: [] })
  })
  afterEach(cleanup)

  it('the PM sign-off row starts with the total, the margin move and the assumptions (§7)', async () => {
    vi.mocked(changesApi.myTasks).mockResolvedValue([
      changeTask({ kind: 'sign_off', side: 'pm', offer_version: 2, needs_you: true,
        offer_total: 4200, offer_currency: 'EUR', margin_pct: 12, margin_delta_pts: -3.1, prev_version: 1,
        assumed_open: 2 }),
    ] as never)
    wrap(<MyTasksPage />)
    const row = await screen.findByText(/Sign for offer v2: 4,200.00 EUR, margin 12.0 % \(-3.1 pts vs v1\); 2 unconfirmed assumptions/)
    expect(row).toBeDefined()
  })

  it('lists decisions under Needs you, on top and by due', async () => {
    vi.mocked(changesApi.myTasks).mockResolvedValue([
      changeTask({ change_id: 8, change_number: 'GB-CM-0008', kind: 'kickoff', due_date: '2026-10-10T00:00:00' }),
      changeTask({ kind: 'sign_off', side: 'pm', offer_version: 2, needs_you: true,
                   kind_label: 'Sign off', due_date: '2026-10-20T00:00:00' }),
      changeTask({ change_id: 9, change_number: 'GB-CM-0009', kind: 'deviation_decision',
                   deviation_id: 4, needs_you: true, kind_label: 'Decide override #4',
                   reason: 'customer waits', due_date: '2026-10-16T00:00:00' }),
    ] as never)
    wrap(<MyTasksPage />)
    const section = await screen.findByTestId('needs-you')
    expect(section.textContent).toContain('Needs you (2)')
    const rows = section.querySelectorAll('[data-testid="task-row"]')
    expect(rows[0].textContent).toContain('GB-CM-0009')       // earlier due first
    expect(rows[1].textContent).toContain(t('tasks.hint.sign_off_v').replace('{v}', '2'))
    // the kickoff stays in the open list, not under Needs you
    expect(section.textContent).not.toContain('GB-CM-0008')
    expect(screen.getByText('GB-CM-0008')).toBeDefined()
  })

  it('a backup decision is not under Needs you', async () => {
    vi.mocked(changesApi.myTasks).mockResolvedValue([
      changeTask({ kind: 'sign_off', side: 'quality', needs_you: true, role: 'backup' }),
    ] as never)
    wrap(<MyTasksPage />)
    await screen.findByText('GB-CM-0007')
    expect(screen.queryByTestId('needs-you')).toBeNull()
  })

  it('says what the due date runs against and marks a late row', async () => {
    vi.useFakeTimers({ toFake: ['Date'] })
    vi.setSystemTime(new Date('2026-10-01T12:00:00'))   // the deadline is weeks out
    vi.mocked(changesApi.myTasks).mockResolvedValue([
      changeTask({ kind: 'create_quote', due_date: '2026-10-08T00:00:00', overdue: true,
                   late: true, deadline_kind: 'quote', deadline_date: '2026-10-20T00:00:00' }),
    ] as never)
    wrap(<MyTasksPage />)
    await screen.findByText('GB-CM-0007')
    expect(screen.getByTestId('task-due-note').textContent).toBe('(quote deadline 20 Oct)')
    expect(screen.getByTestId('task-late').textContent).toBe(t('tasks.late'))
    vi.useRealTimers()
  })

  it('the Late chip names the lead and the digest only when they see it', async () => {
    vi.mocked(changesApi.myTasks).mockResolvedValue([
      changeTask({ kind: 'sign_off', side: 'pm', due_date: '2026-10-08T00:00:00', late: true,
                   escalation: 'lead' }),
      changeTask({ change_id: 8, change_number: 'GB-CM-0008', kind: 'costing_input', department_id: 5,
                   due_date: '2026-10-08T00:00:00', late: true, escalation: 'lead_digest' }),
    ] as never)
    wrap(<MyTasksPage />)
    await screen.findByText('GB-CM-0008')
    const titles = screen.getAllByTestId('task-late').map((e) => e.getAttribute('title'))
    expect(titles).toContain(t('tasks.lateHintLead'))
    expect(titles).toContain(t('tasks.lateHint'))
  })

  it('A6-03: without a lead who can act the Late chip names Project Management, not the lead', async () => {
    vi.mocked(changesApi.myTasks).mockResolvedValue([
      changeTask({ kind: 'costing_input', department_id: 5, due_date: '2026-10-08T00:00:00',
                   late: true, escalation: 'pm_digest' }),
    ] as never)
    wrap(<MyTasksPage />)
    await screen.findByText('GB-CM-0007')
    const title = screen.getByTestId('task-late').getAttribute('title')
    expect(title).toBe(t('tasks.lateHintPm'))
    expect(title).not.toBe(t('tasks.lateHint'))
  })

  it('A6-10: a named owner reads "handed over to X" until the first edit, then "X is working on this"', async () => {
    vi.mocked(changesApi.myTasks).mockResolvedValue([
      changeTask({ kind: 'assessment', department_id: 5, owner_name: 'Holmes', owner_started: false }),
      changeTask({ change_id: 8, change_number: 'GB-CM-0008', kind: 'costing_input', department_id: 5,
                   owner_name: 'Payne', owner_started: true }),
    ] as never)
    wrap(<MyTasksPage />)
    await screen.findByText('GB-CM-0008')
    const owners = screen.getAllByTestId('task-owner').map((e) => e.textContent)
    expect(owners).toContain(t('tasks.assignedTo').replace('{x}', 'Holmes'))
    expect(owners).toContain(t('tasks.workingOn').replace('{x}', 'Payne'))
    expect(owners).not.toContain(t('tasks.workingOn').replace('{x}', 'Holmes'))
  })

  it('the hand-over row names what is missing in words', async () => {
    vi.mocked(changesApi.myTasks).mockResolvedValue([
      changeTask({ kind: 'kickoff', missing: ['description', 'at least one attachment',
                                              'quote deadline', 'change lead'] }),
    ] as never)
    wrap(<MyTasksPage />)
    await screen.findByText('GB-CM-0007')
    expect(screen.getByText(t('tasks.hint.kickoff').replace('{x}', [
      t('kickoff.description'), t('kickoff.attachment'), t('deadline.quote'),
      t('kickoff.leadByPm')].join(', ')))).toBeDefined()
  })

  it('A6-04: the kickoff row shows the backend hint naming who acts first', async () => {
    vi.mocked(changesApi.myTasks).mockResolvedValue([
      changeTask({ kind: 'kickoff', missing: ['change lead'],
                   hint: 'Project Management assigns a lead; then you hand over to scoping' }),
    ] as never)
    wrap(<MyTasksPage />)
    await screen.findByText('GB-CM-0007')
    expect(screen.getByText('Project Management assigns a lead; then you hand over to scoping; '
      + t('tasks.hint.missingOnly').replace('{x}', t('kickoff.leadByPm')))).toBeDefined()
    // NEGATIVE: not the generic "Kickoff pending" line
    expect(screen.queryByText(t('tasks.hint.kickoff').replace('{x}', t('kickoff.leadByPm'))))
      .toBeNull()
  })

  it('a link names the override and the sign-off side', async () => {
    vi.mocked(changesApi.myTasks).mockResolvedValue([
      changeTask({ kind: 'deviation_decision', deviation_id: 4, needs_you: true }),
    ] as never)
    wrap(<MyTasksPage />)
    await screen.findByText('GB-CM-0007')
    fireEvent.click(screen.getAllByRole('button', { name: t('tasks.open') })[0])
    expect(navigate).toHaveBeenCalledWith('/changes/7?tab=overview&task=deviation_decision&dev=4')
  })

  it('an urgent row says so instead of the deadline', async () => {
    vi.mocked(changesApi.myTasks).mockResolvedValue([
      changeTask({ kind: 'kickoff', due_date: '2026-10-16T00:00:00', urgent: true,
                   deadline_kind: 'need_by', deadline_date: '2026-10-30T00:00:00' }),
    ] as never)
    wrap(<MyTasksPage />)
    await screen.findByText('GB-CM-0007')
    expect(screen.getByTestId('task-due-note').textContent).toBe(t('tasks.dueUrgent'))
  })

  it('names who is working on an assessment', async () => {
    vi.mocked(changesApi.myTasks).mockResolvedValue([
      changeTask({ kind: 'assessment', assessment_id: 3, department_id: 2, owner_name: 'Holmes' }),
    ] as never)
    wrap(<MyTasksPage />)
    await screen.findByText('GB-CM-0007')
    expect(screen.getByTestId('task-owner').textContent).toBe('Holmes is working on this')
  })

  it('opens the change with the task card: tab, task and department', async () => {
    vi.mocked(changesApi.myTasks).mockResolvedValue([
      changeTask({ kind: 'costing_input', department_id: 5 }),
    ] as never)
    wrap(<MyTasksPage />)
    await screen.findByText('GB-CM-0007')
    fireEvent.click(screen.getByRole('button', { name: t('tasks.open') }))
    expect(navigate).toHaveBeenCalledWith('/changes/7?tab=costing&task=costing_input&dept=5')
  })

  it('sends the price answer and the internal approval to the offer tab (A3-05)', async () => {
    vi.mocked(changesApi.myTasks).mockResolvedValue([
      changeTask({ kind: 'estimate_low', kind_label: 'Cost above the approved estimate: re-approve or absorb' }),
    ] as never)
    wrap(<MyTasksPage />)
    await screen.findByText('GB-CM-0007')
    expect(screen.getByText('Cost above the approved estimate: re-approve or absorb')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: t('tasks.open') }))
    expect(navigate).toHaveBeenCalledWith('/changes/7?tab=offer&task=estimate_low')
  })

  it('confirms a check item where its task leads (A3-01)', async () => {
    vi.mocked(changesApi.myTasks).mockResolvedValue([
      changeTask({ kind: 'confirm_assumption', target_tab: 'assessments' }),
    ] as never)
    wrap(<MyTasksPage />)
    await screen.findByText('GB-CM-0007')
    fireEvent.click(screen.getByRole('button', { name: t('tasks.open') }))
    expect(navigate).toHaveBeenCalledWith('/changes/7?tab=assessments&task=confirm_assumption')
  })

  it('sends the run team\'s ready row to the overview, naming the next stage', async () => {
    vi.mocked(changesApi.myTasks).mockResolvedValue([
      changeTask({ kind: 'advance', to_status: 'closed', kind_label: 'Ready: move it on' }),
    ] as never)
    wrap(<MyTasksPage />)
    await screen.findByText('GB-CM-0007')
    expect(screen.getByText(/Nothing holds it/)).toBeDefined()
    fireEvent.click(screen.getByRole('button', { name: t('tasks.open') }))
    expect(opened()).toBe('/changes/7?tab=overview')
  })
})
