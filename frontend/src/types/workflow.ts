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
