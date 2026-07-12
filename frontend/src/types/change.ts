export type ChangeStatus =
  | 'captured' | 'scoping' | 'in_assessment' | 'costing' | 'quoted' | 'approved'
  | 'in_implementation' | 'in_validation' | 'released' | 'closed'
  | 'on_hold' | 'rejected' | 'cancelled';

export type ChangeType =
  | 'physical_part' | 'tooling' | 'document_spec' | 'process_im' | 'packaging';

export const CHANGE_STATUS_ORDER: ChangeStatus[] = [
  'captured', 'scoping', 'in_assessment', 'costing', 'quoted', 'approved',
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

export interface Attachment {
  id: number;
  filename: string;
  content_type: string;
  size_bytes: number;
  created_at: string;
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
  car_line?: string | null;
  affected_plant_ids?: number[];
  required_by_date: string | null;
  required_by_reason: string | null;
  deadline_state: 'on_track' | 'at_risk' | 'overdue' | null;
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

export interface ChangeTask {
  kind: string;
  change_id: number;
  change_number: string;
  title: string;
  department_id: number;
  assessment_id: number;
  owner_id: number | null;
  owner_name: string | null;
  accepted_at: string | null;
  due_date: string | null;
  overdue: boolean;
  mine: boolean;
}

// --- Cost & summation types (sub-project A) ---

export type CostKind = 'one_time' | 'lifecycle';

export interface CostLine {
  id: number;
  plant_id: number;
  activity_id?: number | null;
  activity_label?: string | null;
  cost_kind: CostKind;
  demand_hours: number;
  rate_snapshot: number;
  internal_cost: number;
  external_cost: number;
  note?: string | null;
}

export interface CostLineIn {
  plant_id: number;
  cost_kind: CostKind;
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
}

export type GateKey = 'feasibility' | 'budget' | 'release';
export interface Gate {
  gate_key: GateKey;
  decision: 'yes' | 'no' | 'na';
  decided_by?: number | null;
  decided_at?: string | null;
  remark?: string | null;
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

export interface ChangeMeeting {
  id: number;
  change_id: number;
  meeting_date: string;
  participants: MeetingParticipant[];
  notes: string | null;
  decision: 'proceed' | 'reject' | 'needs_info' | null;
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
