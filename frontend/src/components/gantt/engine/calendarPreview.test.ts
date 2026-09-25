import { describe, expect, it } from 'vitest'
import { calendarChangePreview } from './calendarPreview'
import type { GanttCalendar, GanttLink, GanttTask } from './types'

const CAL: Partial<GanttCalendar> = { mode: 'calendar', workdays: [1, 2, 3, 4, 5], holidays: [] }
const WORK: Partial<GanttCalendar> = { mode: 'working', workdays: [1, 2, 3, 4, 5], holidays: [] }
const T = (id: string, start: string, duration: number, over: Partial<GanttTask> = {}): GanttTask => ({ id, name: id, start, duration, ...over })
const L = (from: string, to: string, lagDays = 0): GanttLink => ({ id: `${from}-${to}`, from, to, type: 'FS', lagDays })

describe('calendarChangePreview', () => {
  it('nothing moves when the calendar stays the same', () => {
    expect(calendarChangePreview([T('A', '2026-10-05', 5)], [], CAL, CAL).moves).toEqual([])
  })

  it('keeping the numbers in working days makes tasks longer and snaps weekend starts', () => {
    const r = calendarChangePreview([T('A', '2026-10-05', 7), T('B', '2026-10-10', 1)], [], CAL, WORK)
    expect(r.moves.map((m) => [m.id, m.to.start, m.to.last])).toEqual([
      ['A', '2026-10-05', '2026-10-13'], ['B', '2026-10-12', '2026-10-12'],
    ])
    expect(r.maxShift).toBe(2)
  })

  it('converting keeps the real length: 7 calendar days are 5 working days (half up)', () => {
    const r = calendarChangePreview([T('A', '2026-10-05', 7)], [], CAL, WORK, { convert: true })
    expect(r.converted).toBe(1)
    expect(r.moves).toEqual([expect.objectContaining({ id: 'A', to: { start: '2026-10-05', last: '2026-10-09' }, shift: -2 })])
  })

  it('with automatic scheduling the successors are pushed along', () => {
    const tasks = [T('A', '2026-10-05', 5), T('B', '2026-10-10', 2)]
    const off = calendarChangePreview(tasks, [L('A', 'B')], CAL, WORK)
    const on = calendarChangePreview(tasks, [L('A', 'B')], CAL, WORK, { auto: true })
    expect(off.moves.find((m) => m.id === 'B')!.to.start).toBe('2026-10-12')
    expect(on.moves.find((m) => m.id === 'B')!.to.start).toBe('2026-10-12')
    const long = [T('A', '2026-10-05', 7), T('B', '2026-10-12', 2)]
    expect(calendarChangePreview(long, [L('A', 'B')], CAL, WORK, { auto: true }).moves.find((m) => m.id === 'B')!.to.start).toBe('2026-10-14')
    expect(calendarChangePreview(long, [L('A', 'B')], CAL, WORK).moves.find((m) => m.id === 'B')).toBeUndefined()
  })

  it('a conversion over the limits is reported', () => {
    const r = calendarChangePreview([T('A', '2026-10-05', 36000)], [], WORK, { ...CAL, workdays: [1] }, { convert: true })
    expect(r.error).toContain('more than 36500')
  })
})
