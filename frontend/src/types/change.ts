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
  /** §2: the customer's own file (drawing, 3D, EC sheet); intake links them (C9). */
  | 'customer_file'
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
  /** C10: the named Sales owner; none on an internal change. */
  sales_owner_id?: number | null;
  sales_owner_name?: string | null;
  /** HARD #9: a price still open after approval. */
  price_open?: boolean;
  raised_by: number;
  customer_response: 'pending' | 'accepted' | 'declined' | 'negotiating';
  pm_signed_by?: number | null;
  quality_signed_by?: number | null;
  /** HARD #9: the offer each signature was given on (C14). */
  pm_signed_offer_id?: number | null;
  quality_signed_offer_id?: number | null;
  /** C14: who signed and when, shown to every viewer. */
  pm_signed_by_name?: string | null;
  pm_signed_at?: string | null;
  quality_signed_by_name?: string | null;
  quality_signed_at?: string | null;
  /** §7 still talking: the next contact date (C4). */
  customer_next_contact?: string | null;
  /** Served switch COMMERCIAL_V2 (§6-§7). */
  commercial_v2?: boolean;
  /** §7a start at risk: asked / approved. */
  start_at_risk_requested_at?: string | null;
  start_at_risk_approved_at?: string | null;
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
  /** Departments that owe a cost input and have not finalized it yet: in
   *  assessment (from their own feasible submit on) and in costing. */
  costing_pending_department_ids?: number[];
  /** Departments that owe a cost input at all (feasible, something impacted). */
  costing_owed_department_ids?: number[];
  /** Departments that have finalized their costing. */
  costing_finalized_department_ids?: number[];
  /** C18: departments that said "no cost", with why. */
  costing_no_cost?: Record<string, { reason: NoCostReason; hours?: number }>;
  /** Spec §4: open supplier waits (header "Waiting on FZ since ..."). */
  open_supplier_waits?: SupplierWait[];
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
  /** Served switch: true while Development confirms the impacted set by hand;
   *  false while the set locks itself at the scoping 'proceed' decision. */
  impact_confirm_step?: boolean;
  /** Served switch SCOPING_V2: C33 questions / check items, intake follow-ups. */
  scoping_v2?: boolean;
  /** Served switch ASSESSMENT_V2 (spec §4-§5). */
  assessment_v2?: boolean;
  /** Served switch START_AT_RISK (§7a); off: "No start before PO" */
  start_at_risk_on?: boolean;
  /** HARD #7: Quality's ppap_decision (internal changes) and the customer flip. */
  ppap_decision?: 'no' | 'yes' | null;
  ppap_basis?: string | null;
  ppap_ref?: string | null;
  ppap_part_ids?: number[] | null;
  ppap_decided_at?: string | null;
  customer_flip_at?: string | null;
  customer_flip_reason?: string | null;
  flip_answer?: 'notification' | 'offer' | null;
  flip_ref?: string | null;
  /** §1: a full ECR started beside a live change carrying the same part. */
  related_change_id?: number | null;
  /** §2 urgent (priority critical; need-by = release_due_date) and the internal problem. */
  urgent_reason?: string | null;
  urgent_evidence?: string | null;
  problem_value?: number | null;
  problem_unit?: string | null;
  target_value?: number | null;
  /** §11 internal: what it achieved beside the target, and the source. */
  achieved_value?: number | null;
  achieved_ref?: string | null;
  achieved_at?: string | null;
  /** Served switch RELEASE_V2 (§8-§11). */
  release_v2?: boolean;
  /** §10-§11: the concessions in force (header). */
  active_concessions?: ActiveConcession[];
  /** §3 urgent proceed: need-by realistic? and whether Sales told the customer. */
  need_by_check?: 'yes' | 'at_risk' | 'no' | null;
  need_by_proposed?: string | null;
  need_by_told_ref?: string | null;
  need_by_told_at?: string | null;
  /** The scope of the change in the project manager's words (2026-10-14). */
  scope_definition?: string | null;
  internal_approved_by?: number | null;
  internal_approved_at?: string | null;
  internal_approved_amount?: number | null;
  internal_approval_note?: string | null;
  /** Spec §5: the internal approval's case. */
  internal_rationale?: string | null;
  internal_volume?: number | null;
  internal_saving?: number | null;
  internal_saving_basis?: 'calculated' | 'estimate' | null;
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

