export type ChangeStatus =
  | 'captured' | 'scoping' | 'in_assessment' | 'costing' | 'quoting' | 'quoted'
  | 'approved'
  | 'in_implementation' | 'in_validation' | 'released' | 'closed'
  | 'on_hold' | 'rejected' | 'cancelled';

export type ChangeType =
  | 'physical_part' | 'tooling' | 'document_spec' | 'process_im' | 'packaging';

export const CHANGE_STATUS_ORDER: ChangeStatus[] = [
  // 'quoting' is Sales building the offer out of the costing wrap-up — the step
  // between the departments finishing and the offer going out.
  'captured', 'scoping', 'in_assessment', 'costing', 'quoting', 'quoted', 'approved',
  'in_implementation', 'in_validation', 'released', 'closed',
];

export interface ImpactedItem {
  id: number;
  part_id: number;
  impact_note?: string | null;
  eng_level_before?: string | null;
  eng_level_after?: string | null;
  resulting_revision_id?: number | null;
  is_lead?: boolean;
  /** Human names, when the backend sends them (instead of "Part #id"). */
  part_number?: string | null;
  part_name?: string | null;
}

export interface Assessment {
  id: number;
  department_id: number;
  verdict: 'pending' | 'feasible' | 'feasible_with_conditions' | 'not_feasible';
  cost_impact?: number | null;
  lead_time_impact_days?: number | null;
  conditions?: string | null;
  notes?: string | null;
  responsible_id?: number | null;
  submitted_at?: string | null;
  stage_order: number;
  rasic_letter: string;
  status: string;
  owner_id: number | null;
  owner_name: string | null;
  accepted_at: string | null;
  due_date: string | null;
  overdue: boolean;
  effort_hours?: number | null;
  /** Department-specific answers — shape is that department's questionnaire. */
  details?: Record<string, unknown> | null;
  /** Whether the internal change deck is on file for this row. The backend's own
   *  answer to the not-feasible gate, so the UI does not have to guess from the
   *  attachment list it happens to hold. */
  has_change_ppt?: boolean;
}

export interface RoutingDepartment {
  department_id: number;
  rasic_letter: 'R' | 'A' | 'S' | 'C' | 'I';
  tier: 'blocking' | 'optional' | 'info';
  status: 'pending' | 'active' | 'submitted' | 'waived' | null;
  verdict: string | null;
  assessment_id: number | null;
  /** A declined letter awaiting the lead's decision. */
  pending_rasic_letter?: RasicLetter | null;
  /** A pending deviation asks to take this row off the routing; it stays
   *  (still owed) until the decision. */
  pending_removal?: boolean;
}

export interface RoutingStage {
  stage_order: number;
  departments: RoutingDepartment[];
}

/** What a department actually has to look at, per the impacted set. */
export type AssessmentObjectType = 'tool' | 'equipment' | 'gauge' | 'document' | 'part';

export interface AssessmentObject {
  type: AssessmentObjectType;
  id: number;
  number: string;
  name: string;
  via_part_id?: number | null;
}

/** GET /changes/{id}/impact-objects: what serves each given part. */
export interface ImpactObjectsResponse {
  parts: { part_id: number; served_by: (AssessmentObject & { category?: string | null })[] }[];
}

export interface DepartmentObjects {
  department_id: number;
  name: string;
  objects: AssessmentObject[];
}

export interface AssessmentObjectsResponse {
  departments: DepartmentObjects[];
}

export interface ChangeRouting {
  change_id: number;
  template_id: number | null;
  template_version: number | null;
  has_deviation: boolean;
  deviation_status: 'none' | 'pending_approval' | 'approved' | 'rejected';
  /** Why the pending (or last) deviation was proposed, and by whom. */
  deviation_note?: string | null;
  deviation_proposed_by?: number | null;
  stages: RoutingStage[];
}

export interface DeviationRequest {
  op: 'add' | 'remove' | 'reletter';
  department_id: number;
  rasic_letter?: RasicLetter;
  stage_order?: number;
  /** Required for op 'add': the audit reason the lead decides on. */
  reason?: string;
}

export type AttachmentKind =
  | 'general' | 'info_request' | 'info_response' | 'rejection_letter' | 'rfq'
  /** The internal deck behind a department's answer — a not-feasible verdict
   *  cannot be sent without one (backend-enforced). Filed per assessment. */
  | 'change_ppt'
  /** Saved customer correspondence (.msg/.eml/pdf). Change-level, no assessment. */
  | 'customer_email'
  /** A vendor's written quote, filed under the offer it belongs to. */
  | 'vendor_quote'
  /** The mother plant's timing (MS Project XML); seeds the detailed plan. */
  | 'mother_plant_timing';

export interface Attachment {
  id: number;
  filename: string;
  content_type: string;
  size_bytes: number;
  phase: 'baseline' | 'post_scoping';
  /** Needs-info loop: the question sent out, and the answer that came back. */
  kind?: AttachmentKind | null;
  responds_to_id?: number | null;
  /** The needs-info container this document belongs to, if any. */
  concern_id?: number | null;
  /** The assessment this document is evidence for — exclusive with concern_id. */
  assessment_id?: number | null;
  /** The vendor offer this quote document belongs to. */
  costing_offer_id?: number | null;
  /** The validation issue this evidence or customer mail is filed into. */
  validation_issue_id?: number | null;
  created_at: string;
  /** Who put the file on the record — optional until every endpoint sends it. */
  uploaded_by?: number | null;
  uploaded_by_name?: string | null;
}

