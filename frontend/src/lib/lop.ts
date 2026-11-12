/**
 * Project LOP: grouping and plain-English labels for the list the PM walks
 * through in the weekly meeting. The server decides each line's group
 * (lop_rules.group_of); here they are ordered and labelled.
 */
import type { LopEscalation, LopEscalationReason, LopGroup, LopKind, LopLine, LopStatus, MeetingMark } from '../types/lop'
import { MONTHS } from './format'

export const GROUP_ORDER: LopGroup[] = [
  'overdue', 'due_this_week', 'waiting_check', 'new', 'stale', 'other', 'pdb', 'closed',
]

export const DEFAULT_STALE_DAYS = 14

export function staleLabel(days?: number | null): string {
  return `No update for ${days ?? DEFAULT_STALE_DAYS} days`
}

export const GROUP_LABEL: Record<LopGroup, string> = {
  overdue: 'Overdue',
  due_this_week: 'Due this week',
  waiting_check: 'Done, waiting for PM check',
  new: 'New since last meeting',
  stale: staleLabel(),
  other: 'Other open',
  pdb: 'PDB topics',
  closed: 'Closed',
}

/** Escalated first, then the oldest; a topic without an age goes last. */
function pdbOrder(a: LopLine, b: LopLine): number {
  if (!!a.escalated !== !!b.escalated) return a.escalated ? -1 : 1
  const aa = a.age_days ?? -1
  const bb = b.age_days ?? -1
  return bb - aa
}

export function groupLines(lines: LopLine[]): { group: LopGroup; lines: LopLine[] }[] {
  const buckets = new Map<LopGroup, LopLine[]>()
  for (const line of lines) {
    const list = buckets.get(line.group) ?? []
    list.push(line)
    buckets.set(line.group, list)
  }
  return GROUP_ORDER
    .filter((g) => (buckets.get(g)?.length ?? 0) > 0)
    .map((g) => {
      const list = buckets.get(g)!
      return { group: g, lines: g === 'pdb' ? [...list].sort(pdbOrder) : list }
    })
}

/** "Nov 3" from an ISO day, never shifted by the time zone. */
export function shortDay(iso: string | null | undefined): string {
  if (!iso) return ''
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso)
  if (!m) return iso
  return `${MONTHS[Number(m[2]) - 1]} ${Number(m[3])}`
}

/** "Nov 3 · 8 d late", "Nov 14" or "not set". */
export function dueLabel(line: Pick<LopLine, 'due_date' | 'days_late' | 'late'>): string {
  if (!line.due_date) return 'not set'
  const day = shortDay(line.due_date)
  return line.days_late > 0 ? `${day} · ${line.days_late} d late` : day
}

/** Where a line comes from, in words: "SEP K0/RG1 · item 17", "SEP risk", "PDB topic", "PM task". */
export function sourceLabel(line: Pick<LopLine, 'kind' | 'source_label'>): string {
  if (line.kind === 'task') return 'PM task'
  if (line.kind === 'pdb_topic') return 'PDB topic'
  if (line.kind === 'risk') return 'SEP risk'
  return line.source_label.replace(/ item /, ' · item ')
}

const SOURCE_TONE: Record<LopKind, string> = {
  sep_item: 'border-sky-700/70 bg-sky-900/30 text-sky-200',
  risk: 'border-amber-700/70 bg-amber-900/25 text-amber-200',
  task: 'border-slate-600 bg-slate-800 text-slate-300',
  pdb_topic: 'border-violet-700/70 bg-violet-900/30 text-violet-200',
}

/** Tailwind classes for the source tag of a line. */
export function sourceTone(kind: LopKind): string {
  return SOURCE_TONE[kind] ?? SOURCE_TONE.task
}

export const STATUS_LABEL: Record<LopStatus, string> = {
  new: 'New',
  open: 'Open',
  in_work: 'In work',
  done_check: 'Done, please check',
  closed: 'Closed',
}

export const MARK_LABEL: Record<MeetingMark, string> = {
  updated: 'updated',
  moved: 'moved',
  escalated: 'escalated',
  none: 'not touched',
}

/** PDB's escalation level (0 none, 1 warning, 2 escalated, 3 critical) in words; null for none. */
export function escalationLabel(level: number | null | undefined): string | null {
  if (level === 1) return 'warning'
  if (level === 2) return 'escalated'
  if (level != null && level >= 3) return 'critical'
  return null
}

/** Stable React key: unpinned PDB topics have no line id yet. */
export function lineKey(line: LopLine): string {
  return line.id != null ? String(line.id) : `pdb-${line.ref_key}`
}

const LIVE_FIELDS = [
  'text', 'tool_number', 'age_days', 'escalation_level', 'escalated', 'committed_until',
  'last_log_at', 'handover_impact', 'pdb_department', 'pdb_live',
] as const

/**
 * Pinned PDB topics are lines of the project list (always there, snapshot
 * text). When PDB answered, its live fields are merged onto the pinned line
 * by ref_key; only the unpinned topics are added as rows of their own.
 */
export function withLiveTopics(lines: LopLine[], topics: LopLine[] | null | undefined): LopLine[] {
  if (!topics) return lines
  const live = new Map(topics.filter((t) => t.id != null).map((t) => [t.ref_key, t]))
  const merged = lines.map((l) => {
    const t = l.kind === 'pdb_topic' ? live.get(l.ref_key) : undefined
    if (!t) return l
    const out = { ...l } as Record<string, unknown>
    for (const f of LIVE_FIELDS) out[f] = t[f]
    return out as unknown as LopLine
  })
  return [...merged, ...topics.filter((t) => t.id == null)]
}

const REASON_TEXT: Record<LopEscalationReason, string> = {
  hand: 'escalated by the PM in the last meeting',
  late: 'late at two meetings in a row',
  stale: 'no update at two meetings in a row',
  late_or_stale: 'late or without update at two meetings in a row',
}

/** Why a line is escalated. The server says why (LopMeetings.escalations);
 *  `since` is that meeting's day. */
export function escalationReason(e: Extract<LopEscalation, { kind: 'line' }>): string {
  const day = shortDay(e.since)
  if (e.reason === 'hand') return `${REASON_TEXT.hand} (${day})`
  return `${REASON_TEXT[e.reason] ?? 'escalated'} since ${day}`
}
