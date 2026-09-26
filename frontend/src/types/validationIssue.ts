/**
 * Validation issues: the failure branch of validation (spec 2026-09-25 §12,
 * §12a). A failed check becomes an issue with a light 8D shape, a decided
 * route to the fix, the customer's say, a recovery block in the plan and an
 * escalation level.
 */
import type { Attachment } from './change'

export type IssueCategory =
  | 'tool' | 'equipment_assembly' | 'dimensional' | 'material_weight'
  | 'cycle_time' | 'cosmetic' | 'packaging' | 'documentation' | 'other'

/** 1 low, 2 medium, 3 blocks production. */
export type IssueSeverity = 1 | 2 | 3

export type IssueRoute =
  | 'internal_rework' | 'supplier_rework' | 'design_change'
  | 'customer_concession' | 'follow_up_change'

export type IssueStatus =
  | 'open' | 'contained' | 'route_decided' | 'fixing' | 'revalidation'
  | 'closed' | 'accepted' | 'transferred'

export type CustomerDecision = 'accept_deviation' | 'require_fix' | 'new_timing' | 'pending'

export type CostBearer = 'internal' | 'supplier' | 'customer'

export type EscalationLevel = 1 | 2 | 3

/**
 * What the viewer may do on this issue now, as the backend decides it. The
 * first entry that is a real act is the viewer's next act (the one primary
 * button); the rest show as quiet links.
 */
export type IssueAct =
  | 'contain' | 'root_cause' | 'route' | 'customer' | 'cost'
  | 'add_action' | 'action_done' | 'recheck' | 'close' | 'acknowledge' | 'escalate'
  | 'edit' | 'attach'

/**
 * Acts the card shows outside the step flow (backend `extra_acts`). On a
 * closed issue `cost` is a late invoice or a corrected amount.
 */
export type IssueExtraAct = 'quote_fix' | 'deescalate' | 'cost'

export interface IssueActionOut {
  id: number
  issue_id?: number
  description: string
  owner_id?: number | null
  owner_name?: string | null
  department_id?: number | null
  department_name?: string | null
  due_date?: string | null
  status: 'open' | 'done'
  done_at?: string | null
  done_by_name?: string | null
  /** The viewer may tick this one (owner, owner department, PM, lead, admin). */
  can_done?: boolean
}

export interface IssueEscalationOut {
  id: number
  level: EscalationLevel
  reason: string
  /** Who was told, as text ("PM, change lead, Sales"). */
  notified?: string | null
  created_by_name?: string | null
  created_at: string
  acknowledged_by_name?: string | null
  acknowledged_at?: string | null
  /** The viewer is among the named roles and it is not acknowledged yet. */
  can_acknowledge?: boolean
  /** Still owed an acknowledgement: level 2 or 3, not a de-escalation. */
  needs_ack?: boolean
  trigger?: string | null
}

/**
 * The recovery group in the detailed plan (§12a) and what it does to the
 * finish. Working-day slips come from the server when it sends them; the card
 * falls back to counting Mon to Fri itself.
 */
export interface IssueRecoveryOut {
  /** The summary task "Recovery VI-n: ..." (focus target in the Timing tab). */
  summary_task_id: number
  /** Last day of the recovery group (inclusive). */
  finish: string | null
  /** The plan finish with the recovery in it. */
  plan_finish: string | null
  baseline_finish?: string | null
  release_due_date?: string | null
  /** Plan finish minus baseline finish, working days (+ = later). */
  slip_baseline_wd?: number | null
  /** Plan finish minus release deadline, working days (+ = after it). */
  slip_deadline_wd?: number | null
}