export interface ChangelogEntry {
  id: number;
  action: string;
  action_description: string;
  performed_by: number;
  performed_at: string;
  notes?: string | null;
  /** Which field changed, and its before/after — absent on most rows, and
      blanked server-side for a money-carrying field when the viewer may not
      read prices. */
  field_name?: string | null;
  old_value?: string | null;
  new_value?: string | null;
}

export interface ChangeRequest {
  id: number;
  change_number: string;
  project_id: number;
  title: string;
  description?: string | null;
  reason?: string | null;
  change_type: ChangeType;
  priority: 'low' | 'medium' | 'high' | 'critical';
  status: ChangeStatus;
  lead_id?: number | null;
  lead_name?: string | null;
  raised_by: number;
  customer_response: 'pending' | 'accepted' | 'declined' | 'negotiating';
  pm_signed_by?: number | null;
  quality_signed_by?: number | null;
  estimated_cost?: number | null;
  quoted_price?: number | null;
  created_at: string;
  updated_at: string;
  issuer?: string | null;
  is_series?: boolean;
  cm_internal?: boolean;
  cm_external?: boolean;
  implementation_mode?: 'integrated' | 'separational' | null;
  customer_relevant?: boolean;
  rejected_at?: string | null;
  rejected_by?: number | null;
  rejection_reason?: string | null;
  /** Set once Sales confirms the rejection letter went out; closes the change. */
  rejection_sent_at?: string | null;
  rejection_sent_by?: number | null;
  car_line?: string | null;
  affected_plant_ids?: number[];
  required_by_date: string | null;
  required_by_reason: string | null;
  deadline_state: 'on_track' | 'at_risk' | 'overdue' | null;
  /** The project the change belongs to, denormalised for lists and headers. */
  project_number?: string | null;
  project_name?: string | null;
  /** Departments that still owe their cost input while the change is costing. */
  costing_pending_department_ids?: number[];
  /** Departments with an open assessment concern — their submit is blocked. */
  blocked_department_ids?: number[];
  quoted_at: string | null;
  quoted_on_time: boolean | null;
  active_deadline: 'quote' | 'release' | null;
  release_due_date: string | null;
  release_due_reason: string | null;
  impact_confirmed_by?: number | null;
  impact_confirmed_by_name?: string | null;
  impact_confirmed_at?: string | null;
  internal_approved_by?: number | null;
  internal_approved_at?: string | null;
  internal_approved_amount?: number | null;
  internal_approval_note?: string | null;
  /**
   * What the Tool Engineer says the part will weigh, quoted during costing.
   * It is an estimate on purpose — the validated figure arrives later, and
   * until it does everything reading this number has to say so.
   */
  estimated_part_weight_g?: number | null;
  estimated_weight_by_name?: string | null;
  estimated_weight_at?: string | null;
  /** Set once the estimate has been checked against a real part. */
  validated_part_weight_g?: number | null;
  /**
   * The price the negotiation ended on — the counter price of the entry Sales
   * marked as the final result. Read-only here: it is derived from the
   * negotiation log, never typed into the change.
   */
  negotiated_final_price?: number | null;
  /**
   * How the change gets onto the line once it is approved (stage 7). Either the
   * new state runs in on the fly, or the remaining old stock is scrapped on
   * purpose — and then the customer pays for the scrap, quoted separately.
   * Null until Scheduling has decided.
   */
  bank_build_mode?: BankBuildMode | null;
  bank_build_note?: string | null;
  /** Only set for planned scrap: the additional quote the customer bears. */
  scrap_quote_price?: number | null;
  /** A scrap quote price is on record. Never redacted: a viewer who may not
   *  read prices (scrap_quote_price null) still knows one exists. */
  scrap_price_set?: boolean;
  bank_build_set_by_name?: string | null;
  bank_build_set_at?: string | null;
  /** Set once Sales has put the plan in front of the customer. */
  plan_published_by_name?: string | null;
  plan_published_at?: string | null;
  /** Costing to close (spec 2026-09-25): timing, offer and release stage. */
  plan_revision?: number | null;
  timing_validated_at?: string | null;
  timing_validated_by?: number | null;
  accepted_offer_id?: number | null;
  lessons_done_at?: string | null;
  /** When the change was released / closed (release summary, re-check walk P3-6). */
  released_at?: string | null;
  closed_at?: string | null;
  lessons_done_by?: number | null;
  lessons_none_reason?: string | null;
  /** Where the change comes from (spec §14): customer, internal, or the
   *  mother-plant side track (no assessment, costing or quote). */
  origin?: ChangeOrigin;
  /** Spec §17: started by (or took) a revision intake. */
  from_intake?: boolean;
  mother_plant_name?: string | null;
  mother_plant_ref?: string | null;
  /** The mother plant's SOP (YYYY-MM-DD); the release deadline at approval. */
  mother_plant_sop?: string | null;
  /** Mother plant: first "Send information", and who has not confirmed yet. */
  info_sent_at?: string | null;
  info_department_ids?: number[];
  info_open_department_ids?: number[];
  // --- Early stages polish (spec §16). All optional: an older backend omits
  // them and every reader falls back to what it can derive itself. ---
  /** The statuses THIS viewer may move the change to (backend transition
   *  rights). Absent: the client mirror in lib/transitionRights decides. */
  allowed_transitions?: string[];
  /** The assessment round's first stage, as the backend counts it. */
  stage_state?: StageState | null;
  /** End states: the stage the change was in when it was rejected/cancelled. */
  stopped_at?: ChangeStatus | null;
  cancelled_at?: string | null;
  cancellation_reason?: string | null;
  /** The title is composed from the lead item and follows it (default on). */
  title_auto?: boolean;
  /** Impact edited after the offer went out: the offer no longer covers it. */
  scope_changed_after_quote?: boolean;
  /** The offer version that no longer covers the scope (Blocked by text). */
  scope_offer_version?: number | null;
  /** Who picked the lead (and when), for the Status card. */
  lead_set_at?: string | null;
  /** Cost carrier as the scoping meeting confirmed it. */
  cost_carrier_confirmed_at?: string | null;
  /** Human labels the backend already resolved (lists): the stage owner. */
  stage_owner?: string | null;
  /** Changes list: the viewer leads it or is on its hook. */
  is_mine?: boolean;
}

