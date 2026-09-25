import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, cleanup, fireEvent, waitFor, within, act } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import GanttPlanner from './GanttPlanner'
import { planApi } from '../../../api/changePlan'
import type { PlanOut, TaskOut } from '../../../types/changePlan'

vi.mock('../../../api/changePlan', () => ({
  planApi: {
    get: vi.fn(), seed: vi.fn(), createTask: vi.fn(), patchTask: vi.fn(), bulkPatch: vi.fn(),
    deleteTask: vi.fn(), schedule: vi.fn(), exportXml: vi.fn(), exportCsv: vi.fn(),
    applyChanges: vi.fn(), importXml: vi.fn(),
  },
}))
vi.mock('../../../hooks/queries/useWorkflows', () => ({
  useDepartments: () => ({ data: [
    { id: 11, name: 'Tool Engineer', is_active: true }, { id: 12, name: 'APQP', is_active: true },
    { id: 30, name: 'Scheduling', is_active: true },
  ] }),
}))
vi.mock('sonner', () => ({ toast: { error: vi.fn(), success: vi.fn(), info: vi.fn(), warning: vi.fn() } }))

const task = (over: Partial<TaskOut> & { id: number }): TaskOut => ({
  change_id: 7, plan: 'detailed', name: `Task ${over.id}`, lane: 'Tool Engineer', department_id: 11,
  department_name: 'Tool Engineer', kind: 'work', is_idea: false, start_date: '2026-10-05', duration_days: 5,
  end_date: '2026-10-10', predecessors: [], sort_order: over.id, progress_pct: 0, actual_start: null,
  actual_finish: null, baseline_start: null, baseline_finish: null, notes: null, is_critical: false, ...over,
})

const planOut = (over: Partial<PlanOut> = {}): PlanOut => ({
  plan: 'detailed',
  tasks: [
    task({ id: 1, name: 'Tool rework', kind: 'downtime' }),
    task({ id: 2, name: 'Sampling', kind: 'sampling', start_date: '2026-10-10', duration_days: 3, predecessors: [1] }),
    task({ id: 3, name: 'Customer approval', lane: 'Customer', department_id: null, department_name: null, kind: 'customer', start_date: '2026-10-13', duration_days: 14, predecessors: [2] }),
  ],
  revision: 3, baseline_set: false, can_edit: true, can_edit_dates: true, progress_department_ids: [],
  summary: { start: '2026-10-05', finish: '2026-10-27', duration_days: 22, buffer_days: 0, critical_ids: [1, 2, 3], ideas: 0 },
  validation: { errors: [], warnings: [{ code: 'no_buffer', message: 'The plan has no buffer block.', task_id: null }] },
  deadlines: [{ key: 'release_due', label: 'Release', date: '2026-11-15' }],
  ...over,
})

/** The 088 server: typed links + calendar. */
const modernOut = (over: Partial<PlanOut> = {}): PlanOut => planOut({
  links: [
    { id: 51, from_task_id: 1, to_task_id: 2, type: 'FS', lag_days: 0 },
    { id: 52, from_task_id: 2, to_task_id: 3, type: 'FS', lag_days: 0 },
  ],
  calendar: { mode: 'calendar', workdays: [1, 2, 3, 4, 5], holidays: [] },
  ...over,
})

let qc: QueryClient
const renderPlanner = (props: Partial<Parameters<typeof GanttPlanner>[0]> = {}) => {
  qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <GanttPlanner changeId={7} plan="detailed" {...props} />
    </QueryClientProvider>)
}

/** Drag in day zoom: 28 px per day. */
function drag(el: Element, dx: number, init: { ctrlKey?: boolean } = {}) {
  fireEvent.pointerDown(el, { button: 0, clientX: 100, clientY: 10, ...init })
  fireEvent.pointerMove(window, { clientX: 100 + dx / 2, clientY: 10 })
  fireEvent.pointerMove(window, { clientX: 100 + dx, clientY: 10 })
  fireEvent.pointerUp(window, { clientX: 100 + dx, clientY: 10 })
}

