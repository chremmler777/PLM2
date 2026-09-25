import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { Gantt, type GanttProps } from './Gantt'
import { gridTiming } from './columns'
import type { ChangeSet, GanttLink, GanttModel, GanttTask } from './engine/types'

const base = (): GanttTask[] => [
  { id: 1, name: 'Alpha', start: '2026-10-05', duration: 5, lane: 'Tool' },
  { id: 2, name: 'Beta', start: '2026-10-12', duration: 3, lane: 'Tool' },
  { id: 3, name: 'Gamma', start: '2026-10-15', duration: 2, lane: 'Customer' },
]
const baseLinks = (): GanttLink[] => [{ id: 'L1', from: 1, to: 2, type: 'FS', lagDays: 0 }]

type Props = Partial<GanttProps>
function setup(props: Props = {}) {
  const onChange = vi.fn(async (cs: ChangeSet) => { void cs })
  const onError = vi.fn()
  const utils = render(
    <Gantt tasks={props.tasks ?? base()} links={props.links ?? baseLinks()} onChange={onChange} onError={onError}
      columns={['row', 'name', 'start', 'end', 'duration', 'predecessors']} defaultZoom="day" showToday={false} {...props} />)
  const cs = (i = 0) => onChange.mock.calls[i][0] as ChangeSet
  return { ...utils, onChange, onError, cs }
}

/** Drag in day zoom: 28 px per day. */
function drag(el: Element, dx: number, init: { shiftKey?: boolean; ctrlKey?: boolean } = {}) {
  fireEvent.pointerDown(el, { button: 0, clientX: 100, clientY: 10, ...init })
  fireEvent.pointerMove(window, { clientX: 100 + dx / 2, clientY: 10 })
  fireEvent.pointerMove(window, { clientX: 100 + dx, clientY: 10 })
  fireEvent.pointerUp(window, { clientX: 100 + dx, clientY: 10 })
}
const root = () => screen.getByTestId('gantt-root')
const key = (k: string, init: Record<string, unknown> = {}) => fireEvent.keyDown(root(), { key: k, ...init })
const cell = (id: number | string, col: string) =>
  screen.getByTestId(`gantt-row-${id}`).querySelector(`[data-col="${col}"]`) as HTMLElement
/** Select the row, then click the cell: spreadsheet-style editing of the active row. */
const startEdit = (id: number | string, col: string) => {
  fireEvent.click(screen.getByTestId(`gantt-row-${id}`))
  fireEvent.click(cell(id, col))
}
const editCell = (id: number, col: string, value: string, submit: 'Enter' | 'Escape' = 'Enter') => {
  startEdit(id, col)
  const ed = screen.getByTestId('gantt-cell-editor')
  fireEvent.change(ed, { target: { value } })
  fireEvent.keyDown(ed, { key: submit })
}

beforeEach(() => { vi.useRealTimers(); gridTiming.editDelay = 0 })
afterEach(() => { cleanup(); vi.restoreAllMocks() })

describe('Gantt: rendering', () => {
  it('renders a grid row, a bar and the links', () => {
    setup()
    for (const id of [1, 2, 3]) {
      expect(screen.getByTestId(`gantt-row-${id}`)).toBeTruthy()
      expect(screen.getByTestId(`gantt-bar-${id}`)).toBeTruthy()
      expect(screen.getByTestId(`gantt-bar-shape-${id}`)).toBeTruthy()
    }
    expect(screen.getByTestId('gantt-link-1-2').getAttribute('data-link-type')).toBe('FS')
  })

  it('shows row numbers, dd.mm.yy dates, inclusive finish and predecessors', () => {
    setup()
    expect(cell(2, 'row').textContent).toBe('2')
    expect(cell(1, 'start').textContent).toBe('5 Oct 26')
    expect(cell(1, 'end').textContent).toBe('9 Oct 26')
    expect(cell(1, 'duration').textContent).toBe('5d')
    expect(cell(2, 'predecessors').textContent).toBe('1')
  })

  it('flags a task that breaks its link', () => {
    setup({ tasks: [base()[0], { ...base()[1], start: '2026-10-06' }, base()[2]] })
    expect(within(screen.getByTestId('gantt-row-2')).getByLabelText('Has a plan issue')).toBeTruthy()
  })

  it('draws a milestone as a diamond path', () => {
    setup({ tasks: [...base(), { id: 4, name: 'SOP', start: '2026-10-20', duration: 0 }] })
    expect(screen.getByTestId('gantt-bar-shape-4').tagName.toLowerCase()).toBe('path')
  })

  it('shows markers in the chart and the header', () => {
    setup({ markers: [{ id: 'rel', date: '2026-10-20', label: 'Release' }] })
    expect(screen.getByTestId('gantt-marker-rel')).toBeTruthy()
    expect(screen.getByTestId('gantt-marker-label-rel').textContent).toContain('Release 20 Oct 26')
  })

  it('shows baselines and slip tails', () => {
    setup({ showBaselines: true, tasks: [{ ...base()[0], baselineStart: '2026-10-05', baselineEnd: '2026-10-08' }, base()[1], base()[2]] })
    expect(screen.getByTestId('gantt-baseline-1')).toBeTruthy()
    expect(screen.getByTestId('gantt-slip-1')).toBeTruthy()
  })

  it('toggles baselines from the toolbar', () => {
    setup({ tasks: [{ ...base()[0], baselineStart: '2026-10-05', baselineEnd: '2026-10-10' }, base()[1]] })
    expect(screen.queryByTestId('gantt-baseline-1')).toBeNull()
    fireEvent.click(screen.getByTestId('gantt-baseline-toggle'))
    expect(screen.getByTestId('gantt-baseline-1')).toBeTruthy()
  })

  it('marks the critical path when toggled', () => {
    setup()
    expect(screen.queryByTestId('gantt-critical-3')).toBeNull()
    fireEvent.click(screen.getByTestId('gantt-critical-toggle'))
    // Gamma ends last (17 Oct); Alpha -> Beta ends 15 Oct and has slack.
    expect(screen.getByTestId('gantt-critical-3')).toBeTruthy()
    expect(screen.queryByTestId('gantt-critical-1')).toBeNull()
  })

  it('uses the host critical ids when given', () => {
    setup({ criticalPath: true, criticalIds: [1] })
    expect(screen.getByTestId('gantt-critical-1')).toBeTruthy()
    expect(screen.queryByTestId('gantt-critical-3')).toBeNull()
  })

  it('shows progress fills in track mode', () => {
    setup({ showProgress: true, tasks: [{ ...base()[0], progress: 40 }] , links: [] })
    expect(screen.getByTestId('gantt-progress-1')).toBeTruthy()
  })

  it('renders only the name column when compact', () => {
    setup({ compact: true })
    expect(screen.queryByTestId('gantt-toolbar')).toBeNull()
    expect(cell(1, 'start')).toBeNull()
    expect(cell(1, 'name').textContent).toContain('Alpha')
  })
})

describe('Gantt: zoom', () => {
  it('switches the header scale', () => {
    setup()
    const day = screen.getByTestId('gantt-chart-header').textContent
    fireEvent.click(screen.getByTestId('gantt-zoom-week'))
    expect(screen.getByTestId('gantt-zoom-week').getAttribute('aria-pressed')).toBe('true')
    const week = screen.getByTestId('gantt-chart-header').textContent
    expect(week).toMatch(/CW\d+/)
    expect(week).not.toBe(day)
    fireEvent.click(screen.getByTestId('gantt-zoom-month'))
    expect(screen.getByTestId('gantt-chart-header').textContent).toContain('2026')
    fireEvent.click(screen.getByTestId('gantt-zoom-quarter'))
    expect(screen.getByTestId('gantt-chart-header').textContent).toMatch(/Q[1-4]/)
  })

  it('fits the plan to the width', () => {
    setup()
    const before = Number(screen.getByTestId('gantt-body').getAttribute('width'))
    fireEvent.click(screen.getByTestId('gantt-zoom-fit'))
    expect(screen.getByTestId('gantt-zoom-fit').getAttribute('aria-pressed')).toBe('true')
    expect(Number(screen.getByTestId('gantt-body').getAttribute('width'))).toBeLessThan(before)
  })
})

describe('Gantt: selection', () => {
  it('selects with a click, adds with ctrl and extends with shift', () => {
    setup()
    fireEvent.click(screen.getByTestId('gantt-row-1'))
    expect(screen.getByTestId('gantt-row-1').getAttribute('aria-selected')).toBe('true')
    fireEvent.click(screen.getByTestId('gantt-row-3'), { ctrlKey: true })
    expect(screen.getByTestId('gantt-row-2').getAttribute('aria-selected')).toBe('false')
    expect(screen.getByTestId('gantt-row-3').getAttribute('aria-selected')).toBe('true')
    fireEvent.click(screen.getByTestId('gantt-row-1'))
    fireEvent.click(screen.getByTestId('gantt-row-3'), { shiftKey: true })
    expect(screen.getByTestId('gantt-row-2').getAttribute('aria-selected')).toBe('true')
  })

  it('ctrl-click toggles a selected row off', () => {
    setup()
    fireEvent.click(screen.getByTestId('gantt-row-1'))
    fireEvent.click(screen.getByTestId('gantt-row-1'), { ctrlKey: true })
    expect(screen.getByTestId('gantt-row-1').getAttribute('aria-selected')).toBe('false')
  })

  it('reports the selection to the host', () => {
    const onSelectionChange = vi.fn()
    setup({ onSelectionChange })
    fireEvent.click(screen.getByTestId('gantt-row-2'))
    expect(onSelectionChange).toHaveBeenLastCalledWith([2])
  })

  it('selects a bar on click without a drag and saves nothing', async () => {
    const { onChange } = setup()
    drag(screen.getByTestId('gantt-bar-shape-2'), 1)
    expect(screen.getByTestId('gantt-row-2').getAttribute('aria-selected')).toBe('true')
    await new Promise((r) => setTimeout(r, 10))
    expect(onChange).not.toHaveBeenCalled()
  })

  it('moves the active row with the arrow keys, shift extends', () => {
    setup()
    fireEvent.click(screen.getByTestId('gantt-row-1'))
    key('ArrowDown')
    expect(screen.getByTestId('gantt-row-2').getAttribute('aria-selected')).toBe('true')
    expect(screen.getByTestId('gantt-row-1').getAttribute('aria-selected')).toBe('false')
    key('ArrowDown', { shiftKey: true })
    expect(screen.getByTestId('gantt-row-2').getAttribute('aria-selected')).toBe('true')
    expect(screen.getByTestId('gantt-row-3').getAttribute('aria-selected')).toBe('true')
  })

  it('Escape clears the selection, ctrl+a selects all', () => {
    setup()
    key('a', { ctrlKey: true })
    expect(screen.getAllByRole('row').filter((r) => r.getAttribute('aria-selected') === 'true').length).toBe(3)
    key('Escape')
    expect(screen.getAllByRole('row').filter((r) => r.getAttribute('aria-selected') === 'true').length).toBe(0)
  })
})

