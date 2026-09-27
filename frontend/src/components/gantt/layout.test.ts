import { describe, expect, it } from 'vitest'
import { makeCal, shift, toDay } from './engine/calendar'
import type { GanttLink, GanttTask, LinkType } from './engine/types'
import {
  NO_GROUP, anchorX, barGeo, buildRows, fitLabel, linkBroken, linkSides, majorTicks, minorTicks, offDaySpans,
  routeLink, snapDays, textWidth, timelineRange, typeFromSides, unitFor, visibleWindow, xOf, zoomStep, PX_PER_DAY,
} from './layout'

const t = (id: number, over: Partial<GanttTask> = {}): GanttTask => ({ id, name: `T${id}`, start: '2026-10-05', duration: 3, ...over })

describe('buildRows', () => {
  it('lists a tree in pre-order with depth and summary flags', () => {
    const r = buildRows([t(1), t(2, { parentId: 1 }), t(3, { parentId: 2 }), t(4)])
    expect(r.rows.map((x) => (x.type === 'task' ? [x.task.id, x.depth, x.summary] : null))).toEqual([
      [1, 0, true], [2, 1, true], [3, 2, false], [4, 0, false],
    ])
  })

  it('puts a parent before its children whatever the input order', () => {
    const r = buildRows([t(3, { parentId: 1 }), t(1)])
    expect(r.rows.map((x) => x.type === 'task' && x.task.id)).toEqual([1, 3])
  })

  it('numbers rows 1..n and indexes visible rows', () => {
    const r = buildRows([t(1), t(2)])
    expect(r.rowNo.get('1')).toBe(1)
    expect(r.rowNo.get('2')).toBe(2)
    expect(r.index.get('2')).toBe(1)
  })

  it('hides the children of a collapsed summary but keeps its row numbers', () => {
    const r = buildRows([t(1), t(2, { parentId: 1 }), t(3)], { collapsed: new Set(['1']) })
    expect(r.rows.length).toBe(2)
    expect(r.rows[0].type === 'task' && r.rows[0].collapsed).toBe(true)
    expect(r.rowNo.get('3')).toBe(3)
    expect(r.index.has('2')).toBe(false)
  })

  it('groups top-level tasks by lane, first appearance order, Unassigned last', () => {
    const r = buildRows([t(1, { lane: null }), t(2, { lane: 'B' }), t(3, { lane: 'A' }), t(4, { lane: 'B' })], { groupByLane: true })
    const labels = r.rows.filter((x) => x.type === 'group').map((x) => x.type === 'group' && x.label)
    expect(labels).toEqual(['B', 'A', NO_GROUP])
  })

  it('numbers rows in the grouped order', () => {
    const r = buildRows([t(1, { lane: 'A' }), t(2, { lane: 'B' }), t(3, { lane: 'A' })], { groupByLane: true })
    expect(r.rowNo.get('1')).toBe(1)
    expect(r.rowNo.get('3')).toBe(2)
    expect(r.rowNo.get('2')).toBe(3)
  })

  it('counts children in a group and collapses a whole group', () => {
    const tasks = [t(1, { lane: 'A' }), t(2, { parentId: 1 }), t(3, { lane: 'B' })]
    const open = buildRows(tasks, { groupByLane: true })
    const g = open.rows[0]
    expect(g.type === 'group' && g.count).toBe(2)
    const closed = buildRows(tasks, { groupByLane: true, collapsed: new Set(['group:A']) })
    expect(closed.rows.map((x) => (x.type === 'group' ? x.label : x.task.id))).toEqual(['A', 'B', 3])
  })

  it('treats a blank lane as Unassigned', () => {
    const r = buildRows([t(1, { lane: '  ' })], { groupByLane: true })
    expect(r.rows[0].type === 'group' && r.rows[0].label).toBe(NO_GROUP)
  })

  it('carries the group label on task rows', () => {
    const r = buildRows([t(1, { lane: 'A' })], { groupByLane: true })
    expect(r.rows[1].type === 'task' && r.rows[1].group).toBe('A')
  })
})

describe('visibleWindow', () => {
  it('covers the viewport plus overscan', () => {
    expect(visibleWindow(280, 280, 28, 1000, 2)).toEqual({ first: 8, last: 22 })
  })
  it('clamps at both ends', () => {
    expect(visibleWindow(0, 100, 28, 3, 8)).toEqual({ first: 0, last: 2 })
  })
})