/** The first routing stage's standing (spec §16 P1 6). */
export interface StageState {
  /** R/A departments of the first stage that have not submitted. */
  waiting_department_ids: number[];
  submitted_department_ids?: number[];
  /** Submitted not-feasible verdicts (Blocked by + next step options). */
  not_feasible_department_ids?: number[];
  /** "Not our responsibility" declines awaiting the lead's decision. */
  declined_pending_department_ids?: number[];
  /** Every first-stage R/A row has submitted. */
  all_submitted: boolean;
}

/** Who may lead a change (lead picker on the Status card). */
export interface LeadCandidate {
  id: number;
  name: string;
  /** Login, shown when two candidates share a display name. */
  username?: string | null;
  department?: string | null;
  /** The project's PM: the picker's default. */
  is_default?: boolean;
}

/** engineering_review: the light track of a new customer index (spec §17). */
export type ChangeOrigin = 'customer' | 'internal' | 'mother_plant' | 'engineering_review';

/** Running change vs planned scrap — the two ways a change reaches the line. */
export type BankBuildMode = 'running_change' | 'planned_scrap';

/** How a negotiation round happened. Meetings, calls and mails are the three
 *  ways a price actually gets moved; nothing else is worth a vocabulary. */
export type NegotiationChannel = 'meeting' | 'call' | 'email';

/**
 * One round of the price negotiation at `quoted`: what was said, through which
 * channel, and — when the customer named one — the price they countered with.
 * Exactly one entry per change may be the final result; the backend clears the
 * flag on its siblings when a new final arrives.
 */
export interface ChangeNegotiation {
  id: number;
  channel: NegotiationChannel;
  note: string;
  counter_price?: number | null;
  is_final: boolean;
  created_by_name?: string | null;
  /** Present when the backend serves the raw id; used to gate the delete. */
  created_by?: number | null;
  created_at: string;
  /** The offer version the round was about (spec 2026-09-25). */
  offer_id?: number | null;
}

export interface ChangeDetail extends ChangeRequest {
  /** The project's plant (Project.plant_id). */
  project_plant_id?: number | null;
  impacted_items: ImpactedItem[];
  assessments: Assessment[];
  attachments: Attachment[];
}

/** Stage-responsibility rows my-tasks returns besides the assessment ones. */
export type ChangeTaskKind =
  | 'assessment' | 'kickoff' | 'scoping_wrapup' | 'impact_confirm' | 'customer_response'
  | 'obtain_info' | 'close_question' | 'send_rejection' | 'costing_input'
  /** Sales builds the offer once the departments are done costing. */
  | 'create_quote'
  /** Scheduling picks running change vs planned scrap on an approved change. */
  | 'bank_build'
  /** Sales puts the resulting bank-build plan in front of the customer. */
  | 'publish_plan'
  /** An implementing department owes a word on how the work is going. */
  | 'progress_report'
  /** Sales takes a flagged risk to the customer or internally. */
  | 'escalate_risk'
  /** An implementing department owes a validation check (stage 9). */
  | 'validation_check'
  /** A validated weight moved the part off its estimate — Sales re-quotes. */
  | 'update_quote';

/**
 * A row of my-tasks. Every row carries the change and its active deadline; the
 * rest is per-kind and therefore optional, so an unknown kind from a newer
 * backend still renders as a plain row instead of crashing the page.
 */
export interface ChangeTask {
  kind: ChangeTaskKind | (string & NonNullable<unknown>);
  change_id: number;
  change_number: string;
  title: string;
  project_number?: string | null;
  project_name?: string | null;
  due_date: string | null;
  overdue: boolean;
  // assessment rows
  department_id?: number;
  assessment_id?: number;
  owner_id?: number | null;
  owner_name?: string | null;
  accepted_at?: string | null;
  mine?: boolean;
  /** The backend's word that the row is the viewer's own; wins over `mine`. */
  is_mine?: boolean;
  // kickoff rows: which of description / attachment / date is still missing
  missing?: string[];
  // scoping wrap-up rows
  impact_confirmed?: boolean;
  has_decision?: boolean;
  // obtain_info rows: what the customer was asked for, and how much of it
  reason?: string | null;
  question_count?: number;
  concern_id?: number;
  // send_rejection rows: whether the letter is already attached
  has_letter?: boolean;
  /** Human kind label and the change's stage, when the backend sends them. */
  kind_label?: string | null;
  status?: ChangeStatus | null;
  /** The stage the row belongs to (backend key) and its human label. */
  stage?: string | null;
  stage_label?: string | null;
  /** R and A rows of one department folded into one task. */
  rasic_letters?: string[];
  /** Project team (spec §18): "main" counts; "backup" is listed muted. */
  role?: TeamRole;
  /** The responsible's name, on backup rows. */
  main_name?: string | null;
}

/** The viewer's standing on a role's work for a project (spec §18). */
export type TeamRole = 'main' | 'backup';

// --- Cost & summation types (sub-project A) ---

export type CostKind = 'one_time' | 'lifecycle';

