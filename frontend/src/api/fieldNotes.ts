/**
 * Field notes: comments and a flag per field of a part (article or tool).
 * Mirrors backend/app/api/v1/items/field_notes.py.
 */
import client from './client';

export type FieldFlag = 'open' | 'confirmed' | 'rejected';

export interface FieldNoteComment {
  id: number;
  body: string;
  author_id: number;
  author_name: string | null;
  created_at: string;
}

export interface FieldNoteSummary {
  id: number;
  part_id: number;
  field_key: string;
  flag_status: FieldFlag | null;
  flag_set_by: number | null;
  flag_set_by_name: string | null;
  flag_set_at: string | null;
  created_at: string | null;
  comment_count: number;
  last_comment: FieldNoteComment | null;
}

export interface FieldNoteThread extends Omit<FieldNoteSummary, 'id'> {
  id: number | null;
  comments: FieldNoteComment[];
}

const base = (partId: number, fieldKey: string) => `/v1/parts/${partId}/field-notes/${encodeURIComponent(fieldKey)}`;

export const listPartFieldNotes = async (partId: number): Promise<FieldNoteSummary[]> =>
  (await client.get(`/v1/parts/${partId}/field-notes`)).data;

export const getFieldNoteThread = async (partId: number, fieldKey: string): Promise<FieldNoteThread> =>
  (await client.get(base(partId, fieldKey))).data;

export const addFieldComment = async (partId: number, fieldKey: string, body: string): Promise<FieldNoteThread> =>
  (await client.post(`${base(partId, fieldKey)}/comments`, { body })).data;

export const setFieldFlag = async (partId: number, fieldKey: string, status: FieldFlag | null): Promise<FieldNoteThread> =>
  (await client.put(`${base(partId, fieldKey)}/flag`, { status })).data;

export const listProjectFieldNotes = async (projectId: number): Promise<FieldNoteSummary[]> =>
  (await client.get(`/v1/projects/${projectId}/field-notes`)).data;