/**
 * One line of the cockpit's "missing before <next stage>" box. `kind` says
 * what skipping it costs: "hard" cannot be bypassed, "soft" needs an approved
 * deviation, "todo" is stage work no guard enforces. The key is a stable code;
 * the wording lives in cmLabels under `next.item.<key>`.
 */
export interface NextStepItem {
  key: string;
  kind: 'hard' | 'soft' | 'todo';
  n?: number;
  detail?: string;
  /** C6: the soft rule an Override is bound to (cm_rules key). */
  rule?: string;
  /** Who owns it (and by when), in words. */
  who?: string;
  /** A hard rule's only ways out: concession, absorb, customer_accepts, sign. */
  exits?: ('concession' | 'absorb' | 'absorb_internal' | 'customer_accepts' | 'sign' | 'record_answer')[];
  /** The rule's override, when one is asked or approved. */
  override?: { id: number; status: 'pending' | 'approved' };
  /** Exit 'sign': the sign-offs still owed (missing, or given on an older
   * offer than `detail`, e.g. "v2"). */
  sides?: ('pm' | 'quality')[];
}

/** Who gives the OK on an override (backend cm_rules.decider_group). */
export type DeciderGroup = 'run' | 'pm_mgmt' | 'quality' | 'approver';

/** What still stands between the change and `to` (ChangeService.next_step_missing). */
export interface NextStep {
  to: ChangeStatus;
  items: NextStepItem[];
}

export interface ChangeDetail extends ChangeRequest {
  /** The project's plant (Project.plant_id). */
  project_plant_id?: number | null;
  impacted_items: ImpactedItem[];
  assessments: Assessment[];
  attachments: Attachment[];
  /** Null once there is no onward stage; absent from list payloads. */
  next_step?: NextStep | null;
}

