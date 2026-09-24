import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, cleanup, fireEvent, waitFor, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import GanttPlanner from './GanttPlanner'
import { planApi } from '../../../api/changePlan'
import type { PlanOut, TaskOut } from '../../../types/changePlan'

vi.mock('../../../api/changePlan', () => ({
  planApi: {
    get: vi.fn(), seed: vi.fn(), createTask: vi.fn(), patchTask: vi.fn(), bulkPatch: vi.fn(),
    deleteTask: vi.fn(), schedule: vi.fn(), exportXml: vi.fn(), exportCsv: vi.fn(),
  },
}))
vi.mock('../../../hooks/queries/useWorkflows', () => ({
  useDepartments: () => ({ data: [
    { id: 11, name: 'Tool Engineer', is_active: true }, { id: 12, name: 'APQP', is_active: true },
  ] }),
}))
vi.mock('sonner', () => ({ toast: { error: vi.fn(), success: vi.fn(), info: vi.fn() } }))

const task = (over: Partial<TaskOut> & { id: number }): TaskOut => ({
  change_id: 7, plan: 'detailed', name: `Task ${over.id}`, lane: 'Tool Engineer', department_id: 11,
  kind: 'work', is_idea: false, start_date: '2026-10-05', duration_days: 5, end_date: '2026-10-10',
  predecessors: [], sort_order: over.id, progress_pct: 0, actual_start: null, actual_finish: null,
  baseline_start: null, baseline_finish: null, notes: null, is_critical: false, ...over,
})

const planOut = (over: Partial<PlanOut> = {}): PlanOut => ({
  plan: 'detailed',
  tasks: [
    task({ id: 1, name: 'Tool rework', kind: 'downtime' }),
    task({ id: 2, name: 'Sampling', kind: 'sampling', start_date: '2026-10-10', duration_days: 3, predecessors: [1] }),
    task({ id: 3, name: 'Customer approval', lane: 'Customer', department_id: null, kind: 'customer', start_date: '2026-10-13', duration_days: 14, predecessors: [2] }),
  ],
  revision: 3, baseline_set: false, can_edit: true, can_edit_dates: true, progress_department_ids: [],
  summary: { start: '2026-10-05', finish: '2026-10-27', duration_days: 22, buffer_days: 0, critical_ids: [1, 2, 3], ideas: 0 },
  validation: { errors: [], warnings: [{ code: 'no_buffer', message: 'The plan has no buffer block.', task_id: null }] },
  deadlines: [{ key: 'release_due', label: 'Release', date: '2026-11-15' }],
  ...over,
})

const renderPlanner = (props: Partial<Parameters<typeof GanttPlanner>[0]> = {}) => render(
  <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <GanttPlanner changeId={7} plan="detailed" {...props} />
  </QueryClientProvider>)

/** Drag in day zoom: 28 px per day. */
function drag(el: Element, dx: number, init: { shiftKey?: boolean } = {}) {
  fireEvent.pointerDown(el, { button: 0, clientX: 100, clientY: 10, ...init })
  fireEvent.pointerMove(window, { clientX: 100 + dx / 2, clientY: 10 })
  fireEvent.pointerMove(window, { clientX: 100 + dx, clientY: 10 })
  fireEvent.pointerUp(window, { clientX: 100 + dx, clientY: 10 })
}

