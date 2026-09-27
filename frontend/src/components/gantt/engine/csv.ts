/**
 * CSV export: one row per task in display order. Finish and baseline finish
 * are the inclusive last day (what a spreadsheet reader means by "finish").
 */
import { lastDay, makeCal, toDay, toIso } from './calendar'
import { formatPredecessors } from './notation'
import { buildTree, key, rowNumbers } from './tree'
import type { GanttCalendar, GanttLink, GanttTask } from './types'

export const CSV_HEADER = [
  'ID', 'WBS', 'Name', 'Lane', 'Kind', 'Start', 'Finish', 'Duration', 'Predecessors',
  'Progress', 'Baseline start', 'Baseline finish', 'Constraint', 'Constraint date', 'Idea', 'Notes',
]

export function csvCell(v: unknown): string {
  const s = v == null ? '' : String(v)
  // Neutralise spreadsheet formulas, quote when needed.
  const safe = /^[=+\-@\t\r]/.test(s) && !/^-?\d+(\.\d+)?$/.test(s) ? `'${s}` : s
  return /[",\n\r;]/.test(safe) ? `"${safe.replace(/"/g, '""')}"` : safe
}

export function exportCsv(tasks: GanttTask[], links: GanttLink[], calendar?: Partial<GanttCalendar> | null): string {
  const cal = makeCal(calendar)
  const tree = buildTree(tasks)
  const rows = rowNumbers(tree)
  const out = [CSV_HEADER.join(',')]
  for (const t of tree.order) {
    const k = key(t.id)
    const s = toDay(t.start)
    const baseEnd = t.baselineStart && t.baselineEnd
      ? toIso(toDay(t.baselineEnd) > toDay(t.baselineStart) ? toDay(t.baselineEnd) - 1 : toDay(t.baselineEnd)) : ''
    out.push([
      rows.get(k), tree.wbs.get(k), t.name, t.lane ?? '', t.kind ?? '', t.start,
      toIso(lastDay(cal, s, t.duration)), t.duration, formatPredecessors(t.id, links, rows),
      Math.round(t.progress ?? 0), t.baselineStart ?? '', baseEnd,
      t.constraint && t.constraint.type !== 'asap' ? t.constraint.type.toUpperCase() : '',
      t.constraint?.date ?? '', t.isIdea ? 'yes' : '', t.notes ?? '',
    ].map(csvCell).join(','))
  }
  return out.join('\r\n') + '\r\n'
}
