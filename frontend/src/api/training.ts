/**
 * ECR training record: /v1/training (backend app/api/v1/training.py).
 * Ported from TWOS frontend/src/api/training.ts.
 */
import client, { API_BASE_URL } from './client'

export type SignoffStatus = 'pending_tasks' | 'active' | 'superseded'
export type TrainerSource = 'self_declared' | 'roster'

export interface TaskState {
  key: string
  passed: boolean
  attempts: number
}

export interface RoleState {
  role: string
  label: string
  departments: string[]
  required_version: number
  code_version: number
  status: SignoffStatus | null
  cleared: boolean
  /** A newer version was published after this person's last pass. */
  retrain_due: boolean
  open_reason: string | null
  /** Calendar date of the session (YYYY-MM-DD). */
  training_date: string | null
  attested_at: string | null
  trainer_name: string | null
  trainer_source: TrainerSource | null
  tasks_passed_at: string | null
  /** The software version the tasks were passed on. Null until they are. */
  software_version: string | null
  signoff_id: number | null
  tasks: TaskState[]
  retrain_since: string | null
  retrain_summary: string | null
  attestation_carried_forward: boolean
}

export interface CatalogRole {
  role: string
  label: string
  departments: string[]
  code_version: number
  required_version: number
  tasks: string[]
}

export interface TrainingStatus {
  user_id: number
  software_version: string
  cleared: boolean
  has_roles: boolean
  roles: RoleState[]
  catalog: CatalogRole[]
  gate_enabled: boolean
  gate_source: 'env' | 'org' | 'default'
  can_manage: boolean
  acting_as: string | null
  //: Acting as a department: the tasks can be walked, nothing is recorded.
  practice_only: boolean
  attestation_notice: string
  assessment_notice: string
}

export interface RosterRow {
  signoff_id: number
  user_id: number
  email: string
  display_name: string | null
  role: string
  label: string
  version: number
  required_version: number
  status: SignoffStatus
  cleared: boolean
  training_date: string | null
  attested_at: string | null
  trainer_name: string | null
  trainer_source: TrainerSource | null
  tasks_passed_at: string | null
  software_version: string | null
  attempts: number
  failed_attempts: number
  recorded_by: string | null
  superseded_at: string | null
  carried_from_id: number | null
}

export interface RosterResponse {
  items: RosterRow[]
  required_versions: Record<string, number>
  software_version: string
  pending: number
  active: number
}

export interface TrainingVersionRow {
  id: number
  role: string
  version: number
  summary: string
  software_version: string | null
  published_at: string
  published_by: string
}

export const trainingApi = {
  status: (): Promise<TrainingStatus> =>
    client.get<TrainingStatus>('/v1/training/status').then((r) => r.data),

  attest: (body: {
    role: string
    training_date: string
    trainer_name: string
    trainer_user_id?: number | null
    confirmed: boolean
  }): Promise<RoleState> => client.post<RoleState>('/v1/training/attest', body).then((r) => r.data),

  recordAttempt: (body: {
    role: string
    task_key: string
    result: 'passed' | 'failed'
    detail?: Record<string, unknown> | null
    duration_seconds?: number | null
  }): Promise<{ task_key: string; attempt_no: number; result: string; role_state: RoleState }> =>
    client.post('/v1/training/attempts', body).then((r) => r.data),

  versions: (): Promise<TrainingVersionRow[]> =>
    client.get<TrainingVersionRow[]>('/v1/training/versions').then((r) => r.data),

  publish: (role: string, summary: string): Promise<TrainingVersionRow> =>
    client.post<TrainingVersionRow>('/v1/training/versions', { role, summary }).then((r) => r.data),

  roster: (params?: { role?: string; include_superseded?: boolean }): Promise<RosterResponse> =>
    client.get<RosterResponse>('/v1/training/roster', { params }).then((r) => r.data),

  recordRoster: (body: {
    user_id: number
    role: string
    training_date: string
    trainer_name: string
  }): Promise<RosterRow> => client.post<RosterRow>('/v1/training/roster', body).then((r) => r.data),

  people: (): Promise<{ user_id: number; name: string; email: string; roles: string[] }[]> =>
    client.get('/v1/training/people').then((r) => r.data),

  gate: (): Promise<{ training_gate: boolean; source: string }> =>
    client.get('/v1/training/settings').then((r) => r.data),

  setGate: (on: boolean): Promise<{ training_gate: boolean; source: string }> =>
    client.put('/v1/training/settings', { training_gate: on }).then((r) => r.data),
}

/** The roster file, downloaded through the browser so the cookie goes with it. */
export function rosterCsvUrl(includeSuperseded = true): string {
  const base = API_BASE_URL.replace(/\/+$/, '')
  return `${base}/v1/training/roster.csv?include_superseded=${includeSuperseded}`
}