export interface CostLine {
  id: number;
  plant_id: number;
  activity_id?: number | null;
  activity_label?: string | null;
  cost_kind: CostKind;
  /** Lifecycle lines: the production-time delta per part, in minutes.
   *  Negative when the change makes the part faster to produce. */
  minutes_per_part?: number | null;
  demand_hours: number;
  rate_snapshot: number | null;
  internal_cost: number;
  external_cost: number;
  note?: string | null;
}

export interface CostLineIn {
  plant_id: number;
  cost_kind: CostKind;
  minutes_per_part?: number | null;
  demand_hours: number;
  external_cost: number;
  activity_id?: number | null;
  activity_label?: string | null;
  note?: string | null;
}

export interface PlantRollup {
  plant_id: number;
  /** A plant's row is in that plant's currency. */
  currency?: string;
  one_time_internal: number; one_time_external: number;
  lifecycle_internal: number; lifecycle_external: number;
}
export interface DeptRollup extends Omit<PlantRollup, 'plant_id'> { department_id: number; }
export interface SummationTotals {
  one_time_internal: number; one_time_external: number;
  lifecycle_internal: number; lifecycle_external: number; grand_total: number;
}

export interface SummationPositionLine {
  position_id: number;
  label: string;
  kind: string;
  /** The quoted money of the line (Sales' chosen offer, else the estimate). */
  cost: number;
  currency: string;
  /** hours (trials) x rate; null = no rate in the cost sheet (not counted). */
  line_value: number | null;
  rate: number | null;
}

export interface SummationPositionRollup {
  department_id: number;
  position_cost: number;
  hours: number;
  hours_cost: number;
  machine_hours: number;
  trials: number;
  position_count: number;
  unrated_hours: boolean;
  unpriced_count: number;
  positions: SummationPositionLine[];
}

export interface Summation {
  /** The costing currency (the costing plant's): totals and by_department are in it. */
  currency?: string;
  /** The revenue's currency (the accepted or latest sent offer's, else the costing's). No margin when it differs. */
  revenue_currency?: string;
  /** Every currency's own sums; never added together, never converted. */
  totals_by_currency?: Record<string, SummationTotals>;
  mixed_currency?: boolean;
  unpriced_lines?: { position_id: number; department_id: number; label: string; kind: string;
    quantity: number; unit: string; reason?: string | null; message: string;
    /** machine_time / sampling: what is missing, e.g. "machine rate for class 200-450 t at USA Toccoa". */
    subject?: string | null }[];
  /** no_rate_department names its department_id, or its subject (a machine class's rate at a plant). */
  warnings?: { code: string; message: string; department_id?: number | null; subject?: string | null }[];
  cost_sheet_versions_used?: number[];
  cost_sheet_current_version?: number | null;
  by_plant: PlantRollup[];
  by_department: DeptRollup[];
  totals: { one_time_internal: number; one_time_external: number;
            lifecycle_internal: number; lifecycle_external: number; grand_total: number };
  effort_by_department: { department_id: number; effort_hours: number }[];
  total_effort_hours: number;
  /** Timing roll-up: the change is only as fast as its slowest department. */
  lead_time_by_department?: { department_id: number; lead_time_days: number }[];
  max_lead_time_days?: number;
  /** Production-time delta the change carries per part, summed per plant. */
  lifecycle_minutes_by_plant?: { plant_id: number; minutes_per_part: number }[];
  total_minutes_per_part?: number;
  /** The Tool Engineer's weight quote, carried into the wrap-up Sales prices. */
  part_weight_estimate_g?: number | null;
  /**
   * The costing positions' share of the totals, per department. Already
   * INSIDE totals and by_department (never add it again): position_cost is
   * the quoted money, hours_cost the positions' hours (trials) priced from
   * the cost sheet, both in the costing currency.
   */
  positions_by_department?: SummationPositionRollup[];
  total_position_cost?: number;
  total_position_hours_cost?: number;
  /**
   * What the change actually cost, once the work has run (stage 8/9). Absent
   * before implementation — everything reading it must survive that.
   */
  actuals?: PnlActuals;
}

/** One department's booked time, priced. */
export interface PnlActualDepartment {
  department_id: number;
  hours: number;
  /** €/h as configured; null when the department has no rate. */
  rate?: number | null;
  /** hours × rate, or 0 when there is no rate to multiply by. */
  internal_cost: number;
  /** True when the hours could not be priced — the figure below is incomplete. */
  unrated?: boolean;
  /** What costing planned for this department, for the side-by-side. */
  plan_internal_cost?: number | null;
}

/** A cost the plan did not carry: planned scrap, a weight delta, and so on. */
export interface PnlActualExtra {
  key: string;
  label?: string | null;
  amount: number;
}

export interface PnlActuals {
  by_department: PnlActualDepartment[];
  internal_cost: number;
  plan_internal_cost?: number | null;
  extras?: PnlActualExtra[];
  extra_cost?: number | null;
  total_cost?: number | null;
  /** actual − plan, as the backend computes it. */
  delta?: number | null;
  /** True when any department's hours are unpriced, i.e. the total is a floor. */
  unrated?: boolean;
}

export type GateKey = 'feasibility' | 'budget' | 'release';
export interface Gate {
  gate_key: GateKey;
  /** null: nobody has decided it yet (a seeded gate). */
  decision: 'yes' | 'no' | 'na' | null;
  decided_by?: number | null;
  /** The decider's full name, resolved by the backend. */
  decided_by_name?: string | null;
  decided_at?: string | null;
  remark?: string | null;
}

/** A checklist question the backend defines for a department's assessment. */
export interface ChecklistItemDef {
  key: string;
  label_de: string;
  label_en: string;
  /** false for the common set, true for a department's own additions. */
  extra: boolean;
  /** When present the ticked row must also pick one of these. The backend
   *  serves objects; plain strings are older payloads. */
  choices?: (ChecklistChoice | string)[];
  /** Documents a Yes owes before the assessment can be submitted (external
   *  modification: the change presentation and the change RFQ). Told apart
   *  by attachment kind; the backend refuses the submit without them. */
  requires_documents?: ChecklistRequiredDocument[];
}

