import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest'
import { render, screen, fireEvent, cleanup } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import TaskCard from './TaskCard'
import { changesApi } from '../../api/changes'
import { t } from '../../i18n/cmLabels'

vi.mock('../../api/changes', () => ({ changesApi: { myTasks: vi.fn() } }))

const row = (over: Record<string, unknown> = {}) => ({
  change_id: 7, change_number: 'GB-CM-0007', title: 'Clip', kind: 'assessment',
  department_id: 2, kind_label: 'Assessment', due_date: '2026-10-15T09:00:00',
  overdue: false, deadline_kind: 'quote', deadline_date: '2026-10-19T00:00:00', ...over,
})

let lastClient: QueryClient
function wrap(ui: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  lastClient = qc
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>)
}

describe('TaskCard (spec §0 task links)', () => {
  beforeEach(() => { try { window.localStorage.clear() } catch { /* none */ } })
  afterEach(cleanup)

  it('says your part, the due date with its deadline, and the next button', async () => {
    // "due Thu (quote deadline Mon)": weekdays within the coming week
    vi.useFakeTimers({ toFake: ['Date'] })
    vi.setSystemTime(new Date('2026-10-14T12:00:00'))
    vi.mocked(changesApi.myTasks).mockResolvedValue([row()] as never)
    const onGo = vi.fn()
    wrap(<TaskCard changeId={7} kind="assessment" departmentId={2} onGo={onGo} onClose={vi.fn()}
      actions={[{ kind: 'assessment', label: 'Submit assessment for Process', target_tab: 'assessments', department_id: 2 }]} />)
    const card = await screen.findByTestId('task-card')
    expect(card.textContent).toContain('Your part: Assessment')
    expect(screen.getByTestId('task-card-due').textContent).toBe(', due Thu (quote deadline Mon)')
    vi.useRealTimers()
    fireEvent.click(screen.getByTestId('task-card-next'))
    expect(onGo).toHaveBeenCalledWith('assessments')
    expect(screen.getByTestId('task-card-next').textContent).toBe('Submit assessment for Process')
  })

  it('P3-5: "Record the customer answer" lands on the answer panel; other tasks do not scroll', async () => {
    const panel = document.createElement('div')
    panel.setAttribute('data-testid', 'customer-decision')
    const scroll = vi.fn()
    panel.scrollIntoView = scroll
    document.body.appendChild(panel)
    vi.mocked(changesApi.myTasks).mockResolvedValue([row({ kind: 'customer_response', department_id: null })] as never)
    const onGo = vi.fn()
    wrap(<TaskCard changeId={7} kind="customer_response" onGo={onGo} onClose={vi.fn()}
      actions={[{ kind: 'customer_response', label: 'Record the customer answer', target_tab: 'offer' }]} />)
    await screen.findByTestId('task-card')
    vi.useFakeTimers()
    fireEvent.click(screen.getByTestId('task-card-next'))
    expect(onGo).toHaveBeenCalledWith('offer')
    vi.advanceTimersByTime(200)
    expect(scroll).toHaveBeenCalledTimes(1)
    vi.useRealTimers()
    cleanup()
    vi.mocked(changesApi.myTasks).mockResolvedValue([row()] as never)
    wrap(<TaskCard changeId={7} kind="assessment" departmentId={2} onGo={vi.fn()} onClose={vi.fn()}
      actions={[{ kind: 'assessment', label: 'Submit', target_tab: 'assessments', department_id: 2 }]} />)
    await screen.findByTestId('task-card')
    vi.useFakeTimers()
    fireEvent.click(screen.getByTestId('task-card-next'))
    vi.advanceTimersByTime(200)
    expect(scroll).toHaveBeenCalledTimes(1)
    vi.useRealTimers()
    panel.remove()
  })

  it('turns into "done" at once when the change refreshes and the task is gone (no reload)', async () => {
    vi.mocked(changesApi.myTasks).mockResolvedValueOnce([row()] as never)
    wrap(<TaskCard changeId={7} kind="assessment" departmentId={2} actions={[]} onGo={vi.fn()} onClose={vi.fn()} />)
    expect((await screen.findByTestId('task-card')).textContent).toContain('Your part: Assessment')
    // the viewer submits: the change's queries refresh, the task list no longer has the row
    vi.mocked(changesApi.myTasks).mockResolvedValue([] as never)
    await lastClient.fetchQuery({ queryKey: ['change', 7, 'costing'], queryFn: async () => ({}) })
    expect(await screen.findByText(t('taskcard.done'))).toBeDefined()
  })

  it('shows the first-use help once; dismissed it stays away', async () => {
    vi.mocked(changesApi.myTasks).mockResolvedValue([row()] as never)
    wrap(<TaskCard changeId={7} kind="assessment" actions={[]} onGo={vi.fn()} onClose={vi.fn()} />)
    await screen.findByTestId('task-card')
    fireEvent.click(screen.getByRole('button', { name: t('taskcard.gotIt') }))
    expect(screen.queryByTestId('task-card-help')).toBeNull()
    cleanup()
    wrap(<TaskCard changeId={7} kind="assessment" actions={[]} onGo={vi.fn()} onClose={vi.fn()} />)
    await screen.findByTestId('task-card')
    expect(screen.queryByTestId('task-card-help')).toBeNull()
  })

  it('"Ready: move it on" makes the move, named like the Next step button', async () => {
    vi.mocked(changesApi.myTasks).mockResolvedValue([row({
      kind: 'advance', department_id: null, status: 'in_assessment', to_status: 'costing',
      target_tab: 'overview' })] as never)
    const onGo = vi.fn(); const onAdvance = vi.fn()
    wrap(<TaskCard changeId={7} kind="advance" actions={[]} onGo={onGo} onAdvance={onAdvance}
      currentTab="overview" onClose={vi.fn()} />)
    const next = await screen.findByTestId('task-card-next')
    expect(next.textContent).toBe('Close assessment')
    fireEvent.click(next)
    expect(onAdvance).toHaveBeenCalledWith('costing')
    expect(onGo).not.toHaveBeenCalled()
  })

  it('on the tab where the work is, the card names the step instead of a second button', async () => {
    vi.mocked(changesApi.myTasks).mockResolvedValue([row({
      kind: 'internal_approval', department_id: null, target_tab: 'commercial' })] as never)
    wrap(<TaskCard changeId={7} kind="internal_approval" currentTab="commercial" onGo={vi.fn()}
      onClose={vi.fn()} actions={[{ kind: 'internal_approval', label: 'Approve the internal costs', target_tab: 'commercial' }]} />)
    expect((await screen.findByTestId('task-card-here')).textContent).toBe('Approve the internal costs (below)')
    expect(screen.queryByTestId('task-card-next')).toBeNull()
  })

  it('of two overrides on one change, the card shows the one the link names', async () => {
    vi.mocked(changesApi.myTasks).mockResolvedValue([
      row({ kind: 'deviation_decision', department_id: null, deviation_id: 1, due_date: '2026-10-01T00:00:00' }),
      row({ kind: 'deviation_decision', department_id: null, deviation_id: 2, due_date: '2027-03-09T00:00:00' }),
    ] as never)
    wrap(<TaskCard changeId={7} kind="deviation_decision" deviationId={2} onGo={vi.fn()} onClose={vi.fn()}
      actions={[{ kind: 'deviation_decision', label: 'Decide override #1', deviation_id: 1, target_tab: 'overview' },
                { kind: 'deviation_decision', label: 'Decide override #2', deviation_id: 2, target_tab: 'overview' }]} />)
    expect((await screen.findByTestId('task-card-due')).textContent).toContain('9 Mar')
    expect(screen.getByTestId('task-card-next').textContent).toBe('Decide override #2')
  })

  it('a task that is no longer yours says so and offers no next step', async () => {
    vi.mocked(changesApi.myTasks).mockResolvedValue([row({ department_id: 5 })] as never)
    wrap(<TaskCard changeId={7} kind="assessment" departmentId={2} actions={[]}
      onGo={vi.fn()} onClose={vi.fn()} />)
    expect(await screen.findByTestId('task-card-done')).toBeDefined()
    expect(screen.queryByTestId('task-card-next')).toBeNull()
  })
})
