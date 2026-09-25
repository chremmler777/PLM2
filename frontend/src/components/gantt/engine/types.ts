/**
 * The generic Gantt model (spec 2026-09-25 §11). No module-specific imports:
 * change management, projects or tool build plans map onto these shapes
 * through an adapter.
 *
 * Dates are ISO days (`YYYY-MM-DD`). Every end is EXCLUSIVE: a task starting
 * 2026-10-05 with 5 calendar days ends 2026-10-10 and occupies 5..9 Oct.
 * Finish constraint dates (fnlt, mfo) are exclusive ends too.
 */

export type GanttId = string | number

export type LinkType = 'FS' | 'SS' | 'FF' | 'SF'
export const LINK_TYPES: LinkType[] = ['FS', 'SS', 'FF', 'SF']

export type ConstraintType = 'asap' | 'snet' | 'fnlt' | 'mso' | 'mfo'
export const CONSTRAINT_TYPES: ConstraintType[] = ['asap', 'snet', 'fnlt', 'mso', 'mfo']

export interface GanttConstraint {
  type: ConstraintType
  /** Required for every type except asap. Exclusive for fnlt and mfo. */
  date?: string | null
}

export interface GanttTask {
  id: GanttId
  parentId?: GanttId | null
  name: string
  start: string
  /** Calendar days or working days, per the calendar mode. 0 = milestone. */
  duration: number
  kind?: string
  lane?: string | null
  isIdea?: boolean
  /** 0..100 */
  progress?: number
  baselineStart?: string | null
  /** Exclusive, like every end. */
  baselineEnd?: string | null
  actualStart?: string | null
  /** Inclusive last day actually worked (as a tracker records it). */
  actualEnd?: string | null
  constraint?: GanttConstraint | null
  color?: string
  readOnly?: boolean
  notes?: string | null
  meta?: Record<string, unknown>
}

export interface GanttLink {
  id: GanttId
  from: GanttId
  to: GanttId
  type: LinkType
  /** Working or calendar days per calendar mode; negative = lead. */
  lagDays: number
  /** Shown but not editable or removable (e.g. an old dependency the host cannot address). */
  readOnly?: boolean
}

export interface GanttCalendar {
  mode: 'calendar' | 'working'
  /** ISO weekdays that are worked: 1 = Monday .. 7 = Sunday. */
  workdays: number[]
  /** Non-working ISO days. */
  holidays: string[]
}

export const DEFAULT_CALENDAR: GanttCalendar = { mode: 'calendar', workdays: [1, 2, 3, 4, 5], holidays: [] }

export interface GanttModel {
  tasks: GanttTask[]
  links: GanttLink[]
}

/**
 * One user action, as a set of explicit edits. The component applies it
 * locally at once (optimistic) and hands it to the adapter to persist.
 */
export interface ChangeSet {
  /** Human label for undo/redo ("Move 3 tasks"). */
  label?: string
  /** New tasks. Temporary ids are fine; the adapter maps them to real ones. */
  addTasks?: GanttTask[]
  updateTasks?: { id: GanttId; patch: Partial<Omit<GanttTask, 'id'>> }[]
  removeTasks?: GanttId[]
  addLinks?: GanttLink[]
  updateLinks?: { id: GanttId; patch: Partial<Omit<GanttLink, 'id'>> }[]
  removeLinks?: GanttId[]
  /** New complete display order (task ids, pre-order) when rows moved. */
  order?: GanttId[]
  /** Free adapter data, for example `{ reason }` for a deviation. */
  meta?: Record<string, unknown>
}

/** What an adapter answers after persisting a ChangeSet. */
export interface ApplyResult {
  /** Temporary id -> id given by the server, for tasks and links. */
  idMap?: Record<string, GanttId>
  /** Temporary link id -> id given by the server (a separate id space from tasks). */
  linkIdMap?: Record<string, GanttId>
}

export interface Issue {
  code: string
  message: string
  taskId: GanttId | null
  linkId?: GanttId | null
  level: 'error' | 'warning'
}

export interface ScheduledTask {
  id: GanttId
  /** Early start and early (exclusive) finish. */
  start: string
  end: string
  lateStart: string | null
  lateEnd: string | null
  /** In duration units (working days in working mode); null for ideas. */
  totalSlack: number | null
  freeSlack: number | null
  critical: boolean
  isSummary: boolean
  /** Progress rolled up for summaries, own for leaves. */
  progress: number
}

export interface ScheduleOptions {
  /**
   * false (default): a task never moves earlier than its own start (the
   * planned date is an anchor, links and constraints only push later).
   * true: MS Project "as soon as possible": tasks without predecessors start
   * at the project start, the others right after their predecessors.
   */
  pull?: boolean
  /** Project start for pull mode; defaults to the earliest task start. */
  projectStart?: string
}

export interface ScheduleResult {
  byId: Map<GanttId, ScheduledTask>
  /** Tasks in a cycle (empty when there is none). */
  cycle: GanttId[]
  criticalIds: GanttId[]
  start: string | null
  /** Exclusive project finish over non-idea tasks. */
  finish: string | null
  issues: Issue[]
}

/** Bounds the backend enforces (400/422): mirrored in the inputs. */
export const LIMITS = { minYear: 1900, maxYear: 2200, maxDuration: 36500, maxLag: 3650, maxOutline: 50 } as const
export const inYearRange = (iso: string) => {
  const y = Number(iso.slice(0, 4))
  return y >= LIMITS.minYear && y <= LIMITS.maxYear
}