export interface ChecklistRequiredDocument {
  kind: AttachmentKind;
  label_de: string;
  label_en: string;
  /** File types the slot takes, e.g. ['.ppt', '.pptx', '.pdf']. */
  extensions: string[];
}

export interface ChecklistChoice {
  value: string;
  label_de?: string;
  label_en?: string;
}

export interface DepartmentRateRef { department_id: number; plant_id: number; hourly_rate: number; min_factor: number; }
export interface ActivityRef { id: number; department_id: number; label: string; sort_order: number; }

// --- Task 19: "Your actions" cockpit panel ---

export type MyActionKind =
  | 'assessment' | 'wf_task' | 'deviation_decision' | 'routing_deviation_decision'
  | 'gate' | 'impact_confirm' | 'transition'
  /** Mother plant (spec §14). */
  | 'info_send' | 'info_ack' | 'inform_mother_plant'
  /** Validation issues (spec §12): the viewer's owed act on one issue. */
  | 'validation_issue_contain' | 'validation_issue_root_cause' | 'validation_issue_route'
  | 'validation_issue_action' | 'validation_issue_customer' | 'validation_issue_quote'
  | 'validation_issue_close' | 'validation_issue_escalation'
  /** Re-validation: the check's department answers the linked check again. */
  | 'validation_issue_recheck'
  /** Re-validation failed with every fix action done: a new action is owed. */
  | 'validation_issue_add_action'
  /** Spec §8 kinds the cockpit names itself. */
  | 'offer_build' | 'offer_expiring' | 'plan_feedback' | 'timing_validate'
  | 'plan_deviation' | 'release_check' | 'lessons_step' | 'needs_info'
  /** Stage tasks shared with My Tasks (one builder): label + target_tab
   *  (overview, scoping, commercial, implementation, or a tab name). */
  | 'kickoff' | 'scoping_wrapup' | 'customer_response' | 'close_question'
  | 'send_rejection' | 'costing_input' | 'costing_update' | 'create_quote'
  | 'bank_build' | 'publish_plan' | 'progress_report' | 'escalate_risk'
  | 'update_quote' | 'obtain_info' | 'deadline'
  /** The lead's flag: a department added after its stage passed still owes
   *  its answer. Chase it, or take it off the routing (op remove). */
  | 'late_assessment'
  /** A kind added later still renders from its label and target_tab. */
  | (string & NonNullable<unknown>);

export interface MyAction {
  kind: MyActionKind;
  label: string;
  target_tab: string;
  assessment_id?: number | null;
  task_id?: number | null;
  deviation_id?: number | null;
  gate_key?: GateKey | null;
  /** validation_issue_*: the issue the act is on (deep link ?issue=<id>). */
  issue_id?: number | null;
  escalation_id?: number | null;
  level?: number | null;
  /** Stage tasks: the department the task is owed by, the offer it is on. */
  department_id?: number | null;
  /** late_assessment: the department's name and the stage of its row. */
  department_name?: string | null;
  stage_order?: number | null;
  offer_id?: number | null;
  count?: number | null;
  /** Extra context beyond the label (shown as the button's tooltip). */
  hint?: string | null;
  /** Project team (spec §18): backup items show in a muted "As backup" group. */
  role?: TeamRole;
  main_name?: string | null;
}

export interface MyActionsResponse {
  actions: MyAction[];
  memberships: number[];
}

export interface ImpactTreeNode {
  part_id: number;
  part_number: string;
  customer_part_number?: string | null;
  name: string;
  part_type: string;
  item_category: string;
  is_impacted: boolean;
  is_lead: boolean;
  resulting_revision_id: number | null;
  /** "E2 · 005": the resulting revision's name and customer index. */
  resulting_revision_label?: string | null;
  /** A new customer index still pending triage/release (spec §17a). */
  resulting_revision_pending?: boolean;
  children: ImpactTreeNode[];
}

export interface ImpactTreeResponse {
  tree: ImpactTreeNode[];
  impacted_part_ids: number[];
  lead_part_id: number | null;
}

export interface ImplementationItem {
  item_id: number;
  part_id: number;
  part_number: string | null;
  part_name: string | null;
  item_category: string | null;
  is_lead: boolean;
  revision_id: number | null;
  revision_name: string | null;
  instance_id: number | null;
  instance_status: string | null;
  current_stage_order: number | null;
  total_stages: number | null;
  has_cad_file: boolean;
  no_geometry_change: boolean;
  ready: boolean;
  /** Who still owes a task in the check workflow (department or user names),
      when the backend names them. */
  waiting_on?: string[] | null;
}

export interface ImplementationProgress {
  ready_to_go: boolean;
  items: ImplementationItem[];
}

export interface MeetingParticipant {
  name: string;
  user_id?: number | null;
  /** From the contact picker: lets the backend resolve user_id when missing. */
  username?: string | null;
  email?: string | null;
}

export type MeetingChannel = 'meeting' | 'chat' | 'email';

/** Raisable today: only 'risk'. The other two are history — meetings and the old
 *  assessment flow created them, so they still arrive and still render. */
export type ConcernKind = 'reject_proposal' | 'needs_info' | 'risk';

/** The five things that actually go wrong in a moulding change, as the backend
 *  serves them from /reference/risk-types. */
/**
 * A cost position is what a department actually books against a change: an
 * hour figure for work it does itself, or money it has to spend outside.
 * Three kinds, because the three are answered by different people and read
 * differently in the summation.
 */
