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

  it('shows owner, overdue flag, and Accept on unclaimed rows', async () => {
    wrap(<MyTasksPage />)
    expect(await screen.findByText('Eva Eng')).toBeDefined()
    expect(screen.getByText(/overdue/)).toBeDefined()
    const accept = screen.getByRole('button', { name: /Accept/ })
    fireEvent.click(accept)
    await waitFor(() => expect(clientMocks.post).toHaveBeenCalledWith(
      '/v1/workflow-instances/9/tasks/2/accept'))
  })
})

const navigate = vi.fn()
vi.mock('react-router-dom', async (orig) => ({
  ...(await orig<typeof import('react-router-dom')>()), useNavigate: () => navigate,
}))

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
    expect(navigate).toHaveBeenCalledWith('/changes/7')
  })

  it('says what scoping still owes and opens the scoping tab', async () => {
    await renderWith(changeTask({
      kind: 'scoping_wrapup', impact_confirmed: false, has_decision: false,
    }))
    const hint = screen.getByText(new RegExp(t('tasks.hint.impactOpen')))
    expect(hint.textContent).toContain(t('tasks.hint.decisionOpen'))
    fireEvent.click(screen.getByRole('button', { name: t('tasks.open') }))
    expect(navigate).toHaveBeenCalledWith('/changes/7?tab=scoping')
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
    // The date cell carries the overdue styling; the mark sits inside it.
    const due = screen.getByText(/overdue/).closest('span')?.parentElement
    expect(due?.className).toContain('text-red-400')
    fireEvent.click(screen.getByRole('button', { name: t('tasks.open') }))
    expect(navigate).toHaveBeenCalledWith('/changes/7?tab=impacted')
  })

  it('quotes the open question on an obtain-info row and opens scoping', async () => {
    await renderWith(changeTask({
      kind: 'obtain_info', reason: 'target price for the new gauge',
    }))
    expect(screen.getByText(t('tasks.kind.obtain_info'))).toBeDefined()
    expect(screen.getByText('target price for the new gauge')).toBeDefined()
    fireEvent.click(screen.getByRole('button', { name: t('tasks.open') }))
    expect(navigate).toHaveBeenCalledWith('/changes/7?tab=scoping')
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

  it('sends a costing-input row to the commercial tab', async () => {
    await renderWith(changeTask({ kind: 'costing_input' }))
    expect(screen.getByText(t('tasks.kind.costing_input'))).toBeDefined()
    expect(screen.getByText(t('tasks.hint.costing_input'))).toBeDefined()
    fireEvent.click(screen.getByRole('button', { name: t('tasks.open') }))
    expect(navigate).toHaveBeenCalledWith('/changes/7?tab=commercial')
  })

  it('chases the customer on a quoted change', async () => {
    await renderWith(changeTask({ kind: 'customer_response' }))
    expect(screen.getByText(t('tasks.kind.customer_response'))).toBeDefined()
    expect(screen.getByText(t('tasks.hint.customer_response'))).toBeDefined()
    fireEvent.click(screen.getByRole('button', { name: t('tasks.open') }))
    expect(navigate).toHaveBeenCalledWith('/changes/7')
  })

  it('renders an unknown kind as a plain row instead of crashing', async () => {
    await renderWith(changeTask({ kind: 'something_new' }))
    expect(screen.getByText('something_new')).toBeDefined()
    expect(screen.getByText('Clip rattles')).toBeDefined()
  })

  it('keeps the assessment row with its owner and Accept control', async () => {
    await renderWith(changeTask({
      kind: 'assessment', department_id: 2, assessment_id: 3,
      owner_id: null, owner_name: null, mine: true,
    }))
    fireEvent.click(screen.getByRole('button', { name: t('tasks.accept') }))
    await waitFor(() => expect(changesApi.acceptAssessment).toHaveBeenCalledWith(7, 3))
    fireEvent.click(screen.getByRole('button', { name: 'Assess' }))
    expect(navigate).toHaveBeenCalledWith('/changes/7')
  })
})
