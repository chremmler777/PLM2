/**
 * The change plan (spec 2026-09-25 §4): one Gantt per change and plan kind.
 *
 * Dates travel as ISO days (`YYYY-MM-DD`). `end_date` is exclusive
 * (`start_date + duration_days`); the UI shows the inclusive last day.
 */

export type PlanKind = 'quote' | 'detailed'

export type TaskKind =
  | 'work' | 'supplier' | 'downtime' | 'bank_build' | 'sampling'
  | 'validation' | 'customer' | 'buffer' | 'milestone'

export const TASK_KINDS: TaskKind[] = [
  'work', 'supplier', 'downtime', 'bank_build', 'sampling',
  'validation', 'customer', 'buffer', 'milestone',
]

export interface TaskOut {
  id: number
  change_id: number
  plan: PlanKind
  name: string
  lane: string | null
  department_id: number | null
  department_name?: string | null
  kind: TaskKind
  is_idea: boolean
  start_date: string
  duration_days: number
  /** Exclusive: start_date + duration_days. */
  end_date: string
  predecessors: number[]
  sort_order: number
  progress_pct: number
  actual_start: string | null
  actual_finish: string | null
  baseline_start: string | null
  /** Same convention as end_date (exclusive). */
  baseline_finish: string | null
  source_position_id?: number | null
  notes: string | null
  slack_days?: number | null
  is_critical?: boolean
  /** Migration 088 (optional until the backend serves them). */
  parent_id?: number | null
  constraint_type?: PlanConstraintType | null
  /** Exclusive for fnlt / mfo, like end_date. */
  constraint_date?: string | null
  wbs?: string | null
  is_summary?: boolean
  total_slack?: number | null
  free_slack?: number | null
  created_by?: number | null
  created_at?: string | null
  updated_by?: number | null
  updated_at?: string | null
}

export type PlanConstraintType = 'asap' | 'snet' | 'fnlt' | 'mso' | 'mfo'
export type PlanLinkType = 'FS' | 'SS' | 'FF' | 'SF'

export interface PlanLink {
  id: number | null
  from_task_id: number
  to_task_id: number
  type: PlanLinkType
  /** Days in the plan calendar's unit; negative = lead. */
  lag_days: number
  /** An old `predecessors` dependency: shown, not editable (re-draw to edit). */
  legacy?: boolean
}

export interface PlanCalendar {
  mode: 'calendar' | 'working'
  /** ISO weekdays, Monday = 1. */
  workdays: number[]
  holidays: string[]
  /** Automatic scheduling (MS Project): the server pushes successors on every change. Default true. */
  auto?: boolean
}

export interface Issue {
  code: string
  message: string
  task_id: number | null
}

export interface PlanSummary {
  start: string | null
  finish: string | null
  duration_days: number
  buffer_days: number
  critical_ids: number[]
  ideas: number
}

export interface PlanDeadline {
  key: string
  label: string
  date: string
}

export interface PlanOut {
  plan: PlanKind
  tasks: TaskOut[]
  revision: number
  baseline_set: boolean
  can_edit: boolean
  can_edit_dates: boolean
  progress_department_ids: number[]
  summary: PlanSummary
  validation: { errors: Issue[]; warnings: Issue[] }
  deadlines: PlanDeadline[]
  /** Migration 088: typed links and the plan calendar. Absent on older servers. */
  links?: PlanLink[]
  calendar?: PlanCalendar | null
}

/** Answer of POST /plan/changes: the plan plus temp id maps. */
export interface PlanChangesOut extends PlanOut {
  id_map?: Record<string, number>
  link_id_map?: Record<string, number>
}

export type TempId = number | string

export interface TaskUpsert {
  id?: TempId
  name?: string
  kind?: TaskKind
  lane?: string | null
  department_id?: number | null
  start_date?: string
  duration_days?: number
  predecessors?: TempId[]
  is_idea?: boolean
  sort_order?: number
  progress_pct?: number
  actual_start?: string | null
  actual_finish?: string | null
  notes?: string | null
  parent_id?: TempId | null
  constraint_type?: PlanConstraintType | null
  constraint_date?: string | null
}

export interface LinkUpsert {
  id?: TempId
  from_task_id?: TempId
  to_task_id?: TempId
  type?: PlanLinkType
  lag_days?: number
}

export interface PlanChangeSet {
  tasks_upsert: TaskUpsert[]
  tasks_delete: number[]
  links_upsert: LinkUpsert[]
  links_delete: number[]
}

export interface TaskCreate {
  plan: PlanKind
  name: string
  kind: TaskKind
  lane?: string | null
  department_id?: number | null
  start_date: string
  duration_days: number
  predecessors?: number[]
  is_idea?: boolean
  notes?: string | null
}

export interface TaskPatch {
  name?: string
  kind?: TaskKind
  lane?: string | null
  department_id?: number | null
  start_date?: string
  duration_days?: number
  predecessors?: number[]
  is_idea?: boolean
  notes?: string | null
  progress_pct?: number
  actual_start?: string | null
  actual_finish?: string | null
  sort_order?: number
  parent_id?: number | null
  constraint_type?: PlanConstraintType | null
  constraint_date?: string | null
  reason?: string
}

export interface BulkDateUpdate {
  id: number
  start_date?: string
  duration_days?: number
}

export type FeedbackVerdict = 'confirmed' | 'concern'

export interface PlanFeedbackRow {
  department_id: number
  department_name: string
  verdict: FeedbackVerdict | null
  note: string | null
  by_name: string | null
  at: string | null
  stale: boolean
}

export interface PlanFeedback {
  revision: number
  required: PlanFeedbackRow[]
  all_confirmed: boolean
  validated_at: string | null
  validated_by_name: string | null
}

export type DeviationStatus = 'open' | 'locked' | 'escalated'

export interface PlanDeviation {
  id: number
  task_id: number
  task_name: string
  old_start: string
  old_end: string
  new_start: string
  new_end: string
  slip_days: number
  finish_impact_days: number
  reason: string
  status: DeviationStatus
  created_by_name?: string | null
  created_at?: string | null
  decided_by_name?: string | null
  decided_at?: string | null
  decision_note?: string | null
  escalation_id?: number | null
  /** Set when the row was pushed by another task's move (successor cascade). */
  caused_by_task_id?: number | null
  caused_by_task_name?: string | null
}
