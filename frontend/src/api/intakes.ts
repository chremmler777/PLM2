/**
 * Revision intake (spec 2026-09-25 §17): every new customer index is captured
 * and triaged by Development; the engineering review is its light track.
 * Every rule lives in the backend (/v1/intakes, /v1/changes/{id}/review).
 */
import client from './client';

export type IntakeRoute = 'full_ecr' | 'attach_ecr' | 'engineering_review' | 'administrative';

export interface Intake {
  id: number;
  part_id: number;
  part_number: string | null;
  part_name: string | null;
  customer_part_number: string | null;
  project_id: number;
  project_name: string | null;
  revision_id: number;
  revision_name: string | null;
  customer_index: string | null;
  revision_status: string | null;
  active_revision_name: string | null;
  file_count: number;
  source: string;
  source_label: string;
  batch_id: string | null;
  received_at: string | null;
  received_by_name: string | null;
  status: 'pending' | 'decided' | 'superseded';
  /** The revision is still pending: not active yet, not superseded. */
  waiting: boolean;
  revision_phase: string | null;
  part_phase: string | null;
  suggested_route: IntakeRoute | null;
  route: IntakeRoute | null;
  route_label: string | null;
  reason: string | null;
  decided_by_name: string | null;
  decided_at: string | null;
  change_id: number | null;
  change_number: string | null;
  change_title: string | null;
  change_status: string | null;
  change_origin: string | null;
  activated_at: string | null;
  escalated_at: string | null;
  superseded_by_id: number | null;
  created_at: string;
  needs_triage: boolean;
  can_decide: boolean;
  /** Project team (spec §18), on My Tasks triage rows. */
  role?: 'main' | 'backup';
  main_name?: string | null;
}

export interface IntakeList {
  can_triage: boolean;
  intakes: Intake[];
}

export interface ReviewTask {
  change_id: number;
  change_number: string;
  title: string;
  department_id: number;
  department_name: string | null;
  /** Project team (spec §18), on My Tasks rows. */
  role?: 'main' | 'backup';
  main_name?: string | null;
}

export interface MyIntakes {
  triage: Intake[];
  review: ReviewTask[];
}

export interface ReviewAnswer {
  id: number;
  department_id: number;
  department_name: string | null;
  answer: 'no_impact' | 'impact' | null;
  answer_label: string | null;
  note: string | null;
  answered_by_name: string | null;
  answered_at: string | null;
  objects: { id: number; number: string; name: string; item_category: string; via_part_id: number }[];
  can_answer: boolean;
}

export interface ReviewState {
  change_id: number;
  is_review: boolean;
  escalated: boolean;
  escalated_at: string | null;
  impact_locked: boolean;
  open: boolean;
  answers: ReviewAnswer[];
  open_count: number;
  impact_count: number;
  revisions: { part_id: number; part_number: string | null; revision_id: number;
    revision_name: string; status: string; active: boolean }[];
  intake_id: number | null;
  can_escalate: boolean;
}

export const intakeKeys = {
  part: (partId: number | string) => ['intakes', 'part', Number(partId)] as const,
  my: ['intakes', 'my'] as const,
  review: (changeId: number) => ['change', changeId, 'review'] as const,
};

export const intakesApi = {
  list: (params: { part_id?: number; project_id?: number; status?: string; waiting?: boolean }) =>
    client.get<IntakeList>('/v1/intakes', { params }).then((r) => r.data),
  my: () => client.get<MyIntakes>('/v1/intakes/my').then((r) => r.data),
  decide: (id: number, body: { route: IntakeRoute; reason?: string; change_id?: number }) =>
    client.post<Intake>(`/v1/intakes/${id}/decide`, body).then((r) => r.data),
  review: (changeId: number) =>
    client.get<ReviewState>(`/v1/changes/${changeId}/review`).then((r) => r.data),
  answer: (changeId: number, body: { department_id: number; answer: 'no_impact' | 'impact'; note?: string }) =>
    client.post<ReviewState>(`/v1/changes/${changeId}/review/answers`, body).then((r) => r.data),
  escalate: (changeId: number, note?: string) =>
    client.post<ReviewState>(`/v1/changes/${changeId}/review/escalate`, { note: note || null }).then((r) => r.data),
};

export const ROUTE_LABELS: Record<IntakeRoute, string> = {
  full_ecr: 'Full ECR',
  attach_ecr: 'Attach to an open change',
  engineering_review: 'Engineering review',
  administrative: 'Administrative',
};

/** What each route does, in the words of the route dialog. */
export const ROUTE_EXPLAIN: Record<IntakeRoute, string> = {
  full_ecr: 'Starts a new change in this project with the part as lead item. '
    + 'The new index becomes active when that change is released (scoping, assessment, costing, quote, timing).',
  attach_ecr: 'Adds the new index to an open change you choose (up to implementation). '
    + 'It becomes active when that change is released.',
  engineering_review: 'Light track: Development locks the impact, the departments serving the part '
    + '(tools, stations, gauges, packaging) answer "no impact" or "impact". '
    + 'All "no impact" activates the index; any impact is escalated to a full ECR.',
  administrative: 'Activates the index now, no change. Only for content-free updates '
    + '(title block, re-upload, renamed file). A reason is required and audited.',
};

/** Why a route is suggested, by the snapshot taken at receipt (spec §17a). */
export function suggestionReason(i: Pick<Intake, 'suggested_route' | 'revision_phase' | 'part_phase' | 'active_revision_name'>): string {
  switch (i.suggested_route) {
    case 'administrative': return 'First data on a part still in RFQ';
    case 'full_ecr': return i.part_phase === 'series' ? 'The part is in series' : 'Official customer data';
    case 'engineering_review': return 'Review data (E level) before series';
    default: return '';
  }
}

export const PHASE_LABELS: Record<string, string> = {
  review: 'review data', official: 'official data',
  rfq: 'RFQ', nominated: 'nominated', dfm: 'DFM', preseries: 'preseries', series: 'series',
};

/** The short text a pending revision carries on chips (timeline, project tree). */
export function pendingChipText(i: Pick<Intake, 'needs_triage' | 'change_number'>): string {
  if (i.needs_triage) return 'pending triage'
  if (i.change_number) return `pending, ${i.change_number}`
  return 'pending'
}
