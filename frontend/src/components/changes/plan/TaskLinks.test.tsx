import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import TaskLinks from './TaskLinks'
import type { GanttLink } from '../../gantt/engine/types'

const tasks = [{ id: 1, name: 'Alpha', row: 1 }, { id: 2, name: 'Beta', row: 2 }]
const link = (lagDays: number): GanttLink => ({ id: 'L1', from: 1, to: 2, type: 'FS', lagDays })
const mount = (lag: number, onChange = vi.fn()) => {
  const ui = (l: number) => (
    <TaskLinks taskId={2} links={[link(l)]} tasks={tasks} canEdit types={['FS', 'SS', 'FF', 'SF']} allowLag summary={false}
      unit="days" onChange={onChange} />)
  const r = render(ui(lag))
  return { onChange, rerender: (l: number) => r.rerender(ui(l)) }
}
const lagInput = () => screen.getByLabelText('Lag of the link with Alpha') as HTMLInputElement

describe('TaskLinks lag (review 4b93d732 #4)', () => {
  afterEach(cleanup)

  it('follows the model: a new lag from undo or the server shows at once', () => {
    const { rerender } = mount(2)
    expect(lagInput().value).toBe('2')
    rerender(5)
    expect(lagInput().value).toBe('5')
  })

  it('commits on Enter only when changed, and never re-sends a stale value on blur', () => {
    const { onChange, rerender } = mount(2)
    fireEvent.focus(lagInput())
    fireEvent.change(lagInput(), { target: { value: '4' } })
    fireEvent.keyDown(lagInput(), { key: 'Enter' })
    fireEvent.blur(lagInput())
    expect(onChange).toHaveBeenCalledTimes(1)
    expect(onChange.mock.calls[0][0].updateLinks).toEqual([{ id: 'L1', patch: { lagDays: 4 } }])
    rerender(4)
    // undo brings 2 back: the field shows 2, a blur sends nothing
    rerender(2)
    expect(lagInput().value).toBe('2')
    fireEvent.focus(lagInput()); fireEvent.blur(lagInput())
    expect(onChange).toHaveBeenCalledTimes(1)
  })

  it('Escape, an empty field or an out-of-range lag restore the value without saving', () => {
    const { onChange } = mount(2)
    fireEvent.focus(lagInput())
    fireEvent.change(lagInput(), { target: { value: '9' } })
    fireEvent.keyDown(lagInput(), { key: 'Escape' })
    fireEvent.blur(lagInput())
    expect(lagInput().value).toBe('2')
    fireEvent.focus(lagInput())
    fireEvent.change(lagInput(), { target: { value: '' } })
    fireEvent.blur(lagInput())
    expect(lagInput().value).toBe('2')
    fireEvent.focus(lagInput())
    fireEvent.change(lagInput(), { target: { value: '99999' } })
    fireEvent.blur(lagInput())
    expect(lagInput().value).toBe('2')
    expect(onChange).not.toHaveBeenCalled()
  })
})
