import client from './client';

export interface PipelineFunnelRow {
  status: string;
  count: number;
}

export interface PipelineThroughputRow {
  month: string;
  released: number;
}

export interface PipelineStageDays {
  from_status: string;
  to_status: string;
  avg_days: number;
}

export interface PipelineReport {
  funnel: PipelineFunnelRow[];
  throughput: PipelineThroughputRow[];
  avg_stage_days: PipelineStageDays[];
  on_time_rate: number | null;
}

export interface WorkloadDepartmentRow {
  department_id: number;
  name: string;
  open: number;
  overdue: number;
}

export interface WorkloadOwnerRow {
  owner_id: number;
  owner_name: string;
  open: number;
  overdue: number;
}

export interface WorkloadAtRiskChange {
  id: number;
  change_number: string;
  title: string;
  required_by_date: string | null;
  state: string;
}

export interface WorkloadReport {
  departments: WorkloadDepartmentRow[];
  owners: WorkloadOwnerRow[];
  at_risk_changes: WorkloadAtRiskChange[];
  escalation_count: number;
}

export interface CostProjectRow {
  project_id: number;
  name: string;
  budget: number;
  actual: number;
}

export interface CostPlantRow {
  plant_id: number;
  name: string;
  actual: number;
}

export interface CostReport {
  projects: CostProjectRow[];
  plants: CostPlantRow[];
}

export const reportsApi = {
  pipeline: (): Promise<PipelineReport> =>
    client.get('/v1/reports/pipeline').then((r) => r.data),
  workload: (): Promise<WorkloadReport> =>
    client.get('/v1/reports/workload').then((r) => r.data),
  cost: (): Promise<CostReport> =>
    client.get('/v1/reports/cost').then((r) => r.data),
};
