/**
 * Project LOP (list of open points). Shapes mirror backend/app/api/v1/lop.py
 * and LopService.line_dict / pdb_topic_dict in backend/app/services/lop_service.py.
 */

export type LopKind = 'task' | 'sep_item' | 'risk' | 'pdb_topic'
export type LopStatus = 'new' | 'open' | 'in_work' | 'done_check' | 'closed'
export type LopGroup = 'overdue' | 'due_this_week' | 'waiting_check' | 'new' | 'stale' | 'other' | 'pdb' | 'closed'
export type LopView = 'meeting' | 'open' | 'closed'
export type MeetingMark = 'updated' | 'moved' | 'escalated' | 'none'

export interface LopMeetingRef {
  id: number
  held_on: string
  open: boolean
}

export interface LopLastComment {
  id: number
  text: string
  user_id: number | null
  user_name: string | null
  created_at: string | null
}

export interface LopLine {
  /** null for a PDB topic nobody pinned (it is not a LOP line yet). */
  id: number | null
  project_id: number | null
  kind: LopKind
  ref_key: string | null
  title: string | null
  department_id: number | null
  responsible_id: number | null
  responsible_is_default: boolean
  due_date: string | null
  first_due_date: string | null
  due_is_default: boolean
  next_check_date: string | null
  status: LopStatus
  closed_at: string | null
  closed_by: number | null
  last_update_at: string | null
  last_update_by: number | null
  created_at: string | null
  created_by: number | null
  source_label: string
  text: string | null
  source_context: string | null
  source_closed: boolean
  department_name: string | null
  responsible_name: string | null
  days_late: number
  late: boolean
  stale: boolean
  under_control: boolean
  group: LopGroup
  moved: boolean
  reopened: boolean
  meeting?: LopMeetingRef | null
  meeting_mark?: MeetingMark | null
  last_comment: LopLastComment | null
  can_manage: boolean
  can_report: boolean
  // PDB topics (pinned or not)
  pinned?: boolean
  tool_number?: string | null
  age_days?: number | null
  escalation_level?: number | null
  escalated?: boolean
  committed_until?: string | null
  last_log_at?: string | null
  handover_impact?: boolean
  pdb_department?: string | null
  pdb_live?: boolean
}

export interface LopProjectResponse {
  project: { id: number; code: string; name: string; lop_enabled: boolean }
  can_manage: boolean
  lines: LopLine[]
  last_meeting: string | null
  /** The newest meeting, open or closed. */
  meeting: LopMeetingRef | null
  /** Lines not touched in the last closed meeting. */
  untouched: number
}

export interface LopMeetingDetail extends LopMeetingRef {
  project_id: number
  closed_at: string | null
  minutes_sent_at: string | null
  marks: { line_id: number; mark: MeetingMark; was_late: boolean; was_stale: boolean }[]
}

/** One tool of the project as PDB reports it (TWOS tool plus PDB counts). */
export interface PdbTool {
  tool_number: string
  tool_name?: string | null
  ps?: string | null
  ts?: string | null
  es?: string | null
  open_topics?: number
  /** The next sampling on PDB's calendar that has not ended (never a cancelled one). */
  next_sampling?: PdbNextSampling | null
  /** Monday of the week of an open sampling wish that has no slot yet. */
  sampling_requested_week?: string | null
}

export interface PdbNextSampling {
  id: number
  start_date: string
  start_shift?: number | null
  end_date?: string | null
  machine?: string | null
  state: 'requested' | 'confirmed' | string
  purpose?: string | null
}

export interface PdbStatus {
  tool_count: number
  funnel: Partial<Record<'sampling' | 'qualifying' | 'technical_handover' | 'ready' | 'series', number>>
  tools: PdbTool[]
}

export interface PdbResponse {
  available: boolean
  reason: string | null
  status: PdbStatus | null
  status_reason?: string | null
  topics: LopLine[]
  hidden: number
}

export interface SepCandidateGate {
  gate_id: number
  code: string
  status: string
  target_date: string | null
  items: { id: number; item_no: number; title: string | null; department: string | null }[]
}

export type LopHistoryItem =
  | { type: 'comment'; id: number; user_id: number | null; user_name: string | null; text: string; created_at: string | null }
  | {
    type: 'event'; id: number; user_id: number | null; user_name: string | null; field: string
    old_value: string | null; new_value: string | null; reason: string | null; created_at: string | null
  }

export interface LinePatch {
  title?: string
  department_id?: number | null
  responsible_id?: number
  clear_responsible?: boolean
  due_date?: string | null
  next_check_date?: string | null
  status?: LopStatus
  reason?: string
}

export interface LineCreate {
  title: string
  department_id?: number | null
  due_date?: string | null
  next_check_date?: string | null
  responsible_id?: number | null
}

export interface PinBody {
  responsible_id?: number | null
  due_date?: string | null
  next_check_date?: string | null
}

// ------------------------------------------------------------------ overview
// Shapes of GET /v1/lop/overview, /lines, /escalations and /mine
// (backend/app/services/lop_kpi.py, lop_meetings.escalations, api/v1/lop.py).

/** The line filters behind an overview count (GET /v1/lop/lines?flag=). */
export type LopFlag = 'open' | 'stale' | 'late' | 'no_control' | 'untouched'

/** lop_kpi.kpi(): one row of control KPIs. Percentages are null without a base. */
export interface LopKpi {
  open: number
  no_control: number
  with_name_and_date_pct: number | null
  stale: number
  late: number
  avg_days_late: number
  untouched_last_meeting: number
  on_time_pct_4w: number | null
  dates_moved_4w: number
  opened_week: number
  closed_week: number
}

/** The first SEP gate of the project that is not closed. */
export interface LopGateSummary {
  code: string
  done_pct: number | null
  target_date: string | null
}

/** PDB numbers of a project; every count is null when PDB did not answer. */
export interface LopPdbSummary {
  available: boolean
  tools_c: number | null
  tools_b: number | null
  tools_a: number | null
  open_topics: number | null
  escalated: number | null
  pinned: number
  pdb_without_name_and_date: number | null
}

export interface LopProjectKpi extends LopKpi {
  project_id: number
  code: string
  name: string
  gate: LopGateSummary | null
  pdb: LopPdbSummary
}

/** department_id null = "No department". */
export interface LopDepartmentKpi extends LopKpi {
  department_id: number | null
  name: string
}

/** Why a line is escalated: hand-marked by the PM in the newest closed meeting
 *  (wins), or late / stale / a mix of both at the two newest closed meetings. */
export type LopEscalationReason = 'hand' | 'late' | 'stale' | 'late_or_stale'

export type LopEscalation =
  | { kind: 'line'; line: LopLine; project_code: string; project_id: number; since: string; reason: LopEscalationReason }
  | { kind: 'no_meeting'; project_code: string; project_id: number; pm_name: string | null; since: string }

/** GET /v1/lop/escalations/mine: an escalation the caller has to act on.
 *  `own`: the caller is the line's responsible (else they run that LOP). */
export type LopMyEscalation = LopEscalation & { own: boolean }

export interface LopOverview {
  totals: LopKpi & { pdb_without_name_and_date: number }
  projects: LopProjectKpi[]
  departments: LopDepartmentKpi[]
  escalations: LopEscalation[]
}

/** A line of GET /lines or /mine: the line plus its project number (and name on /mine). */
export interface LopLineInProject extends LopLine {
  project_code: string
  project_name?: string
}

export interface LopLinesQuery {
  project_id?: number
  /** 0 = lines without a department. */
  department_id?: number
  flag?: LopFlag
}
