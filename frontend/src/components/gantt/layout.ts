/**
 * Pure layout for the Gantt: rows (tree + optional lane groups + collapse),
 * the time scale and its header ticks, bar geometry and link routing. No
 * React, so every rule is unit tested.
 */
import {
  MONTHS, dayOf, isoWeek, mondayOf, toDay, ymd, type Cal,
} from './engine/calendar'
import { buildTree, key, type Tree } from './engine/tree'
import type { GanttLink, GanttTask, LinkType } from './engine/types'

// ------------------------------------------------------------------ rows

export const NO_GROUP = 'Unassigned'

export type Row =
  | { type: 'group'; key: string; label: string; count: number; collapsed: boolean }
  | { type: 'task'; task: GanttTask; depth: number; summary: boolean; collapsed: boolean; group: string | null }

export interface RowModel {
  rows: Row[]
  /** Tasks in effective order (groups applied), the basis of row numbers. */
  tree: Tree
  rowNo: Map<string, number>
  /** Visible row index per task key. */
  index: Map<string, number>
}

/**
 * Rows for display. With `groupByLane`, top-level tasks are grouped by lane
 * (first appearance order, "Unassigned" last) and the row numbers follow that
 * grouped order, so "#3" in the predecessor column is the third row shown.
 */
export function buildRows(tasks: GanttTask[], opts: { groupByLane?: boolean; collapsed?: Set<string> } = {}): RowModel {
  const collapsed = opts.collapsed ?? new Set<string>()
  let ordered = tasks
  if (opts.groupByLane) {
    const t0 = buildTree(tasks)
    const groups = new Map<string, GanttTask[]>()
    for (const r of t0.roots) {
      const g = laneKey(r)
      if (!groups.has(g)) groups.set(g, [])
      groups.get(g)!.push(r)
    }
    const keys = [...groups.keys()].sort((a, b) => Number(a === NO_GROUP) - Number(b === NO_GROUP))
    const flat: GanttTask[] = []
    const addSub = (t: GanttTask) => { flat.push(t); for (const c of t0.children.get(key(t.id)) ?? []) addSub(c) }
    for (const g of keys) for (const r of groups.get(g)!) addSub(r)
    ordered = flat
  }
  const tree = buildTree(ordered)
  const rowNo = new Map(tree.order.map((t, i) => [key(t.id), i + 1]))
  const rows: Row[] = []
  const walk = (list: GanttTask[], depth: number, group: string | null) => {
    for (const t of list) {
      const k = key(t.id)
      const kids = tree.children.get(k) ?? []
      rows.push({ type: 'task', task: t, depth, summary: kids.length > 0, collapsed: collapsed.has(k), group })
      if (kids.length && !collapsed.has(k)) walk(kids, depth + 1, group)
    }
  }
  if (opts.groupByLane) {
    let i = 0
    while (i < tree.roots.length) {
      const g = laneKey(tree.roots[i])
      const members: GanttTask[] = []
      while (i < tree.roots.length && laneKey(tree.roots[i]) === g) members.push(tree.roots[i++])
      const gk = `group:${g}`
      const count = members.reduce((n, m) => n + 1 + countDesc(tree, m), 0)
      rows.push({ type: 'group', key: gk, label: g, count, collapsed: collapsed.has(gk) })
      if (!collapsed.has(gk)) walk(members, 0, g)
    }
  } else walk(tree.roots, 0, null)
  const index = new Map<string, number>()
  rows.forEach((r, i) => { if (r.type === 'task') index.set(key(r.task.id), i) })
  return { rows, tree, rowNo, index }
}

const laneKey = (t: GanttTask) => (t.lane ?? '').trim() || NO_GROUP
function countDesc(tree: Tree, t: GanttTask): number {
  return (tree.children.get(key(t.id)) ?? []).reduce((n, c) => n + 1 + countDesc(tree, c), 0)
}

/** First and last row index to render for a scroll window (with overscan). */
export function visibleWindow(scrollTop: number, viewport: number, rowH: number, total: number, overscan = 8) {
  const first = Math.max(0, Math.floor(scrollTop / rowH) - overscan)
  const last = Math.min(total - 1, Math.ceil((scrollTop + viewport) / rowH) + overscan)
  return { first, last }
}

// ------------------------------------------------------------------ scale

export type Zoom = 'day' | 'week' | 'month' | 'quarter'
export const ZOOMS: Zoom[] = ['day', 'week', 'month', 'quarter']
export const PX_PER_DAY: Record<Zoom, number> = { day: 28, week: 9, month: 3.2, quarter: 1.1 }

/** The tick unit that reads well at a pixel density (used by "fit"). */
export function unitFor(ppd: number): Zoom {
  if (ppd >= 16) return 'day'
  if (ppd >= 5) return 'week'
  if (ppd >= 1.8) return 'month'
  return 'quarter'
}