describe('Gantt: dragging bars', () => {
  it('moves a bar by whole days', async () => {
    const { onChange, cs } = setup()
    drag(screen.getByTestId('gantt-bar-shape-1'), 56)
    await waitFor(() => expect(onChange).toHaveBeenCalledTimes(1))
    expect(cs().updateTasks).toEqual([{ id: 1, patch: { start: '2026-10-07' } }])
    expect(cs().label).toBe('Move task')
    // Optimistic: the grid shows the new date at once.
    expect(cell(1, 'start').textContent).toBe('7 Oct 26')
  })

  it('moves a multi-selection as one block', async () => {
    const { onChange, cs } = setup()
    fireEvent.click(screen.getByTestId('gantt-row-1'))
    fireEvent.click(screen.getByTestId('gantt-row-3'), { ctrlKey: true })
    drag(screen.getByTestId('gantt-bar-shape-1'), 28)
    await waitFor(() => expect(onChange).toHaveBeenCalledTimes(1))
    expect(cs().updateTasks).toEqual([
      { id: 1, patch: { start: '2026-10-06' } }, { id: 3, patch: { start: '2026-10-16' } },
    ])
  })

  it('resizes from the right edge', async () => {
    const { onChange, cs } = setup()
    drag(screen.getByTestId('gantt-resize-1'), -84)
    await waitFor(() => expect(onChange).toHaveBeenCalled())
    expect(cs().updateTasks).toEqual([{ id: 1, patch: { duration: 2 } }])
  })

  it('never resizes below one day', async () => {
    const { onChange, cs } = setup()
    drag(screen.getByTestId('gantt-resize-1'), -28 * 20)
    await waitFor(() => expect(onChange).toHaveBeenCalled())
    expect(cs().updateTasks).toEqual([{ id: 1, patch: { duration: 1 } }])
  })

  it('resizes from the left edge keeping the end', async () => {
    const { onChange, cs } = setup()
    drag(screen.getByTestId('gantt-resize-start-1'), 28)
    await waitFor(() => expect(onChange).toHaveBeenCalled())
    expect(cs().updateTasks).toEqual([{ id: 1, patch: { start: '2026-10-06', duration: 4 } }])
  })

  it('has no left handle on narrow bars', () => {
    setup({ tasks: [{ id: 9, name: 'Tiny', start: '2026-10-05', duration: 1 }], links: [], defaultZoom: 'week' })
    expect(screen.queryByTestId('gantt-resize-start-9')).toBeNull()
    expect(screen.getByTestId('gantt-resize-9')).toBeTruthy()
  })

  it('drags progress in 5 % steps', async () => {
    const { onChange, cs } = setup({ showProgress: true, rights: { progress: true } })
    drag(screen.getByTestId('gantt-progress-handle-1'), 70) // half of the 140 px bar
    await waitFor(() => expect(onChange).toHaveBeenCalled())
    expect(cs().updateTasks).toEqual([{ id: 1, patch: { progress: 50 } }])
    expect(cs().label).toBe('Progress')
  })

  it('moves the leaves when a summary bar is dragged', async () => {
    const { onChange, cs } = setup({
      tasks: [{ id: 10, name: 'Phase', start: '2026-10-05', duration: 1 }, { ...base()[0], parentId: 10 }, { ...base()[1], parentId: 10 }],
    })
    drag(screen.getByTestId('gantt-bar-shape-10'), 28)
    await waitFor(() => expect(onChange).toHaveBeenCalled())
    expect(cs().updateTasks?.map((u) => u.id).sort()).toEqual([1, 2])
  })

  it('nudges the selection with the arrow keys (shift = a week)', async () => {
    const { onChange, cs } = setup()
    fireEvent.click(screen.getByTestId('gantt-row-3'))
    key('ArrowRight', { shiftKey: true })
    key('ArrowLeft')
    await waitFor(() => expect(onChange).toHaveBeenCalled(), { timeout: 2000 })
    expect(cs().updateTasks).toEqual([{ id: 3, patch: { start: '2026-10-21' } }])
  })

  it('pushes successors when autoSchedule is on', async () => {
    const { onChange, cs } = setup({ autoSchedule: true })
    drag(screen.getByTestId('gantt-bar-shape-1'), 28 * 5)
    await waitFor(() => expect(onChange).toHaveBeenCalled())
    expect(cs().updateTasks).toEqual(expect.arrayContaining([
      { id: 1, patch: { start: '2026-10-10' } }, { id: 2, patch: { start: '2026-10-15' } },
    ]))
  })

  it('snaps to working days in working mode', async () => {
    const { onChange, cs } = setup({ calendar: { mode: 'working', workdays: [1, 2, 3, 4, 5], holidays: [] } })
    drag(screen.getByTestId('gantt-bar-shape-1'), 28 * 5) // Mon + 5 = Saturday -> Monday
    await waitFor(() => expect(onChange).toHaveBeenCalled())
    expect(cs().updateTasks).toEqual([{ id: 1, patch: { start: '2026-10-12' } }])
  })
})

describe('Gantt: links', () => {
  const drawLink = (from: string, target: Element) => {
    fireEvent.pointerDown(screen.getByTestId(from), { button: 0, clientX: 10, clientY: 10 })
    fireEvent.pointerMove(window, { clientX: 20, clientY: 40 })
    fireEvent.pointerUp(target, { clientX: 0, clientY: 40 })
  }

  it('draws finish-to-start from the end dot onto a bar', async () => {
    const { onChange, cs } = setup()
    drawLink('gantt-connector-end-2', screen.getByTestId('gantt-bar-shape-3'))
    await waitFor(() => expect(onChange).toHaveBeenCalled())
    expect(cs().addLinks).toEqual([expect.objectContaining({ from: 2, to: 3, type: 'FS', lagDays: 0 })])
  })

  it.each([
    ['gantt-connector-start-2', 'gantt-connector-start-3', 'SS'],
    ['gantt-connector-end-2', 'gantt-connector-end-3', 'FF'],
    ['gantt-connector-start-2', 'gantt-connector-end-3', 'SF'],
  ])('takes the type from the ends used (%s -> %s = %s)', async (from, to, type) => {
    const { onChange, cs } = setup()
    drawLink(from, screen.getByTestId(to))
    await waitFor(() => expect(onChange).toHaveBeenCalled())
    expect(cs().addLinks?.[0].type).toBe(type)
  })

  it('refuses a loop', async () => {
    const { onChange, onError } = setup()
    drawLink('gantt-connector-end-2', screen.getByTestId('gantt-bar-shape-1'))
    expect(onError).toHaveBeenCalledWith('That link would create a loop', undefined)
    await new Promise((r) => setTimeout(r, 10))
    expect(onChange).not.toHaveBeenCalled()
  })

  it('refuses link types the host does not offer', () => {
    const { onChange, onError } = setup({ linkTypes: ['FS'] })
    drawLink('gantt-connector-start-2', screen.getByTestId('gantt-connector-start-3'))
    expect(onError.mock.calls[0][0]).toContain('SS links are not available')
    expect(onChange).not.toHaveBeenCalled()
  })

  it('tells when the tasks are already linked', () => {
    const onNotify = vi.fn()
    const { onChange } = setup({ onNotify })
    drawLink('gantt-connector-end-1', screen.getByTestId('gantt-bar-shape-2'))
    expect(onNotify).toHaveBeenCalledWith(expect.stringContaining('These tasks are already linked'))
    expect(onChange).not.toHaveBeenCalled()
  })

  it('ignores a drop on nothing or on the same task', () => {
    const { onChange } = setup()
    drawLink('gantt-connector-end-1', screen.getByTestId('gantt-bar-shape-1'))
    drawLink('gantt-connector-end-1', screen.getByTestId('gantt-body'))
    expect(onChange).not.toHaveBeenCalled()
  })

  it('edits type and lag in the link popover', async () => {
    const { onChange, cs } = setup()
    fireEvent.click(screen.getByTestId('gantt-link-hit-L1'))
    const pop = screen.getByTestId('gantt-link-popover')
    fireEvent.change(within(pop).getByLabelText('Link type'), { target: { value: 'SS' } })
    fireEvent.change(within(pop).getByLabelText('Lag'), { target: { value: '-2' } })
    fireEvent.click(within(pop).getByTestId('gantt-link-save'))
    await waitFor(() => expect(onChange).toHaveBeenCalled())
    expect(cs().updateLinks).toEqual([{ id: 'L1', patch: { type: 'SS', lagDays: -2 } }])
    expect(screen.queryByTestId('gantt-link-popover')).toBeNull()
  })

  it('removes a link from the popover', async () => {
    const { onChange, cs } = setup()
    fireEvent.click(screen.getByTestId('gantt-link-hit-L1'))
    fireEvent.click(screen.getByTestId('gantt-link-delete'))
    await waitFor(() => expect(onChange).toHaveBeenCalled())
    expect(cs().removeLinks).toEqual(['L1'])
    await waitFor(() => expect(screen.queryByTestId('gantt-link-1-2')).toBeNull())
  })

  it('hides the lag field when lags are not allowed', () => {
    setup({ allowLag: false })
    fireEvent.click(screen.getByTestId('gantt-link-hit-L1'))
    expect(within(screen.getByTestId('gantt-link-popover')).queryByLabelText('Lag')).toBeNull()
  })

  it('links and unlinks the selection from the toolbar', async () => {
    const { onChange, cs } = setup()
    fireEvent.click(screen.getByTestId('gantt-row-2'))
    fireEvent.click(screen.getByTestId('gantt-row-3'), { ctrlKey: true })
    fireEvent.click(screen.getByTestId('gantt-tasks-menu'))
    fireEvent.click(screen.getByTestId('gantt-link-selected'))
    await waitFor(() => expect(onChange).toHaveBeenCalledTimes(1))
    expect(cs().addLinks).toEqual([expect.objectContaining({ from: 2, to: 3, type: 'FS' })])
    fireEvent.click(screen.getByTestId('gantt-row-1'))
    fireEvent.click(screen.getByTestId('gantt-tasks-menu'))
    fireEvent.click(screen.getByTestId('gantt-unlink'))
    await waitFor(() => expect(onChange).toHaveBeenCalledTimes(2))
    expect(cs(1).removeLinks).toEqual(['L1'])
  })
})

