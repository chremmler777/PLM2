/**
 * What a plan calendar change does to the tasks (backend `set_calendar`):
 * durations and lags converted half up on a mode switch when asked (real
 * work stays at least one day), starts snapped to a working day in working
 * mode, then, with automatic scheduling, the forward push repairs the links
 * (later only; pinned and started tasks stay). Leaves only.
 */
import { lastDay, makeCal, normStart, toDay, toIso } from './calendar'
import { push } from './schedule'
import { buildTree, key } from './tree'
import { LIMITS, type GanttCalendar, type GanttId, type GanttLink, type GanttTask } from './types'

export interface CalendarMove {
  id: GanttId
  name: string
  from: { start: string; last: string }
  to: { start: string; last: string }
  /** Largest shift of start or last day, in calendar days (signed, later > 0). */
  shift: number
}

export interface CalendarPreview {
  moves: CalendarMove[]
  /** Leaves whose duration was converted. */
  converted: number
  /** max |shift| over the moves, 0 when none. */
  maxShift: number
  /** A converted value over the limits: the server refuses the change. */
  error: string | null
}

export function calendarChangePreview(
  tasks: GanttTask[], links: GanttLink[], from: Partial<GanttCalendar>, to: Partial<GanttCalendar>,
  opts: { convert?: boolean; auto?: boolean } = {},
): CalendarPreview {
  const oldCal = makeCal(from), newCal = makeCal(to)
  const tree = buildTree(tasks)
  const summaries = new Set([...tree.children.entries()].filter(([, c]) => c.length).map(([k]) => k))
  const wasWorking = oldCal.mode === 'working', isWorking = newCal.mode === 'working'
  let nt = tasks.map((t) => ({ ...t }))
  let nl = links.map((l) => ({ ...l }))
  let converted = 0
  let error: string | null = null
  if (opts.convert && wasWorking !== isWorking) {
    const n = (isWorking ? to.workdays : from.workdays)?.length || 5
    const [num, den] = isWorking ? [n, 7] : [7, n]
    const conv = (d: number, cap: number, what: string) => {
      const v = Math.floor(Math.abs(d) * num / den + 0.5)
      if (v > cap && !error) error = `Converted, a ${what} would be ${v} days, more than ${cap}`
      return (d >= 0 ? 1 : -1) * v
    }
    nt = nt.map((t) => {
      if (summaries.has(key(t.id)) || !(t.duration > 0)) return t
      converted++
      return { ...t, duration: Math.max(1, conv(t.duration, LIMITS.maxDuration, 'duration')) }
    })
    nl = nl.map((l) => (l.lagDays ? { ...l, lagDays: conv(l.lagDays, LIMITS.maxLag, 'lag') } : l))
  }
  if (isWorking) nt = nt.map((t) => ({ ...t, start: toIso(normStart(newCal, toDay(t.start))) }))
  if (opts.auto && nt.length) {
    const free = nt.filter((t) => !t.constraint || (t.constraint.type !== 'mso' && t.constraint.type !== 'mfo')).map((t) => t.id)
    const moved = new Map(push(nt, nl, to, [], free).map((m) => [key(m.id), m.patch.start]))
    nt = nt.map((t) => (moved.has(key(t.id)) ? { ...t, start: moved.get(key(t.id))! } : t))
  }
  const moves: CalendarMove[] = []
  const before = new Map(tasks.map((t) => [key(t.id), t]))
  for (const t of nt) {
    const k = key(t.id)
    if (summaries.has(k)) continue
    const o = before.get(k)!
    const os = toDay(o.start), ns = toDay(t.start)
    const ol = lastDay(oldCal, normStart(oldCal, os), o.duration), nl2 = lastDay(newCal, normStart(newCal, ns), t.duration)
    if (os === ns && ol === nl2) continue
    const ds = ns - os, dl = nl2 - ol
    moves.push({
      id: t.id, name: t.name,
      from: { start: o.start, last: toIso(ol) }, to: { start: t.start, last: toIso(nl2) },
      shift: Math.abs(ds) >= Math.abs(dl) ? ds : dl,
    })
  }
  const maxShift = moves.reduce((m, x) => Math.max(m, Math.abs(x.shift)), 0)
  return { moves, converted, maxShift, error }
}
