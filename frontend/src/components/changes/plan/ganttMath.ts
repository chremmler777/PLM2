/**
 * Pure helpers for the Gantt: day arithmetic, the time scale, lane grouping
 * and the alignment actions. Kept free of React so every rule is testable.
 *
 * A "day" is an integer: days since 1970-01-01 (UTC). ISO strings go in and
 * out at the edges only, so no timezone ever touches the arithmetic.
 */
import type { BulkDateUpdate, TaskKind, TaskOut } from '../../../types/changePlan'

const MS_DAY = 86_400_000
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

export function toDay(iso: string): number {
  const [y, m, d] = iso.slice(0, 10).split('-').map(Number)
  return Math.round(Date.UTC(y, m - 1, d) / MS_DAY)
}

export function toIso(day: number): string {
  return new Date(day * MS_DAY).toISOString().slice(0, 10)
}

export function addDaysIso(iso: string, n: number): string {
  return toIso(toDay(iso) + n)
}

/** Today in the viewer's calendar, as a day number. */
export function todayDay(now: Date = new Date()): number {
  return Math.round(Date.UTC(now.getFullYear(), now.getMonth(), now.getDate()) / MS_DAY)
}

/** 0 = Sunday .. 6 = Saturday. */
export function weekday(day: number): number {
  return (((day + 4) % 7) + 7) % 7
}

export const isWeekend = (day: number) => {
  const w = weekday(day)
  return w === 0 || w === 6
}

/** Monday of the day's week. */
export function mondayOf(day: number): number {
  return day - ((weekday(day) + 6) % 7)
}

export function isoWeek(day: number): number {
  // Thursday of this week decides the year; week 1 holds the first Thursday.
  const thursday = mondayOf(day) + 3
  const d = new Date(thursday * MS_DAY)
  const jan1 = Math.round(Date.UTC(d.getUTCFullYear(), 0, 1) / MS_DAY)
  return Math.floor((thursday - jan1) / 7) + 1
}

export function ymd(day: number): { y: number; m: number; d: number } {
  const dt = new Date(day * MS_DAY)
  return { y: dt.getUTCFullYear(), m: dt.getUTCMonth(), d: dt.getUTCDate() }
}

/** "5 Oct 26". */
export function fmtDay(day: number | null | undefined): string {
  if (day == null) return '-'
  const { y, m, d } = ymd(day)
  return `${d} ${MONTHS[m]} ${String(y).slice(2)}`
}

export const fmtIso = (iso: string | null | undefined) => (iso ? fmtDay(toDay(iso)) : '-')

// ---------------------------------------------------------------- tasks

export interface Geo { start: number; dur: number }

export const taskGeo = (t: TaskOut): Geo => ({ start: toDay(t.start_date), dur: t.duration_days })

/** Exclusive end day. */
export const endOf = (g: Geo) => g.start + g.dur

/** The last day the task occupies, as the grid shows it. A milestone sits on its start. */
export const inclusiveEnd = (g: Geo) => (g.dur > 0 ? g.start + g.dur - 1 : g.start)

/** Duration from an inclusive last day typed by the user. */
export function durationFromInclusiveEnd(start: number, lastDay: number, milestone = false): number {
  if (milestone) return 0
  return Math.max(1, lastDay - start + 1)
}

/** Days the task finishes after its baseline (0 without one, never negative). */
export function slipDays(t: TaskOut, g: Geo = taskGeo(t)): number {
  if (!t.baseline_finish) return 0
  return Math.max(0, endOf(g) - toDay(t.baseline_finish))
}

/** A task counts as critical only when the toggle is on and the task is not an idea. */
export function showCritical(t: TaskOut, enabled: boolean, criticalIds?: number[]): boolean {
  if (!enabled || t.is_idea) return false
  return !!t.is_critical || (criticalIds?.includes(t.id) ?? false)
}

// ---------------------------------------------------------------- scale

export type Zoom = 'day' | 'week' | 'month'
export const ZOOMS: Zoom[] = ['day', 'week', 'month']
export const PX_PER_DAY: Record<Zoom, number> = { day: 28, week: 10, month: 3.5 }

export function zoomStep(z: Zoom, dir: 1 | -1): Zoom {
  // dir 1 = zoom in (more pixels per day).
  const i = ZOOMS.indexOf(z) - dir
  return ZOOMS[Math.min(ZOOMS.length - 1, Math.max(0, i))]
}

