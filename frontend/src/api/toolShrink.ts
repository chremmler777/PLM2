import client from './client';

export type ShrinkSourceKind = 'datasheet' | 'supplier' | 'ktx_experience' | 'own';
export type ShrinkVerdict = 'correct' | 'offset' | 'wrong';

export interface ShrinkCandidate {
  key: string;
  kind: Exclude<ShrinkSourceKind, 'own'>;
  materialdb_id: number;
  material_label: string;
  parallel_pct: number | null;
  normal_pct: number | null;
  parallel_text: string | null;
  normal_text: string | null;
  method: string | null;
  condition: string | null;
  source_label: string;
  doc_date: string | null;
  origin: string | null;
  verdict?: ShrinkVerdict | null;
}

export interface ShrinkDecision {
  id: number;
  status: 'current' | 'superseded';
  parallel_pct: number;
  normal_pct: number;
  source_kind: ShrinkSourceKind;
  source_label: string | null;
  materialdb_id: number | null;
  material_label: string | null;
  candidates: ShrinkCandidate[];
  rationale: string;
  decided_by: string | null;
  decided_at: string | null;
  measured_parallel_pct: number | null;
  measured_normal_pct: number | null;
  measured_ref: string | null;
  verdict: ShrinkVerdict | null;
  next_time_note: string | null;
  verified_by: string | null;
  verified_at: string | null;
  feedback_status: 'sent' | 'failed' | 'skipped' | null;
  feedback_error: string | null;
  feedback_at: string | null;
}

export interface ShrinkMaterial {
  materialdb_id: number;
  label: string | null;
  articles: string[];
  filler_type?: string | null;
  notes?: string | null;
}

export interface ToolShrinkage {
  tool: { parallel_pct: number | null; normal_pct: number | null };
  decisions: ShrinkDecision[];
  materials: ShrinkMaterial[];
  candidates: ShrinkCandidate[];
  error: string | null;
  no_material: boolean;
  no_article: boolean;
}

export interface DecideBody {
  parallel_pct: number;
  normal_pct: number;
  source_kind: ShrinkSourceKind;
  source_label: string | null;
  rationale: string;
  materialdb_id: number | null;
  material_label: string | null;
  candidates: ShrinkCandidate[];
}

export interface VerifyBody {
  measured_parallel_pct: number | null;
  measured_normal_pct: number | null;
  measured_ref: string;
  verdict: ShrinkVerdict;
  next_time_note: string | null;
}

export const fetchToolShrinkage = async (partId: number): Promise<ToolShrinkage> =>
  (await client.get(`/v1/parts/${partId}/shrinkage`)).data;

export const decideShrinkage = async (partId: number, body: DecideBody) =>
  (await client.post(`/v1/parts/${partId}/shrinkage/decisions`, body)).data;

export const verifyShrinkage = async (partId: number, decisionId: number, body: VerifyBody) =>
  (await client.post(`/v1/parts/${partId}/shrinkage/decisions/${decisionId}/verify`, body)).data;

export const reportShrinkage = async (partId: number, decisionId: number) =>
  (await client.post(`/v1/parts/${partId}/shrinkage/decisions/${decisionId}/report`)).data;
