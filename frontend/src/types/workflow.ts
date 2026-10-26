/**
 * Workflow template types
 */

export interface Department {
  id: number;
  name: string;
  flow_type: 'action' | 'info';
  is_active: boolean;
  sort_order: number;
  /** Migration 149: the department's one optional manager (escalation overview). */
  manager_id?: number | null;
  manager_name?: string | null;
}

/** A person on the Departments admin page (name + email). */
export interface DepartmentPerson {
  id: number;
  name: string;
  username: string;
  email: string;
  is_active: boolean;
}

/** GET /departments/admin: a department with its manager and members. */
export interface DepartmentAdmin {
  id: number;
  name: string;
  is_active: boolean;
  sort_order: number;
  manager_id: number | null;
  manager_name: string | null;
  manager_active: boolean | null;
  members: DepartmentPerson[];
}

/** One late item of a managed department (My Tasks, "Late in my departments"). */
export interface DepartmentEscalation {
  kind: string;
  change_id: number;
  change_number: string;
  change_title: string;
  department_id: number;
  department_name: string;
  label: string;
  owner_name: string | null;
  due_date: string | null;
  days_overdue: number;
}

export interface WfStepRasic {
  id: number;
  step_id: number;
  department_id: number;
  department: Department;
  rasic_letter: string; // R|A|S|I|C
}

export interface WfStep {
  id: number;
  stage_id: number;
  step_name: string;
  position_in_stage: number;
  rasic_assignments: WfStepRasic[];
}

export interface WfStage {
  id: number;
  template_id: number;
  stage_order: number;
  name: string | null;
  steps: WfStep[];
}

export interface WfTemplate {
  id: number;
  name: string;
  description: string | null;
  version: number;
  is_active: boolean;
  created_at: string;
  created_by: number;
  updated_at: string | null;
  updated_by: number | null;
  stages: WfStage[];
}

export interface WfTemplateList {
  id: number;
  name: string;
  description: string | null;
  version: number;
  is_active: boolean;
  created_at: string;
  updated_at: string | null;
}

// Request types
export interface WfStepRasicCreate {
  department_id: number;
  rasic_letter: string;
}

export interface WfStepCreate {
  step_name: string;
  position_in_stage: number;
  rasic_assignments: WfStepRasicCreate[];
}

export interface WfStageCreate {
  stage_order: number;
  name: string | null;
  steps: WfStepCreate[];
}

export interface WfTemplateSave {
  name: string;
  description: string | null;
  stages: WfStageCreate[];
  change_note?: string;
}

// ============================================================================
// Phase 3c: Workflow instance types
// ============================================================================

export type WfTaskStatus = 'pending' | 'active' | 'approved' | 'rejected' | 'noted' | 'waived';
export type WfInstanceStatus = 'active' | 'completed' | 'canceled' | 'rejected';
export type WfDecision = 'approved' | 'rejected' | 'waived';

export interface WfInstanceTask {
  id: number;
  instance_id: number;
  stage_order: number;
  step_id: number;
  step_name: string;
  department_id: number;
  department_name: string;
  rasic_letter: string;
  status: WfTaskStatus;
  is_actionable: boolean;
  completed_by: number | null;
  completed_at: string | null;
  decision: WfDecision | null;
  notes: string | null;
  owner_id: number | null;
  owner_name: string | null;
  accepted_at: string | null;
  due_date: string | null;
  overdue: boolean;
  /** The step refuses "approved" until the revision has 3D evidence. */
  requires_cad_evidence?: boolean;
  /** R24: this viewer may approve / reject / waive it (the backend rule). */
  can_act?: boolean;
  /** R38: '<X> has no member here: <lead|Project Management> coordinates'. */
  coordinator_hint?: string | null;
}

export interface Escalation {
  kind: 'assessment' | 'wf_task' | 'deadline';
  change_id: number;
  change_number: string;
  change_title: string;
  label: string;
  owner_id?: number | null;
  owner_name?: string | null;
  due_date?: string;
  days_overdue: number;
  /** Present only for kind === 'deadline'. */
  required_by_date?: string;
  /** Which deadline a deadline row is (A6-08). */
  deadline_kind?: 'quote' | 'release';
  state?: 'on_track' | 'at_risk' | 'overdue';
}

export interface WfInstance {
  id: number;
  template_id: number;
  template_name: string;
  part_revision_id: number;
  status: WfInstanceStatus;
  current_stage_order: number;
  started_by: number;
  started_at: string;
  completed_at: string | null;
  canceled_at: string | null;
  /** Whether the revision has a CAD file or a signed "no geometry change";
   *  null when no step of the instance needs it. */
  has_3d_evidence?: boolean | null;
  cancel_reason: string | null;
  tasks: WfInstanceTask[];
}

export interface MyTask {
  task_id: number;
  instance_id: number;
  status: WfTaskStatus;
  is_actionable: boolean;
  rasic_letter: string;
  department_name: string;
  step_name: string;
  stage_order: number;
  stage_name: string | null;
  part_id: number;
  part_number: string;
  part_name: string;
  project_id: number;
  revision_id: number;
  revision_name: string;
  instance_started_at: string;
  owner_id: number | null;
  owner_name: string | null;
  accepted_at: string | null;
  due_date: string | null;
  overdue: boolean;
  mine: boolean;
  /** Project team (spec §18): "main" counts; "backup" is listed muted. */
  role?: 'main' | 'backup';
  /** D2b: overdue, so it is the named backup's too: the responsible's name. */
  covering_for?: string | null;
  main_name?: string | null;
  /** R38: a member-less department's step this user coordinates. */
  coordinated?: boolean;
  hint?: string | null;
}

// Instance request types
export interface StartWorkflowRequest {
  template_id: number;
}

export interface CompleteTaskRequest {
  decision: WfDecision;
  notes?: string;
}

export interface CancelWorkflowRequest {
  reason?: string;
}
