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

export interface EcrKpi {
  on_time: number;
  late: number;
  rate: number | null;
  avg_days_late: number | null;
  open_overdue: number;
  open_due_7d: number;
  open_total: number;
}

export interface EcrKpiTrendRow {
  month: string;
  rfq_on_time: number;
  rfq_late: number;
  impl_on_time: number;
  impl_late: number;
}

export interface EcrKpiProjectRow {
  project_id: number | null;
  project_number: string | null;
  project_name: string | null;
  rfq_on_time: number;
  rfq_late: number;
  impl_on_time: number;
  impl_late: number;
}

export interface EcrKpiMiss {
  id: number;
  change_number: string;
  title: string;
  project_number: string | null;
  lead_name: string | null;
  status: string;
  kind: 'rfq' | 'implementation';
  due: string;
  /** null = still open and past its date */
  done: string | null;
  days_late: number;
}

export interface EcrKpiReport {
  window_months: number | null;
  rfq: EcrKpi;
  implementation: EcrKpi;
  trend: EcrKpiTrendRow[];
  by_project: EcrKpiProjectRow[];
  late: EcrKpiMiss[];
}

export const reportsApi = {
  pipeline: (): Promise<PipelineReport> =>
    client.get('/v1/reports/pipeline').then((r) => r.data),
  workload: (): Promise<WorkloadReport> =>
    client.get('/v1/reports/workload').then((r) => r.data),
  cost: (): Promise<CostReport> =>
    client.get('/v1/reports/cost').then((r) => r.data),
  /** months = 0 for all time */
  ecrKpis: (months: number): Promise<EcrKpiReport> =>
    client.get('/v1/reports/ecr-kpis', { params: { months } }).then((r) => r.data),
};
