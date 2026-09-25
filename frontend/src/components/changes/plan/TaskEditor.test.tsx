import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, cleanup, fireEvent } from '@testing-library/react'
import TaskEditor from './TaskEditor'
import type { TaskOut } from '../../../types/changePlan'

const task = (over: Partial<TaskOut> = {}): TaskOut => ({
  id: 1, change_id: 7, plan: 'detailed', name: 'Tool rework', lane: 'Tool Engineer', department_id: 11,
  department_name: 'Tool Engineer', kind: 'downtime', is_idea: false, start_date: '2026-10-05', duration_days: 5,
  end_date: '2026-10-10', predecessors: [], sort_order: 1, progress_pct: 0, actual_start: null, actual_finish: null,
  baseline_start: null, baseline_finish: null, notes: null, ...over,
})

const base = {
  tasks: [task(), task({ id: 2, name: 'Sampling' })], rowNo: new Map([[1, 1], [2, 2]]),
  departments: [{ id: 11, name: 'Tool Engineer' }], canEdit: true, canDates: true, canProgress: false,
  track: false, baselineSet: false, saving: false, onClose: vi.fn(),
}

describe('TaskEditor', () => {
  afterEach(cleanup)

  it('keeps unsaved edits when the server copy of the task changes', () => {
    const onSave = vi.fn()
    const { rerender } = render(<TaskEditor {...base} task={task()} onSave={onSave} />)
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Tool rework, second loop' } })
    // A drag elsewhere moves the task: the server answers with a new start.
    rerender(<TaskEditor {...base} task={task({ start_date: '2026-10-08' })} onSave={onSave} />)
    expect((screen.getByLabelText('Name') as HTMLInputElement).value).toBe('Tool rework, second loop')
    // The untouched start follows the server.
    expect((screen.getByLabelText('Start') as HTMLInputElement).value).toBe('8 Oct 2026')
    fireEvent.click(screen.getByTestId('task-editor-save'))
    expect(onSave).toHaveBeenCalledWith({ name: 'Tool rework, second loop' })
  })

  it('takes server values again once a field was saved', () => {
    const { rerender } = render(<TaskEditor {...base} task={task()} onSave={vi.fn()} />)
    fireEvent.change(screen.getByLabelText('Notes'), { target: { value: 'a' } })
    rerender(<TaskEditor {...base} task={task({ notes: 'a' })} onSave={vi.fn()} />)
    rerender(<TaskEditor {...base} task={task({ notes: 'b from someone else' })} onSave={vi.fn()} />)
    expect((screen.getByLabelText('Notes') as HTMLTextAreaElement).value).toBe('b from someone else')
  })

  it('starts over for another task', () => {
    const { rerender } = render(<TaskEditor {...base} task={task()} onSave={vi.fn()} />)
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'typing' } })
    rerender(<TaskEditor {...base} task={task({ id: 2, name: 'Sampling' })} onSave={vi.fn()} />)
    expect((screen.getByLabelText('Name') as HTMLInputElement).value).toBe('Sampling')
  })

  it('after the baseline only dates and notes are editable', () => {
    render(<TaskEditor {...base} canEdit={false} baselineSet task={task()} onSave={vi.fn()} />)
    expect((screen.getByLabelText('Name') as HTMLInputElement).disabled).toBe(true)
    expect((screen.getByLabelText('Kind') as HTMLSelectElement).disabled).toBe(true)
    expect((screen.getByLabelText('Lane') as HTMLInputElement).disabled).toBe(true)
    expect((screen.getByLabelText('Owner department') as HTMLSelectElement).disabled).toBe(true)
    expect((screen.getByLabelText('Start') as HTMLInputElement).disabled).toBe(false)
    expect((screen.getByLabelText('Notes') as HTMLTextAreaElement).disabled).toBe(false)
    expect(screen.getByText(/moves the successors along/)).toBeTruthy()
  })

  it('is docked in the page, not a fixed overlay over the chart', () => {
    render(<TaskEditor {...base} task={task()} onSave={vi.fn()} />)
    expect(screen.getByTestId('task-editor').className).not.toContain('fixed')
  })

  it('turns a milestone kind into a zero duration', () => {
    const onSave = vi.fn()
    render(<TaskEditor {...base} task={task()} onSave={onSave} />)
    fireEvent.change(screen.getByLabelText('Kind'), { target: { value: 'milestone' } })
    fireEvent.click(screen.getByTestId('task-editor-save'))
    expect(onSave).toHaveBeenCalledWith({ kind: 'milestone', duration_days: 0 })
  })

  it('a cleared Start says "Start is required" and keeps the start (review #8)', () => {
    const onSave = vi.fn()
    render(<TaskEditor {...base} task={task()} onSave={onSave} />)
    const start = screen.getByLabelText('Start') as HTMLInputElement
    fireEvent.change(start, { target: { value: '' } })
    fireEvent.blur(start)
    expect(screen.getByTestId('date-input-error').textContent).toBe('Start is required')
    expect(start.value).toBe('5 Oct 2026')
    fireEvent.change(screen.getByLabelText('Notes'), { target: { value: 'x' } })
    const reset = screen.getByText('Reset') as HTMLButtonElement
    expect(reset.disabled).toBe(false)
    fireEvent.click(reset)
    expect((screen.getByLabelText('Notes') as HTMLTextAreaElement).value).toBe('')
  })

  it('a summary has no idea switch of its own (spec §11)', () => {
    render(<TaskEditor {...base} task={task()} isSummary onSave={vi.fn()} />)
    expect(screen.queryByText('Idea block')).toBeNull()
    cleanup()
    render(<TaskEditor {...base} task={task()} onSave={vi.fn()} />)
    expect(screen.getByText('Idea block')).toBeTruthy()
  })
})