describe('Gantt: inline editing', () => {
  it('renames a task', async () => {
    const { onChange, cs } = setup()
    editCell(1, 'name', 'Alpha 2')
    await waitFor(() => expect(onChange).toHaveBeenCalled())
    expect(cs().updateTasks).toEqual([{ id: 1, patch: { name: 'Alpha 2' } }])
  })

  it('Escape cancels an edit', async () => {
    const { onChange } = setup()
    editCell(1, 'name', 'Nope', 'Escape')
    expect(screen.queryByTestId('gantt-cell-editor')).toBeNull()
    await new Promise((r) => setTimeout(r, 10))
    expect(onChange).not.toHaveBeenCalled()
  })

  it('refuses an empty name', () => {
    const { onChange, onError } = setup()
    editCell(1, 'name', '  ')
    expect(onError).toHaveBeenCalledWith('A task needs a name', undefined)
    expect(onChange).not.toHaveBeenCalled()
  })

  it('edits the start date', async () => {
    const { onChange, cs } = setup()
    editCell(2, 'start', '2026-10-13')
    await waitFor(() => expect(onChange).toHaveBeenCalled())
    expect(cs().updateTasks).toEqual([{ id: 2, patch: { start: '2026-10-13' } }])
  })

  it('edits the finish as the inclusive last day', async () => {
    const { onChange, cs } = setup()
    editCell(1, 'end', '2026-10-11')
    await waitFor(() => expect(onChange).toHaveBeenCalled())
    expect(cs().updateTasks).toEqual([{ id: 1, patch: { duration: 7 } }])
  })

  it('refuses a finish before the start', () => {
    const { onError } = setup()
    editCell(1, 'end', '2026-10-01')
    expect(onError).toHaveBeenCalledWith('The finish cannot be before the start', undefined)
  })

  it('edits the duration', async () => {
    const { onChange, cs } = setup()
    editCell(3, 'duration', '7')
    await waitFor(() => expect(onChange).toHaveBeenCalled())
    expect(cs().updateTasks).toEqual([{ id: 3, patch: { duration: 7 } }])
  })

  it('keeps the duration when the field is emptied', async () => {
    const { onChange } = setup()
    editCell(3, 'duration', '')
    await new Promise((r) => setTimeout(r, 10))
    expect(onChange).not.toHaveBeenCalled()
  })

  it('edits progress in its column', async () => {
    const { onChange, cs } = setup({ columns: ['name', 'progress'], rights: { progress: true } })
    editCell(1, 'progress', '140')
    await waitFor(() => expect(onChange).toHaveBeenCalled())
    expect(cs().updateTasks).toEqual([{ id: 1, patch: { progress: 100 } }])
  })

  it('refuses a negative duration', () => {
    const { onError } = setup()
    editCell(3, 'duration', '-1')
    expect(onError).toHaveBeenCalledWith('The duration must be 0 or more days', undefined)
  })

  it('creates a link from MS Project notation', async () => {
    const { onChange, cs } = setup()
    editCell(3, 'predecessors', '1FS+2d')
    await waitFor(() => expect(onChange).toHaveBeenCalled())
    expect(cs().addLinks).toEqual([expect.objectContaining({ from: 1, to: 3, type: 'FS', lagDays: 2 })])
  })

  it('changes an existing link through the notation', async () => {
    const { onChange, cs } = setup()
    editCell(2, 'predecessors', '1SS-1')
    await waitFor(() => expect(onChange).toHaveBeenCalled())
    expect(cs().updateLinks).toEqual([{ id: 'L1', patch: { type: 'SS', lagDays: -1 } }])
  })

  it('removes links when the cell is cleared', async () => {
    const { onChange, cs } = setup()
    editCell(2, 'predecessors', '')
    await waitFor(() => expect(onChange).toHaveBeenCalled())
    expect(cs().removeLinks).toEqual(['L1'])
  })

  it('reports bad notation', () => {
    const { onChange, onError } = setup()
    editCell(3, 'predecessors', 'abc')
    expect(onError).toHaveBeenCalled()
    expect(onChange).not.toHaveBeenCalled()
  })

  it('reports a loop typed in the notation', () => {
    const { onChange, onError } = setup()
    editCell(1, 'predecessors', '2')
    expect(onError).toHaveBeenCalledWith('Those predecessors would create a loop', undefined)
    expect(onChange).not.toHaveBeenCalled()
  })

  it('refuses a lag when lags are not allowed', () => {
    const { onError } = setup({ allowLag: false })
    editCell(3, 'predecessors', '1+2')
    expect(onError).toHaveBeenCalledWith('Lag and lead are not available here', undefined)
  })

  it('does not edit date cells of a summary', () => {
    setup({ tasks: [{ id: 10, name: 'Phase', start: '2026-10-05', duration: 1 }, { ...base()[0], parentId: 10 }], links: [] })
    startEdit(10, 'start')
    expect(screen.queryByTestId('gantt-cell-editor')).toBeNull()
  })
})

describe('Gantt: new rows', () => {
  it('adds a draft row that is saved only once it has a name', async () => {
    const { onChange, cs } = setup()
    fireEvent.click(screen.getByTestId('gantt-row-3'))
    fireEvent.click(screen.getByTestId('gantt-add-task'))
    const ed = screen.getByTestId('gantt-cell-editor')
    await new Promise((r) => setTimeout(r, 10))
    expect(onChange).not.toHaveBeenCalled()
    fireEvent.change(ed, { target: { value: 'Delta' } })
    fireEvent.keyDown(ed, { key: 'Enter' })
    await waitFor(() => expect(onChange).toHaveBeenCalled())
    const add = cs().addTasks![0]
    expect(add).toEqual(expect.objectContaining({ name: 'Delta', duration: 1, lane: 'Customer', start: '2026-10-17' }))
    expect(cs().order?.map(String)).toEqual(['1', '2', '3', String(add.id)])
  })

  it('Escape discards the draft', async () => {
    const { onChange } = setup()
    fireEvent.click(screen.getByTestId('gantt-add-task'))
    expect(screen.getAllByRole('row').length).toBe(1 + 4) // header + 3 + draft
    fireEvent.keyDown(screen.getByTestId('gantt-cell-editor'), { key: 'Escape' })
    expect(screen.getAllByRole('row').length).toBe(1 + 3)
    await new Promise((r) => setTimeout(r, 10))
    expect(onChange).not.toHaveBeenCalled()
  })

  it('an empty name drops the draft', async () => {
    const { onChange } = setup()
    fireEvent.click(screen.getByTestId('gantt-add-task'))
    fireEvent.keyDown(screen.getByTestId('gantt-cell-editor'), { key: 'Enter' })
    await new Promise((r) => setTimeout(r, 10))
    expect(onChange).not.toHaveBeenCalled()
    expect(screen.getAllByRole('row').length).toBe(1 + 3)
  })

  it('Insert starts a draft; a milestone draft has duration 0', async () => {
    const { onChange, cs } = setup({ newTask: ({ milestone }) => ({ kind: milestone ? 'milestone' : 'work' }) })
    key('Insert')
    expect(screen.getByTestId('gantt-cell-editor')).toBeTruthy()
    fireEvent.keyDown(screen.getByTestId('gantt-cell-editor'), { key: 'Escape' })
    fireEvent.click(screen.getByTestId('gantt-add-milestone'))
    const ed = screen.getByTestId('gantt-cell-editor')
    fireEvent.change(ed, { target: { value: 'Gate' } })
    fireEvent.keyDown(ed, { key: 'Enter' })
    await waitFor(() => expect(onChange).toHaveBeenCalled())
    expect(cs().addTasks![0]).toEqual(expect.objectContaining({ name: 'Gate', duration: 0, kind: 'milestone' }))
  })

  it('duplicates the selection with ctrl+d', async () => {
    const { onChange, cs } = setup()
    fireEvent.click(screen.getByTestId('gantt-row-1'))
    key('d', { ctrlKey: true })
    await waitFor(() => expect(onChange).toHaveBeenCalled())
    expect(cs().addTasks![0]).toEqual(expect.objectContaining({ name: 'Alpha (copy)', start: '2026-10-05', duration: 5 }))
  })

  it('copy and paste duplicates too', async () => {
    const { onChange } = setup()
    fireEvent.click(screen.getByTestId('gantt-row-2'))
    key('c', { ctrlKey: true })
    key('v', { ctrlKey: true })
    await waitFor(() => expect(onChange).toHaveBeenCalled())
  })
})

describe('Gantt: structure', () => {
  it('indents with Tab and outdents with shift+Tab', async () => {
    const { onChange, cs } = setup()
    fireEvent.click(screen.getByTestId('gantt-row-2'))
    key('Tab')
    await waitFor(() => expect(onChange).toHaveBeenCalledTimes(1))
    expect(cs().updateTasks).toEqual([{ id: 2, patch: { parentId: 1 } }])
    await waitFor(() => expect(screen.getByTestId('gantt-toggle-1')).toBeTruthy())
    key('Tab', { shiftKey: true })
    await waitFor(() => expect(onChange).toHaveBeenCalledTimes(2))
    expect(cs(1).updateTasks).toEqual([{ id: 2, patch: { parentId: null } }])
  })

  it('indents from the toolbar', async () => {
    const { onChange, cs } = setup()
    fireEvent.click(screen.getByTestId('gantt-row-3'))
    fireEvent.click(screen.getByTestId('gantt-tasks-menu'))
    fireEvent.click(screen.getByTestId('gantt-indent'))
    await waitFor(() => expect(onChange).toHaveBeenCalled())
    expect(cs().updateTasks).toEqual([{ id: 3, patch: { parentId: 2 } }])
  })

  it('has no indent without hierarchy', () => {
    const { onChange } = setup({ hierarchy: false })
    expect(screen.queryByTestId('gantt-indent')).toBeNull()
    fireEvent.click(screen.getByTestId('gantt-row-2'))
    key('Tab')
    expect(onChange).not.toHaveBeenCalled()
  })

  it('Delete removes the task and its links', async () => {
    const { onChange, cs } = setup()
    fireEvent.click(screen.getByTestId('gantt-row-1'))
    key('Delete')
    await waitFor(() => expect(onChange).toHaveBeenCalled())
    expect(cs().removeTasks).toEqual([1])
    expect(cs().removeLinks).toEqual(['L1'])
    await waitFor(() => expect(screen.queryByTestId('gantt-row-1')).toBeNull())
  })

  it('collapses a summary', () => {
    setup({ tasks: [{ id: 10, name: 'Phase', start: '2026-10-05', duration: 1 }, { ...base()[0], parentId: 10 }], links: [] })
    expect(screen.getByTestId('gantt-row-1')).toBeTruthy()
    fireEvent.click(screen.getByTestId('gantt-toggle-10'))
    expect(screen.queryByTestId('gantt-row-1')).toBeNull()
    fireEvent.click(screen.getByTestId('gantt-toggle-10'))
    expect(screen.getByTestId('gantt-row-1')).toBeTruthy()
  })

  it('groups by lane and collapses a group', () => {
    setup({ groupByLane: true })
    expect(screen.getByTestId('gantt-group-Tool')).toBeTruthy()
    fireEvent.click(screen.getByTestId('gantt-group-Tool'))
    expect(screen.queryByTestId('gantt-row-1')).toBeNull()
    expect(screen.getByTestId('gantt-row-3')).toBeTruthy()
  })

  it('reorders rows by dragging the first cell', async () => {
    const { onChange, cs } = setup()
    const handle = cell(3, 'row')
    fireEvent.pointerDown(handle, { button: 0, clientX: 5, clientY: 2 * 28 + 10 })
    fireEvent.pointerMove(window, { clientX: 5, clientY: 5 })
    expect(screen.getByTestId('gantt-drop-line')).toBeTruthy()
    fireEvent.pointerUp(window, { clientX: 5, clientY: 5 })
    await waitFor(() => expect(onChange).toHaveBeenCalled())
    expect(cs().order).toEqual([3, 1, 2])
  })

  it('moving a row into another lane group changes its lane', async () => {
    const { onChange, cs } = setup({ groupByLane: true })
    // rows: group Tool(0), 1(1), 2(2), group Customer(3), 3(4) -> drag 3 before row 1
    fireEvent.pointerDown(cell(3, 'row'), { button: 0, clientX: 5, clientY: 4 * 28 + 10 })
    fireEvent.pointerMove(window, { clientX: 5, clientY: 28 + 3 })
    fireEvent.pointerUp(window, { clientX: 5, clientY: 28 + 3 })
    await waitFor(() => expect(onChange).toHaveBeenCalled())
    expect(cs().updateTasks).toEqual([{ id: 3, patch: { lane: 'Tool' } }])
  })
})

