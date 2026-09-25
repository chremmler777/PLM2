/**
 * Day arithmetic. A "day" is an integer: days since 1970-01-01 in UTC. ISO
 * strings go in and out at the edges only, so no timezone or DST ever touches
 * the math.
 *
 * Calendar mode: every day counts; workdays and holidays only shade the chart.
 * Working mode: durations and lags count working days. A start (milestones
 * included) is moved forward to the next working day. The exclusive end of a task is
 * the day after its last working day (Mon + 5 working days ends on Saturday,
 * shown as "last day Friday").
 */
import type { GanttCalendar } from './types'

const MS_DAY = 86_400_000
const ISO_RE = /^(\d{4})-(\d{2})-(\d{2})$/

export function isIsoDay(s: unknown): s is string {
  if (typeof s !== 'string') return false
  const m = ISO_RE.exec(s)
  if (!m) return false
  const [y, mo, d] = [Number(m[1]), Number(m[2]), Number(m[3])]
  const dt = new Date(Date.UTC(y, mo - 1, d))
  return dt.getUTCFullYear() === y && dt.getUTCMonth() === mo - 1 && dt.getUTCDate() === d
}

export function toDay(iso: string): number {
  const [y, m, d] = iso.slice(0, 10).split('-').map(Number)
  return Math.round(Date.UTC(y, m - 1, d) / MS_DAY)
}

export function toIso(day: number): string {
  return new Date(day * MS_DAY).toISOString().slice(0, 10)
}

export const addDaysIso = (iso: string, n: number): string => toIso(toDay(iso) + n)

/** Today in the viewer's local calendar, as a day number. */
export function todayDay(now: Date = new Date()): number {
  return Math.round(Date.UTC(now.getFullYear(), now.getMonth(), now.getDate()) / MS_DAY)
}

/** ISO weekday: 1 = Monday .. 7 = Sunday. */
export function isoWeekday(day: number): number {
  // 1970-01-01 was a Thursday (4).
  return ((((day + 3) % 7) + 7) % 7) + 1
}

export function mondayOf(day: number): number {
  return day - (isoWeekday(day) - 1)
}

export function isoWeek(day: number): number {
  const thursday = mondayOf(day) + 3
  const y = new Date(thursday * MS_DAY).getUTCFullYear()
  const jan1 = Math.round(Date.UTC(y, 0, 1) / MS_DAY)
  return Math.floor((thursday - jan1) / 7) + 1
}

export function ymd(day: number): { y: number; m: number; d: number } {
  const dt = new Date(day * MS_DAY)
  return { y: dt.getUTCFullYear(), m: dt.getUTCMonth(), d: dt.getUTCDate() }
}

export const dayOf = (y: number, m: number, d: number) => Math.round(Date.UTC(y, m, d) / MS_DAY)

export const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

/** "5 Oct 26". */
export function fmtDay(day: number | null | undefined): string {
  if (day == null || Number.isNaN(day)) return '-'
  const { y, m, d } = ymd(day)
  return `${d} ${MONTHS[m]} ${String(y).slice(2)}`
}

export const fmtIso = (iso: string | null | undefined) => (iso ? fmtDay(toDay(iso)) : '-')

/** "05.10.26": the app's dd.mm.yy style for axis, grid and tooltips. */
export function fmtShort(day: number | null | undefined): string {
  if (day == null || Number.isNaN(day)) return '-'
  const { y, m, d } = ymd(day)
  return `${String(d).padStart(2, '0')}.${String(m + 1).padStart(2, '0')}.${String(y).slice(2)}`
}

// ------------------------------------------------------------------ calendar

/** A calendar with fast holiday lookup. Build once per render/schedule. */
export interface Cal {
  mode: 'calendar' | 'working'
  isWork: (day: number) => boolean
  source: GanttCalendar
}