/** Stage-responsibility rows my-tasks returns besides the assessment ones. */
export type ChangeTaskKind =
  | 'assessment' | 'kickoff' | 'hold_resume' | 'scoping_wrapup' | 'impact_confirm' | 'customer_response'
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
  | 'update_quote'
  /** C3 "Needs you": an override or Absorb this person decides. */
  | 'deviation_decision'
  /** C3 "Needs you": a PM or Quality sign-off for the latest offer. */
  | 'sign_off'
  /** C3 "Needs you": the internal approver's OK (HARD #8). */
  | 'internal_approval'
  /** C3: nothing holds the onward hop; the run team moves it on. */
  | 'advance'
  | 'plan_watch'
  /** C3 "Needs you": a pending routing change (added department) to decide. */
  | 'routing_deviation_decision'
  /** C3: a department answered 'not feasible'; the run team decides. */
  | 'not_feasible'
  /** A4-03: a declined supplement left the price open: absorb or a new version. */
  | 'price_open'
  /** C33: an Assumed answer to confirm with evidence by its date. */
  | 'confirm_assumption'
  /** HARD #7: Quality's ppap_decision on an internal change ("Needs you"). */
  | 'ppap_decision'
  /** The change became a customer change: notification only or offer? */
  | 'customer_flip'
  /** §1: a new index on a part the change carried: the department rechecks. */
  | 'assessment_recheck'
  /** §6 [R3] scope change card: the lead decides, Sales revises or tells. */
  | 'scope_change_decide' | 'revise_offer' | 'scope_change_tell' | 'scope_change_question'
  /** §7a start at risk: Quality's line, then the PM member's approval. */
  | 'start_at_risk_quality' | 'start_at_risk_approve'
  /** §1: the lead: does the new index add parts or departments? */
  | 'index_decision'
  /** §1: Sales: the new index replaces the old one; deadline holds? */
  | 'index_deadline'
  /** §1: an Assumed "not asked yet" deadline to confirm by its date. */
  | 'index_deadline_confirm'
  /** §3 urgent: need-by not realistic: Sales tells the customer. */
  | 'need_by_tell'
  /** R18: the lead picks the impacted parts (proceed and PPAP 'yes' wait). */
  | 'pick_impacted';

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
  impact_confirmed?: boolean | null;
  has_decision?: boolean;
  /** C33: open questions / cancel votes holding proceed, who they wait on,
   *  and the check items that go along. */
  open_questions?: number;
  waiting_on?: string[];
  /** A2-04: answered questions still open: their askers settle them. */
  answered_questions?: number;
  settle_by?: string[];
  /** What else holds proceed, each with its owner (and due) in words:
   *  ppap_decision (Quality), customer_flip (Sales), impacted_items. */
  holds?: { key: string; owner: string }[];
  open_checks?: number;
  // obtain_info rows: what the customer was asked for, and how much of it
  reason?: string | null;
  question_count?: number;
  /** obtain_info on a customer question: the mail text Sales copies. */
  customer_copy?: string | null;
  /** obtain_info: who owns the question, the asking department (else the
   *  person who asked). */
  asking_side?: string | null;
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
  /** C3: a decision only this person gives; listed under "Needs you". */
  needs_you?: boolean;
  /** C20: past due + 1 working day. */
  late?: boolean;
  /** Who sees a late row besides its owner: the lead's "Overdue" group and
   *  the digest (lead_digest) or the lead alone (lead, digest switched off)
   *  for assessments and the rows that owe a number or a decision; the
   *  digest alone (no lead, or Sales' stage rows); Project Management
   *  instead of the lead when the lead cannot act (pm_digest, pm); nobody else. */
  escalation?: 'lead_digest' | 'lead' | 'pm_digest' | 'pm' | 'digest' | null;
  /** C20: the deadline the row runs against ("due Thu (quote deadline Mon)"). */
  deadline_date?: string | null;
  deadline_kind?: 'quote' | 'need_by' | null;
  urgent?: boolean;
  /** Per-kind extras of the C3 rows. */
  label?: string | null;
  deviation_id?: number;
  side?: 'pm' | 'quality';
  offer_version?: number | null;
  /** §7 [R3] PM sign-off brief: total, margin (delta vs the version before),
   *  unconfirmed Assumed answers. Never on Quality's row. */
  offer_total?: number | null;
  offer_currency?: string | null;
  margin_pct?: number | null;
  margin_delta_pts?: number | null;
  /** A supplement's sign_off row (supplement: true): the delta (offer_total)
   *  and the accepted total after it, no margin. */
  accepted_total?: number | null;
  /** revise_offer: every department said 'no cost impact': confirm, nothing to price. */
  no_cost?: boolean;
  prev_version?: number | null;
  assumed_open?: number;
  /** §7 still talking: the next contact date of a customer_response row. */
  next_contact?: string | null;
  /** §6: the supplement a customer_response row is about. */
  supplement_version?: number | null;
  /** §6 [R3]: the scope change card a row belongs to; revise_offer past approval. */
  scope_change_id?: number | null;
  supplement?: boolean;
  to_status?: ChangeStatus | null;
  open_count?: number;
  target_tab?: string | null;
  /** The backend's one-line brief (not_feasible names the departments). */
  hint?: string | null;
  /** not_feasible: the departments that answered 'not feasible'. */
  departments?: string[];
  /** assessment row of a consulted department: its open check items and
   *  the department that owns them (R5/R18). */
  checks_open?: number;
  department_name?: string | null;
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
  /** ECR-solid §10: Quality's Fix task, and the fixing department's work. */
  | 'validation_issue_fix' | 'validation_issue_fix_work'
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
  /** advance: the onward status the step moves the change to. */
  to_status?: ChangeStatus | null;
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
  /** C25: the supplier's quote number, its date, how long it holds. */
  quote_ref?: string | null;
  quoted_on?: string | null;
  valid_until?: string | null;
}

