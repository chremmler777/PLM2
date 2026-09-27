/**
 * Predecessor notation as MS Project writes it: "3FS+2d", "5SS-1d", "7"
 * (plain row number = finish-to-start, no lag). Entries are separated by
 * commas or semicolons. Row numbers are the 1-based pre-order rows.
 * Lag units: d (days of the calendar mode), w (weeks: 7 days in calendar
 * mode, 5 working days in working mode); no unit means days.
 */
import { buildTree, key } from './tree'
import type { ChangeSet, GanttId, GanttLink, GanttTask, LinkType } from './types'

export interface ParsedPred { row: number; type: LinkType; lag: number }

export interface ParseResult { preds: ParsedPred[]; errors: string[] }

const ENTRY = /^(\d+)\s*(FS|SS|FF|SF)?\s*(?:([+-])\s*(\d+(?:\.\d+)?)\s*(d|w|ed|ew|days?|weeks?)?)?$/i

export function parsePredecessors(text: string, mode: 'calendar' | 'working' = 'calendar'): ParseResult {
  const preds: ParsedPred[] = []
  const errors: string[] = []
  for (const raw of text.split(/[,;]/)) {
    const s = raw.trim()
    if (!s) continue
    const m = ENTRY.exec(s)
    if (!m) { errors.push(`"${s}" is not a predecessor (use for example 3, 3FS+2d or 5SS-1d)`); continue }
    const row = Number(m[1])
    const type = (m[2]?.toUpperCase() ?? 'FS') as LinkType
    let lag = 0
    if (m[3]) {
      const n = Number(m[4])
      const unit = (m[5] ?? 'd').toLowerCase()
      const week = unit.startsWith('w') || unit === 'ew'
      const perWeek = unit === 'ew' ? 7 : mode === 'working' ? 5 : 7
      lag = Math.round(n * (week ? perWeek : 1)) * (m[3] === '-' ? -1 : 1)
    }
    if (row < 1) { errors.push(`Row ${row} does not exist`); continue }
    if (preds.some((p) => p.row === row)) { errors.push(`Row ${row} is listed twice`); continue }
    preds.push({ row, type, lag: lag === 0 ? 0 : lag })
  }
  return { preds, errors }
}

export function formatPredecessor(row: number, type: LinkType, lag: number): string {
  if (type === 'FS' && lag === 0) return String(row)
  const l = lag === 0 ? '' : `${lag > 0 ? '+' : '-'}${Math.abs(lag)}d`
  return `${row}${type}${l}`
}

/** The notation of every link into `taskId`, sorted by row. */
export function formatPredecessors(taskId: GanttId, links: GanttLink[], rows: Map<string, number>): string {
  return links
    .filter((l) => key(l.to) === key(taskId) && rows.has(key(l.from)))
    .map((l) => ({ row: rows.get(key(l.from))!, l }))
    .sort((a, b) => a.row - b.row)
    .map(({ row, l }) => formatPredecessor(row, l.type, l.lagDays))
    .join(', ')
}

let seq = 0
export const tempId = (prefix = 'tmp') => `${prefix}-${Date.now().toString(36)}-${(seq++).toString(36)}`

/**
 * Turn an edited predecessor cell into link edits: keep links whose source
 * row stays (updating type/lag), add the new ones, remove the dropped ones.
 * Returns errors instead when a row is unknown or points at the task itself.
 */
export function predecessorChangeSet(
  taskId: GanttId, text: string, tasks: GanttTask[], links: GanttLink[],
  mode: 'calendar' | 'working' = 'calendar', newId: () => GanttId = () => tempId('link'),
): { changes: ChangeSet | null; errors: string[] } {
  const { preds, errors } = parsePredecessors(text, mode)
  const order = buildTree(tasks).order
  for (const p of preds) {
    const t = order[p.row - 1]
    if (!t) errors.push(`Row ${p.row} does not exist`)
    else if (key(t.id) === key(taskId)) errors.push('A task cannot follow itself')
  }
  if (errors.length) return { changes: null, errors }
  const current = links.filter((l) => key(l.to) === key(taskId))
  const cs: ChangeSet = { label: 'Edit predecessors', addLinks: [], updateLinks: [], removeLinks: [] }
  const keep = new Set<string>()
  for (const p of preds) {
    const from = order[p.row - 1]
    keep.add(key(from.id))
    const existing = current.find((l) => key(l.from) === key(from.id))
    if (existing) {
      if (existing.type !== p.type || existing.lagDays !== p.lag) {
        cs.updateLinks!.push({ id: existing.id, patch: { type: p.type, lagDays: p.lag } })
      }
    } else {
      cs.addLinks!.push({ id: newId(), from: from.id, to: taskId, type: p.type, lagDays: p.lag })
    }
  }
  for (const l of current) if (!keep.has(key(l.from))) cs.removeLinks!.push(l.id)
  const empty = !cs.addLinks!.length && !cs.updateLinks!.length && !cs.removeLinks!.length
  return { changes: empty ? null : cs, errors: [] }
}