describe('scale', () => {
  it('snaps drag distances to whole days without -0', () => {
    expect(snapDays(29, 28)).toBe(1)
    expect(Object.is(snapDays(-3, 28), 0)).toBe(true)
    expect(snapDays(-57, 28)).toBe(-2)
  })

  it('picks a tick unit by pixel density', () => {
    expect(unitFor(28)).toBe('day')
    expect(unitFor(9)).toBe('week')
    expect(unitFor(3)).toBe('month')
    expect(unitFor(1)).toBe('quarter')
  })

  it('steps the zoom and stops at the ends', () => {
    expect(zoomStep('week', 1)).toBe('day')
    expect(zoomStep('day', 1)).toBe('day')
    expect(zoomStep('month', -1)).toBe('quarter')
    expect(zoomStep('quarter', -1)).toBe('quarter')
  })

  it('starts a day/week range on a Monday before the data', () => {
    const r = timelineRange([toDay('2026-10-07')], 'day')
    expect(r.from).toBeLessThan(toDay('2026-10-07'))
    expect(((r.from + 3) % 7 + 7) % 7).toBe(0) // Monday
    expect(r.to - r.from).toBeGreaterThanOrEqual(42)
  })

  it('starts a month range on the 1st and a quarter range on a quarter start', () => {
    const m = timelineRange([toDay('2026-10-15')], 'month')
    expect(new Date(m.from * 86400000).getUTCDate()).toBe(1)
    const q = timelineRange([toDay('2026-11-15')], 'quarter')
    const d = new Date(q.from * 86400000)
    expect(d.getUTCDate()).toBe(1)
    expect(d.getUTCMonth() % 3).toBe(0)
  })

  it('keeps a minimum span per unit', () => {
    const r = timelineRange([toDay('2026-10-05')], 'quarter')
    expect(r.to - r.from).toBeGreaterThanOrEqual(270)
  })

  it('quarter zoom shows the plan span plus a margin, not years (G19)', () => {
    const r = timelineRange([toDay('2026-10-05'), toDay('2027-06-30')], 'quarter')
    expect(r.from).toBe(toDay('2026-07-01')) // quarter start before the margin
    expect(r.to - toDay('2027-06-30')).toBe(62)
  })

  it('handles an empty list', () => {
    const r = timelineRange([], 'week')
    expect(r.to).toBeGreaterThan(r.from)
  })

  it('maps days to x', () => {
    expect(xOf(10, { from: 5, to: 20 }, PX_PER_DAY.day)).toBe(140)
  })
})

describe('ticks', () => {
  const range = { from: toDay('2026-09-28'), to: toDay('2027-03-01') }
  const fits = (ticks: { label: string; w: number }[], size: number) =>
    ticks.every((x) => x.label === '' || textWidth(x.label, size) + 6 <= x.w)

  it('labels months with the year when there is room (day zoom)', () => {
    const m = majorTicks(range, 28, 'day')
    expect(m.some((x) => x.label === 'Oct 2026')).toBe(true)
    expect(fits(m, 11)).toBe(true)
  })

  it('shows years on top and months below at month zoom', () => {
    expect(majorTicks(range, 3.2, 'month').map((x) => x.label)).toContain('2027')
    const minor = minorTicks(range, 3.2, 'month')
    expect(minor.map((x) => x.label)).toContain('Nov')
    expect(fits(minor, 10)).toBe(true)
  })

  it('labels calendar weeks at week zoom', () => {
    const minor = minorTicks(range, 9, 'week')
    expect(minor.some((x) => /^CW\d+$|^\d+$/.test(x.label))).toBe(true)
    expect(fits(minor, 10)).toBe(true)
  })

  it('labels quarters', () => {
    expect(minorTicks(range, 1.1, 'quarter').map((x) => x.label)).toContain('Q1')
  })

  it('has one day tick per day at day zoom', () => {
    expect(minorTicks({ from: 0, to: 10 }, 28, 'day').length).toBe(10)
  })

  it('never overlaps neighbouring ticks', () => {
    const minor = minorTicks(range, 9, 'week')
    for (let i = 1; i < minor.length; i++) expect(minor[i].x).toBeGreaterThanOrEqual(minor[i - 1].x + minor[i - 1].w - 0.001)
  })

  it('fitLabel falls back to shorter candidates and then to nothing', () => {
    expect(fitLabel(['October 2026', 'Oct', 'O'], 200)).toBe('October 2026')
    expect(fitLabel(['October 2026', 'Oct', 'O'], 30)).toBe('Oct')
    expect(fitLabel(['October 2026'], 5)).toBe('')
  })
})

describe('offDaySpans', () => {
  it('merges weekends and adjacent holidays', () => {
    const cal = makeCal({ mode: 'working', workdays: [1, 2, 3, 4, 5], holidays: ['2026-10-09'] })
    const spans = offDaySpans({ from: toDay('2026-10-05'), to: toDay('2026-10-19') }, cal)
    expect(spans[0]).toEqual({ day: toDay('2026-10-09'), len: 3 })
    expect(spans[1]).toEqual({ day: toDay('2026-10-17'), len: 2 })
  })
  it('has none when every day is worked', () => {
    const cal = makeCal({ mode: 'calendar', workdays: [1, 2, 3, 4, 5, 6, 7], holidays: [] })
    expect(offDaySpans({ from: 0, to: 30 }, cal)).toEqual([])
  })
})

