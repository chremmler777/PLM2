/**
 * Plan against baseline and actual for a detailed plan: shared by the
 * Release tab's closing summary and the Timing tab's tracking line.
 */
import type { TaskOut } from '../../../types/changePlan'

const DAY = 86_400_000
const dayOf = (iso: string) => {
  const [y, m, d] = iso.slice(0, 10).split('-').map(Number)
  return Math.round(Date.UTC(y, m - 1, d) / DAY)
}
const isoOf = (day: number) => new Date(day * DAY).toISOString().slice(0, 10)
/** The last day a span occupies, as the Timing grid shows it: a milestone sits on its start. */
const lastDayOf = (start: number, endExcl: number) => (endExcl > start ? endExcl - 1 : start)

/**
 * Plan against baseline and actual, read the way the Timing tab reads it:
 * finishes are the inclusive last day of the latest real task.
 */
export function closingFigures(tasks: TaskOut[]) {
  const real = tasks.filter((t) => !t.is_idea && !t.is_summary)
  // end_date is the server's own, exclusive and calendar-aware (weekends,
  // holidays, constraints) — start_date + duration_days is plain day
  // arithmetic and can disagree with it.
  const planEnds = real.map((t) => lastDayOf(dayOf(t.start_date), dayOf(t.end_date)))
  const baseEnds = real.filter((t) => t.baseline_start && t.baseline_finish)
    .map((t) => lastDayOf(dayOf(t.baseline_start!), dayOf(t.baseline_finish!)))
  const planned = planEnds.length ? Math.max(...planEnds) : null
  const baseline = baseEnds.length ? Math.max(...baseEnds) : null
  const open = real.filter((t) => !t.actual_finish && (t.progress_pct ?? 0) < 100).length
  const finished = real.filter((t) => !!t.actual_finish).map((t) => dayOf(t.actual_finish!))
  const actual = real.length > 0 && open === 0 && finished.length ? Math.max(...finished) : null
  const slipped = real.filter((t) => t.baseline_finish && dayOf(t.end_date) > dayOf(t.baseline_finish)).length
  const against = actual ?? planned
  const slip = baseline != null && against != null ? against - baseline : null
  return {
    planned: planned != null ? isoOf(planned) : null,
    baseline: baseline != null ? isoOf(baseline) : null,
    actual: actual != null ? isoOf(actual) : null,
    open, slipped, slip, count: real.length,
  }
}
