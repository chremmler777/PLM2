import { describe, it, expect } from 'vitest'
import type { TaskOut } from '../../../types/changePlan'
import {
  addDaysIso, applyDrag, buildRows, createsCycle, diffUpdates, durationFromInclusiveEnd, endOf,
  fmtDay, groupByLane, inclusiveEnd, isWeekend, isoWeek, matchTo, minorTicks, monthTicks,
  predecessorText, rowNumbers, runParallel, showCritical, slipDays, snapDays, snapToPredecessors,
  taskGeo, timelineRange, toDay, toIso, weekendSpans, xOf, zoomStep, NO_LANE,
} from './ganttMath'

const task = (over: Partial<TaskOut> & { id: number }): TaskOut => ({
  change_id: 1, plan: 'detailed', name: `T${over.id}`, lane: 'Tool Engineer', department_id: null,
  kind: 'work', is_idea: false, start_date: '2026-10-05', duration_days: 5, end_date: '2026-10-10',
  predecessors: [], sort_order: over.id, progress_pct: 0, actual_start: null, actual_finish: null,
  baseline_start: null, baseline_finish: null, notes: null, ...over,
})

describe('day arithmetic', () => {
  it('round-trips ISO days without timezone drift', () => {
    expect(toIso(toDay('2026-10-05'))).toBe('2026-10-05')
    expect(toIso(toDay('2024-02-29'))).toBe('2024-02-29')
    expect(addDaysIso('2026-12-30', 3)).toBe('2027-01-02')
    expect(addDaysIso('2026-03-29', 1)).toBe('2026-03-30') // DST switch in Berlin
  })

  it('knows weekends and ISO weeks', () => {
    expect(isWeekend(toDay('2026-10-03'))).toBe(true) // Saturday
    expect(isWeekend(toDay('2026-10-04'))).toBe(true) // Sunday
    expect(isWeekend(toDay('2026-10-05'))).toBe(false) // Monday
    expect(isoWeek(toDay('2026-01-01'))).toBe(1)
    expect(isoWeek(toDay('2026-09-24'))).toBe(39)
    expect(isoWeek(toDay('2027-01-01'))).toBe(53) // 2026 has 53 ISO weeks
  })

  it('formats a day compactly', () => {
    expect(fmtDay(toDay('2026-10-05'))).toBe('5 Oct 26')
    expect(fmtDay(null)).toBe('-')
  })
})

describe('inclusive end and durations', () => {
  it('shows end_date minus one for a task with duration', () => {
    const g = taskGeo(task({ id: 1, start_date: '2026-10-05', duration_days: 5 }))
    expect(toIso(endOf(g))).toBe('2026-10-10')
    expect(toIso(inclusiveEnd(g))).toBe('2026-10-09')
  })

  it('puts a milestone on its start day', () => {
    expect(toIso(inclusiveEnd({ start: toDay('2026-10-05'), dur: 0 }))).toBe('2026-10-05')
  })

  it('turns a typed last day back into a duration', () => {
    const s = toDay('2026-10-05')
    expect(durationFromInclusiveEnd(s, toDay('2026-10-09'))).toBe(5)
    expect(durationFromInclusiveEnd(s, toDay('2026-10-05'))).toBe(1)
    expect(durationFromInclusiveEnd(s, toDay('2026-10-01'))).toBe(1) // never below one day
    expect(durationFromInclusiveEnd(s, toDay('2026-10-20'), true)).toBe(0)
  })

  it('measures slip against the baseline end', () => {
    const t = task({ id: 1, start_date: '2026-10-05', duration_days: 8, baseline_finish: '2026-10-10' })
    expect(slipDays(t)).toBe(3)
    expect(slipDays(task({ id: 2, baseline_finish: '2026-10-20' }))).toBe(0)
    expect(slipDays(task({ id: 3 }))).toBe(0)
  })
})

describe('scale', () => {
  it('maps days to pixels and snaps drags to whole days', () => {
    const range = { from: toDay('2026-10-05'), to: toDay('2026-11-05') }
    expect(xOf(toDay('2026-10-08'), range, 10)).toBe(30)
    expect(snapDays(34, 10)).toBe(3)
    expect(snapDays(36, 10)).toBe(4)
    expect(snapDays(-15, 28)).toBe(-1)
    expect(Object.is(snapDays(-2, 28), 0)).toBe(true)
  })

  it('pads the range, starts on a Monday and includes deadlines and today', () => {
    const tasks = [task({ id: 1, start_date: '2026-10-07', duration_days: 10 })]
    const r = timelineRange(tasks, [toDay('2027-02-01')], toDay('2026-09-24'), 'week')
    expect(new Date(r.from * 86400000).getUTCDay()).toBe(1)
    expect(r.from).toBeLessThan(toDay('2026-09-24'))
    expect(r.to).toBeGreaterThan(toDay('2027-02-01'))
  })

  it('builds month and week headers', () => {
    const range = { from: toDay('2026-09-28'), to: toDay('2026-11-02') }
    const months = monthTicks(range, 10)
    expect(months.map((m) => m.label)).toEqual(['Sep', 'Oct 2026', '']) // 1 Nov day: too narrow for a label
    expect(months[1].x).toBe(30)
    const weeks = minorTicks(range, 'week', 10)
    expect(weeks[0].label).toBe('CW40')
    expect(weeks).toHaveLength(5)
    expect(minorTicks(range, 'day', 28)).toHaveLength(35)
    expect(weekendSpans(range)[0]).toEqual({ day: toDay('2026-10-03'), len: 2 })
  })

  it('steps zoom levels and stops at the ends', () => {
    expect(zoomStep('week', 1)).toBe('day')
    expect(zoomStep('day', 1)).toBe('day')
    expect(zoomStep('week', -1)).toBe('month')
    expect(zoomStep('month', -1)).toBe('month')
  })
})