export interface IssueOut {
  id: number
  change_id: number
  /** Per change, 1..n. Shown "VI-3". */
  number: number
  title: string
  category: IssueCategory
  severity: IssueSeverity
  department_id?: number | null
  department_name?: string | null
  /** The failed validation check it came from. */
  check_id?: number | null
  check_key?: string | null
  check_department_id?: number | null
  /** The linked check as the backend names it (label in the viewer's words). */
  check?: {
    id: number; check_key: string; label?: string | null
    department_id?: number | null; department_name?: string | null; status?: string | null
  } | null
  affected_part_id?: number | null
  affected_part_number?: string | null
  affected_tool_ref?: string | null
  description: string
  containment?: string | null
  contained_at?: string | null
  contained_by_name?: string | null
  root_cause?: string | null
  root_cause_at?: string | null
  root_cause_by_name?: string | null
  route?: IssueRoute | null
  route_reason?: string | null
  route_decided_at?: string | null
  route_decided_by_name?: string | null
  supplier_name?: string | null
  chargeback?: boolean
  customer_inform?: boolean
  customer_decision?: CustomerDecision | null
  customer_decision_note?: string | null
  customer_decided_at?: string | null
  customer_decided_by_name?: string | null
  concession_until?: string | null
  /** Money; null for viewers outside the cost roles (redacted). */
  extra_cost?: number | null
  /** True when a cost is recorded, whether or not the viewer may see it. */
  cost_set?: boolean
  cost_bearer?: CostBearer | null
  /** The costing plant's currency; null when the change has no costing plant (shown unitless). */
  currency?: string | null
  /** The linked check is no longer asked of its department: no re-check, the issue closes with a note. */
  check_retired?: boolean
  /** Sales quoted a customer-paid fix to the customer. */
  fix_quoted_at?: string | null
  fix_quoted_by_name?: string | null
  follow_up_change_id?: number | null
  follow_up_change_number?: string | null
  status: IssueStatus
  closed_at?: string | null
  closed_by_name?: string | null
  closure_note?: string | null
  created_by: number
  created_by_name?: string | null
  created_at: string
  updated_at?: string | null
  actions: IssueActionOut[]
  /** can_delete: the backend's word on removing this file, when sent. */
  attachments: (Attachment & { can_delete?: boolean })[]
  next_acts?: IssueAct[]
  /**
   * The backend's pick of the one primary button (null: none). Wins over the
   * first non-quiet act when the key is sent, so add_action can lead after a
   * failed re-validation.
   */
  primary_act?: IssueAct | null
  extra_acts?: IssueExtraAct[]
  /** raised, contained, root_cause, route, fixing, revalidation, closed. */
  step?: string | null
  escalation?: { level?: EscalationLevel | null; unacknowledged?: boolean } | null
  escalation_level?: EscalationLevel | null
  escalations?: IssueEscalationOut[]
  recovery?: IssueRecoveryOut | null
}

export interface IssueCreate {
  title: string
  category: IssueCategory
  severity: IssueSeverity
  department_id?: number | null
  description: string
  check_id?: number | null
  /** The failed check by its key and department, when no id is known. */
  check_key?: string | null
  check_department_id?: number | null
  /** The linked check as the backend names it (label in the viewer's words). */
  check?: {
    id: number; check_key: string; label?: string | null
    department_id?: number | null; department_name?: string | null; status?: string | null
  } | null
  affected_part_id?: number | null
  affected_tool_ref?: string | null
}

export type IssuePatch = Partial<Pick<IssueCreate,
  'title' | 'description' | 'severity' | 'category' | 'department_id'
  | 'affected_part_id' | 'affected_tool_ref'>> & { customer_inform?: boolean }

export interface IssueActionIn {
  description: string
  owner_id?: number | null
  department_id?: number | null
  due_date?: string | null
}

export interface IssueRouteIn {
  route: IssueRoute
  reason: string
  supplier_name?: string
  chargeback?: boolean
  customer_inform?: boolean
  actions?: IssueActionIn[]
}

export interface IssueCustomerIn {
  decision: CustomerDecision
  note: string
  concession_until?: string | null
  /** new_timing: the customer's new release date (updates release_due_date). */
  new_release_due_date?: string | null
}

export interface IssueCostIn {
  extra_cost: number
  cost_bearer: CostBearer
}

export const OPEN_STATUSES: IssueStatus[] = ['open', 'contained', 'route_decided', 'fixing', 'revalidation']
export const isIssueOpen = (i: Pick<IssueOut, 'status'>) => OPEN_STATUSES.includes(i.status)
export const issueCode = (i: Pick<IssueOut, 'number'>) => `VI-${i.number}`
