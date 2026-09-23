/**
 * DFM archive API: topics per tool, three-column ledger entries with files.
 * Mirrors backend/app/api/v1/items/dfm.py.
 */
import client, { API_BASE_URL } from './client';

export type DfmParty = 'toolmaker' | 'ktx' | 'tier1';
export const PARTIES: DfmParty[] = ['toolmaker', 'ktx', 'tier1'];
export const PARTY_LABELS: Record<DfmParty, string> = { toolmaker: 'Toolmaker', ktx: 'KTX', tier1: 'Tier 1' };

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
}

export interface DfmTopicDetail extends DfmTopicSummary {
  entries: DfmEntry[];
}

export interface DfmEntryInput {
  party: DfmParty;
  addressed_to: DfmParty[];
  note: string;
  sent_at: string;
  supersedes_id: number | null;
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