export type CostPositionKind =
  | 'internal_effort' | 'support_effort' | 'own_time' | 'external'
  /** hours x the machine class rate of the cost sheet */
  | 'machine_time'
  /** trials x the sampling price of the class */
  | 'sampling';

/** What a line under a category is: money bought, or the department's own hours. */
export type CostEntryType = 'money' | 'time';

/** One entry of the department's costing category list, coded or its own. */
export interface CostCategory {
  key: string;
  label_de?: string;
  label_en?: string;
  extra?: boolean;
  entry_type?: CostEntryType;
  /** Present on a department-defined category: the id to remove it by. */
  custom_id?: number;
}

/**
 * Lead time means different things in different departments: a shop floor
 * counts working days, a vendor quotes calendar weeks. The number is useless
 * without saying which, so every lead time carries its unit.
 */
export type LeadTimeUnit = 'business_days' | 'calendar_days';

/** External work is either a house number or a vendor's written offer. */
export type CostPositionPricing = 'estimate' | 'quote';

/** One vendor's answer to an external position. Several may compete. */
export interface CostingOffer {
  id: number;
  vendor_name: string;
  cost: number;
  /** Freight billed on top; ignored when the vendor includes it in the price. */
  shipping_cost?: number | null;
  shipping_included?: boolean;
  lead_time_days?: number | null;
  lead_time_unit?: LeadTimeUnit | null;
  /** The department's vote — exactly one favourite per position. */
  favorite?: boolean;
  /** A partial quote: part of the line, always counted. Default full quote = alternative. */
  is_partial?: boolean;
  /**
   * Sales' binding decision — exactly one chosen offer per position. The
   * favourite is only the recommendation; this is the offer that is bought.
   */
  chosen?: boolean;
  /** Required when the chosen offer is not the department's favourite. */
  chosen_reason?: string | null;
  chosen_by_name?: string | null;
  chosen_at?: string | null;
  attachments?: Attachment[];
}

export interface CostPosition {
  id: number;
  department_id: number;
  label: string;
  /** A key from the costing-tags reference, or a free-text word. */
  tag?: string | null;
  kind: CostPositionKind;
  pricing?: CostPositionPricing | null;
  est_cost?: number | null;
  /** Who gave the house number on an estimated line. */
  vendor_name?: string | null;
  hours?: number | null;
  lead_time_days?: number | null;
  lead_time_unit?: LeadTimeUnit | null;
  notes?: string | null;
  /** What the backend counts: the estimate, or the favourite offer's price. */
  effective_cost?: number | null;
  /** The summed partial quotes on a quoted line. */
  parts_cost?: number;
  offers: CostingOffer[];
  /** Cost sheet pricing (spec §15 phase 2). */
  labour_position?: string | null;
  /** The line's own class; null = priced on the change's class (follows it). */
  machine_class_id?: number | null;
  /** The class the line is priced on (its own or the change's). */
  machine_class?: string | null;
  machine_class_used_id?: number | null;
  machine_class_from_change?: boolean;
  /** A named MachineDB press: its own cost sheet rate beats the class rate. */
  machine_id?: number | null;
  machine_name?: string | null;
  /** True when the line is priced on the machine's own rate. */
  machine_rate_own?: boolean;
  trials?: number | null;
  /** The rate snapshot the line is priced with; null = no rate (not 0). */
  rate?: number | null;
  /** The rate's currency (the cost sheet row's): line_value is in it. */
  rate_currency?: string | null;
  /** The money currency of the line (estimate, offers): the costing plant's. */
  currency?: string | null;
  /** An old line that never recorded its currency: shown in the costing plant's, flagged. */
  currency_unrecorded?: boolean;
  rate_unit?: 'h' | 'trial' | null;
  rate_source?: 'cost_sheet' | 'department_rate' | null;
  cost_sheet_version_id?: number | null;
  cost_sheet_version?: number | null;
  rate_match?: string | null;
  rate_on?: string | null;
  /** "Cost sheet v2, Tool Engineer, Engineer, 21,50 USD/h" or "No rate in the cost sheet". */
  rate_label?: string | null;
  /** Hours (trials) on the line but nothing to price them with. */
  rate_missing?: boolean;
  rate_missing_reason?: string | null;
  rate_is_snapshot?: boolean;
  /** quantity x rate in `rate_currency`; null when the rate is missing. */
  line_value?: number | null;
}

/** GET /changes/{id}/costing/context */
export interface CostingContext {
  plant_id: number | null;
  plant_name: string | null;
  currency: string;
  rate_source: 'cost_sheet' | 'department_rate';
  /** The version that prices this change: valid on its creation date. */
  current_version: { id: number; version: number; valid_from: string } | null;
  /** The change's creation date (business date): the day its rates come from. */
  pricing_date?: string | null;
  /** "priced with v1, the earliest cost sheet": the change is older than the first version. */
  pricing_note?: string | null;
  /** The costing plant's second currency (Silao: MXN); null = one currency. */
  local_currency?: string | null;
  /** The change's version's exchange rates. */
  fx_rates?: { pair: string; base: string; quote: string; rate: string }[];
  latest_version: number | null;
  stale: {
    stale: boolean; review_months: number; latest_version: number | null;
    reviewed_on: string | null; due_on: string | null; reason: string | null;
  } | null;
  machine_classes: { id: number; name: string; tonnage_min: number | null; tonnage_max: number | null }[];
  machine_class_id: number | null;
  default_machine_class_id: number | null;
  effective_machine_class_id: number | null;
  tonnage: number | null;
  /** Always {} since the cost sheet has one rate per department and plant. */
  positions_by_department: Record<string, string[]>;
  can_set_machine_class?: boolean;
}