export function makeCal(c?: Partial<GanttCalendar> | null): Cal {
  const mode = c?.mode === 'working' ? 'working' : 'calendar'
  const workdays = new Set((c?.workdays && c.workdays.length ? c.workdays : [1, 2, 3, 4, 5]))
  const holidays = new Set((c?.holidays ?? []).filter(isIsoDay).map(toDay))
  const source: GanttCalendar = {
    mode, workdays: [...workdays].sort((a, b) => a - b), holidays: (c?.holidays ?? []).filter(isIsoDay),
  }
  // A calendar with no working day at all would loop forever: treat it as calendar mode.
  const anyWork = [1, 2, 3, 4, 5, 6, 7].some((w) => workdays.has(w))
  const isWork = (day: number) => workdays.has(isoWeekday(day)) && !holidays.has(day)
  return { mode: anyWork ? mode : 'calendar', isWork, source }
}

/** Shading helper: is this day off (weekend or holiday) in either mode? */
export const isOffDay = (cal: Cal, day: number) => !cal.isWork(day)

// Guard against pathological calendars (e.g. every day a holiday for years).
const MAX_SCAN = 366 * 50

/** First working day on or after `day` (calendar mode: the day itself). */
export function nextWork(cal: Cal, day: number): number {
  if (cal.mode === 'calendar') return day
  let d = day
  for (let i = 0; i < MAX_SCAN && !cal.isWork(d); i++) d++
  return d
}

/** Last working day on or before `day` (calendar mode: the day itself). */
export function prevWork(cal: Cal, day: number): number {
  if (cal.mode === 'calendar') return day
  let d = day
  for (let i = 0; i < MAX_SCAN && !cal.isWork(d); i++) d--
  return d
}

/**
 * Move `n` duration units from `day`. Forward: the day after the n-th working
 * day counted from `day` (so a task's exclusive end is `shift(start, dur)`).
 * Backward (n < 0): the |n|-th working day before `day`.
 */
export function shift(cal: Cal, day: number, n: number): number {
  if (cal.mode === 'calendar' || n === 0) return day + n
  let d = day
  if (n > 0) {
    let count = 0
    for (let i = 0; count < n && i < MAX_SCAN * 7; i++) {
      if (cal.isWork(d)) count++
      d++
    }
    return d
  }
  let count = 0
  for (let i = 0; count < -n && i < MAX_SCAN * 7; i++) {
    d--
    if (cal.isWork(d)) count++
  }
  return d
}

/**
 * Normalised start: the next working day in working mode, milestones too (a
 * milestone after a Friday finish sits on Monday, as the backend does).
 */
export function normStart(cal: Cal, day: number): number {
  return nextWork(cal, day)
}

/** Exclusive end of a task starting on `start` (a milestone ends on its start). */
export function endOf(cal: Cal, start: number, duration: number): number {
  const s = normStart(cal, start)
  if (duration <= 0) return s
  return shift(cal, s, duration)
}

/** The latest start that still ends by `end` (exclusive). */
export function startFor(cal: Cal, end: number, duration: number): number {
  if (duration <= 0) return end
  return shift(cal, end, -duration)
}

/**
 * Duration units between two days: working days in [a, b) in working mode,
 * plain days in calendar mode. Negative when b < a.
 */
export function diff(cal: Cal, a: number, b: number): number {
  if (cal.mode === 'calendar') return b - a
  if (b === a) return 0
  const [lo, hi, sign] = b > a ? [a, b, 1] : [b, a, -1]
  let n = 0
  for (let d = lo; d < hi; d++) if (cal.isWork(d)) n++
  return n * sign
}

/** Duration that makes a task starting `start` end on the exclusive `end`. */
export function durationBetween(cal: Cal, start: number, end: number): number {
  return Math.max(0, diff(cal, normStart(cal, start), end))
}

/** The inclusive last day a task occupies (a milestone sits on its start). */
export function lastDay(cal: Cal, start: number, duration: number): number {
  if (duration <= 0) return start
  return endOf(cal, start, duration) - 1
}

/** Duration from an inclusive last day typed by the user (at least 1). */
export function durationFromLastDay(cal: Cal, start: number, last: number): number {
  return Math.max(1, diff(cal, normStart(cal, start), last + 1))
}