describe('geometry', () => {
  it('gives bars at least 2px and milestones 0 width', () => {
    const r = { from: 0, to: 100 }
    expect(barGeo(10, 10, r, 28, false).w).toBe(2)
    expect(barGeo(10, 13, r, 28, false)).toEqual({ x: 280, w: 84, milestone: false })
    expect(barGeo(10, 10, r, 28, true).w).toBe(0)
  })
  it('attaches links to the edges, around a milestone diamond', () => {
    expect(anchorX({ x: 100, w: 50, milestone: false }, 'start')).toBe(100)
    expect(anchorX({ x: 100, w: 50, milestone: false }, 'end')).toBe(150)
    expect(anchorX({ x: 100, w: 0, milestone: true }, 'start')).toBe(94)
    expect(anchorX({ x: 100, w: 0, milestone: true }, 'end')).toBe(106)
  })
  it.each([
    ['FS', 'end', 'start'], ['SS', 'start', 'start'], ['FF', 'end', 'end'], ['SF', 'start', 'end'],
  ] as [LinkType, 'start' | 'end', 'start' | 'end'][])('%s link attaches %s -> %s and back', (type, from, to) => {
    expect(linkSides(type)).toEqual({ from, to })
    expect(typeFromSides(from, to)).toBe(type)
  })
})

describe('routeLink', () => {
  const base = { rowH: 28, y1: 14, row1: 0, y2: 70, row2: 2 }
  it('uses one vertical when the target starts after the source ends', () => {
    const d = routeLink({ ...base, x1: 100, fromSide: 'end', x2: 200, toSide: 'start' })
    expect(d).toBe('M100,14 H108 V70 H200')
  })
  it('detours along the row boundary when the target starts before the source ends', () => {
    const d = routeLink({ ...base, x1: 200, fromSide: 'end', x2: 100, toSide: 'start' })
    expect(d).toBe('M200,14 H208 V56 H92 V70 H100')
  })
  it('runs along the lower boundary when the target is above', () => {
    const d = routeLink({ ...base, y1: 70, row1: 2, y2: 14, row2: 0, x1: 200, fromSide: 'end', x2: 100, toSide: 'start' })
    expect(d).toContain('V28')
  })
  it('moves the vertical off a bar in between when there is room', () => {
    const d = routeLink({ ...base, x1: 100, fromSide: 'end', x2: 300, toSide: 'start', obstacles: [{ row: 1, x1: 100, x2: 150 }] })
    expect(d).toBe('M100,14 H158 V70 H300')
  })
  it('goes through a bar when every x is blocked', () => {
    const d = routeLink({ ...base, x1: 100, fromSide: 'end', x2: 130, toSide: 'start', obstacles: [{ row: 1, x1: 0, x2: 400 }] })
    expect(d.startsWith('M100,14 H')).toBe(true)
  })
  it('SS exits and enters on the left', () => {
    const d = routeLink({ ...base, x1: 100, fromSide: 'start', x2: 150, toSide: 'start' })
    expect(d).toBe('M100,14 H92 V70 H150')
  })
  it('FF exits and enters on the right', () => {
    const d = routeLink({ ...base, x1: 150, fromSide: 'end', x2: 100, toSide: 'end' })
    expect(d).toBe('M150,14 H158 V70 H100')
  })
  it('SF exits left and enters the end from the right', () => {
    const d = routeLink({ ...base, x1: 200, fromSide: 'start', x2: 150, toSide: 'end' })
    expect(d).toBe('M200,14 H192 V70 H150')
  })
  it('SF detours when the target end is after the source start', () => {
    const d = routeLink({ ...base, x1: 100, fromSide: 'start', x2: 200, toSide: 'end' })
    expect(d).toBe('M100,14 H92 V56 H208 V70 H200')
  })
})

describe('linkBroken', () => {
  const cal = makeCal(null)
  const sh = (d: number, n: number) => shift(cal, d, n)
  const l = (type: LinkType, lagDays = 0): GanttLink => ({ id: 1, from: 1, to: 2, type, lagDays })
  it('FS is broken when the successor starts before the end plus lag', () => {
    expect(linkBroken(l('FS'), 0, 5, 5, 8, sh)).toBe(false)
    expect(linkBroken(l('FS', 1), 0, 5, 5, 8, sh)).toBe(true)
    expect(linkBroken(l('FS', -2), 0, 5, 3, 8, sh)).toBe(false)
  })
  it('SS, FF and SF compare the right edges', () => {
    expect(linkBroken(l('SS'), 2, 5, 1, 8, sh)).toBe(true)
    expect(linkBroken(l('FF'), 0, 5, 1, 4, sh)).toBe(true)
    expect(linkBroken(l('FF'), 0, 5, 1, 5, sh)).toBe(false)
    expect(linkBroken(l('SF'), 3, 5, 0, 2, sh)).toBe(true)
  })
})