export interface CostPositionIn {
  department_id: number;
  label: string;
  tag?: string | null;
  kind: CostPositionKind;
  pricing?: CostPositionPricing | null;
  est_cost?: number | null;
  vendor_name?: string | null;
  hours?: number | null;
  lead_time_days?: number | null;
  lead_time_unit?: LeadTimeUnit | null;
  notes?: string | null;
  labour_position?: string | null;
  machine_class_id?: number | null;
  machine_id?: number | null;
  trials?: number | null;
}

export interface CostingOfferIn {
  vendor_name: string;
  cost: number;
  is_partial?: boolean;
  shipping_cost?: number | null;
  shipping_included?: boolean;
  lead_time_days?: number | null;
  lead_time_unit?: LeadTimeUnit | null;
}

/** The vocabulary is the backend's per-department list
    (app/services/risk_types.py); these are only the legacy keys kept for
    typing older rows. Any string the backend serves is valid. */
export type RiskType =
  | 'fill_issue' | 'dimensional_issue' | 'visual_surface'
  | 'process_capability' | 'other' | (string & NonNullable<unknown>);

/** A risk a department wrote down once to raise again. */
export interface RiskTemplate {
  id: number;
  department_id: number;
  risk_type: RiskType;
  severity: RiskSeverity;
  note: string;
  created_by: number;
  created_at: string;
}
export interface RiskTemplateIn {
  department_id: number;
  risk_type: RiskType;
  severity: RiskSeverity;
  note: string;
}

/** 1 low … 3 highest. A number, so it sorts and compares without a lookup. */
export type RiskSeverity = 1 | 2 | 3;

/** A team member's flag against a change, raised in parallel with the meeting. */
export interface ChangeConcern {
  id: number;
  change_id: number;
  kind: ConcernKind;
  note: string;
  raised_by: number;
  raised_by_name?: string | null;
  /** The asker's department memberships — their role in the room. */
  raised_by_departments?: string[];
  raised_at: string;
  withdrawn_at?: string | null;
  resolved_by_meeting_id?: number | null;
  is_open: boolean;
  /** Sales' stored answer to the question. Answering does not close the card. */
  answer_note?: string | null;
  answered_at?: string | null;
  answered_by?: number | null;
  answered_by_name?: string | null;
  /** The meeting whose needs-info decision raised this flag, when it was automatic. */
  raised_by_meeting_id?: number | null;
  /** Set for assessment-phase concerns: the department the flag is scoped to. */
  department_id?: number | null;
  /** How the concern was addressed — required to withdraw a scoped one. */
  resolution_note?: string | null;
  /** Risk rows only: what kind of risk it is and how bad it is. */
  risk_type?: RiskType | null;
  severity?: RiskSeverity | null;
  /** Risk raised from a checklist row: that row's key (or free:<label>). */
  checklist_key?: string | null;
  /** Who settled it ("solved by <name>"), and how it ended for a cancel vote:
   *  settled by the PM, or withdrawn by its author. */
  withdrawn_by?: number | null;
  withdrawn_by_name?: string | null;
  settled_as?: 'settled' | 'withdrawn' | null;
}

export interface ChangeMeeting {
  id: number;
  change_id: number;
  meeting_date: string;
  channel: MeetingChannel;
  participants: MeetingParticipant[];
  notes: string | null;
  decision: 'proceed' | 'reject' | 'needs_info' | null;
  decision_reason?: string | null;
  selected_department_ids: number[];
  /** The room's RASIC call, {department_id: letter}; absent on older meetings. */
  department_rasic?: Record<string, RasicLetter> | null;
  /** Cost carrier as the room confirmed it (spec §16): customer or internal. */
  cost_carrier?: CostCarrier | null;
  created_by: number;
  created_at: string;
  decided_by: number | null;
  decided_at: string | null;
}

/** R and A assess (blocking); S supports; C is consulted; I is informed
 *  (an FYI task, no assessment). */
export type RasicLetter = 'R' | 'A' | 'S' | 'C' | 'I';

/** Who pays: the customer (customer relevant) or the plant itself. */
export type CostCarrier = 'customer' | 'internal';

export interface TransitionDeviation {
  id: number;
  to_status: string;
  reason: string;
  status: 'pending' | 'approved' | 'rejected' | 'consumed';
  proposed_by: number;
  proposed_at: string;
  decided_by?: number | null;
  decided_at?: string | null;
  decision_note?: string | null;
}

// --- Stage 8: what actually happens while the change is being implemented ---
//
// The scheduling plan says how the change reaches the line; this says how the
// work is going. Three records, because three different people write them: the
// department books its hours, the department reports progress (and flags when
// it is going wrong), and Sales escalates a flagged risk to the customer or
// internally. Nothing here is derived from anything else.

/** Hours a department has booked against the change, one entry per sitting. */
export interface ImplBooking {
  id: number;
  department_id: number;
  hours: number;
  note?: string | null;
  /** Present when the backend serves the raw id; used to gate the delete. */
  created_by?: number | null;
  created_by_name?: string | null;
  created_at?: string | null;
}

/**
 * A progress report. `at_risk` is the whole point of the cadence: a department
 * that says nothing is not the same as one that says "this is going wrong",
 * and the risk note explains which it is.
 */
export interface ImplReport {
  id: number;
  department_id: number;
  note: string;
  at_risk: boolean;
  risk_note?: string | null;
  created_by?: number | null;
  created_by_name?: string | null;
  created_at?: string | null;
}

/** Outwards to the customer, or inwards to management. */
export type ImplEscalationDirection = 'customer' | 'internal';