describe('Gantt: undo and redo', () => {
  it('undoes and redoes through the queue', async () => {
    const { onChange, cs } = setup()
    expect((screen.getByTestId('gantt-undo') as HTMLButtonElement).disabled).toBe(true)
    drag(screen.getByTestId('gantt-bar-shape-1'), 56)
    await waitFor(() => expect(onChange).toHaveBeenCalledTimes(1))
    expect((screen.getByTestId('gantt-undo') as HTMLButtonElement).disabled).toBe(false)
    key('z', { ctrlKey: true })
    await waitFor(() => expect(onChange).toHaveBeenCalledTimes(2))
    expect(cs(1).updateTasks).toEqual([{ id: 1, patch: { start: '2026-10-05' } }])
    key('y', { ctrlKey: true })
    await waitFor(() => expect(onChange).toHaveBeenCalledTimes(3))
    expect(cs(2).updateTasks).toEqual([{ id: 1, patch: { start: '2026-10-07' } }])
  })

  it('undo of a delete brings the task and its link back', async () => {
    const { onChange, cs } = setup()
    fireEvent.click(screen.getByTestId('gantt-row-1'))
    key('Delete')
    await waitFor(() => expect(onChange).toHaveBeenCalledTimes(1))
    fireEvent.click(screen.getByTestId('gantt-undo'))
    await waitFor(() => expect(onChange).toHaveBeenCalledTimes(2))
    expect(cs(1).addTasks?.[0].id).toBe(1)
    expect(cs(1).addLinks?.[0].id).toBe('L1')
  })

  it('ctrl+shift+z redoes', async () => {
    const { onChange } = setup()
    drag(screen.getByTestId('gantt-bar-shape-1'), 28)
    await waitFor(() => expect(onChange).toHaveBeenCalledTimes(1))
    key('z', { ctrlKey: true })
    await waitFor(() => expect(onChange).toHaveBeenCalledTimes(2))
    key('z', { ctrlKey: true, shiftKey: true })
    await waitFor(() => expect(onChange).toHaveBeenCalledTimes(3))
  })
})

describe('Gantt: context menu', () => {
  it('opens on right click with the task actions', () => {
    setup()
    fireEvent.contextMenu(screen.getByTestId('gantt-row-2'))
    const menu = screen.getByTestId('gantt-context-menu')
    for (const t of ['gantt-menu-open', 'gantt-menu-insert', 'gantt-menu-duplicate', 'gantt-menu-indent', 'gantt-menu-delete']) {
      expect(within(menu).getByTestId(t)).toBeTruthy()
    }
    expect(screen.getByTestId('gantt-row-2').getAttribute('aria-selected')).toBe('true')
  })

  it('deletes through the menu', async () => {
    const { onChange, cs } = setup()
    fireEvent.contextMenu(screen.getByTestId('gantt-bar-2'))
    fireEvent.click(screen.getByTestId('gantt-menu-delete'))
    await waitFor(() => expect(onChange).toHaveBeenCalled())
    expect(cs().removeTasks).toEqual([2])
    expect(screen.queryByTestId('gantt-context-menu')).toBeNull()
  })

  it('adds the host items', () => {
    const run = vi.fn()
    setup({ menuItems: (ids) => [{ label: `Custom ${ids.join(',')}`, onSelect: run, testId: 'custom' }] })
    fireEvent.contextMenu(screen.getByTestId('gantt-row-3'))
    expect(screen.getByTestId('custom').textContent).toContain('Custom 3')
    fireEvent.click(screen.getByTestId('custom'))
    expect(run).toHaveBeenCalled()
  })

  it('offers no edit actions when read-only', () => {
    setup({ readOnly: true })
    fireEvent.contextMenu(screen.getByTestId('gantt-row-2'))
    expect(screen.queryByTestId('gantt-menu-delete')).toBeNull()
    expect(screen.getByTestId('gantt-menu-open')).toBeTruthy()
  })
})

describe('Gantt: rights', () => {
  it('read-only shows no handles and saves nothing on drag', async () => {
    const { onChange } = setup({ readOnly: true })
    expect(screen.queryByTestId('gantt-connector-end-1')).toBeNull()
    expect(screen.queryByTestId('gantt-resize-1')).toBeNull()
    expect(screen.queryByTestId('gantt-add-task')).toBeNull()
    expect(screen.queryByTestId('gantt-undo')).toBeNull()
    drag(screen.getByTestId('gantt-bar-shape-1'), 56)
    await new Promise((r) => setTimeout(r, 10))
    expect(onChange).not.toHaveBeenCalled()
  })

  it('without date rights bars do not move but links still draw', async () => {
    const { onChange } = setup({ rights: { dates: false } })
    expect(screen.queryByTestId('gantt-resize-1')).toBeNull()
    expect(screen.getByTestId('gantt-connector-end-1')).toBeTruthy()
    drag(screen.getByTestId('gantt-bar-shape-1'), 56)
    await new Promise((r) => setTimeout(r, 10))
    expect(onChange).not.toHaveBeenCalled()
  })

  it('without link rights there are no connectors and the popover is read-only', () => {
    setup({ rights: { links: false } })
    expect(screen.queryByTestId('gantt-connector-end-1')).toBeNull()
    fireEvent.click(screen.getByTestId('gantt-link-hit-L1'))
    expect(screen.queryByTestId('gantt-link-save')).toBeNull()
  })

  it('field rights lock single columns', () => {
    setup({ rights: { field: (_t, f) => f !== 'name' } })
    startEdit(1, 'name')
    expect(screen.queryByTestId('gantt-cell-editor')).toBeNull()
    fireEvent.click(cell(1, 'duration'))
    expect(screen.getByTestId('gantt-cell-editor')).toBeTruthy()
  })

  it('a read-only task cannot be dragged', () => {
    setup({ tasks: [{ ...base()[0], readOnly: true }, base()[1]] })
    expect(screen.queryByTestId('gantt-resize-1')).toBeNull()
    expect(screen.getByTestId('gantt-resize-2')).toBeTruthy()
  })
})

describe('Gantt: host hooks', () => {
  it('beforeChange returning null cancels and reverts the drag', async () => {
    const { onChange } = setup({ beforeChange: () => null })
    drag(screen.getByTestId('gantt-bar-shape-1'), 56)
    await new Promise((r) => setTimeout(r, 20))
    expect(onChange).not.toHaveBeenCalled()
    expect(cell(1, 'start').textContent).toBe('5 Oct 26')
  })

  it('beforeChange can add meta (a reason)', async () => {
    const { onChange, cs } = setup({ beforeChange: async (c) => ({ ...c, meta: { reason: 'late' } }) })
    drag(screen.getByTestId('gantt-bar-shape-1'), 28)
    await waitFor(() => expect(onChange).toHaveBeenCalled())
    expect(cs().meta).toEqual({ reason: 'late' })
  })

  it('beforeChange sees the ChangeSet and the model', async () => {
    const before = vi.fn((c: ChangeSet, m: GanttModel) => { void m; return c })
    setup({ beforeChange: before })
    drag(screen.getByTestId('gantt-bar-shape-1'), 28)
    await waitFor(() => expect(before).toHaveBeenCalled())
    expect(before.mock.calls[0]?.[1].tasks.length).toBe(3)
  })

  it('rolls back and reports when the save fails', async () => {
    const onError = vi.fn()
    const onChange = vi.fn(() => Promise.reject({ response: { data: { detail: 'Plan is read-only' } } }))
    render(<Gantt tasks={base()} links={baseLinks()} onChange={onChange} onError={onError} defaultZoom="day" showToday={false}
      columns={['row', 'name', 'start']} />)
    drag(screen.getByTestId('gantt-bar-shape-1'), 56)
    await waitFor(() => expect(onError).toHaveBeenCalledWith('Plan is read-only', expect.anything()))
    await waitFor(() => expect(cell(1, 'start').textContent).toBe('5 Oct 26'))
    expect((screen.getByTestId('gantt-undo') as HTMLButtonElement).disabled).toBe(true)
  })

  it('shows a saving indicator while a save is in flight', async () => {
    let resolve!: () => void
    const onChange = vi.fn(() => new Promise<void>((r) => { resolve = r }))
    render(<Gantt tasks={base()} links={baseLinks()} onChange={onChange} defaultZoom="day" showToday={false} />)
    drag(screen.getByTestId('gantt-bar-shape-1'), 28)
    await waitFor(() => expect(screen.getByTestId('gantt-saving')).toBeTruthy())
    await act(async () => { resolve() })
    await waitFor(() => expect(screen.queryByTestId('gantt-saving')).toBeNull())
  })

  it('applies a host ChangeSet through the handle', async () => {
    const ref = { current: null as null | import('./Gantt').GanttHandle }
    const onChange = vi.fn(async () => undefined)
    render(<Gantt ref={(h) => { ref.current = h }} tasks={base()} links={baseLinks()} onChange={onChange} defaultZoom="day" />)
    await act(async () => { await ref.current!.apply({ updateTasks: [{ id: 3, patch: { name: 'G2' } }] }) })
    await waitFor(() => expect(onChange).toHaveBeenCalled())
    expect(ref.current!.getModel().tasks.find((t) => t.id === 3)?.name).toBe('G2')
  })
})

