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
  deviation_status: 'none' | 'pending_approval' | 'approved';
  stages: RoutingStage[];
}

export interface DeviationRequest {
  op: 'add' | 'remove' | 'reletter';
  department_id: number;
  rasic_letter?: 'R' | 'A' | 'S' | 'C';
  stage_order?: number;
}

export type AttachmentKind =
  | 'general' | 'info_request' | 'info_response' | 'rejection_letter' | 'rfq'
  /** The internal deck behind a department's answer — a not-feasible verdict
   *  cannot be sent without one (backend-enforced). Filed per assessment. */
  | 'change_ppt'
  /** Saved customer correspondence (.msg/.eml/pdf). Change-level, no assessment. */
  | 'customer_email'
  /** A vendor's written quote, filed under the offer it belongs to. */
  | 'vendor_quote';

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
}

export interface ChangeDetail extends ChangeRequest {
  impacted_items: ImpactedItem[];
  assessments: Assessment[];
  attachments: Attachment[];
}

/** Stage-responsibility rows my-tasks returns besides the assessment ones. */
export type ChangeTaskKind =
  | 'assessment' | 'kickoff' | 'scoping_wrapup' | 'impact_confirm' | 'customer_response'
  | 'obtain_info' | 'close_question' | 'send_rejection' | 'costing_input'
  /** Sales builds the offer once the departments are done costing. */
  | 'create_quote';

/**
 * A row of my-tasks. Every row carries the change and its active deadline; the
 * rest is per-kind and therefore optional, so an unknown kind from a newer
 * backend still renders as a plain row instead of crashing the page.
 */
export interface ChangeTask {
  kind: ChangeTaskKind | (string & {});
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
}

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
  rate_snapshot: number;
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
  one_time_internal: number; one_time_external: number;
  lifecycle_internal: number; lifecycle_external: number;
}
export interface DeptRollup extends Omit<PlantRollup, 'plant_id'> { department_id: number; }
export interface Summation {
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
}

export type GateKey = 'feasibility' | 'budget' | 'release';
export interface Gate {
  gate_key: GateKey;
  decision: 'yes' | 'no' | 'na';
  decided_by?: number | null;
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
  /** When present the ticked row must also pick one of these. */
  choices?: string[];
}

export interface DepartmentRateRef { department_id: number; plant_id: number; hourly_rate: number; min_factor: number; }
export interface ActivityRef { id: number; department_id: number; label: string; sort_order: number; }

// --- Task 19: "Your actions" cockpit panel ---

export type MyActionKind =
  | 'assessment' | 'wf_task' | 'deviation_decision' | 'gate' | 'impact_confirm' | 'transition';

export interface MyAction {
  kind: MyActionKind;
  label: string;
  target_tab: string;
  assessment_id?: number | null;
  task_id?: number | null;
  deviation_id?: number | null;
  gate_key?: GateKey | null;
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
}

export interface ImplementationProgress {
  ready_to_go: boolean;
  items: ImplementationItem[];
}

export interface MeetingParticipant { name: string; user_id?: number | null }

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
export type CostPositionKind = 'internal_effort' | 'support_effort' | 'external';

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
  /** The department's vote — exactly one favourite per position. */
  favorite?: boolean;
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
  hours?: number | null;
  lead_time_days?: number | null;
  notes?: string | null;
  /** What the backend counts: the estimate, or the favourite offer's price. */
  effective_cost?: number | null;
  offers: CostingOffer[];
}

export interface CostPositionIn {
  department_id: number;
  label: string;
  tag?: string | null;
  kind: CostPositionKind;
  pricing?: CostPositionPricing | null;
  est_cost?: number | null;
  hours?: number | null;
  lead_time_days?: number | null;
  notes?: string | null;
}

export interface CostingOfferIn {
  vendor_name: string;
  cost: number;
  shipping_cost?: number | null;
  shipping_included?: boolean;
  lead_time_days?: number | null;
}

export type RiskType =
  | 'fill_issue' | 'dimensional_issue' | 'visual_surface'
  | 'process_capability' | 'other';

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
  created_by: number;
  created_at: string;
  decided_by: number | null;
  decided_at: string | null;
}

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
