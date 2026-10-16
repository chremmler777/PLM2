/**
 * Moldflow timing per tool: one row per tool, MF version and (optional) cavity
 * layout with the inputs, step dates and an explicit status.
 * Mirrors backend/app/api/v1/items/moldflow.py.
 */
import client from './client';
import { shortName } from '../lib/partDisplay';

export type MfInputStatus = 'open' | 'in_progress' | 'ready' | 'n/a';
export type MfStatus =
  | 'not_started' | 'inputs_open' | 'ready_for_mf' | 'running' | 'received' | 'in_review'
  | 'sent_to_customer' | 'customer_feedback' | 'rework' | 'final';
export type MfDateKey =
  | 'mf_requested_on' | 'received_on' | 'ktx_review_on' | 'sent_customer_on' | 'customer_feedback_on' | 'final_on';

export const MF_STATUSES: MfStatus[] = [
  'not_started', 'inputs_open', 'ready_for_mf', 'running', 'received', 'in_review',
  'sent_to_customer', 'customer_feedback', 'rework', 'final',
];
export const MF_STATUS_LABELS: Record<MfStatus, string> = {
  not_started: 'Not started', inputs_open: 'Inputs open', ready_for_mf: 'Ready for MF', running: 'MF running',
  received: 'Received', in_review: 'KTX review', sent_to_customer: 'At customer',
  customer_feedback: 'Customer feedback', rework: 'Rework', final: 'Final',
};
export type MfTone = 'slate' | 'amber' | 'sky' | 'emerald';
/** amber: blocked or needs a decision; sky: under way; emerald: done or answered; slate: idle. */
export const MF_STATUS_TONE: Record<MfStatus, MfTone> = {
  not_started: 'slate', inputs_open: 'amber', ready_for_mf: 'sky', running: 'sky', received: 'sky',
  in_review: 'sky', sent_to_customer: 'sky', customer_feedback: 'emerald', rework: 'amber', final: 'emerald',
};
export const MF_INPUT_STATUSES: MfInputStatus[] = ['open', 'in_progress', 'ready', 'n/a'];
export const MF_INPUT_LABELS: Record<MfInputStatus, string> = {
  open: 'open', in_progress: 'in progress', ready: 'ready', 'n/a': 'n/a',
};
export const MF_DATES: { key: MfDateKey; label: string }[] = [
  { key: 'mf_requested_on', label: 'MF requested' },
  { key: 'received_on', label: 'Received' },
  { key: 'ktx_review_on', label: 'KTX review' },
  { key: 'sent_customer_on', label: 'Sent to customer' },
  { key: 'customer_feedback_on', label: 'Customer feedback' },
  { key: 'final_on', label: 'Final' },
];

export interface MoldflowRow {
  id: number;
  tool_part_id: number;
  version: string;
  cavity_layout: string | null;
  geometry_status: MfInputStatus;
  gate_status: MfInputStatus;
  udb_status: MfInputStatus;
  material_label: string | null;
  udb_source: string | null;
  mf_requested_on: string | null;
  received_on: string | null;
  ktx_review_on: string | null;
  sent_customer_on: string | null;
  customer_feedback_on: string | null;
  final_on: string | null;
  customer_feedback: string | null;
  status: MfStatus;
  /** What the dates and inputs point to; the stored status may differ (e.g. rework). */
  derived_status: MfStatus;
  blockers: string | null;
  owner: string | null;
  notes: string | null;
  source_ref: string | null;
  updated_at: string | null;
}

export interface MoldflowArticle {
  part_id: number;
  part_number: string;
  customer_part_number: string | null;
  tier1_part_number: string | null;
  name: string;
}

export interface MoldflowTool {
  tool: { part_id: number; part_number: string; name: string; cavities: string | null };
  articles: MoldflowArticle[];
  rows: MoldflowRow[];
  latest_id: number | null;
}

export interface ProjectMoldflow {
  project_id: number;
  tools: MoldflowTool[];
  can_edit: boolean;
}

export type MoldflowPatch = Partial<Omit<MoldflowRow, 'id' | 'tool_part_id' | 'derived_status' | 'updated_at'>>;

export const moldflowKey = (projectId: number) => ['moldflow', projectId] as const;

export async function getProjectMoldflow(projectId: number): Promise<ProjectMoldflow> {
  return (await client.get(`/v1/projects/${projectId}/moldflow`)).data;
}

export async function createMoldflow(toolId: number, body: MoldflowPatch): Promise<MoldflowRow> {
  return (await client.post(`/v1/parts/${toolId}/moldflow`, body)).data;
}

export async function updateMoldflow(rowId: number, body: MoldflowPatch): Promise<MoldflowRow> {
  return (await client.patch(`/v1/moldflow/${rowId}`, body)).data;
}

export async function deleteMoldflow(rowId: number): Promise<void> {
  await client.delete(`/v1/moldflow/${rowId}`);
}

/** "V3" for a tool whose highest version is V2. */
export function nextVersion(rows: MoldflowRow[]): string {
  const n = Math.max(0, ...rows.map((r) => Number((r.version.match(/\d+/) ?? ['0'])[0])));
  return `V${n + 1}`;
}

/** The latest recorded step: label and date, or null. */
export function lastStep(r: Pick<MoldflowRow, MfDateKey>): { label: string; on: string } | null {
  for (let i = MF_DATES.length - 1; i >= 0; i--) {
    const d = r[MF_DATES[i].key];
    if (d) return { label: MF_DATES[i].label, on: d };
  }
  return null;
}

/** Customer identity per the naming rule: "<Brose no.> / <Scout no.> <part name>", one per article. */
export function articleIdentity(a: MoldflowArticle, projectCode: string | null = null): string {
  const nos = [a.customer_part_number, a.tier1_part_number].filter(Boolean).join(' / ');
  return [nos || a.part_number, shortName(a.name, projectCode, a.customer_part_number)].filter(Boolean).join(' ');
}