export function zoomStep(z: Zoom, dir: 1 | -1): Zoom {
  const i = ZOOMS.indexOf(z) - dir
  return ZOOMS[Math.min(ZOOMS.length - 1, Math.max(0, i))]
}

export interface Range { from: number; to: number }

/** Visible window: everything plus padding, starting on a Monday (or a month / quarter start). */
export function timelineRange(days: number[], unit: Zoom, minSpanDays = 0): Range {
  const valid = days.filter((d) => Number.isFinite(d))
  const min = valid.length ? Math.min(...valid) : 0
  const max = valid.length ? Math.max(...valid) : 0
  const padBefore = { day: 7, week: 14, month: 31, quarter: 92 }[unit]
  const padAfter = { day: 21, week: 42, month: 92, quarter: 184 }[unit]
  let from = mondayOf(min - padBefore)
  if (unit === 'month' || unit === 'quarter') {
    const { y, m } = ymd(min - padBefore)
    from = dayOf(y, unit === 'quarter' ? m - (m % 3) : m, 1)
  }
  const minSpan = Math.max(minSpanDays, { day: 42, week: 120, month: 365, quarter: 730 }[unit])
  const to = Math.max(max + padAfter, from + minSpan)
  return { from, to }
}

export const xOf = (day: number, range: Range, ppd: number) => (day - range.from) * ppd

/** Whole days from a pixel distance, never -0. */
export const snapDays = (dx: number, ppd: number) => {
  const d = Math.round(dx / ppd)
  return d === 0 ? 0 : d
}

export interface Tick { day: number; x: number; w: number; label: string }

/** Rough text width at 10-11px for label fitting. */
export const textWidth = (s: string, size = 11) => s.length * size * 0.56 + 4

/** Longest label that fits `w`, from a list of candidates (longest first). */
export function fitLabel(candidates: string[], w: number, size = 11): string {
  for (const c of candidates) if (textWidth(c, size) + 6 <= w) return c
  return ''
}

function monthTicksRaw(range: Range, ppd: number, stepMonths: number, label: (y: number, m: number, w: number) => string): Tick[] {
  const out: Tick[] = []
  let { y, m } = ymd(range.from)
  m -= m % stepMonths
  for (let guard = 0; guard < 2000; guard++) {
    const startDay = dayOf(y, m, 1)
    const next = dayOf(y, m + stepMonths, 1)
    if (startDay >= range.to) break
    const s = Math.max(range.from, startDay)
    const e = Math.min(range.to, next)
    if (e > s) {
      const w = (e - s) * ppd
      out.push({ day: s, x: xOf(s, range, ppd), w, label: label(y, m, w) })
    }
    m += stepMonths
    while (m > 11) { m -= 12; y += 1 }
  }
  return out
}

function yearTicks(range: Range, ppd: number): Tick[] {
  const out: Tick[] = []
  for (let y = ymd(range.from).y; ; y++) {
    const s = Math.max(range.from, dayOf(y, 0, 1))
    if (s >= range.to) break
    const e = Math.min(range.to, dayOf(y + 1, 0, 1))
    const w = (e - s) * ppd
    out.push({ day: s, x: xOf(s, range, ppd), w, label: fitLabel([String(y)], w) })
  }
  return out
}

/** Upper header row: months for day/week units, years for month/quarter. */
export function majorTicks(range: Range, ppd: number, unit: Zoom): Tick[] {
  if (unit === 'month' || unit === 'quarter') return yearTicks(range, ppd)
  return monthTicksRaw(range, ppd, 1, (y, m, w) => fitLabel([`${MONTHS[m]} ${y}`, MONTHS[m], MONTHS[m][0]], w))
}

/** Lower header row: days, calendar weeks, months or quarters. */
export function minorTicks(range: Range, ppd: number, unit: Zoom): Tick[] {
  const out: Tick[] = []
  if (unit === 'day') {
    for (let d = range.from; d < range.to; d++) {
      out.push({ day: d, x: xOf(d, range, ppd), w: ppd, label: fitLabel([String(ymd(d).d)], ppd, 10) })
    }
    return out
  }
  if (unit === 'week') {
    for (let d = mondayOf(range.from); d < range.to; d += 7) {
      const s = Math.max(d, range.from)
      const w = (Math.min(d + 7, range.to) - s) * ppd
      out.push({ day: s, x: xOf(s, range, ppd), w, label: fitLabel([`CW${isoWeek(d)}`, String(isoWeek(d))], w, 10) })
    }
    return out
  }
  if (unit === 'month') return monthTicksRaw(range, ppd, 1, (_y, m, w) => fitLabel([MONTHS[m], MONTHS[m][0]], w, 10))
  return monthTicksRaw(range, ppd, 3, (_y, m, w) => fitLabel([`Q${m / 3 + 1}`], w, 10))
}