export interface CostPosition {
  id: number;
  department_id: number;
  label: string;
  /** Spec §4 (C25): what the number stands on, its reference, "estimated",
   *  and the quote vs the estimate an offer / approval was given on. */
  basis?: CostBasis | null;
  basis_ref?: string | null;
  basis_part_id?: number | null;
  basis_part_number?: string | null;
  basis_differs?: string | null;
  /** A3-07: how many of what ("2 inserts"); null on lines from before. */
  quantity?: number | null;
  quantity_unit?: string | null;
  estimated?: boolean;
  /** settled: the open price an 'above' caused was absorbed or accepted. */
  estimate_check?: 'pending' | 'within' | 'above' | 'settled' | null;
  estimate_over?: number | null;
  /** R24: this caller may compare the quote with the estimate now (any
   *  status after the offer or approval; with no quote yet it records it). */
  can_check_estimate?: boolean;
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
  /** Where the class came from; null on a line priced before tool tonnage. */
  machine_class_origin?: MachineClassOrigin | null;
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

/**
 * Where a machine time / sampling line's class came from: picked by hand on
 * the line, a named press, picked by hand on the change, the change's tool
 * tonnage (MachineDB first, TWOS second, typed in PLM2 last), or none.
 */
export type MachineClassOrigin =
  | { kind: 'line' | 'machine' | 'change' }
  | {
      kind: 'tool'; tool_number: string; source: 'machinedb' | 'twos' | 'plm2';
      tonnage: number; basis?: 'assigned' | 'qualified_min' | null;
      machine?: string | null; class_found?: boolean;
    }
  | { kind: 'none'; tools: string[]; without: string[] }

export interface ToolTonnageSourceReport {
  status: 'ok' | 'failed' | 'not_configured' | 'no_tools';
  matched: number; updated: number; no_tonnage: string[]; error: string | null;
}

/** POST /changes/{id}/costing/tool-tonnage/refresh (report part). */
export interface ToolTonnageRefresh {
  tools: number;
  machinedb: ToolTonnageSourceReport;
  twos: ToolTonnageSourceReport;
  without: string[];
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
  /** Where the default class comes from (the change's tools). */
  tool_class_origin?: MachineClassOrigin | null;
  /** Which tonnage sources the backend can ask. */
  tonnage_sources?: { machinedb: boolean; twos: boolean };
  /** Only on the answer of a tool tonnage refresh. */
  tool_tonnage_refresh?: ToolTonnageRefresh;
  /** Always {} since the cost sheet has one rate per department and plant. */
  positions_by_department: Record<string, string[]>;
  can_set_machine_class?: boolean;
  /** May refresh the tool tonnage: may set the class, or Sales, Finance, admin. */
  can_refresh_tonnage?: boolean;
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
  /** Spec §4 (C25): what the number stands on. */
  basis?: CostBasis | null;
  basis_ref?: string | null;
  basis_part_id?: number | null;
  basis_differs?: string | null;
  /** A3-07: how many of what a money line stands for (ASSESSMENT_V2). */
  quantity?: number | null;
  quantity_unit?: string | null;
}

export type CostBasis = 'rate' | 'quote' | 'same_as' | 'estimate'

export interface CostingOfferIn {
  vendor_name: string;
  cost: number;
  /** C25: the supplier's quote number, its date, how long it holds. */
  quote_ref?: string | null;
  quoted_on?: string | null;
  valid_until?: string | null;
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
  /** The stored answer to the question. Answering does not close the card. */
  answer_note?: string | null;
  /** Questions (2026-10-14): the department the question was asked for (it
   *  owns the task), and whether the viewer may answer it (the asking
   *  department or the author, Sales, Project Management). Served by the list
   *  endpoint. */
  asking_department_name?: string | null;
  /** A3-13: an open question from an assessment is answered by this date. */
  answer_due?: string | null;
  can_answer?: boolean | null;
  /** C33: the caller may confirm this Assumed answer (named confirmer, or
   *  who may answer it), in any live status. */
  can_confirm?: boolean | null;
  /** A customer question: the mail text Sales copies. */
  customer_copy?: string | null;
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
  /** C33: a scoping flag is a question (blocks proceed) or a check item
   *  (checked in the owning department's assessment). null = legacy question. */
  flag_type?: FlagType | null;
  check_what?: CheckWhat | null;
  part_id?: number | null;
  part_number?: string | null;
  /** A question: who can answer it, and what the answer changes in the scope. */
  answer_from?: AnswerFrom | null;
  scope_effect?: string | null;
  co_department_ids?: number[] | null;
  /** The raised-for department and "same as" co-owners, by name. */
  owner_department_names?: string[];
  /** A check item's due: its department's assessment due (once routed). */
  owner_due?: string | null;
  /** The answer form: Confirmed (evidence) or Assumed (value, unit, risk). */
  answer_kind?: 'confirmed' | 'assumed' | null;
  answer_ref?: string | null;
  assumed_value?: string | null;
  assumed_unit?: string | null;
  assumed_risk?: string | null;
  confirm_by_id?: number | null;
  confirm_by_name?: string | null;
  confirm_due?: string | null;
  confirmed_at?: string | null;
  /** May the viewer switch question / check item (asker or PM)? */
  can_switch?: boolean | null;
  /** C33 'add to #n' (R24): same predicate as the backend's join with a note */
  can_add_to?: boolean | null;
  /** Spec §4: how the owning department closed a check item; may the viewer
   *  close it inline (a member) or reopen it (raiser, lead)? */
  check_outcome?: 'answered' | 'not_relevant' | 'assumed' | null;
  can_check?: boolean | null;
  can_reopen?: boolean | null;
}

/** Spec §4: POST .../concerns/{id}/check */
export interface CheckCloseBody {
  outcome: 'answered' | 'not_relevant' | 'assumed';
  value?: string;
  unit?: string;
  ref?: string;
  basis?: 'checklist_row' | 'drawing_ref' | 'outside_scope' | 'same_as';
  checklist_key?: string;
  who?: string;
  same_as_id?: number;
  assumed_risk?: string;
}

export type FlagType = 'question' | 'check';
export type CheckWhat = 'drawing' | 'volume' | 'cycle_time' | 'weight' | 'tool'
  | 'material' | 'tolerance' | 'schedule' | 'other';
export const CHECK_WHAT: CheckWhat[] = ['drawing', 'volume', 'cycle_time', 'weight',
  'tool', 'material', 'tolerance', 'schedule', 'other'];
export type AnswerFrom = 'customer' | 'our_team' | 'supplier';

/** C33 answer form body (POST .../answer). */
export interface AnswerForm {
  answer_kind: 'confirmed' | 'assumed';
  note?: string;
  ref?: string;
  mail_id?: number;
  assumed_value?: string;
  assumed_unit?: string;
  assumed_risk?: string;
  confirm_by_id?: number;
  confirm_due?: string;
}

/** C33: is this flag a check item (never blocks proceed)? */
export const isCheckItem = (c: Pick<ChangeConcern, 'kind' | 'flag_type'>) =>
  c.kind === 'needs_info' && c.flag_type === 'check';

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
  /** C33 "Go with conditions": the check items open at 'proceed'. */
  go_conditions?: { id: number; department_id: number | null; check_what?: string | null;
    note: string }[] | null;
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
  /** lapsed: approved but not used before the change left that status;
   * withdrawn: an Absorb the customer's acceptance made moot. */
  status: 'pending' | 'approved' | 'rejected' | 'consumed' | 'lapsed' | 'withdrawn';
  proposed_by: number;
  proposed_at: string;
  decided_by?: number | null;
  decided_at?: string | null;
  decision_note?: string | null;
  /** The viewer may decide this pending deviation (backend: the rule's deciders, never the proposer). */
  can_decide?: boolean;
  proposed_by_name?: string | null;
  decided_by_name?: string | null;
  /** C6: the soft rule it waives (null: asked before the binding). */
  guard_key?: string | null;
  guard_reason?: string | null;
  reason_code?: string | null;
  rule_label?: string | null;
  /** Pending only: whose OK it needs. */
  deciders?: { group: DeciderGroup; lead_name?: string | null } | null;
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
  /** C23: reporting | waiting (on a supplier, until a date) | done. */
  cadence?: 'reporting' | 'waiting' | 'done';
  part_done?: boolean;
  waiting_on?: string | null;
  waiting_until?: string | null;
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
  /** A5-10 b: a plain 'Part measured' passes with the measuring report. */
  pass_needs_report?: boolean;
  /** ECR-solid §10: computed from measurements against fixed limits. */
  computed?: boolean;
  unit_short?: string | null;
  needs_lot?: boolean;
  lower_limit?: number | null;
  upper_limit?: number | null;
  spec_source?: string | null;
  measurements?: ValidationMeasurement[];
  /** A5-02: who set the limits, who confirmed them; a PASS against
   *  limits only their setter stated counts once Quality confirms. */
  check_id?: number | null;
  limits_set_by_name?: string | null;
  limits_confirmed_by_name?: string | null;
  limits_confirmed_at?: string | null;
  limits_pending?: boolean;
  can_confirm_limits?: boolean;
}