describe('Gantt: task dialog', () => {
  it('opens the built-in dialog on double click and saves a patch', async () => {
    const { onChange, cs } = setup()
    fireEvent.doubleClick(screen.getByTestId('gantt-bar-2'))
    const dlg = screen.getByTestId('gantt-task-dialog')
    fireEvent.change(within(dlg).getByLabelText('Name'), { target: { value: 'Beta 2' } })
    fireEvent.change(within(dlg).getByLabelText('Duration'), { target: { value: '4' } })
    fireEvent.click(within(dlg).getByTestId('gantt-task-dialog-save'))
    await waitFor(() => expect(onChange).toHaveBeenCalled())
    expect(cs().updateTasks).toEqual([{ id: 2, patch: { name: 'Beta 2', duration: 4 } }])
  })

  it('sets a constraint in the dialog', async () => {
    const { onChange, cs } = setup()
    fireEvent.doubleClick(screen.getByTestId('gantt-bar-3'))
    const dlg = screen.getByTestId('gantt-task-dialog')
    fireEvent.change(within(dlg).getByLabelText('Constraint'), { target: { value: 'snet' } })
    expect((within(dlg).getByTestId('gantt-task-dialog-save') as HTMLButtonElement).disabled).toBe(true)
    // Typed as dd.mm.yyyy (the field never shows the locale's mm/dd).
    const date = within(dlg).getByLabelText('Constraint date')
    fireEvent.change(date, { target: { value: '20.10.2026' } })
    fireEvent.blur(date)
    expect((date as HTMLInputElement).value).toBe('20 Oct 2026')
    fireEvent.click(within(dlg).getByTestId('gantt-task-dialog-save'))
    await waitFor(() => expect(onChange).toHaveBeenCalled())
    expect(cs().updateTasks).toEqual([{ id: 3, patch: { constraint: { type: 'snet', date: '2026-10-20' } } }])
  })

  it('Enter on the active row opens the dialog', () => {
    setup()
    fireEvent.click(screen.getByTestId('gantt-row-1'))
    key('Enter')
    expect(screen.getByTestId('gantt-task-dialog')).toBeTruthy()
  })

  it('calls the host editor instead when given', () => {
    const onTaskOpen = vi.fn()
    setup({ onTaskOpen })
    fireEvent.doubleClick(cell(1, 'row'))
    expect(onTaskOpen).toHaveBeenCalledWith(expect.objectContaining({ id: 1 }))
    expect(screen.queryByTestId('gantt-task-dialog')).toBeNull()
  })
})

describe('Gantt: export', () => {
  it('hands data exports to the host when it asks', () => {
    const onExport = vi.fn()
    setup({ onExport })
    fireEvent.click(screen.getByTestId('gantt-export'))
    fireEvent.click(screen.getByTestId('gantt-export-csv'))
    expect(onExport).toHaveBeenCalledWith('csv')
    fireEvent.click(screen.getByTestId('gantt-export'))
    fireEvent.click(screen.getByTestId('gantt-export-xml'))
    expect(onExport).toHaveBeenCalledWith('mspdi')
  })

  it('downloads a client side CSV otherwise', () => {
    const createObjectURL = vi.fn(() => 'blob:x')
    Object.assign(URL, { createObjectURL, revokeObjectURL: vi.fn() })
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined)
    setup({ exportName: 'plan-x' })
    fireEvent.click(screen.getByTestId('gantt-export'))
    fireEvent.click(screen.getByTestId('gantt-export-csv'))
    expect(createObjectURL).toHaveBeenCalled()
    expect(click).toHaveBeenCalled()
  })

  it('opens a print window', () => {
    const doc = { open: vi.fn(), write: vi.fn(), close: vi.fn() }
    const open = vi.spyOn(window, 'open').mockReturnValue({ document: doc } as unknown as Window)
    setup()
    fireEvent.click(screen.getByTestId('gantt-export'))
    fireEvent.click(screen.getByTestId('gantt-export-print'))
    expect(open).toHaveBeenCalled()
    expect(doc.write.mock.calls[0][0]).toContain('<svg')
  })

  it('reports a blocked print window', () => {
    vi.spyOn(window, 'open').mockReturnValue(null)
    const { onError } = setup()
    fireEvent.click(screen.getByTestId('gantt-export'))
    fireEvent.click(screen.getByTestId('gantt-export-print'))
    expect(onError).toHaveBeenCalledWith('The print window was blocked by the browser', undefined)
  })
})

describe('Gantt: review fixes', () => {
  const tree = (): GanttTask[] => [
    { id: 1, name: 'Alpha', start: '2026-10-05', duration: 5 },
    { id: 10, name: 'Phase', start: '2026-10-05', duration: 0 },
    { id: 11, name: 'Child', start: '2026-10-12', duration: 2, parentId: 10 },
  ]
  const drawLink = (from: string, target: Element) => {
    fireEvent.pointerDown(screen.getByTestId(from), { button: 0, clientX: 10, clientY: 10 })
    fireEvent.pointerMove(window, { clientX: 20, clientY: 40 })
    fireEvent.pointerUp(target, { clientX: 0, clientY: 40 })
  }

  // (1) undo of a delete re-adds under the old ids; the adapter maps them to new ones.
  it('undo of a delete then remaps the re-added task, and redo deletes the new id', async () => {
    const onChange = vi.fn(async (cs: ChangeSet) => (cs.addTasks?.length ? { idMap: { 1: 91 }, linkIdMap: { L1: 92 } } : undefined))
    render(<Gantt tasks={base()} links={baseLinks()} onChange={onChange} defaultZoom="day" showToday={false} />)
    fireEvent.click(screen.getByTestId('gantt-row-1'))
    key('Delete')
    await waitFor(() => expect(onChange).toHaveBeenCalledTimes(1))
    key('z', { ctrlKey: true })
    await waitFor(() => expect(onChange).toHaveBeenCalledTimes(2))
    expect(onChange.mock.calls[1][0].addTasks?.[0].id).toBe(1)
    key('y', { ctrlKey: true })
    await waitFor(() => expect(onChange).toHaveBeenCalledTimes(3))
    expect(onChange.mock.calls[2][0].removeTasks).toEqual([91])
    expect(onChange.mock.calls[2][0].removeLinks).toEqual([92])
  })

  // (2) a second draft named while the first insert is still saving.
  it('a second draft named while the first save is in flight orders by the real id', async () => {
    let release!: (v: { idMap: Record<string, number> }) => void
    let n = 0
    const onChange = vi.fn((cs: ChangeSet): Promise<{ idMap: Record<string, number> } | void> => (++n === 1
      ? new Promise<{ idMap: Record<string, number> }>((r) => { release = r })
      : Promise.resolve(void cs)))
    render(<Gantt tasks={base()} links={[]} onChange={onChange} defaultZoom="day" showToday={false} />)
    fireEvent.click(screen.getByTestId('gantt-row-3'))
    fireEvent.click(screen.getByTestId('gantt-add-task'))
    let ed = screen.getByTestId('gantt-cell-editor')
    fireEvent.change(ed, { target: { value: 'First' } })
    fireEvent.keyDown(ed, { key: 'Enter' })
    await waitFor(() => expect(onChange).toHaveBeenCalledTimes(1))
    const firstId = String(onChange.mock.calls[0][0].addTasks![0].id)
    fireEvent.click(screen.getByTestId(`gantt-row-${firstId}`))
    fireEvent.click(screen.getByTestId('gantt-add-task'))
    ed = screen.getByTestId('gantt-cell-editor')
    await act(async () => { release({ idMap: { [firstId]: 500 } }) })
    fireEvent.change(ed, { target: { value: 'Second' } })
    fireEvent.keyDown(ed, { key: 'Enter' })
    await waitFor(() => expect(onChange).toHaveBeenCalledTimes(2))
    const order = onChange.mock.calls[1][0].order!.map(String)
    expect(order).not.toContain(firstId)
    expect(order.indexOf('500')).toBe(order.length - 2)
  })

  // (4) summary rule in the UI.
  it('refuses FF/SF drawn into a summary and a link to its own summary', async () => {
    const { onChange, onError } = setup({ tasks: tree(), links: [] })
    drawLink('gantt-connector-end-1', screen.getByTestId('gantt-connector-end-10'))
    expect(onError).toHaveBeenCalledWith(expect.stringContaining('into a summary task are not allowed'), undefined)
    drawLink('gantt-connector-end-11', screen.getByTestId('gantt-bar-shape-10'))
    expect(onError).toHaveBeenLastCalledWith(expect.stringContaining('own summary'), undefined)
    await new Promise((r) => setTimeout(r, 10))
    expect(onChange).not.toHaveBeenCalled()
  })

  it('allows FS drawn into a summary', async () => {
    const { onChange, cs } = setup({ tasks: tree(), links: [] })
    drawLink('gantt-connector-end-1', screen.getByTestId('gantt-bar-shape-10'))
    await waitFor(() => expect(onChange).toHaveBeenCalled())
    expect(cs().addLinks![0]).toMatchObject({ from: 1, to: 10, type: 'FS' })
  })

  it('refuses FF into a summary typed as a predecessor', () => {
    const { onChange, onError } = setup({ tasks: tree(), links: [], columns: ['row', 'name', 'predecessors'] })
    startEdit(10, 'predecessors')
    const ed = screen.getByTestId('gantt-cell-editor')
    fireEvent.change(ed, { target: { value: '1FF' } })
    fireEvent.keyDown(ed, { key: 'Enter' })
    expect(onError).toHaveBeenCalledWith(expect.stringContaining('FF links into a summary'), undefined)
    expect(onChange).not.toHaveBeenCalled()
  })

  it('the link popover into a summary offers no FF/SF', () => {
    setup({ tasks: tree(), links: [{ id: 'x', from: 1, to: 10, type: 'FS', lagDays: 0 }] })
    fireEvent.click(screen.getByTestId('gantt-link-hit-x'))
    const opts = within(screen.getByTestId('gantt-link-popover')).getAllByRole('option').map((o) => (o as HTMLOptionElement).value)
    expect(opts).toEqual(['FS', 'SS'])
  })

  it('the task dialog offers no must-start/finish-on for a summary', () => {
    setup({ tasks: tree(), links: [] })
    fireEvent.doubleClick(screen.getByTestId('gantt-bar-10'))
    const opts = within(screen.getByTestId('gantt-task-dialog')).getByLabelText('Constraint').querySelectorAll('option')
    expect([...opts].map((o) => o.value)).toEqual(['asap', 'snet', 'fnlt'])
  })

  it('a refused save rolls back only that change; the next one still goes out', async () => {
    const onChange = vi.fn(async (cs: ChangeSet) => { if (cs.label === 'Move task' && onChange.mock.calls.length === 1) throw new Error('refused') })
    const onError = vi.fn()
    render(<Gantt tasks={base()} links={[]} onChange={onChange} onError={onError} defaultZoom="day" showToday={false} columns={['row', 'name', 'start']} />)
    drag(screen.getByTestId('gantt-bar-shape-1'), 28)
    drag(screen.getByTestId('gantt-bar-shape-3'), 28)
    await waitFor(() => expect(onChange).toHaveBeenCalledTimes(2))
    await waitFor(() => expect(onError).toHaveBeenCalledWith('refused', expect.any(Error)))
    expect(cell(1, 'start').textContent).toBe('5 Oct 26')
    expect(cell(3, 'start').textContent).toBe('16 Oct 26')
    // Undo skips the refused move: it undoes the one that went through.
    fireEvent.click(screen.getByTestId('gantt-undo'))
    await waitFor(() => expect(onChange).toHaveBeenCalledTimes(3))
    expect(onChange.mock.calls[2][0].updateTasks).toEqual([{ id: 3, patch: { start: '2026-10-15' } }])
  })

  // (5) keys typed on toolbar buttons / dialogs do not reach the chart.
  it('Delete on a toolbar button or Tab in a menu does not act on the selection', async () => {
    const { onChange } = setup()
    fireEvent.click(screen.getByTestId('gantt-row-1'))
    fireEvent.keyDown(screen.getByTestId('gantt-zoom-week'), { key: 'Delete' })
    fireEvent.keyDown(screen.getByTestId('gantt-undo'), { key: 'Tab' })
    fireEvent.keyDown(screen.getByTestId('gantt-undo'), { key: 'z', ctrlKey: true })
    fireEvent.contextMenu(screen.getByTestId('gantt-row-1'))
    fireEvent.keyDown(screen.getByTestId('gantt-context-menu'), { key: 'Delete' })
    await new Promise((r) => setTimeout(r, 10))
    expect(onChange).not.toHaveBeenCalled()
    // In the chart the same key works.
    fireEvent.keyDown(screen.getByTestId('gantt-scroller'), { key: 'Delete' })
    await waitFor(() => expect(onChange).toHaveBeenCalled())
  })

  // (8) the drag commits with the current model, not a stale closure.
  it('a drag that starts before a model update commits against the new dates', async () => {
    const { onChange, cs, rerender } = setup()
    const shape = screen.getByTestId('gantt-bar-shape-1')
    fireEvent.pointerDown(shape, { button: 0, clientX: 100, clientY: 10 })
    fireEvent.pointerMove(window, { clientX: 128, clientY: 10 })
    rerender(<Gantt tasks={[{ ...base()[0], start: '2026-10-06' }, ...base().slice(1)]} links={baseLinks()} onChange={onChange}
      columns={['row', 'name', 'start', 'end', 'duration', 'predecessors']} defaultZoom="day" showToday={false} />)
    fireEvent.pointerUp(window, { clientX: 128, clientY: 10 })
    await waitFor(() => expect(onChange).toHaveBeenCalled())
    expect(cs().updateTasks).toEqual([{ id: 1, patch: { start: '2026-10-07' } }])
  })

  // (9) pointer moves that do not change the snapped day do not re-render.
  it('ignores pointer moves inside the same day', async () => {
    const raf = vi.spyOn(window, 'requestAnimationFrame')
    setup()
    const shape = screen.getByTestId('gantt-bar-shape-1')
    fireEvent.pointerDown(shape, { button: 0, clientX: 100, clientY: 10 })
    const before = raf.mock.calls.length
    for (const x of [104, 106, 108, 110, 112]) fireEvent.pointerMove(window, { clientX: x, clientY: 10 })
    expect(raf.mock.calls.length - before).toBeLessThanOrEqual(1)
    fireEvent.pointerUp(window, { clientX: 112, clientY: 10 })
  })

  // (12) lane grouping is a view: row numbers and stored order stay.
  it('lane grouping keeps the stored order and row numbers', async () => {
    const tasks: GanttTask[] = [
      { id: 1, name: 'A', start: '2026-10-05', duration: 1, lane: 'X' },
      { id: 2, name: 'B', start: '2026-10-05', duration: 1, lane: 'Y' },
      { id: 3, name: 'C', start: '2026-10-05', duration: 1, lane: 'X' },
    ]
    const { onChange, cs } = setup({ tasks, links: [{ id: 'l', from: 3, to: 2, type: 'FS', lagDays: 0 }], groupByLane: true, hierarchy: true })
    expect(cell(3, 'row').textContent).toBe('3')
    expect(cell(2, 'predecessors').textContent).toBe('3')
    fireEvent.click(screen.getByTestId('gantt-row-3'))
    key('d', { ctrlKey: true })
    await waitFor(() => expect(onChange).toHaveBeenCalled())
    expect(cs().order!.slice(0, 3).map(String)).toEqual(['1', '2', '3'])
  })

  // (14) a cancelled pointer ends a row drag without a move.
  it('pointercancel ends a row reorder without saving', async () => {
    const { onChange } = setup()
    fireEvent.pointerDown(cell(1, 'row'), { button: 0, clientY: 10 })
    fireEvent.pointerMove(window, { clientY: 70 })
    expect(screen.getByTestId('gantt-drop-line')).toBeTruthy()
    fireEvent.pointerCancel(window, { clientY: 70 })
    expect(screen.queryByTestId('gantt-drop-line')).toBeNull()
    await new Promise((r) => setTimeout(r, 10))
    expect(onChange).not.toHaveBeenCalled()
  })

  // (16) selection follows a temp id to the server id.
  it('keeps the new task selected after its temp id is replaced', async () => {
    const onChange = vi.fn(async (cs: ChangeSet) => ({ idMap: { [String(cs.addTasks![0].id)]: 70 } }))
    const { rerender } = render(<Gantt tasks={base()} links={[]} onChange={onChange} defaultZoom="day" showToday={false} />)
    fireEvent.click(screen.getByTestId('gantt-add-task'))
    const ed = screen.getByTestId('gantt-cell-editor')
    fireEvent.change(ed, { target: { value: 'New' } })
    fireEvent.keyDown(ed, { key: 'Enter' })
    await waitFor(() => expect(onChange).toHaveBeenCalled())
    rerender(<Gantt tasks={[...base(), { id: 70, name: 'New', start: '2026-10-19', duration: 1 }]} links={[]} onChange={onChange} defaultZoom="day" showToday={false} />)
    await waitFor(() => expect(screen.getByTestId('gantt-row-70').getAttribute('aria-selected')).toBe('true'))
  })

  // (17) cancelling the reason for an undo keeps the history entry.
  it('an undo cancelled by beforeChange stays undoable', async () => {
    let cancel = false
    const { onChange } = setup({ beforeChange: (cs) => (cancel ? null : cs) })
    drag(screen.getByTestId('gantt-bar-shape-1'), 28)
    await waitFor(() => expect(onChange).toHaveBeenCalledTimes(1))
    cancel = true
    key('z', { ctrlKey: true })
    await new Promise((r) => setTimeout(r, 10))
    expect(onChange).toHaveBeenCalledTimes(1)
    expect((screen.getByTestId('gantt-undo') as HTMLButtonElement).disabled).toBe(false)
    expect((screen.getByTestId('gantt-redo') as HTMLButtonElement).disabled).toBe(true)
    cancel = false
    key('z', { ctrlKey: true })
    await waitFor(() => expect(onChange).toHaveBeenCalledTimes(2))
  })

  // (18) accessibility of links, bars and virtual rows.
  it('links and bars are focusable with keyboard actions; rows carry aria-rowindex', async () => {
    const { onChange, cs } = setup()
    expect(screen.getByTestId('gantt-body').getAttribute('role')).toBe('group')
    const hit = screen.getByTestId('gantt-link-hit-L1')
    expect(hit.getAttribute('tabindex')).toBe('0')
    fireEvent.keyDown(hit, { key: 'Enter' })
    expect(screen.getByTestId('gantt-link-popover')).toBeTruthy()
    fireEvent.keyDown(document, { key: 'Escape' })
    fireEvent.keyDown(screen.getByTestId('gantt-link-hit-L1'), { key: 'Delete' })
    await waitFor(() => expect(onChange).toHaveBeenCalled())
    expect(cs().removeLinks).toEqual(['L1'])
    const bar = screen.getByTestId('gantt-bar-2')
    expect(bar.getAttribute('tabindex')).toBe('0')
    fireEvent.keyDown(bar, { key: ' ' })
    expect(screen.getByTestId('gantt-row-2').getAttribute('aria-selected')).toBe('true')
    expect(screen.getByTestId('gantt-row-3').getAttribute('aria-rowindex')).toBe('3')
  })

  it('clears undo when the rights change (baseline set)', async () => {
    const { onChange, rerender } = setup()
    drag(screen.getByTestId('gantt-bar-shape-1'), 28)
    await waitFor(() => expect(onChange).toHaveBeenCalled())
    expect((screen.getByTestId('gantt-undo') as HTMLButtonElement).disabled).toBe(false)
    rerender(<Gantt tasks={base()} links={baseLinks()} onChange={onChange} rights={{ structure: false, links: false }}
      columns={['row', 'name', 'start']} defaultZoom="day" showToday={false} />)
    await waitFor(() => expect((screen.getByTestId('gantt-undo') as HTMLButtonElement).disabled).toBe(true))
  })
})

