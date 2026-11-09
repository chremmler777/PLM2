import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, fireEvent, cleanup } from '@testing-library/react'
import TimingTable from './TimingTable'
import type { GanttTask } from '../../gantt/engine/types'

const tasks: GanttTask[] = [
  { id: 1, name: 'Tool rework', kind: 'downtime', start: '2027-01-04', duration: 14 },
  { id: 2, name: 'Bank build', kind: 'bank_build', start: '2026-12-21', duration: 10 },
  { id: 3, name: 'Sampling', kind: 'sampling', start: '2027-01-18', duration: 5 },
]
const rowNo = new Map([[1, 1], [2, 2], [3, 3]])

describe('TimingTable (typed timing)', () => {
  afterEach(cleanup)

  it('types a duration in weeks and sends it in days', () => {
    const onApply = vi.fn()
    render(<TimingTable tasks={tasks} links={[]} rowNo={rowNo} canDates canLinks onApply={onApply} />)
    const dur = screen.getByLabelText('Tool rework duration') as HTMLInputElement
    expect(dur.value).toBe('2') // 14 days shown as 2 weeks
    fireEvent.change(dur, { target: { value: '3' } })
    fireEvent.blur(dur)
    expect(onApply).toHaveBeenCalledWith({ label: 'Edit duration', updateTasks: [{ id: 1, patch: { duration: 21 } }] })
  })

  it('"starts after" relinks and moves the task to the predecessor end', () => {
    const onApply = vi.fn()
    render(<TimingTable tasks={tasks} links={[{ id: 9, from: 2, to: 3, type: 'FS', lagDays: 0 }]} rowNo={rowNo} canDates canLinks onApply={onApply} />)
    fireEvent.change(screen.getByLabelText('Sampling starts after'), { target: { value: '1' } })
    const cs = onApply.mock.calls[0][0]
    expect(cs.removeLinks).toEqual([9])
    expect(cs.addLinks[0]).toMatchObject({ from: 1, to: 3, type: 'FS', lagDays: 0 })
    // the tool rework ends on 18 Jan 2027, where the sampling already starts: no move needed
    expect(cs.updateTasks).toBeUndefined()
  })

  it('marks bank builds as an estimate and is read-only without rights', () => {
    render(<TimingTable tasks={tasks} links={[]} rowNo={rowNo} canDates={false} canLinks={false} onApply={vi.fn()} />)
    expect(screen.getByTestId('timing-row-2').textContent).toContain('Estimate')
    expect((screen.getByLabelText('Tool rework duration') as HTMLInputElement).disabled).toBe(true)
    expect((screen.getByLabelText('Sampling starts after') as HTMLSelectElement).disabled).toBe(true)
  })
})