export type RetestChangeKind = 'parameter' | 'tool' | 'material' | 'method';

export interface ValidationMeasurement {
  id: number;
  sample_size: number;
  min_value: number;
  max_value: number;
  measuring_ref: string;
  lot_ref?: string | null;
  what_changed_kind?: RetestChangeKind | null;
  what_changed_ref?: string | null;
  result: 'passed' | 'failed';
  measured_by_name?: string | null;
  measured_at?: string | null;
  /** "n=5, 503-516.2 g vs 495-515 g; scale WG-0042" */
  line: string;
}

export interface ValidationMeasurementIn {
  sample_size: number;
  min_value: number;
  max_value: number;
  measuring_ref: string;
  lot_ref?: string;
  lower_limit?: number;
  upper_limit?: number;
  spec_source?: string;
  what_changed_kind?: RetestChangeKind;
  what_changed_ref?: string;
}

export interface ActiveConcession {
  id: number;
  ref: string;
  until?: string | null;
  quantity?: number | null;
  not_for_shipment?: boolean;
  /** "Accepted under concession VI-1 until 2026-12-15" */
  text: string;
}

export interface ValidationDepartmentState {
  department_id: number;
  checks: ValidationCheck[];
  /** C7: may this viewer record the department's checks (backend rule). */
  can_write?: boolean;
  /** A5-04 d: '<X> has no member here: <lead|Project Management> coordinates'. */
  no_member_hint?: string | null;
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
  /** The backend's verdict on whether Sales owes the quote update (§10:
   *  a delta above 2 % of the estimate, or the switch's older rule). */
  weight_quote_update_open?: boolean;
  /** §10: "Not releasable: <check> vs <limits>; fix: <who>, retest <day>;
   *  concession: <state>", or null. */
  release_line?: string | null;
  /** §10-§11: the concessions in force. */
  active_concessions?: ActiveConcession[];
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
  /** Forward hops refused today: kind hard | gate | guard | decide, the reason and,
   * for a soft rule, its key (C6: what an override binds to). */
  transition_blocks?: Record<string, {
    /** hard | gate | guard | decide (a rule with its own decision, never overridden) */
    kind: string; reason: string; rule?: string | null;
    pending_deviation_id?: number | null;
  }>;
  can_edit_impact: boolean;
  impact_edit_needs_reason: boolean;
  /** C16: locked before the offer: the edit reopens the departments' costing. */
  impact_edit_reopens?: boolean;
  /** May the viewer record the scoping meeting and its decision (lead, PM, admin). */
  can_record_meeting?: boolean;
  lead_assigned: boolean;
  /** The one price rule (backend PriceViewer): admin, lead, PM, Sales, Management. */
  can_see_prices?: boolean;
  /** HARD #8: may the viewer give the internal approval (an engineering
   * approver, never the raiser; only an internal change in costing). */
  can_approve_internal?: boolean;
  /** HARD #8: who approves this internal change, in words (the configured
   * approvers other than the raiser, else the PM/admin fallback). */
  internal_approvers?: string | null;
  /** §5 card: any cost at all, so volume, saving and basis are asked (served
   *  for an approver without price view, R24). */
  internal_needs_money?: boolean | null;
  /** A3-09 (C5): why the approver cannot approve yet, and whether the
   *  viewer may ask the override of 'Costing not finalized'. */
  internal_approval_hold?: string | null;
  internal_hold_can_override?: boolean;
  title_auto: boolean;
  assessment: StageAssessment | null;
  routing_deviation: { text: string; can_decide?: boolean; decider?: string } | null;
  end_state: StageEndState | null;
  scope_change: { covered: boolean; offer_version?: number | null } | null;
  waits: StageWait[];
}