describe('Gantt: read-only (legacy) links', () => {
  it('shows them, but the popover cannot edit or remove them and Delete does nothing', async () => {
    const { onChange } = setup({ links: [{ id: 'legacy-1-2-0', from: 1, to: 2, type: 'FS', lagDays: 0, readOnly: true }] })
    fireEvent.click(screen.getByTestId('gantt-link-hit-legacy-1-2-0'))
    const pop = screen.getByTestId('gantt-link-popover')
    expect(within(pop).getByTestId('gantt-link-note').textContent).toBe('Old dependency, re-draw to edit')
    expect(within(pop).queryByTestId('gantt-link-delete')).toBeNull()
    fireEvent.keyDown(document, { key: 'Escape' })
    fireEvent.keyDown(screen.getByTestId('gantt-link-hit-legacy-1-2-0'), { key: 'Delete' })
    fireEvent.click(screen.getByTestId('gantt-row-1'))
    fireEvent.click(screen.getByTestId('gantt-tasks-menu'))
    fireEvent.click(screen.getByTestId('gantt-unlink'))
    await new Promise((r) => setTimeout(r, 10))
    expect(onChange).not.toHaveBeenCalled()
  })

  it('drawing a pair covered only by an old dependency creates the real link', async () => {
    const { onChange, cs } = setup({ links: [{ id: 'legacy-1-2-0', from: 1, to: 2, type: 'FS', lagDays: 0, readOnly: true }] })
    fireEvent.pointerDown(screen.getByTestId('gantt-connector-end-1'), { button: 0, clientX: 10, clientY: 10 })
    fireEvent.pointerMove(window, { clientX: 20, clientY: 40 })
    fireEvent.pointerUp(screen.getByTestId('gantt-bar-shape-2'), { clientX: 0, clientY: 40 })
    await waitFor(() => expect(onChange).toHaveBeenCalled())
    expect(cs().addLinks![0]).toMatchObject({ from: 1, to: 2, type: 'FS' })
  })

  it('double-click on a row or bar opens the task; F2 edits the name (G16)', () => {
    const onTaskOpen = vi.fn()
    setup({ onTaskOpen })
    fireEvent.doubleClick(cell(2, 'start'))
    expect(onTaskOpen).toHaveBeenCalledWith(expect.objectContaining({ id: 2 }))
    expect(screen.queryByTestId('gantt-cell-editor')).toBeNull()
    fireEvent.doubleClick(screen.getByTestId('gantt-bar-3'))
    expect(onTaskOpen).toHaveBeenLastCalledWith(expect.objectContaining({ id: 3 }))
    fireEvent.click(screen.getByTestId('gantt-row-1'))
    key('F2')
    expect((screen.getByTestId('gantt-cell-editor') as HTMLInputElement).value).toBe('Alpha')
  })

  it('a new row under a selected summary becomes its last child with the lane of the leaf above (G13)', async () => {
    const tasks: GanttTask[] = [
      { id: 10, name: 'Phase', start: '2026-10-05', duration: 1, lane: 'Summary lane' },
      { id: 11, name: 'A', start: '2026-10-05', duration: 2, parentId: 10, lane: 'Tool' },
      { id: 12, name: 'B', start: '2026-10-07', duration: 2, parentId: 10, lane: 'APQP' },
      { id: 20, name: 'After', start: '2026-10-20', duration: 1 },
    ]
    const { onChange, cs } = setup({ tasks, links: [] })
    fireEvent.click(screen.getByTestId('gantt-row-10'))
    fireEvent.click(screen.getByTestId('gantt-add-task'))
    const ed = screen.getByTestId('gantt-cell-editor')
    fireEvent.change(ed, { target: { value: 'C' } })
    fireEvent.keyDown(ed, { key: 'Enter' })
    await waitFor(() => expect(onChange).toHaveBeenCalled())
    const t = cs().addTasks![0]
    expect(t).toMatchObject({ parentId: 10, lane: 'APQP', start: '2026-10-09' })
    expect(cs().order!.map(String)).toEqual(['10', '11', '12', String(t.id), '20'])
    // The new row stays selected.
    await waitFor(() => expect(screen.getByTestId(`gantt-row-${String(t.id)}`).getAttribute('aria-selected')).toBe('true'))
  })

  it('arrow keys nudge by working days in a working calendar (G5)', async () => {
    const { onChange, cs } = setup({ calendar: { mode: 'working', workdays: [1, 2, 3, 4, 5], holidays: [] } })
    fireEvent.click(screen.getByTestId('gantt-row-1')) // Mon 5 Oct
    key('ArrowLeft')
    await waitFor(() => expect(onChange).toHaveBeenCalled(), { timeout: 2000 })
    expect(cs().updateTasks).toEqual([{ id: 1, patch: { start: '2026-10-02' } }]) // Friday before
  })

  it('the first edit after the rights arrive stays undoable (G6)', async () => {
    const { onChange, rerender } = setup({ rights: { structure: false, dates: false, links: false } })
    rerender(<Gantt tasks={base()} links={baseLinks()} onChange={onChange} columns={['row', 'name', 'start']} defaultZoom="day" showToday={false} />)
    drag(screen.getByTestId('gantt-bar-shape-1'), 28)
    await waitFor(() => expect(onChange).toHaveBeenCalled())
    expect((screen.getByTestId('gantt-undo') as HTMLButtonElement).disabled).toBe(false)
  })

  it('automatic scheduling pushes successors in the same step, listed as derived (G9)', async () => {
    // Alpha 5..10 Oct -> Beta (12 Oct, FS) keeps its slack: move Alpha by 4 days (ends 14 Oct) pushes Beta to 14 Oct.
    const { onChange, cs } = setup({ autoSchedule: true })
    drag(screen.getByTestId('gantt-bar-shape-1'), 28 * 4)
    await waitFor(() => expect(onChange).toHaveBeenCalled())
    expect(cs().updateTasks).toEqual([{ id: 1, patch: { start: '2026-10-09' } }, { id: 2, patch: { start: '2026-10-14' } }])
    expect(cs().meta?.derived).toEqual([2])
    // One undo step restores both.
    key('z', { ctrlKey: true })
    await waitFor(() => expect(onChange).toHaveBeenCalledTimes(2))
    expect(cs(1).updateTasks).toEqual([{ id: 1, patch: { start: '2026-10-05' } }, { id: 2, patch: { start: '2026-10-12' } }])
    expect(cs(1).meta?.derived).toBeUndefined()
  })

  it('shows actual work as a thin bar and tracking columns (G17)', () => {
    setup({
      showProgress: true, columns: ['row', 'name', 'baselineStart', 'baselineEnd', 'variance', 'actualStart', 'actualEnd'],
      tasks: [{ ...base()[0], baselineStart: '2026-10-05', baselineEnd: '2026-10-08', actualStart: '2026-10-05', actualEnd: '2026-10-09' }, base()[1], base()[2]],
    })
    expect(screen.getByTestId('gantt-actual-1')).toBeTruthy()
    expect(cell(1, 'baselineEnd').textContent).toBe('7 Oct 26')
    expect(cell(1, 'variance').textContent).toBe('+2d')
    expect(cell(1, 'actualEnd').textContent).toBe('9 Oct 26')
  })
})

