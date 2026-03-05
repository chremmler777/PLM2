/**
 * Workflow template types
 */

export interface Department {
  id: number;
  name: string;
  flow_type: 'action' | 'info';
  is_active: boolean;
  sort_order: number;
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

export type WfTaskStatus = 'pending' | 'active' | 'approved' | 'rejected' | 'noted';
export type WfInstanceStatus = 'active' | 'completed' | 'canceled' | 'rejected';
export type WfDecision = 'approved' | 'rejected';

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
