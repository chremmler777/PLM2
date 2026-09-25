import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { Gantt, type GanttProps } from './Gantt'
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
const editCell = (id: number, col: string, value: string, submit: 'Enter' | 'Escape' = 'Enter') => {
  fireEvent.doubleClick(cell(id, col))
  const ed = screen.getByTestId('gantt-cell-editor')
  fireEvent.change(ed, { target: { value } })
  fireEvent.keyDown(ed, { key: submit })
}

beforeEach(() => { vi.useRealTimers() })
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
    expect(cell(1, 'start').textContent).toBe('05.10.26')
    expect(cell(1, 'end').textContent).toBe('09.10.26')
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
    expect(screen.getByTestId('gantt-marker-label-rel').textContent).toContain('Release 20.10.26')
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
    expect(cell(1, 'start').textContent).toBe('07.10.26')
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
    expect(onNotify).toHaveBeenCalledWith('These tasks are already linked')
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
    fireEvent.click(screen.getByTestId('gantt-link-selected'))
    await waitFor(() => expect(onChange).toHaveBeenCalledTimes(1))
    expect(cs().addLinks).toEqual([expect.objectContaining({ from: 2, to: 3, type: 'FS' })])
    fireEvent.click(screen.getByTestId('gantt-row-1'))
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
    fireEvent.doubleClick(cell(10, 'start'))
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
    fireEvent.doubleClick(cell(1, 'name'))
    expect(screen.queryByTestId('gantt-cell-editor')).toBeNull()
    fireEvent.doubleClick(cell(1, 'duration'))
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
    expect(cell(1, 'start').textContent).toBe('05.10.26')
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
    await waitFor(() => expect(cell(1, 'start').textContent).toBe('05.10.26'))
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
    fireEvent.change(within(dlg).getByLabelText('Constraint date'), { target: { value: '2026-10-20' } })
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
    const onChange = vi.fn(async (cs: ChangeSet) => (cs.addTasks?.length ? { idMap: { 1: 91, L1: 92 } } : undefined))
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
    fireEvent.doubleClick(cell(10, 'predecessors'))
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
    expect(cell(1, 'start').textContent).toBe('05.10.26')
    expect(cell(3, 'start').textContent).toBe('16.10.26')
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