describe('Gantt: actual dates', () => {
  afterEach(cleanup)
  const tracked = () => setup({
    showProgress: true, columns: ['row', 'name', 'actualStart', 'actualEnd'],
    tasks: [{ ...base()[0], actualStart: '2026-01-10' }, base()[1], base()[2]],
  })

  it('refuses an actual finish before the actual start', () => {
    const { onChange, onError } = tracked()
    editCell(1, 'actualEnd', '2026-01-05')
    expect(onError).toHaveBeenCalledWith('The actual finish cannot be before the actual start', undefined)
    expect(onChange).not.toHaveBeenCalled()
  })

  it('refuses an actual date after today, tomorrow included', () => {
    const { onChange, onError } = tracked()
    const d = new Date(); d.setDate(d.getDate() + 1)
    const tomorrow = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
    editCell(1, 'actualEnd', tomorrow)
    expect(onError).toHaveBeenCalledWith('Actual dates cannot lie in the future', undefined)
    expect(onChange).not.toHaveBeenCalled()
  })
})

describe('Gantt: full screen', () => {
  const full = () => String(screen.getByTestId('gantt-root').getAttribute('data-full-screen') === 'true')

  it('turns the same instance into a full-viewport layer and back, keeping selection, zoom, draft and undo', async () => {
    const { onChange } = setup({ title: 'CR-1 - Quote plan' })
    fireEvent.click(screen.getByTestId('gantt-zoom-week'))
    fireEvent.click(screen.getByTestId('gantt-row-2'))
    drag(screen.getByTestId('gantt-bar-shape-3'), 28)
    await waitFor(() => expect(onChange).toHaveBeenCalledTimes(1))
    const rowBefore = screen.getByTestId('gantt-row-2')
    fireEvent.click(screen.getByTestId('gantt-full-screen'))
    expect(full()).toBe('true')
    expect(screen.getByTestId('gantt-root').className).toContain('fixed')
    expect(screen.getByTestId('gantt-full-header').textContent).toContain('CR-1 - Quote plan')
    expect(document.body.style.overflow).toBe('hidden')
    // no remount: the same row element, same zoom, selection and undo history
    expect(screen.getByTestId('gantt-row-2')).toBe(rowBefore)
    expect(screen.getByTestId('gantt-zoom-week').getAttribute('aria-pressed')).toBe('true')
    expect(screen.getByTestId('gantt-row-2').getAttribute('aria-selected')).toBe('true')
    expect((screen.getByTestId('gantt-undo') as HTMLButtonElement).disabled).toBe(false)
    fireEvent.click(screen.getByTestId('gantt-add-task'))
    fireEvent.keyDown(screen.getByTestId('gantt-cell-editor'), { key: 'F', ctrlKey: true, shiftKey: true })
    expect(full()).toBe('false')
    expect(document.body.style.overflow).toBe('')
    expect(screen.getByTestId('gantt-cell-editor')).toBeTruthy() // the draft row survives
    expect(screen.getAllByRole('row').length).toBe(1 + 4)
    expect((screen.getByTestId('gantt-undo') as HTMLButtonElement).disabled).toBe(false)
  })

  it('Ctrl+Shift+F toggles; Escape closes after popups and inline edits had theirs', () => {
    setup()
    fireEvent.click(screen.getByTestId('gantt-row-1'))
    key('F', { ctrlKey: true, shiftKey: true })
    expect(full()).toBe('true')
    // inline edit takes Escape first
    startEdit(1, 'name')
    fireEvent.keyDown(screen.getByTestId('gantt-cell-editor'), { key: 'Escape' })
    expect(screen.queryByTestId('gantt-cell-editor')).toBeNull()
    expect(full()).toBe('true')
    // the link popover takes Escape first
    fireEvent.click(screen.getByTestId('gantt-link-hit-L1'))
    expect(screen.getByTestId('gantt-link-popover')).toBeTruthy()
    fireEvent.keyDown(screen.getByTestId('gantt-link-popover'), { key: 'Escape' })
    expect(screen.queryByTestId('gantt-link-popover')).toBeNull()
    expect(full()).toBe('true')
    // now Escape closes the layer and keeps the selection
    key('Escape')
    expect(full()).toBe('false')
    expect(screen.getByTestId('gantt-row-1').getAttribute('aria-selected')).toBe('true')
    key('F', { ctrlKey: true, shiftKey: true })
    expect(full()).toBe('true')
    key('F', { ctrlKey: true, shiftKey: true })
    expect(full()).toBe('false')
  })

  it('Ctrl+Shift+F works from anywhere when this is the only Gantt on the page, not with two', () => {
    setup()
    fireEvent.keyDown(document.body, { key: 'F', ctrlKey: true, shiftKey: true })
    expect(full()).toBe('true')
    fireEvent.keyDown(document.body, { key: 'F', ctrlKey: true, shiftKey: true })
    expect(full()).toBe('false')
    render(<Gantt tasks={base()} links={[]} onChange={vi.fn()} showToday={false} />)
    fireEvent.keyDown(document.body, { key: 'F', ctrlKey: true, shiftKey: true })
    expect(screen.getAllByTestId('gantt-root').every((r) => r.getAttribute('data-full-screen') !== 'true')).toBe(true)
  })

  it('Escape from outside the chart closes too, unless a dialog is open', () => {
    setup()
    fireEvent.click(screen.getByTestId('gantt-full-screen'))
    const dlg = document.createElement('div'); dlg.setAttribute('role', 'dialog'); document.body.appendChild(dlg)
    fireEvent.keyDown(window, { key: 'Escape' })
    expect(full()).toBe('true')
    dlg.remove()
    fireEvent.keyDown(window, { key: 'Escape' })
    expect(full()).toBe('false')
  })

  it('Escape leaves full screen alone while a native dialog or an alert dialog is open', () => {
    setup()
    fireEvent.click(screen.getByTestId('gantt-full-screen'))
    const native = document.createElement('dialog'); native.setAttribute('open', ''); document.body.appendChild(native)
    fireEvent.keyDown(window, { key: 'Escape' })
    expect(full()).toBe('true')
    native.remove()
    const alert = document.createElement('div'); alert.setAttribute('role', 'alertdialog'); document.body.appendChild(alert)
    fireEvent.keyDown(window, { key: 'Escape' })
    expect(full()).toBe('true')
    alert.remove()
    fireEvent.keyDown(window, { key: 'Escape' })
    expect(full()).toBe('false')
  })

  it('moves focus in and restores it on close', async () => {
    setup()
    const btn = screen.getByTestId('gantt-full-screen')
    btn.focus()
    fireEvent.click(btn)
    await waitFor(() => expect(document.activeElement?.getAttribute('data-testid')).toBe('gantt-scroller'))
    fireEvent.click(screen.getByTestId('gantt-full-close'))
    expect(document.activeElement).toBe(btn)
  })

  it('renders the host content below in the layer, and hides the button when the host opts out', () => {
    setup({ below: <p data-testid="host-below">Legend</p> })
    fireEvent.click(screen.getByTestId('gantt-full-screen'))
    expect(within(screen.getByTestId('gantt-root')).getByTestId('host-below')).toBeTruthy()
    cleanup()
    setup({ fullScreen: false })
    expect(screen.queryByTestId('gantt-full-screen')).toBeNull()
  })
})