/** §1: one area of a recheck: 'no effect' with a ref, or 'effect' with what + evidence. */
export interface RecheckAreaAnswer {
  area: string;
  effect: boolean;
  ref?: string;
  what?: string;
  evidence?: string;
}

export interface ChangeRecheck {
  id: number;
  department_id: number;
  department_name: string | null;
  areas: string[];
  status: 'open' | 'answered';
  effect: boolean | null;
  answers: RecheckAreaAnswer[];
  something_else: string | null;
  answered_by_name: string | null;
  answered_at: string | null;
  created_at: string | null;
}

/** §1: a new customer index on a part the change carried, and its follow-ups. */
export interface IndexFollowup {
  intake_id: number;
  part_id: number;
  part_number: string | null;
  from_revision: string | null;
  to_revision: string | null;
  superseded: boolean;
  what_changed: string[];
  what_changed_ref: string | null;
  no_change_reason: string | null;
  rechecks: ChangeRecheck[];
  lead_open: boolean;
  scope_answer: 'no' | 'yes' | null;
  scope_note: string | null;
  scope_by_name: string | null;
  scope_at: string | null;
  deadline_open: boolean;
  deadline_answer: 'holds' | 'new_date' | 'not_asked' | null;
  deadline_ref: string | null;
  deadline_confirm_by: string | null;
  deadline_by_name: string | null;
}