describe('GanttPlanner (ECR adapter)', () => {
  afterEach(cleanup)
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(planApi.get).mockResolvedValue(planOut())
    vi.mocked(planApi.bulkPatch).mockResolvedValue(planOut())
    vi.mocked(planApi.patchTask).mockResolvedValue(planOut())
    vi.mocked(planApi.createTask).mockResolvedValue(planOut())
    vi.mocked(planApi.deleteTask).mockResolvedValue(planOut())
    vi.mocked(planApi.applyChanges).mockResolvedValue({ ...modernOut(), id_map: {}, link_id_map: {} })
    vi.mocked(planApi.exportXml).mockResolvedValue('x.xml')
  })

  it('renders lanes, rows, links and the deadline marker', async () => {
    renderPlanner()
    await screen.findByTestId('gantt-planner')
    expect(screen.getByTestId('gantt-group-Tool Engineer')).toBeTruthy()
    expect(screen.getByTestId('gantt-group-Customer')).toBeTruthy()
    const row3 = screen.getByTestId('gantt-row-3')
    expect(row3.textContent).toContain('Customer approval')
    // Inclusive finish: 13 Oct + 14 days -> last day 26 Oct.
    expect(row3.textContent).toContain('26.10.26')
    expect(row3.textContent).toContain('2') // predecessor row 2
    expect(screen.getByTestId('gantt-link-1-2')).toBeTruthy()
    expect(screen.getByTestId('gantt-marker-release_due')).toBeTruthy()
    fireEvent.click(screen.getByTestId('gantt-group-Tool Engineer'))
    expect(screen.queryByTestId('gantt-row-1')).toBeNull()
    expect(screen.getByTestId('gantt-row-3')).toBeTruthy()
  })

  it('summarises the plan (inclusive finish) and lists issues behind the pill', async () => {
    renderPlanner()
    const pill = await screen.findByTestId('gantt-validation-pill')
    expect(pill.textContent).toBe('0 errors, 1 warning')
    fireEvent.click(pill)
    expect(screen.getByTestId('gantt-validation-list').textContent).toContain('no buffer block')
    const summary = screen.getByTestId('gantt-summary').textContent ?? ''
    expect(summary).toContain('05.10.26')
    expect(summary).toContain('26.10.26')
    expect(summary).toContain('22 d, 3.1 wk')
  })

  it('uses summary.finish as an exclusive end when there are no leaves to measure', async () => {
    vi.mocked(planApi.get).mockResolvedValue(planOut({ tasks: [task({ id: 1, is_idea: true })], summary: { start: '2026-10-05', finish: '2026-10-10', duration_days: 5, buffer_days: 0, critical_ids: [], ideas: 1 } }))
    renderPlanner()
    expect((await screen.findByTestId('gantt-summary')).textContent).toContain('09.10.26')
  })

  it('moves a multi-selection as one block with a single bulk patch (legacy server)', async () => {
    renderPlanner()
    await screen.findByTestId('gantt-planner')
    fireEvent.click(screen.getByTestId('gantt-row-1'))
    fireEvent.click(screen.getByTestId('gantt-row-2'), { ctrlKey: true })
    drag(screen.getByTestId('gantt-bar-shape-1'), 56) // two days
    await waitFor(() => expect(planApi.bulkPatch).toHaveBeenCalledTimes(1))
    expect(planApi.bulkPatch).toHaveBeenCalledWith(7, 'detailed', [
      { id: 1, start_date: '2026-10-07' }, { id: 2, start_date: '2026-10-12' },
    ], undefined)
  })

  it('sends one atomic ChangeSet to POST /plan/changes on a 088 server', async () => {
    vi.mocked(planApi.get).mockResolvedValue(modernOut())
    renderPlanner()
    await screen.findByTestId('gantt-planner')
    drag(screen.getByTestId('gantt-bar-shape-2'), 28)
    await waitFor(() => expect(planApi.applyChanges).toHaveBeenCalledTimes(1))
    expect(planApi.applyChanges).toHaveBeenCalledWith(7, 'detailed', {
      tasks_upsert: [{ id: 2, start_date: '2026-10-11' }], tasks_delete: [], links_upsert: [], links_delete: [],
    }, undefined)
    expect(planApi.bulkPatch).not.toHaveBeenCalled()
  })

  it('offers typed links with lag on a 088 server and FS only otherwise', async () => {
    vi.mocked(planApi.get).mockResolvedValue(modernOut())
    renderPlanner()
    await screen.findByTestId('gantt-planner')
    fireEvent.click(screen.getByTestId('gantt-link-hit-51'))
    const pop = await screen.findByTestId('gantt-link-popover')
    expect(within(pop).getAllByRole('option')).toHaveLength(4)
    fireEvent.change(within(pop).getByLabelText('Link type'), { target: { value: 'SS' } })
    fireEvent.change(within(pop).getByLabelText('Lag'), { target: { value: '2' } })
    fireEvent.click(within(pop).getByTestId('gantt-link-save'))
    await waitFor(() => expect(planApi.applyChanges).toHaveBeenCalledWith(7, 'detailed', {
      tasks_upsert: [], tasks_delete: [], links_upsert: [{ id: 51, type: 'SS', lag_days: 2 }], links_delete: [],
    }, undefined))
  })

  it('removes a legacy link through the link popover', async () => {
    renderPlanner()
    await screen.findByTestId('gantt-planner')
    fireEvent.click(screen.getByTestId('gantt-link-hit-p1-2'))
    const pop = await screen.findByTestId('gantt-link-popover')
    expect(within(pop).getAllByRole('option')).toHaveLength(1)
    expect(within(pop).queryByLabelText('Lag')).toBeNull()
    fireEvent.click(within(pop).getByTestId('gantt-link-delete'))
    await waitFor(() => expect(planApi.patchTask).toHaveBeenCalledWith(7, 2, { predecessors: [] }))
  })

  it('resizes from the right edge', async () => {
    renderPlanner()
    await screen.findByTestId('gantt-planner')
    drag(screen.getByTestId('gantt-resize-3'), -84) // three days shorter
    await waitFor(() => expect(planApi.bulkPatch).toHaveBeenCalledWith(7, 'detailed',
      [{ id: 3, duration_days: 11 }], undefined))
  })

  it('selects on click, opens the task panel on double-click only', async () => {
    renderPlanner()
    await screen.findByTestId('gantt-planner')
    drag(screen.getByTestId('gantt-bar-shape-2'), 1)
    expect(screen.queryByTestId('task-editor')).toBeNull()
    expect(screen.getByTestId('gantt-row-2').getAttribute('aria-selected')).toBe('true')
    fireEvent.doubleClick(screen.getByTestId('gantt-bar-2'))
    expect(await screen.findByTestId('task-editor')).toBeTruthy()
    expect(planApi.bulkPatch).not.toHaveBeenCalled()
  })

  it('closes the task panel when several tasks are selected', async () => {
    renderPlanner()
    await screen.findByTestId('gantt-planner')
    fireEvent.click(screen.getByTestId('gantt-row-1'))
    fireEvent.doubleClick(screen.getByTestId('gantt-bar-1'))
    await screen.findByTestId('task-editor')
    fireEvent.click(screen.getByTestId('gantt-row-2'), { ctrlKey: true })
    await waitFor(() => expect(screen.queryByTestId('task-editor')).toBeNull())
  })

  it('does not shift the chart when tasks get selected (no extra bar)', async () => {
    renderPlanner()
    await screen.findByTestId('gantt-planner')
    const before = screen.getByTestId('gantt-planner').children.length
    fireEvent.click(screen.getByTestId('gantt-row-1'))
    expect(screen.getByTestId('gantt-planner').children.length).toBe(before)
    expect(screen.queryByTestId('gantt-selection-bar')).toBeNull()
  })

  it('asks for a reason after the baseline, previews the pushed successors, cancel reverts', async () => {
    vi.mocked(planApi.get).mockResolvedValue(planOut({ baseline_set: true, can_edit: false }))
    renderPlanner({ mode: 'track' })
    await screen.findByTestId('gantt-planner')
    drag(screen.getByTestId('gantt-bar-shape-1'), 28)
    const dialog = await screen.findByRole('dialog', { name: 'Record a deviation' })
    expect(dialog.textContent).toContain('Why does this move?')
    expect(within(dialog).getByTestId('deviation-successors').textContent).toContain('Sampling')
    expect(within(dialog).getByTestId('deviation-successors').textContent).toContain('Customer approval')
    fireEvent.click(within(dialog).getByText('Cancel'))
    await waitFor(() => expect(screen.queryByRole('dialog', { name: 'Record a deviation' })).toBeNull())
    expect(planApi.bulkPatch).not.toHaveBeenCalled()
    expect(screen.getByTestId('gantt-row-1').textContent).toContain('05.10.26')

    drag(screen.getByTestId('gantt-bar-shape-1'), 28)
    const d2 = await screen.findByRole('dialog', { name: 'Record a deviation' })
    fireEvent.change(within(d2).getByRole('textbox'), { target: { value: 'Toolmaker one day late' } })
    fireEvent.click(within(d2).getByText('Save move'))
    await waitFor(() => expect(planApi.bulkPatch).toHaveBeenCalledWith(7, 'detailed', [
      { id: 1, start_date: '2026-10-06' }, { id: 2, start_date: '2026-10-11' }, { id: 3, start_date: '2026-10-14' },
    ], 'Toolmaker one day late'))
  })

  it('locks links, kind, idea and name after the baseline; notes and dates stay', async () => {
    vi.mocked(planApi.get).mockResolvedValue(planOut({ baseline_set: true, can_edit: false }))
    renderPlanner({ mode: 'track' })
    await screen.findByTestId('gantt-planner')
    expect(screen.queryByTestId('gantt-connector-end-1')).toBeNull()
    expect(screen.queryByTestId('gantt-add-task')).toBeNull()
    expect(screen.getByTestId('gantt-resize-1')).toBeTruthy()
    fireEvent.doubleClick(screen.getByTestId('gantt-bar-1'))
    const editor = await screen.findByTestId('task-editor')
    expect((within(editor).getByLabelText('Name') as HTMLInputElement).disabled).toBe(true)
    expect((within(editor).getByLabelText('Kind') as HTMLSelectElement).disabled).toBe(true)
    for (const box of within(editor).queryAllByLabelText('Starts after', { exact: false })) expect((box as HTMLInputElement).disabled).toBe(true)
    expect((within(editor).getByLabelText('Notes') as HTMLTextAreaElement).disabled).toBe(false)
    expect((within(editor).getByLabelText('Start') as HTMLInputElement).disabled).toBe(false)
    fireEvent.change(within(editor).getByLabelText('Notes'), { target: { value: 'tool shop busy' } })
    fireEvent.click(within(editor).getByTestId('task-editor-save'))
    await waitFor(() => expect(planApi.patchTask).toHaveBeenCalledWith(7, 1, { notes: 'tool shop busy' }))
  })

  it('offers no drag handles, links or tools without rights', async () => {
    vi.mocked(planApi.get).mockResolvedValue(planOut({ can_edit: false, can_edit_dates: false }))
    renderPlanner()
    await screen.findByTestId('gantt-planner')
    expect(screen.queryByTestId('gantt-resize-1')).toBeNull()
    expect(screen.queryByTestId('gantt-connector-end-1')).toBeNull()
    expect(screen.queryByTestId('gantt-add-task')).toBeNull()
    expect(screen.queryByTestId('gantt-schedule')).toBeNull()
    expect(screen.queryByTestId('gantt-undo')).toBeNull()
    drag(screen.getByTestId('gantt-bar-shape-1'), 56)
    expect(planApi.bulkPatch).not.toHaveBeenCalled()
  })

  it('nudges the selection with the arrow keys (shift = a week)', async () => {
    renderPlanner()
    await screen.findByTestId('gantt-planner')
    fireEvent.click(screen.getByTestId('gantt-row-3'))
    const root = screen.getByTestId('gantt-root')
    fireEvent.keyDown(root, { key: 'ArrowRight', shiftKey: true })
    fireEvent.keyDown(root, { key: 'ArrowLeft' })
    await waitFor(() => expect(planApi.bulkPatch).toHaveBeenCalledWith(7, 'detailed',
      [{ id: 3, start_date: '2026-10-19' }], undefined), { timeout: 2000 })
  })

  it('aligns the selection to its predecessors from the Align menu', async () => {
    vi.mocked(planApi.get).mockResolvedValue(planOut({
      tasks: [task({ id: 1 }), task({ id: 2, start_date: '2026-10-20', predecessors: [1] })],
    }))
    renderPlanner()
    await screen.findByTestId('gantt-planner')
    fireEvent.click(screen.getByTestId('gantt-row-2'))
    fireEvent.click(screen.getByTestId('gantt-align'))
    fireEvent.click(screen.getByTestId('gantt-align-snap'))
    await waitFor(() => expect(planApi.bulkPatch).toHaveBeenCalledWith(7, 'detailed',
      [{ id: 2, start_date: '2026-10-10' }], undefined))
  })

  it('adds a buffer in front of the last milestone', async () => {
    vi.mocked(planApi.get).mockResolvedValue(modernOut({
      tasks: [...planOut().tasks, task({ id: 4, name: 'SOP', kind: 'milestone', lane: 'Customer', start_date: '2026-10-27', duration_days: 0, predecessors: [3] })],
      links: [{ id: 51, from_task_id: 1, to_task_id: 2, type: 'FS', lag_days: 0 }, { id: 52, from_task_id: 2, to_task_id: 3, type: 'FS', lag_days: 0 }, { id: 53, from_task_id: 3, to_task_id: 4, type: 'FS', lag_days: 0 }],
    }))
    renderPlanner()
    await screen.findByTestId('gantt-planner')
    fireEvent.click(screen.getByTestId('gantt-add-buffer'))
    await waitFor(() => expect(planApi.applyChanges).toHaveBeenCalledTimes(1))
    const body = vi.mocked(planApi.applyChanges).mock.calls[0][2]
    expect(body.tasks_upsert[0]).toMatchObject({ name: 'Safety buffer', kind: 'buffer', start_date: '2026-10-27', duration_days: 5, lane: 'Customer' })
    expect(body.links_delete).toEqual([53])
    expect(body.links_upsert.map((l) => [l.from_task_id, l.to_task_id])).toEqual([[3, body.tasks_upsert[0].id], [body.tasks_upsert[0].id, 4]])
    expect(body.tasks_upsert.find((u) => u.id === 4)).toMatchObject({ start_date: '2026-11-01' })
  })

  it('adds a bank build idea in the Scheduling lane, ending at the first downtime', async () => {
    vi.mocked(planApi.get).mockResolvedValue(modernOut())
    renderPlanner()
    await screen.findByTestId('gantt-planner')
    fireEvent.click(screen.getByTestId('gantt-add-bank-build'))
    await waitFor(() => expect(planApi.applyChanges).toHaveBeenCalledTimes(1))
    expect(vi.mocked(planApi.applyChanges).mock.calls[0][2].tasks_upsert[0]).toMatchObject({
      name: 'Bank build (idea)', kind: 'bank_build', is_idea: true, lane: 'Scheduling', department_id: 30,
      start_date: '2026-09-25', duration_days: 10,
    })
  })

  it('keeps a new task local until it has a name', async () => {
    vi.mocked(planApi.get).mockResolvedValue(modernOut())
    vi.mocked(planApi.applyChanges).mockImplementation(async (_id, _p, cs) => ({ ...modernOut(), id_map: { [String(cs.tasks_upsert[0].id)]: 99 }, link_id_map: {} }))
    renderPlanner()
    await screen.findByTestId('gantt-planner')
    fireEvent.click(screen.getByTestId('gantt-add-task'))
    const input = await screen.findByTestId('gantt-cell-editor')
    expect(planApi.applyChanges).not.toHaveBeenCalled()
    fireEvent.keyDown(input, { key: 'Escape' })
    await waitFor(() => expect(screen.queryByTestId('gantt-cell-editor')).toBeNull())
    expect(planApi.applyChanges).not.toHaveBeenCalled()

    fireEvent.click(screen.getByTestId('gantt-add-task'))
    const input2 = await screen.findByTestId('gantt-cell-editor')
    fireEvent.change(input2, { target: { value: 'Laser trial' } })
    fireEvent.keyDown(input2, { key: 'Enter' })
    await waitFor(() => expect(planApi.applyChanges).toHaveBeenCalledTimes(1))
    expect(vi.mocked(planApi.applyChanges).mock.calls[0][2].tasks_upsert[0]).toMatchObject({ name: 'Laser trial', kind: 'work' })
  })

  it('reverts, toasts and refetches when the server refuses', async () => {
    const { toast } = await import('sonner')
    vi.mocked(planApi.bulkPatch).mockRejectedValue({ response: { data: { detail: 'Plan is read-only' } } })
    renderPlanner()
    await screen.findByTestId('gantt-planner')
    const gets = vi.mocked(planApi.get).mock.calls.length
    drag(screen.getByTestId('gantt-bar-shape-1'), 28)
    await waitFor(() => expect(toast.error).toHaveBeenCalledWith('Plan is read-only'))
    await waitFor(() => expect(vi.mocked(planApi.get).mock.calls.length).toBeGreaterThan(gets))
    expect(screen.getByTestId('gantt-row-1').textContent).toContain('05.10.26')
  })

  it('refetches after a partly failed multi-call save', async () => {
    vi.mocked(planApi.deleteTask).mockResolvedValueOnce(planOut()).mockRejectedValueOnce(new Error('boom'))
    renderPlanner()
    await screen.findByTestId('gantt-planner')
    const gets = vi.mocked(planApi.get).mock.calls.length
    fireEvent.click(screen.getByTestId('gantt-row-2'))
    fireEvent.click(screen.getByTestId('gantt-row-3'), { ctrlKey: true })
    fireEvent.keyDown(screen.getByTestId('gantt-root'), { key: 'Delete' })
    await waitFor(() => expect(vi.mocked(planApi.get).mock.calls.length).toBeGreaterThan(gets))
  })

  it('serializes overlapping saves: the second waits for the first', async () => {
    let release!: (p: PlanOut) => void
    vi.mocked(planApi.bulkPatch).mockImplementationOnce(() => new Promise((r) => { release = r }))
    renderPlanner()
    await screen.findByTestId('gantt-planner')
    drag(screen.getByTestId('gantt-bar-shape-1'), 28)
    await waitFor(() => expect(planApi.bulkPatch).toHaveBeenCalledTimes(1))
    drag(screen.getByTestId('gantt-bar-shape-3'), 28)
    await new Promise((r) => setTimeout(r, 30))
    expect(planApi.bulkPatch).toHaveBeenCalledTimes(1)
    // The first move is still shown while the second is queued.
    expect(screen.getByTestId('gantt-row-1').textContent).toContain('06.10.26')
    expect(screen.getByTestId('gantt-row-3').textContent).toContain('14.10.26')
    await act(async () => { release(planOut()) })
    await waitFor(() => expect(planApi.bulkPatch).toHaveBeenCalledTimes(2))
    expect(vi.mocked(planApi.bulkPatch).mock.calls[1][2]).toEqual([{ id: 3, start_date: '2026-10-14' }])
  })

  it('invalidates the offers after a quote plan edit', async () => {
    vi.mocked(planApi.get).mockResolvedValue(planOut({ plan: 'quote' }))
    renderPlanner({ plan: 'quote' })
    await screen.findByTestId('gantt-planner')
    const spy = vi.spyOn(qc, 'invalidateQueries')
    drag(screen.getByTestId('gantt-bar-shape-1'), 28)
    await waitFor(() => expect(spy).toHaveBeenCalledWith({ queryKey: ['change', 7, 'offers'] }))
  })

  it('offers the seed on an empty plan, unless the host hides it', async () => {
    vi.mocked(planApi.get).mockResolvedValue(planOut({ tasks: [] }))
    vi.mocked(planApi.seed).mockResolvedValue(planOut())
    renderPlanner()
    fireEvent.click(await screen.findByTestId('gantt-seed'))
    await waitFor(() => expect(planApi.seed).toHaveBeenCalledWith(7, 'detailed', false))
    cleanup()
    vi.mocked(planApi.get).mockResolvedValue(planOut({ tasks: [] }))
    renderPlanner({ hideSeed: true })
    await screen.findByTestId('gantt-empty')
    expect(screen.queryByTestId('gantt-seed')).toBeNull()
    expect(screen.getByTestId('gantt-add-first')).toBeTruthy()
  })

  it('hides the re-seed button with hideSeed', async () => {
    renderPlanner({ hideSeed: true })
    await screen.findByTestId('gantt-planner')
    expect(screen.queryByTestId('gantt-reseed')).toBeNull()
    cleanup()
    renderPlanner()
    await screen.findByTestId('gantt-planner')
    expect(screen.getByTestId('gantt-reseed')).toBeTruthy()
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
    fireEvent.doubleClick(screen.getByTestId('gantt-bar-1'))
    const editor = await screen.findByTestId('task-editor')
    expect((within(editor).getByLabelText('Name') as HTMLInputElement).disabled).toBe(true)
    expect((within(editor).getByLabelText('Start') as HTMLInputElement).disabled).toBe(true)
    fireEvent.change(within(editor).getByLabelText('Progress'), { target: { value: '60' } })
    fireEvent.click(within(editor).getByTestId('task-editor-save'))
    await waitFor(() => expect(planApi.patchTask).toHaveBeenCalledWith(7, 1, { progress_pct: 60 }))
  })

  it('exports through the backend', async () => {
    renderPlanner()
    await screen.findByTestId('gantt-planner')
    fireEvent.click(screen.getByTestId('gantt-export'))
    fireEvent.click(await screen.findByTestId('gantt-export-xml'))
    expect(planApi.exportXml).toHaveBeenCalledWith(7, 'detailed')
  })

  it('imports an MS Project file on a 088 server after confirming the replace', async () => {
    vi.mocked(planApi.get).mockResolvedValue(modernOut())
    vi.mocked(planApi.importXml).mockResolvedValue(modernOut())
    renderPlanner()
    await screen.findByTestId('gantt-planner')
    const file = new File(['<Project/>'], 'plan.xml', { type: 'application/xml' })
    fireEvent.change(screen.getByTestId('gantt-import-file'), { target: { files: [file] } })
    fireEvent.click(await screen.findByTestId('confirm-ok'))
    await waitFor(() => expect(planApi.importXml).toHaveBeenCalledWith(7, 'detailed', file, true))
  })

  it('has no import on a legacy server', async () => {
    renderPlanner()
    await screen.findByTestId('gantt-planner')
    expect(screen.queryByTestId('gantt-import')).toBeNull()
  })

  it('reports the plan to the host', async () => {
    const onPlanChange = vi.fn()
    renderPlanner({ onPlanChange })
    await screen.findByTestId('gantt-planner')
    expect(onPlanChange).toHaveBeenCalledWith(expect.objectContaining({ revision: 3 }))
  })

  it('a refetch that started before a save cannot hide the saved move', async () => {
    const moved = modernOut({ tasks: modernOut().tasks.map((t) => (t.id === 2 ? { ...t, start_date: '2026-10-11' } : t)) })
    vi.mocked(planApi.get).mockResolvedValueOnce(modernOut())
    let releaseGet!: (p: PlanOut) => void
    vi.mocked(planApi.get).mockImplementationOnce(() => new Promise((r) => { releaseGet = r }))
    vi.mocked(planApi.applyChanges).mockResolvedValue({ ...moved, id_map: {}, link_id_map: {} })
    renderPlanner()
    await screen.findByTestId('gantt-planner')
    void qc.refetchQueries({ queryKey: ['change', 7, 'plan', 'detailed'] })
    await waitFor(() => expect(planApi.get).toHaveBeenCalledTimes(2))
    drag(screen.getByTestId('gantt-bar-shape-2'), 28)
    await waitFor(() => expect(planApi.applyChanges).toHaveBeenCalled())
    await act(async () => { releaseGet(modernOut()) })
    await new Promise((r) => setTimeout(r, 30))
    expect(screen.getByTestId('gantt-row-2').textContent).toContain('11.10.26')
  })

  it('progress: only on the detailed plan during implementation, for editors or the task department', async () => {
    // Before the baseline and without a listed department: no progress.
    vi.mocked(planApi.get).mockResolvedValue(planOut({ baseline_set: false, can_edit: true, can_edit_dates: true, progress_department_ids: [] }))
    renderPlanner({ mode: 'track' })
    await screen.findByTestId('gantt-planner')
    expect(screen.queryByTestId('gantt-progress-handle-1')).toBeNull()
    cleanup()
    vi.mocked(planApi.get).mockResolvedValue(planOut({ baseline_set: true, can_edit: false, can_edit_dates: true, progress_department_ids: [11] }))
    renderPlanner({ mode: 'track' })
    await screen.findByTestId('gantt-planner')
    expect(screen.getByTestId('gantt-progress-handle-1')).toBeTruthy()
    cleanup()
    vi.mocked(planApi.get).mockResolvedValue(planOut({ plan: 'quote', can_edit: true, can_edit_dates: true, progress_department_ids: [11] }))
    renderPlanner({ mode: 'track', plan: 'quote' })
    await screen.findByTestId('gantt-planner')
    expect(screen.queryByTestId('gantt-progress-handle-1')).toBeNull()
  })

  it('the slack column shows the server slack', async () => {
    vi.mocked(planApi.get).mockResolvedValue(modernOut({ tasks: modernOut().tasks.map((t) => ({ ...t, total_slack: t.id * 3 })) }))
    renderPlanner()
    await screen.findByTestId('gantt-planner')
    expect(screen.getByTestId('gantt-row-2').querySelector('[data-col="slack"]')!.textContent).toBe('6d')
  })

  it('lists the notes the server made while importing', async () => {
    vi.mocked(planApi.get).mockResolvedValue(modernOut({ tasks: [] }))
    vi.mocked(planApi.importXml).mockResolvedValue({ ...modernOut(), import_warnings: ['Task 5 has no name and was skipped'] })
    renderPlanner()
    await screen.findByTestId('gantt-empty')
    cleanup()
    vi.mocked(planApi.get).mockResolvedValue(modernOut())
    renderPlanner()
    await screen.findByTestId('gantt-planner')
    const file = new File(['<Project/>'], 'plan.xml', { type: 'application/xml' })
    fireEvent.change(screen.getByTestId('gantt-import-file'), { target: { files: [file] } })
    fireEvent.click(await screen.findByTestId('confirm-ok'))
    expect((await screen.findByTestId('gantt-import-warnings')).textContent).toContain('Task 5 has no name')
  })

  it('after the baseline auto-schedule previews the moves and sends a reason', async () => {
    vi.mocked(planApi.get).mockResolvedValue(modernOut({
      baseline_set: true, can_edit: false,
      tasks: modernOut().tasks.map((t) => (t.id === 2 ? { ...t, start_date: '2026-10-08' } : t)),
    }))
    vi.mocked(planApi.schedule).mockResolvedValue(modernOut({ baseline_set: true, can_edit: false }))
    renderPlanner({ mode: 'track' })
    await screen.findByTestId('gantt-planner')
    fireEvent.click(screen.getByTestId('gantt-schedule'))
    const dialog = await screen.findByRole('dialog', { name: 'Record a deviation' })
    expect(within(dialog).getByTestId('deviation-changed').textContent).toContain('Sampling')
    fireEvent.change(within(dialog).getByRole('textbox'), { target: { value: 'tool late' } })
    fireEvent.click(within(dialog).getByText('Save move'))
    await waitFor(() => expect(planApi.schedule).toHaveBeenCalledWith(7, 'detailed', 'tool late'))
  })

  it('undo of a delete re-creates the task through "re:" temp ids', async () => {
    vi.mocked(planApi.get).mockResolvedValue(modernOut())
    renderPlanner()
    await screen.findByTestId('gantt-planner')
    vi.mocked(planApi.applyChanges).mockResolvedValueOnce({ ...modernOut({ tasks: modernOut().tasks.filter((t) => t.id !== 3), links: [modernOut().links![0]] }), id_map: {}, link_id_map: {} })
    fireEvent.click(screen.getByTestId('gantt-row-3'))
    fireEvent.keyDown(screen.getByTestId('gantt-scroller'), { key: 'Delete' })
    await waitFor(() => expect(planApi.applyChanges).toHaveBeenCalledTimes(1))
    vi.mocked(planApi.applyChanges).mockResolvedValueOnce({ ...modernOut(), id_map: { 're:3': 30 }, link_id_map: { 're:52': 62 } })
    fireEvent.click(screen.getByTestId('gantt-undo'))
    await waitFor(() => expect(planApi.applyChanges).toHaveBeenCalledTimes(2))
    const body = vi.mocked(planApi.applyChanges).mock.calls[1][2]
    expect(body.tasks_upsert[0].id).toBe('re:3')
    expect(body.links_upsert).toEqual([expect.objectContaining({ id: 're:52', from_task_id: 2, to_task_id: 're:3' })])
  })

  it('progress: an editor may report after the baseline even when no department is listed', async () => {
    vi.mocked(planApi.get).mockResolvedValue(planOut({ baseline_set: true, can_edit: false, can_edit_dates: true, progress_department_ids: [] }))
    renderPlanner({ mode: 'track' })
    await screen.findByTestId('gantt-planner')
    expect(screen.getByTestId('gantt-progress-handle-1')).toBeTruthy()
  })

})