export interface Range { from: number; to: number }

/**
 * The visible window: every task, baseline and deadline plus today, padded so
 * bars never touch the edge. Starts on a Monday so week columns line up.
 */
export function timelineRange(tasks: TaskOut[], extraDays: number[], today: number, zoom: Zoom): Range {
  const days: number[] = [today, ...extraDays]
  for (const t of tasks) {
    const g = taskGeo(t)
    days.push(g.start, endOf(g))
    if (t.baseline_start) days.push(toDay(t.baseline_start))
    if (t.baseline_finish) days.push(toDay(t.baseline_finish))
  }
  const min = Math.min(...days)
  const max = Math.max(...days)
  const padBefore = zoom === 'day' ? 7 : zoom === 'week' ? 14 : 30
  const padAfter = zoom === 'day' ? 21 : zoom === 'week' ? 42 : 90
  const from = mondayOf(min - padBefore)
  const minSpan = zoom === 'day' ? 42 : zoom === 'week' ? 120 : 365
  const to = Math.max(max + padAfter, from + minSpan)
  return { from, to }
}

export const xOf = (day: number, range: Range, ppd: number) => (day - range.from) * ppd

/** Pixel drag distance to whole days (snaps to the nearest day). */
export const snapDays = (dx: number, ppd: number) => {
  const d = Math.round(dx / ppd)
  return d === 0 ? 0 : d // avoid -0
}

export interface Tick { day: number; x: number; w: number; label: string }

export function monthTicks(range: Range, ppd: number): Tick[] {
  const out: Tick[] = []
  let { y, m } = ymd(range.from)
  for (;;) {
    const start = Math.max(range.from, Math.round(Date.UTC(y, m, 1) / MS_DAY))
    if (start >= range.to) break
    const next = Math.round(Date.UTC(y, m + 1, 1) / MS_DAY)
    const end = Math.min(range.to, next)
    const w = (end - start) * ppd
    out.push({
      day: start, x: xOf(start, range, ppd), w,
      label: w > 60 ? `${MONTHS[m]} ${y}` : w > 24 ? MONTHS[m] : '',
    })
    m += 1
    if (m > 11) { m = 0; y += 1 }
  }
  return out
}

/** Second header row: days (day zoom) or calendar weeks. */
export function minorTicks(range: Range, zoom: Zoom, ppd: number): Tick[] {
  const out: Tick[] = []
  if (zoom === 'day') {
    for (let d = range.from; d < range.to; d++) {
      out.push({ day: d, x: xOf(d, range, ppd), w: ppd, label: String(ymd(d).d) })
    }
    return out
  }
  for (let d = mondayOf(range.from); d < range.to; d += 7) {
    const s = Math.max(d, range.from)
    const w = (Math.min(d + 7, range.to) - s) * ppd
    out.push({
      day: s, x: xOf(s, range, ppd), w,
      label: zoom === 'week' ? `CW${isoWeek(d)}` : (w >= 18 ? String(isoWeek(d)) : ''),
    })
  }
  return out
}

/** Weekend spans (Saturday + Sunday) inside the range. */
export function weekendSpans(range: Range): { day: number; len: number }[] {
  const out: { day: number; len: number }[] = []
  let sat = mondayOf(range.from) + 5
  while (sat < range.to) {
    const s = Math.max(sat, range.from)
    const e = Math.min(sat + 2, range.to)
    if (e > s) out.push({ day: s, len: e - s })
    sat += 7
  }
  return out
}

// ---------------------------------------------------------------- lanes / rows

export const NO_LANE = 'Unassigned'

export const laneOf = (t: TaskOut) => t.lane?.trim() || t.department_name || NO_LANE

const byOrder = (a: TaskOut, b: TaskOut) => a.sort_order - b.sort_order || a.id - b.id

export interface LaneGroup { lane: string; tasks: TaskOut[] }

/** Lanes in order of their first task; tasks inside a lane in plan order. */
export function groupByLane(tasks: TaskOut[]): LaneGroup[] {
  const groups = new Map<string, TaskOut[]>()
  for (const t of [...tasks].sort(byOrder)) {
    const l = laneOf(t)
    if (!groups.has(l)) groups.set(l, [])
    groups.get(l)!.push(t)
  }
  const out = [...groups.entries()].map(([lane, ts]) => ({ lane, tasks: ts }))
  // "Unassigned" always last.
  out.sort((a, b) => Number(a.lane === NO_LANE) - Number(b.lane === NO_LANE))
  return out
}