describe('lanes and rows', () => {
  const tasks = [
    task({ id: 3, lane: 'Customer', sort_order: 1 }),
    task({ id: 1, lane: 'Tool Engineer', sort_order: 2 }),
    task({ id: 2, lane: null, department_name: null, sort_order: 3 }),
    task({ id: 4, lane: 'Customer', sort_order: 4, predecessors: [1, 3] }),
  ]

  it('groups by lane in plan order with unassigned last', () => {
    const g = groupByLane(tasks)
    expect(g.map((x) => x.lane)).toEqual(['Customer', 'Tool Engineer', NO_LANE])
    expect(g[0].tasks.map((t) => t.id)).toEqual([3, 4])
  })

  it('numbers rows in display order and prints predecessors as row numbers', () => {
    const g = groupByLane(tasks)
    const rows = rowNumbers(g)
    expect([...rows.entries()]).toEqual([[3, 1], [4, 2], [1, 3], [2, 4]])
    expect(predecessorText(tasks[3], rows)).toBe('1, 3')
  })

  it('hides the tasks of a collapsed lane but keeps its header', () => {
    const r = buildRows(groupByLane(tasks), new Set(['Customer']))
    expect(r.map((x) => (x.type === 'lane' ? `L:${x.lane}` : x.task.id)))
      .toEqual(['L:Customer', 'L:Tool Engineer', 1, `L:${NO_LANE}`, 2])
  })
})

describe('critical highlight', () => {
  it('only highlights when enabled and never for ideas', () => {
    const crit = task({ id: 1, is_critical: true })
    expect(showCritical(crit, true)).toBe(true)
    expect(showCritical(crit, false)).toBe(false)
    expect(showCritical(task({ id: 2, is_critical: true, is_idea: true }), true)).toBe(false)
    expect(showCritical(task({ id: 3 }), true, [3])).toBe(true)
  })
})

describe('moves', () => {
  const tasks = [
    task({ id: 1, start_date: '2026-10-05', duration_days: 5 }), // ends 10-10
    task({ id: 2, start_date: '2026-10-12', duration_days: 3, predecessors: [1] }),
    task({ id: 3, start_date: '2026-10-08', duration_days: 2, predecessors: [1, 2] }),
    task({ id: 4, kind: 'milestone', start_date: '2026-10-20', duration_days: 0 }),
  ]
  const geos = new Map(tasks.map((t) => [t.id, taskGeo(t)]))

  it('moves a block and resizes one bar, never below a day, milestones fixed', () => {
    const moved = applyDrag(geos, 'move', [1, 2], 3)
    expect(diffUpdates(tasks, moved)).toEqual([
      { id: 1, start_date: '2026-10-08' }, { id: 2, start_date: '2026-10-15' },
    ])
    expect(diffUpdates(tasks, applyDrag(geos, 'resize', [1], -10))).toEqual([{ id: 1, duration_days: 1 }])
    expect(diffUpdates(tasks, applyDrag(geos, 'resize', [4], 5))).toEqual([])
  })

  it('snaps to the latest predecessor end, using moved predecessors', () => {
    expect(snapToPredecessors(tasks, [2])).toEqual([{ id: 2, start_date: '2026-10-10' }])
    // 2 moves to 10-10 (ends 10-13), so 3 follows it.
    expect(snapToPredecessors(tasks, [2, 3])).toEqual([
      { id: 2, start_date: '2026-10-10' }, { id: 3, start_date: '2026-10-13' },
    ])
  })

  it('matches start or end to the first selected task', () => {
    expect(matchTo(tasks, [2, 1], 'start')).toEqual([{ id: 1, start_date: '2026-10-12' }])
    // End of 2 is 10-15; task 1 (5 days) then starts 10-10.
    expect(matchTo(tasks, [2, 1], 'end')).toEqual([{ id: 1, start_date: '2026-10-10' }])
  })

  it('runs a selection in parallel: drops inner links and aligns starts', () => {
    const r = runParallel(tasks, [1, 2, 3])
    expect(r.links).toEqual([{ id: 2, predecessors: [] }, { id: 3, predecessors: [] }])
    expect(r.updates).toEqual([
      { id: 2, start_date: '2026-10-05' }, { id: 3, start_date: '2026-10-05' },
    ])
    // Links to tasks outside the selection stay.
    expect(runParallel(tasks, [2, 3]).links).toEqual([{ id: 3, predecessors: [1] }])
  })

  it('refuses links that would close a loop', () => {
    expect(createsCycle(tasks, 3, 1)).toBe(true) // 3 already depends on 1
    expect(createsCycle(tasks, 1, 4)).toBe(false)
    expect(createsCycle(tasks, 2, 2)).toBe(true)
  })
})