/** Runs of consecutive non-working days, for shading. */
export function offDaySpans(range: Range, cal: Cal): { day: number; len: number }[] {
  const out: { day: number; len: number }[] = []
  let run: { day: number; len: number } | null = null
  for (let d = range.from; d < range.to; d++) {
    if (!cal.isWork(d)) {
      if (run && run.day + run.len === d) run.len++
      else { run = { day: d, len: 1 }; out.push(run) }
    }
  }
  return out
}

// ------------------------------------------------------------------ geometry

export interface BarGeo { x: number; w: number; milestone: boolean }

export function barGeo(startDay: number, endDay: number, range: Range, ppd: number, milestone: boolean): BarGeo {
  const x = xOf(startDay, range, ppd)
  return { x, w: milestone ? 0 : Math.max((endDay - startDay) * ppd, 2), milestone }
}

/** Point on a bar where a link attaches ("start" left edge, "end" right edge). */
export function anchorX(g: BarGeo, side: 'start' | 'end', diamond = 6): number {
  if (g.milestone) return side === 'start' ? g.x - diamond : g.x + diamond
  return side === 'start' ? g.x : g.x + g.w
}

export const linkSides = (t: LinkType): { from: 'start' | 'end'; to: 'start' | 'end' } => ({
  from: t === 'SS' || t === 'SF' ? 'start' : 'end',
  to: t === 'FS' || t === 'SS' ? 'start' : 'end',
})

export const typeFromSides = (from: 'start' | 'end', to: 'start' | 'end'): LinkType =>
  from === 'end' ? (to === 'start' ? 'FS' : 'FF') : (to === 'start' ? 'SS' : 'SF')

export interface Obstacle { row: number; x1: number; x2: number }

/**
 * Orthogonal route for a link between two rows. Exits the source edge
 * outward by `gap`, enters the target edge from outside. With room between
 * the edges one vertical segment is used, placed where it crosses the fewest
 * bars of the rows in between; otherwise the route runs along the row
 * boundary next to the target (between bars, never through their middle).
 */
export function routeLink(p: {
  x1: number; y1: number; row1: number; fromSide: 'start' | 'end'
  x2: number; y2: number; row2: number; toSide: 'start' | 'end'
  rowH: number; gap?: number; obstacles?: Obstacle[]
}): string {
  const gap = p.gap ?? 8
  const exitDir = p.fromSide === 'end' ? 1 : -1
  const enterDir = p.toSide === 'start' ? 1 : -1 // direction of travel into the target edge
  // Feasible x for a single vertical: exit half-line ∩ approach half-line.
  let lo = -Infinity, hi = Infinity
  if (exitDir === 1) lo = Math.max(lo, p.x1 + gap); else hi = Math.min(hi, p.x1 - gap)
  if (enterDir === 1) hi = Math.min(hi, p.x2 - gap); else lo = Math.max(lo, p.x2 + gap)
  const between = (p.obstacles ?? []).filter((o) =>
    o.row > Math.min(p.row1, p.row2) && o.row < Math.max(p.row1, p.row2))
  const crossings = (x: number) => between.reduce((n, o) => n + (x >= o.x1 - 2 && x <= o.x2 + 2 ? 1 : 0), 0)
  const r = (n: number) => Math.round(n * 10) / 10
  if (lo <= hi) {
    const cands = new Set<number>()
    if (Number.isFinite(lo)) cands.add(lo)
    if (Number.isFinite(hi)) cands.add(hi)
    if (Number.isFinite(lo) && Number.isFinite(hi)) cands.add((lo + hi) / 2)
    for (const o of between) {
      for (const c of [o.x2 + gap, o.x1 - gap]) if (c >= lo && c <= hi) cands.add(c)
    }
    const prefer = exitDir === 1 ? lo : hi
    // Crossing a bar costs about 100 px of detour: short routes win unless they cut through bars.
    const cost = (x: number) => crossings(x) * 50 + Math.abs(x - prefer) * 0.5
    const best = [...cands].sort((a, b) => cost(a) - cost(b))[0]
    return `M${r(p.x1)},${r(p.y1)} H${r(best)} V${r(p.y2)} H${r(p.x2)}`
  }
  const xa = p.x1 + exitDir * gap
  const xb = p.x2 - enterDir * gap
  const down = p.row2 > p.row1
  const rowTop = p.row2 * p.rowH
  const yg = down ? rowTop : rowTop + p.rowH
  return `M${r(p.x1)},${r(p.y1)} H${r(xa)} V${r(yg)} H${r(xb)} V${r(p.y2)} H${r(p.x2)}`
}

/** Does a link run backwards against the tasks' dates (drawn red)? */
export function linkBroken(l: GanttLink, fromStart: number, fromEnd: number, toStart: number, toEnd: number, shiftFn: (d: number, n: number) => number): boolean {
  const sides = linkSides(l.type)
  const src = sides.from === 'start' ? fromStart : fromEnd
  const bound = shiftFn(src, l.lagDays)
  const tgt = sides.to === 'start' ? toStart : toEnd
  return tgt < bound
}

export const isoToDay = (iso: string | null | undefined) => (iso ? toDay(iso) : null)