describe('GanttPlanner', () => {
  afterEach(cleanup)
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(planApi.get).mockResolvedValue(planOut())
    vi.mocked(planApi.bulkPatch).mockResolvedValue(planOut())
    vi.mocked(planApi.patchTask).mockResolvedValue(planOut())
  })

  it('renders the tasks grouped by lane with row numbers and predecessors', async () => {
    renderPlanner()
    await screen.findByTestId('gantt-planner')
    expect(screen.getByTestId('gantt-lane-Tool Engineer')).toBeTruthy()
    expect(screen.getByTestId('gantt-lane-Customer')).toBeTruthy()
    const row3 = screen.getByTestId('gantt-row-3')
    expect(row3.textContent).toContain('Customer approval')
    // Inclusive end: 13 Oct + 14 days -> last day 26 Oct.
    expect(row3.textContent).toContain('26 Oct 26')
    expect(row3.textContent).toContain('2') // after row 2
    expect(screen.getByTestId('gantt-bar-1')).toBeTruthy()
    expect(screen.getByTestId('gantt-link-1-2')).toBeTruthy()
    expect(screen.getByTestId('gantt-deadline-release_due')).toBeTruthy()

    // Collapsing a lane hides its rows.
    fireEvent.click(screen.getByTestId('gantt-lane-Tool Engineer'))
    expect(screen.queryByTestId('gantt-row-1')).toBeNull()
    expect(screen.getByTestId('gantt-row-3')).toBeTruthy()
  })

  it('summarises the plan and lists issues behind the validation pill', async () => {
    renderPlanner()
    const pill = await screen.findByTestId('gantt-validation-pill')
    expect(pill.textContent).toBe('0 errors, 1 warning')
    fireEvent.click(pill)
    expect(screen.getByTestId('gantt-validation-list').textContent).toContain('no buffer block')
    const summary = screen.getByTestId('gantt-summary').textContent ?? ''
    expect(summary).toContain('5 Oct 26')
    expect(summary).toContain('26 Oct 26')
    expect(summary).toContain('22 d, 3.1 wk')
  })

  it('moves a multi-selection as one block with a single bulk patch', async () => {
    renderPlanner()
    await screen.findByTestId('gantt-planner')
    fireEvent.click(screen.getByTestId('gantt-row-1'))
    fireEvent.click(screen.getByTestId('gantt-row-2'), { shiftKey: true })
    expect(screen.getByTestId('gantt-selection-bar').textContent).toContain('2 selected')
    drag(screen.getByTestId('gantt-bar-shape-1'), 56) // two days
    await waitFor(() => expect(planApi.bulkPatch).toHaveBeenCalledTimes(1))
    expect(planApi.bulkPatch).toHaveBeenCalledWith(7, 'detailed', [
      { id: 1, start_date: '2026-10-07' }, { id: 2, start_date: '2026-10-12' },
    ], undefined)
  })

  it('resizes from the right edge', async () => {
    renderPlanner()
    await screen.findByTestId('gantt-planner')
    drag(screen.getByTestId('gantt-resize-3'), -84) // three days shorter
    await waitFor(() => expect(planApi.bulkPatch).toHaveBeenCalledWith(7, 'detailed',
      [{ id: 3, duration_days: 11 }], undefined))
  })

  it('opens the editor on a click without a drag, and never patches', async () => {
    renderPlanner()
    await screen.findByTestId('gantt-planner')
    drag(screen.getByTestId('gantt-bar-shape-2'), 1)
    expect(await screen.findByTestId('task-editor')).toBeTruthy()
    expect(planApi.bulkPatch).not.toHaveBeenCalled()
  })

  it('asks for a reason after the baseline, and cancel reverts without saving', async () => {
    vi.mocked(planApi.get).mockResolvedValue(planOut({ baseline_set: true }))
    renderPlanner({ mode: 'track' })
    await screen.findByTestId('gantt-planner')
    drag(screen.getByTestId('gantt-bar-shape-1'), 28)
    const dialog = await screen.findByRole('dialog')
    expect(dialog.textContent).toContain('Why does this move?')
    expect(dialog.textContent).toContain('deviation')
    expect(planApi.bulkPatch).not.toHaveBeenCalled()
    fireEvent.click(within(dialog).getByText('Cancel'))
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(planApi.bulkPatch).not.toHaveBeenCalled()

    drag(screen.getByTestId('gantt-bar-shape-1'), 28)
    const d2 = await screen.findByRole('dialog')
    fireEvent.change(within(d2).getByRole('textbox'), { target: { value: 'Toolmaker two days late' } })
    fireEvent.click(within(d2).getByText('Save move'))
    await waitFor(() => expect(planApi.bulkPatch).toHaveBeenCalledWith(7, 'detailed',
      [{ id: 1, start_date: '2026-10-06' }], 'Toolmaker two days late'))
  })

  it('offers no drag handles or links without date rights', async () => {
    vi.mocked(planApi.get).mockResolvedValue(planOut({ can_edit: false, can_edit_dates: false }))
    renderPlanner()
    await screen.findByTestId('gantt-planner')
    expect(screen.queryByTestId('gantt-resize-1')).toBeNull()
    expect(screen.queryByTestId('gantt-connector-1')).toBeNull()
    expect(screen.queryByTestId('gantt-add-task')).toBeNull()
    expect(screen.queryByTestId('gantt-schedule')).toBeNull()
    drag(screen.getByTestId('gantt-bar-shape-1'), 56)
    expect(planApi.bulkPatch).not.toHaveBeenCalled()
  })

  it('removes a link after confirming', async () => {
    renderPlanner()
    await screen.findByTestId('gantt-planner')
    fireEvent.click(screen.getByRole('button', { name: 'Remove link 1 to 2' }))
    fireEvent.click(await screen.findByTestId('confirm-ok'))
    await waitFor(() => expect(planApi.patchTask).toHaveBeenCalledWith(7, 2, { predecessors: [] }))
  })

  it('nudges the selection with the arrow keys (shift = a week)', async () => {
    renderPlanner()
    await screen.findByTestId('gantt-planner')
    fireEvent.click(screen.getByTestId('gantt-row-3'))
    fireEvent.click(screen.getByLabelText('Close task editor'))
    const scroller = screen.getByTestId('gantt-scroller')
    fireEvent.keyDown(scroller, { key: 'ArrowRight', shiftKey: true })
    fireEvent.keyDown(scroller, { key: 'ArrowLeft' })
    await waitFor(() => expect(planApi.bulkPatch).toHaveBeenCalledWith(7, 'detailed',
      [{ id: 3, start_date: '2026-10-19' }], undefined), { timeout: 2000 })
    fireEvent.keyDown(scroller, { key: 'Escape' })
    expect(screen.queryByTestId('gantt-selection-bar')).toBeNull()
  })

  it('aligns the selection to its predecessors in one bulk patch', async () => {
    vi.mocked(planApi.get).mockResolvedValue(planOut({
      tasks: [
        task({ id: 1 }),
        task({ id: 2, start_date: '2026-10-20', predecessors: [1] }),
      ],
    }))
    renderPlanner()
    await screen.findByTestId('gantt-planner')
    fireEvent.click(screen.getByTestId('gantt-row-2'), { ctrlKey: true })
    fireEvent.click(screen.getByText('Snap to predecessors'))
    await waitFor(() => expect(planApi.bulkPatch).toHaveBeenCalledWith(7, 'detailed',
      [{ id: 2, start_date: '2026-10-10' }], undefined))
  })

  it('reverts and toasts when the server refuses', async () => {
    const { toast } = await import('sonner')
    vi.mocked(planApi.bulkPatch).mockRejectedValue({ response: { data: { detail: 'Plan is read-only' } } })
    renderPlanner()
    await screen.findByTestId('gantt-planner')
    drag(screen.getByTestId('gantt-bar-shape-1'), 28)
    await waitFor(() => expect(toast.error).toHaveBeenCalledWith('Plan is read-only'))
    expect(screen.getByTestId('gantt-row-1').textContent).toContain('5 Oct 26')
  })

  it('offers the seed on an empty plan', async () => {
    vi.mocked(planApi.get).mockResolvedValue(planOut({ tasks: [] }))
    vi.mocked(planApi.seed).mockResolvedValue(planOut())
    renderPlanner()
    fireEvent.click(await screen.findByTestId('gantt-seed'))
    await waitFor(() => expect(planApi.seed).toHaveBeenCalledWith(7, 'detailed', false))
  })

  it('is a read-only mini chart when compact', async () => {
    renderPlanner({ compact: true, plan: 'quote' })
    await screen.findByTestId('gantt-planner')
    expect(screen.queryByTestId('gantt-toolbar')).toBeNull()
    expect(screen.queryByTestId('gantt-summary')).toBeNull()
    expect(screen.queryByTestId('gantt-resize-1')).toBeNull()
    expect(screen.getByTestId('gantt-row-1').textContent).toBe('Tool rework')
    expect(planApi.get).toHaveBeenCalledWith(7, 'quote')
  })

  it('shows baseline ghosts, progress and slip in track mode', async () => {
    vi.mocked(planApi.get).mockResolvedValue(planOut({
      baseline_set: true,
      tasks: [task({ id: 1, progress_pct: 40, baseline_start: '2026-10-05', baseline_finish: '2026-10-08' })],
    }))
    renderPlanner({ mode: 'track' })
    await screen.findByTestId('gantt-planner')
    expect(screen.getByTestId('gantt-baseline-1')).toBeTruthy()
    expect(screen.getByTestId('gantt-progress-1')).toBeTruthy()
    expect(screen.getByTestId('gantt-slip-1')).toBeTruthy()
    expect(screen.getByTestId('gantt-row-1').textContent).toContain('40%')
  })

  it('lets a department member edit progress only', async () => {
    vi.mocked(planApi.get).mockResolvedValue(planOut({
      baseline_set: true, can_edit: false, can_edit_dates: false, progress_department_ids: [11],
    }))
    renderPlanner({ mode: 'track' })
    await screen.findByTestId('gantt-planner')
    fireEvent.click(screen.getByTestId('gantt-row-1'))
    const editor = await screen.findByTestId('task-editor')
    expect((within(editor).getByLabelText('Name') as HTMLInputElement).disabled).toBe(true)
    expect((within(editor).getByLabelText('Start') as HTMLInputElement).disabled).toBe(true)
    fireEvent.change(within(editor).getByLabelText('Progress'), { target: { value: '60' } })
    fireEvent.click(within(editor).getByTestId('task-editor-save'))
    await waitFor(() => expect(planApi.patchTask).toHaveBeenCalledWith(7, 1, { progress_pct: 60 }))
  })
})