/** 1-based row numbers in display order (lane grouped), used for predecessors. */
export function rowNumbers(groups: LaneGroup[]): Map<number, number> {
  const m = new Map<number, number>()
  let n = 1
  for (const g of groups) for (const t of g.tasks) m.set(t.id, n++)
  return m
}

export function predecessorText(t: TaskOut, rows: Map<number, number>): string {
  return t.predecessors
    .map((p) => rows.get(p))
    .filter((n): n is number => n != null)
    .sort((a, b) => a - b)
    .join(', ')
}

export type Row =
  | { type: 'lane'; lane: string; count: number; collapsed: boolean }
  | { type: 'task'; task: TaskOut; lane: string }

export function buildRows(groups: LaneGroup[], collapsed: Set<string>): Row[] {
  const rows: Row[] = []
  for (const g of groups) {
    const c = collapsed.has(g.lane)
    rows.push({ type: 'lane', lane: g.lane, count: g.tasks.length, collapsed: c })
    if (!c) for (const t of g.tasks) rows.push({ type: 'task', task: t, lane: g.lane })
  }
  return rows
}

// ---------------------------------------------------------------- moves

/** Geometry after dragging: move shifts every id, resize changes one duration. */
export function applyDrag(
  geos: Map<number, Geo>, mode: 'move' | 'resize', ids: number[], delta: number,
): Map<number, Geo> {
  const out = new Map(geos)
  for (const id of ids) {
    const g = geos.get(id)
    if (!g) continue
    if (mode === 'move') out.set(id, { start: g.start + delta, dur: g.dur })
    else if (g.dur > 0) out.set(id, { start: g.start, dur: Math.max(1, g.dur + delta) })
  }
  return out
}

/** Bulk-patch payload for the geometries that differ from the server's. */
export function diffUpdates(tasks: TaskOut[], next: Map<number, Geo>): BulkDateUpdate[] {
  const out: BulkDateUpdate[] = []
  for (const t of tasks) {
    const n = next.get(t.id)
    if (!n) continue
    const g = taskGeo(t)
    const u: BulkDateUpdate = { id: t.id }
    if (n.start !== g.start) u.start_date = toIso(n.start)
    if (n.dur !== g.dur) u.duration_days = n.dur
    if (u.start_date !== undefined || u.duration_days !== undefined) out.push(u)
  }
  return out
}

const geoMap = (tasks: TaskOut[]) => new Map(tasks.map((t) => [t.id, taskGeo(t)]))

/** Start each selected task at its latest predecessor end (earlier or later). */
export function snapToPredecessors(tasks: TaskOut[], ids: number[]): BulkDateUpdate[] {
  const geos = geoMap(tasks)
  const next = new Map<number, Geo>()
  // Walk in dependency order so a selected predecessor's new position is used.
  const byId = new Map(tasks.map((t) => [t.id, t]))
  const sel: TaskOut[] = []
  const seen = new Set<number>()
  const visit = (id: number) => {
    if (seen.has(id) || !ids.includes(id)) return
    seen.add(id)
    const t = byId.get(id)
    if (!t) return
    t.predecessors.forEach(visit)
    sel.push(t)
  }
  ids.forEach(visit)
  for (const t of sel) {
    const ends = t.predecessors
      .map((p) => next.get(p) ?? geos.get(p))
      .filter((g): g is Geo => !!g)
      .map(endOf)
    if (ends.length === 0) continue
    next.set(t.id, { start: Math.max(...ends), dur: geos.get(t.id)!.dur })
  }
  return diffUpdates(tasks, next)
}

/** Align the selection to the first selected task: same start or same end. */
export function matchTo(tasks: TaskOut[], ids: number[], edge: 'start' | 'end'): BulkDateUpdate[] {
  const geos = geoMap(tasks)
  const anchor = geos.get(ids[0])
  if (!anchor) return []
  const next = new Map<number, Geo>()
  for (const id of ids.slice(1)) {
    const g = geos.get(id)
    if (!g) continue
    next.set(id, edge === 'start'
      ? { start: anchor.start, dur: g.dur }
      : { start: endOf(anchor) - g.dur, dur: g.dur })
  }
  return diffUpdates(tasks, next)
}