/**
 * Sales taking a flagged risk somewhere. It hangs off the report it answers
 * (`report_id`), which is also how a department block finds its own; an
 * escalation without one belongs to the change as a whole.
 */
export interface ImplEscalation {
  id: number;
  direction: ImplEscalationDirection;
  note: string;
  report_id?: number | null;
  resolved_at?: string | null;
  resolution_note?: string | null;
  resolved_by_name?: string | null;
  created_by?: number | null;
  created_by_name?: string | null;
  created_at?: string | null;
}

/**
 * The board the tracking card is drawn from: one row per implementing
 * department, as the backend counts it. `owes_report` is the backend's cadence
 * verdict — the client never recomputes it from `last_report_at`.
 */
export interface ImplDepartmentState {
  department_id: number;
  booked_hours: number;
  last_report_at: string | null;
  at_risk_open: boolean;
  owes_report: boolean;
}

// ── Stage 9: validation ─────────────────────────────────────────────────────
//
// The work is done; now somebody has to show it actually works. Every
// implementing department answers a fixed, small list of checks — the same five
// keys across the flow, not a free-text sign-off — and two of them carry a
// number the rest of the system already has an opinion about: the cycle time
// costing assumed, and the weight the Tool Engineer estimated. A measured value
// that disagrees with the assumption is the whole reason this stage exists.

/**
 * The five things a department can be asked at validation. `weight` is the Tool
 * Engineer's, `revision_bump` is Development's ("revision levels raised per
 * customer statement and verified"); the other three are asked of whoever is
 * implementing.
 */
export type ValidationCheckKey =
  | 'sampled' | 'measured' | 'cycle_time' | 'weight' | 'revision_bump';

/** Open until somebody says otherwise; a fail is a statement, not a silence. */
export type ValidationCheckStatus = 'open' | 'passed' | 'failed';

export interface ValidationCheck {
  check_key: ValidationCheckKey | (string & NonNullable<unknown>);
  /** The catalog's labels (backend validation_checklist). */
  label_en?: string | null;
  label_de?: string | null;
  status: ValidationCheckStatus;
  /** Seconds for `cycle_time`, grams for `weight`; null for the yes/no checks. */
  value?: number | null;
  note?: string | null;
  checked_by_name?: string | null;
  checked_at?: string | null;
  /** No longer in the catalog: kept for the record when it was answered,
   *  never owed. Every count and gate skips it (the backend does too). */
  retired?: boolean;
}

export interface ValidationDepartmentState {
  department_id: number;
  checks: ValidationCheck[];
}

/**
 * What validation is standing on, in one payload: the per-department checks,
 * plus the two planned figures they are measured against. The delta is the
 * backend's — the client never recomputes it from estimate and value, so the
 * banner and the quote always argue with the same number.
 */
export interface ValidationState {
  departments: ValidationDepartmentState[];
  /** The costing assumption for production time, minutes per part. */
  planned_cycle_time_min_per_part?: number | null;
  /** What the Tool Engineer quoted during costing, grams. */
  weight_estimate_g?: number | null;
  /** What the part actually weighs, once the weight check has passed. */
  validated_weight_g?: number | null;
  /** validated − estimate, in grams. Non-zero means the quote is out of date. */
  weight_delta_g?: number | null;
  /** Set once Sales has taken the delta into the quote. */
  weight_ack_at?: string | null;
  weight_ack_by_name?: string | null;
  weight_ack_note?: string | null;
}

// --- GET /changes/{id}/stage-state (spec §16) ---------------------------------

export interface StageDept {
  department_id: number;
  department_name?: string | null;
  assessment_id?: number;
  rasic_letter?: string;
}

export interface StageWait {
  kind: string;
  text: string;
  target_tab?: string;
  department_id?: number;
  assessment_id?: number;
  has_change_ppt?: boolean;
  concern_ids?: number[];
  missing?: string[];
}

export interface StageAssessment {
  first_stage: number | null;
  total: number;
  submitted: number;
  all_submitted: boolean;
  waiting_on: StageDept[];
  not_feasible: (StageDept & { has_change_ppt?: boolean })[];
  declined_pending: (StageDept & { to_letter?: string | null })[];
  verdicts: (StageDept & { verdict: string; verdict_label?: string | null; open_risks?: number })[];
  open_risks: {
    id: number; department_id: number | null; department_name?: string | null;
    risk_type?: string | null; risk_type_label?: string | null;
    severity?: number | null; note: string; checklist_key?: string | null;
  }[];
  routing_deviation_pending: boolean;
  can_close: boolean;
  /** Client side: a transition deviation to costing past a not-feasible answer. */
  override?: 'pending' | 'approved' | null;
}

export interface StageEndState {
  kind: 'rejected' | 'cancelled';
  status: ChangeStatus;
  closed: boolean;
  stopped_at: ChangeStatus | null;
  stopped_at_label?: string | null;
  at?: string | null;
  by?: number | null;
  by_name?: string | null;
  reason?: string | null;
  label?: string | null;
}

export interface StageStateResponse {
  change_id: number;
  status: ChangeStatus;
  status_label?: string;
  /** {to_status: may the viewer} for every hop out of the current status. */
  can_transition: Record<string, boolean>;
  can_edit_impact: boolean;
  impact_edit_needs_reason: boolean;
  /** May the viewer record the scoping meeting and its decision (lead, PM, admin). */
  can_record_meeting?: boolean;
  lead_assigned: boolean;
  title_auto: boolean;
  assessment: StageAssessment | null;
  routing_deviation: { text: string; can_decide?: boolean; decider?: string } | null;
  end_state: StageEndState | null;
  scope_change: { covered: boolean; offer_version?: number | null } | null;
  waits: StageWait[];
}