describe('Gantt: click, double-click and modifier clicks (review 4b93d732 #2, #3)', () => {
  beforeEach(() => { gridTiming.editDelay = 300 })
  const press = (el: Element, init: Record<string, unknown> = {}, detail = 1) => {
    fireEvent.pointerDown(el, { button: 0, ...init })
    fireEvent.pointerUp(el, { button: 0, ...init })
    fireEvent.click(el, { button: 0, detail, ...init })
  }

  it('double-click on the selected row opens the task panel, never the inline editor', async () => {
    const onTaskOpen = vi.fn()
    setup({ onTaskOpen })
    press(cell(2, 'name'))
    expect(screen.getByTestId('gantt-row-2').getAttribute('aria-selected')).toBe('true')
    // real sequence on the now active row: click, click, dblclick
    press(cell(2, 'name'), {}, 1)
    press(cell(2, 'name'), {}, 2)
    fireEvent.doubleClick(cell(2, 'name'), { detail: 2 })
    await new Promise((r) => setTimeout(r, 400))
    expect(onTaskOpen).toHaveBeenCalledWith(expect.objectContaining({ id: 2 }))
    expect(screen.queryByTestId('gantt-cell-editor')).toBeNull()
  })

  it('a double-click on a row that was not selected opens it too', async () => {
    const onTaskOpen = vi.fn()
    setup({ onTaskOpen })
    press(cell(3, 'start'), {}, 1)
    press(cell(3, 'start'), {}, 2)
    fireEvent.doubleClick(cell(3, 'start'), { detail: 2 })
    await new Promise((r) => setTimeout(r, 400))
    expect(onTaskOpen).toHaveBeenCalledTimes(1)
    expect(screen.queryByTestId('gantt-cell-editor')).toBeNull()
  })

  it('a single click on a cell of the already active row edits it after the double-click interval', async () => {
    setup()
    press(cell(1, 'name'))
    press(cell(1, 'name'))
    expect(screen.queryByTestId('gantt-cell-editor')).toBeNull()
    await waitFor(() => expect(screen.getByTestId('gantt-cell-editor')).toBeTruthy())
  })

  it('the first click on a row only selects it', async () => {
    setup()
    press(cell(1, 'name'))
    await new Promise((r) => setTimeout(r, 400))
    expect(screen.queryByTestId('gantt-cell-editor')).toBeNull()
  })

  it('ctrl or shift click on the selected row changes the selection and never edits', async () => {
    setup()
    press(cell(1, 'name'))
    press(cell(2, 'name'), { ctrlKey: true })
    expect(screen.getByTestId('gantt-row-2').getAttribute('aria-selected')).toBe('true')
    press(cell(2, 'name'), { ctrlKey: true })
    expect(screen.getByTestId('gantt-row-2').getAttribute('aria-selected')).toBe('false')
    press(cell(1, 'name'), { shiftKey: true })
    await new Promise((r) => setTimeout(r, 400))
    expect(screen.queryByTestId('gantt-cell-editor')).toBeNull()
    expect(screen.getByTestId('gantt-row-1').getAttribute('aria-selected')).toBe('true')
  })
})

describe('Gantt: columns that do not fit (review 4b93d732 #9)', () => {
  const TRACK = ['row', 'name', 'start', 'end', 'progress', 'baselineStart', 'baselineEnd', 'actualStart', 'actualEnd', 'variance', 'predecessors'] as const
  const withWidth = (w: number) => vi.spyOn(HTMLElement.prototype, 'clientWidth', 'get').mockReturnValue(w)
  const headers = () => screen.getAllByRole('columnheader').map((h) => h.getAttribute('title'))

  it('all tracking columns fit a 1600 px screen at 0.6 of the width (narrowed, not dropped)', () => {
    withWidth(1350)
    setup({ columns: [...TRACK], maxGridFraction: 0.6 })
    expect(headers()).toEqual(['#', 'Task', 'Start', 'Finish', 'Done', 'Base start', 'Base finish', 'Act. start', 'Act. finish', 'Var.', 'Predecessors'])
    expect(screen.getByTestId('gantt-columns').textContent).toBe('Columns')
    // names keep at least 180 px; narrowed headers are abbreviated, the full title is the tooltip
    const cols = screen.getAllByRole('columnheader')
    expect(parseFloat(cols[1].style.width)).toBeGreaterThanOrEqual(180)
    const pred = cols.find((h) => h.getAttribute('title') === 'Predecessors')!
    expect(pred.textContent).toBe('Pred.')
  })

  it('says how many columns were dropped and brings one back from the picker', () => {
    withWidth(900)
    setup({ columns: [...TRACK] })
    const btn = screen.getByTestId('gantt-columns')
    const n = TRACK.length - headers().length
    expect(n).toBeGreaterThan(0)
    expect(btn.textContent).toBe(`+${n} column${n === 1 ? '' : 's'}`)
    fireEvent.click(btn)
    const picker = screen.getByTestId('gantt-columns-picker')
    expect(within(picker).getAllByText('no room')).toHaveLength(n)
    fireEvent.click(within(picker).getByRole('checkbox', { name: /^Predecessors/ }))
    expect(headers()).toContain('Predecessors')
    // and hides one on request
    fireEvent.click(within(picker).getByRole('checkbox', { name: /^Start/ }))
    expect(headers()).not.toContain('Start')
    fireEvent.keyDown(picker, { key: 'Escape' })
    expect(screen.queryByTestId('gantt-columns-picker')).toBeNull()
  })
})

describe('Gantt: idea blocks hold no tasks (spec §11)', () => {
  it('refuses to indent a task under an idea', async () => {
    const { onChange, onError } = setup({ tasks: [{ ...base()[0], isIdea: true }, base()[1], base()[2]], links: [] })
    fireEvent.click(screen.getByTestId('gantt-row-2'))
    fireEvent.click(screen.getByTestId('gantt-tasks-menu'))
    fireEvent.click(screen.getByTestId('gantt-indent'))
    await new Promise((r) => setTimeout(r, 10))
    expect(onChange).not.toHaveBeenCalled()
    expect(onError).toHaveBeenCalledWith(expect.stringContaining('is an idea block: it cannot hold tasks'), undefined)
  })
})

describe('Gantt: scale and labels (review 4b93d732 #10)', () => {
  it('the quarter scale still fills a wide chart', () => {
    vi.spyOn(HTMLElement.prototype, 'clientWidth', 'get').mockReturnValue(1600)
    setup({ defaultZoom: 'quarter' })
    const body = screen.getByTestId('gantt-body')
    const w = Number(body.getAttribute('width'))
    const gw = parseFloat(screen.getByTestId('gantt-grid-header').style.width)
    expect(w).toBeGreaterThanOrEqual(1600 - gw - 4)
  })

  it('a long name that fits on neither side is cut with an ellipsis and keeps the full name as tooltip', () => {
    vi.spyOn(HTMLElement.prototype, 'clientWidth', 'get').mockReturnValue(700)
    const long = 'A very long task name that describes everything about the tooling rework in detail'
    setup({ tasks: [{ id: 1, name: long, start: '2026-10-05', duration: 20 }], links: [], defaultZoom: 'fit', columns: ['name'] })
    const label = screen.getByTestId('gantt-label-1')
    expect(label.textContent).toMatch(/…/)
    expect(label.querySelector('title')?.textContent).toBe(long)
    expect(screen.getByTestId('gantt-label-chip-1')).toBeTruthy()
  })
})

describe('Gantt: server pushes join the undo step (review 4b93d732 #11)', () => {
  it('undo restores a task the server moved on its own', async () => {
    const calls: ChangeSet[] = []
    const onChange = vi.fn(async (cs: ChangeSet) => {
      calls.push(cs)
      if (calls.length === 1) {
        // the server also pushed Gamma (not in the ChangeSet) by two days
        return { server: { tasks: [base()[0], { ...base()[1], duration: 4 }, { ...base()[2], start: '2026-10-17' }], links: chain } }
      }
      return {}
    })
    const chain: GanttLink[] = [...baseLinks(), { id: 'L2', from: 2, to: 3, type: 'FS', lagDays: 0 }]
    render(<Gantt tasks={base()} links={chain} onChange={onChange}
      columns={['row', 'name', 'start', 'end', 'duration']} defaultZoom="day" showToday={false} />)
    editCell(2, 'duration', '4')
    await waitFor(() => expect(onChange).toHaveBeenCalledTimes(1))
    await waitFor(() => expect((screen.getByTestId('gantt-undo') as HTMLButtonElement).disabled).toBe(false))
    await new Promise((r) => setTimeout(r, 0))
    fireEvent.click(screen.getByTestId('gantt-undo'))
    await waitFor(() => expect(onChange).toHaveBeenCalledTimes(2))
    expect(calls[1].updateTasks).toEqual(expect.arrayContaining([
      { id: 2, patch: { duration: 3 } },
      { id: 3, patch: { start: '2026-10-15' } },
    ]))
  })
})

describe('Gantt: server refusals with an object detail', () => {
  it('reads detail.message (400 summary_idea)', async () => {
    const onError = vi.fn()
    const err = { response: { status: 400, data: { detail: { message: 'A block with blocks under it cannot be an idea', code: 'summary_idea' } } } }
    render(<Gantt tasks={base()} links={baseLinks()} onChange={async () => { throw err }} onError={onError}
      columns={['row', 'name']} defaultZoom="day" showToday={false} />)
    editCell(1, 'name', 'Renamed')
    await waitFor(() => expect(onError).toHaveBeenCalledWith('A block with blocks under it cannot be an idea', err))
  })
})

describe('Gantt: undo while the step is still saving (review ee43fb8c #3)', () => {
  it('waits for the answer, so the server moves are undone too', async () => {
    const chain: GanttLink[] = [...baseLinks(), { id: 'L2', from: 2, to: 3, type: 'FS', lagDays: 0 }]
    let release!: (v: unknown) => void
    const calls: ChangeSet[] = []
    const onChange = vi.fn((cs: ChangeSet) => {
      calls.push(cs)
      if (calls.length === 1) {
        return new Promise((r) => { release = r }).then(() => ({
          server: { tasks: [base()[0], { ...base()[1], duration: 4 }, { ...base()[2], start: '2026-10-17' }], links: chain },
        }))
      }
      return Promise.resolve({})
    })
    render(<Gantt tasks={base()} links={chain} onChange={onChange}
      columns={['row', 'name', 'start', 'end', 'duration']} defaultZoom="day" showToday={false} />)
    editCell(2, 'duration', '4')
    await waitFor(() => expect(onChange).toHaveBeenCalledTimes(1))
    fireEvent.click(screen.getByTestId('gantt-undo'))
    await new Promise((r) => setTimeout(r, 20))
    expect(onChange).toHaveBeenCalledTimes(1) // the undo waits
    release(undefined)
    await waitFor(() => expect(onChange).toHaveBeenCalledTimes(2))
    expect(calls[1].updateTasks).toEqual(expect.arrayContaining([
      { id: 2, patch: { duration: 3 } },
      { id: 3, patch: { start: '2026-10-15' } },
    ]))
  })
})