/**
 * Run in parallel: drop the links between selected tasks and give them all the
 * earliest selected start. Returns the predecessor edits and the date moves.
 */
export function runParallel(tasks: TaskOut[], ids: number[]): {
  links: { id: number; predecessors: number[] }[]
  updates: BulkDateUpdate[]
} {
  const set = new Set(ids)
  const sel = tasks.filter((t) => set.has(t.id))
  const links = sel
    .filter((t) => t.predecessors.some((p) => set.has(p)))
    .map((t) => ({ id: t.id, predecessors: t.predecessors.filter((p) => !set.has(p)) }))
  if (sel.length === 0) return { links, updates: [] }
  const start = Math.min(...sel.map((t) => toDay(t.start_date)))
  const next = new Map(sel.map((t) => [t.id, { start, dur: t.duration_days }]))
  return { links, updates: diffUpdates(tasks, next) }
}

/** Would linking `from` -> `to` (to depends on from) close a cycle? */
export function createsCycle(tasks: TaskOut[], from: number, to: number): boolean {
  if (from === to) return true
  const preds = new Map(tasks.map((t) => [t.id, t.predecessors]))
  // Is `to` already an ancestor of `from`?
  const stack = [from]
  const seen = new Set<number>()
  while (stack.length) {
    const cur = stack.pop()!
    if (cur === to) return true
    if (seen.has(cur)) continue
    seen.add(cur)
    stack.push(...(preds.get(cur) ?? []))
  }
  return false
}

// ---------------------------------------------------------------- look

export const KIND_LABEL: Record<TaskKind, string> = {
  work: 'Work', supplier: 'Supplier', downtime: 'Tool downtime', bank_build: 'Bank build',
  sampling: 'Sampling', validation: 'Validation', customer: 'Customer', buffer: 'Buffer',
  milestone: 'Milestone',
}

/** Bar fill / stroke per kind (Tailwind 500/400 hexes, readable on slate-900). */
export const KIND_COLOR: Record<TaskKind, { fill: string; stroke: string }> = {
  work: { fill: '#0ea5e9', stroke: '#38bdf8' },
  supplier: { fill: '#8b5cf6', stroke: '#a78bfa' },
  downtime: { fill: '#f43f5e', stroke: '#fb7185' },
  bank_build: { fill: '#f59e0b', stroke: '#fbbf24' },
  sampling: { fill: '#14b8a6', stroke: '#2dd4bf' },
  validation: { fill: '#10b981', stroke: '#34d399' },
  customer: { fill: '#6366f1', stroke: '#818cf8' },
  buffer: { fill: '#64748b', stroke: '#94a3b8' },
  milestone: { fill: '#e2e8f0', stroke: '#f8fafc' },
}

/** Deadline line colour from its key: release red, quote amber, offer slate. */
export function deadlineColor(key: string): string {
  const k = key.toLowerCase()
  if (k.includes('release')) return '#ef4444'
  if (k.includes('quote') || k.includes('required')) return '#f59e0b'
  return '#94a3b8'
}

// ---------------------------------------------------------------- layout

export const ROW_H = 28
export const HEADER_H = 44

export function taskTooltip(t: TaskOut, g: Geo, rows: Map<number, number>): string {
  const dates = g.dur > 0
    ? `${fmtDay(g.start)} to ${fmtDay(inclusiveEnd(g))}`
    : fmtDay(g.start)
  const dur = g.dur > 0 ? `${g.dur} day${g.dur === 1 ? '' : 's'}` : 'milestone'
  const preds = predecessorText(t, rows)
  return [
    `#${rows.get(t.id) ?? '?'} ${t.name}${t.is_idea ? ' (idea)' : ''}`,
    `${dates}, ${dur}`,
    `Lane: ${laneOf(t)}`,
    ...(preds ? [`After: ${preds}`] : []),
    ...(t.progress_pct ? [`Progress: ${t.progress_pct}%`] : []),
  ].join('\n')
}

/** Width of the left grid: name only when compact, progress column in track mode. */
export function gridWidth({ compact, track }: { compact: boolean; track: boolean }): number {
  if (compact) return 190
  return 28 + 196 + 74 + 74 + 44 + 58 + (track ? 50 : 0)
}