/** C18: why a department has no cost. */
export type NoCostReason = 'no_work' | 'absorbed' | 'supplier'

/** Spec §4: a department waits on a supplier. */
export interface SupplierWait {
  id: number
  change_id: number
  department_id: number
  department_name?: string | null
  phase: 'costing' | 'implementation'
  vendor_name: string
  asked_on: string
  expected_by: string
  position_id?: number | null
  note?: string | null
  is_open: boolean
  overdue: boolean
  /** "day 9 of 21" */
  chip: string
  closed_at?: string | null
  close_reason?: 'received' | 'price_on_estimate' | 'not_needed' | null
}

/** ECR-solid §6 [R3]: a scope change card (no prices in it). */
export interface ScopeChangeCard {
  id: number
  kind: 'customer' | 'customer_index' | 'po_differs'
  status: 'requested' | 'recosting' | 'ready' | 'offered' | 'accepted' | 'refused' | 'dropped' | 'moved' | 'absorbed'
  part_number?: string | null
  what: string
  expects_by?: string | null
  evidence_ref?: string | null
  post_accept: boolean
  requested_by_name?: string | null
  requested_at: string
  decided_by_name?: string | null
  decision_note?: string | null
  departments: { id: number; name: string; done: boolean }[]
  waiting_for: string[]
  recost_due?: string | null
  offer_id?: number | null
  new_change_id?: number | null
  told_at?: string | null
  told_ref?: string | null
  /** Ready with 'no cost impact' from every department: Sales confirms it
   *  to the customer (told), nothing to price. */
  no_cost?: boolean
  /** §6 step 1: missing info is a question to the customer (Sales). */
  question?: {
    text: string; at?: string | null; open: boolean; by_name?: string | null
    answer?: string | null; ref?: string | null; answered_at?: string | null
    customer_copy?: string | null
  } | null
}
