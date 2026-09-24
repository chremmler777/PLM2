/**
 * DFM archive API: topics per tool, a flow of messages (original, forward,
 * answer, question) between toolmaker, KTX and Tier 1, with files and the
 * derived answered / waiting state.
 * Mirrors backend/app/api/v1/items/dfm.py.
 */
import client, { API_BASE_URL } from './client';

export type DfmParty = 'toolmaker' | 'ktx' | 'tier1';
export const PARTIES: DfmParty[] = ['toolmaker', 'ktx', 'tier1'];
export const PARTY_LABELS: Record<DfmParty, string> = { toolmaker: 'Toolmaker', ktx: 'KTX', tier1: 'Tier 1' };

export type DfmKind = 'original' | 'forward' | 'answer' | 'question';
export const KINDS: DfmKind[] = ['original', 'forward', 'answer', 'question'];
export const KIND_LABELS: Record<DfmKind, string> = { original: 'Original', forward: 'Forward', answer: 'Answer', question: 'Question' };

export interface DfmAnsweredBy {
  party: DfmParty;
  entry_id: number;
  date: string;
}

export interface DfmAwaiting {
  party: DfmParty;
  days: number;
}

export interface DfmWaitingOn {
  party: DfmParty;
  count: number;
  oldest_days: number;
}

export interface DfmLastStep {
  kind: DfmKind;
  party: DfmParty;
  addressed_to: DfmParty[];
  date: string;
}

export interface DfmNextStep {
  entry_id: number;
  kind: DfmKind;
  from: DfmParty;
  to: DfmParty;
  days: number;
}

export interface DfmFile {
  id: number;
  entry_id: number;
  original_filename: string;
  file_size: number;
  content_type: string;
  uploaded_by: number;
  uploaded_by_name: string | null;
  uploaded_at: string;
}

export interface DfmEntry {
  id: number;
  topic_id: number;
  party: DfmParty;
  addressed_to: DfmParty[];
  note: string | null;
  kind: DfmKind;
  reply_to_id: number | null;
  answered_by: DfmAnsweredBy[];
  awaiting: DfmAwaiting[];
  sent_at: string | null;
  supersedes_id: number | null;
  recorded_by: number;
  recorded_by_name: string | null;
  recorded_at: string;
  files: DfmFile[];
  history: Omit<DfmEntry, 'history'>[];
}

export interface DfmTopicSummary {
  id: number;
  tool_part_id: number;
  title: string;
  status: 'open' | 'finished_confirmed';
  opened_by: number;
  opened_at: string;
  closed_by: number | null;
  closed_at: string | null;
  entry_count: number;
  last_activity: string;
  waiting_on: DfmWaitingOn[];
  last_step: DfmLastStep | null;
  all_answered: boolean;
}

export interface DfmTopicDetail extends DfmTopicSummary {
  next_step: DfmNextStep | null;
  entries: DfmEntry[];
}

export interface DfmEntryInput {
  party: DfmParty;
  addressed_to: DfmParty[];
  note: string;
  sent_at: string;
  supersedes_id: number | null;
  kind: DfmKind;
  reply_to_id: number | null;
  files: File[];
}

const base = (partId: number) => `/v1/parts/${partId}/dfm`;

export async function listTopics(partId: number): Promise<DfmTopicSummary[]> {
  return (await client.get(`${base(partId)}/topics`)).data;
}

export async function createTopic(partId: number, title: string): Promise<DfmTopicSummary> {
  return (await client.post(`${base(partId)}/topics`, { title })).data;
}

export async function getTopic(partId: number, topicId: number): Promise<DfmTopicDetail> {
  return (await client.get(`${base(partId)}/topics/${topicId}`)).data;
}

export async function closeTopic(partId: number, topicId: number): Promise<DfmTopicDetail> {
  return (await client.post(`${base(partId)}/topics/${topicId}/close`)).data;
}

export async function reopenTopic(partId: number, topicId: number): Promise<DfmTopicDetail> {
  return (await client.post(`${base(partId)}/topics/${topicId}/reopen`)).data;
}

export function buildEntryFormData(input: DfmEntryInput): FormData {
  const fd = new FormData();
  fd.append('party', input.party);
  fd.append('addressed_to', JSON.stringify(input.addressed_to));
  fd.append('note', input.note);
  if (input.sent_at) fd.append('sent_at', input.sent_at);
  if (input.supersedes_id != null) fd.append('supersedes_id', String(input.supersedes_id));
  fd.append('kind', input.kind);
  if (input.reply_to_id != null) fd.append('reply_to_id', String(input.reply_to_id));
  for (const f of input.files) fd.append('files', f);
  return fd;
}

export async function createEntry(partId: number, topicId: number, input: DfmEntryInput): Promise<DfmEntry> {
  return (await client.post(`${base(partId)}/topics/${topicId}/entries`, buildEntryFormData(input),
    { headers: { 'Content-Type': 'multipart/form-data' } })).data;
}

export function dfmFileUrl(partId: number, fileId: number, mode: 'download' | 'inline'): string {
  return `${API_BASE_URL}${base(partId)}/files/${fileId}/${mode}`;
}

export type DfmAuditAction =
  | 'topic_opened' | 'topic_closed' | 'topic_reopened'
  | 'entry_recorded' | 'entry_updated'
  | 'file_attached' | 'file_downloaded' | 'file_viewed';

export interface DfmAuditActor {
  id: number;
  name: string;
}

export interface DfmAuditTopicRef {
  id: number;
  title: string;
}

export interface DfmAuditEntryRef {
  id: number;
  kind: DfmKind;
  party: DfmParty;
}

export interface DfmAuditFileRef {
  id: number;
  filename: string;
}

export interface DfmAuditEvent {
  id: number;
  at: string;
  action: DfmAuditAction;
  actor: DfmAuditActor;
  topic: DfmAuditTopicRef | null;
  entry: DfmAuditEntryRef | null;
  file: DfmAuditFileRef | null;
  details: {
    title?: string;
    kind?: DfmKind;
    party?: DfmParty;
    addressed_to?: DfmParty[];
    reply_to_id?: number | null;
    note?: string | null;
    supersedes_id?: number | null;
    filename?: string;
    size?: number;
    content_type?: string;
    sha256?: string | null;
    backfilled?: boolean;
  };
}

export interface DfmAuditQuery {
  topicId?: number;
  action?: DfmAuditAction;
  limit?: number;
  beforeId?: number;
}

export async function getAudit(partId: number, query: DfmAuditQuery = {}): Promise<DfmAuditEvent[]> {
  const params: Record<string, string | number> = {};
  if (query.topicId != null) params.topic_id = query.topicId;
  if (query.action) params.action = query.action;
  if (query.limit != null) params.limit = query.limit;
  if (query.beforeId != null) params.before_id = query.beforeId;
  return (await client.get(`${base(partId)}/audit`, { params })).data;
}

export function dfmAuditCsvUrl(partId: number, topicId?: number | null): string {
  const qs = topicId != null ? `?topic_id=${topicId}` : '';
  return `${API_BASE_URL}${base(partId)}/audit.csv${qs}`;
}
