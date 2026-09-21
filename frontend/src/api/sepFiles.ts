/**
 * Files on SEP work items — upload, list, remove, and the project-wide index
 * behind the Documents tab.
 */
import client, { API_BASE_URL } from './client';
import type { SepItemFile, SepProjectFilesGate } from '../types/sep';

/** One multipart request carries the whole drop; the field repeats per file. */
export const uploadItemFiles = async (itemId: number, files: File[]): Promise<SepItemFile[]> => {
  const form = new FormData();
  files.forEach((f) => form.append('files', f));
  // The shared client sets a global `Content-Type: application/json`; clearing
  // it here lets the browser write multipart/form-data WITH its boundary,
  // without which FastAPI never finds the `files` field (422).
  const res = await client.post(`/v1/sep/items/${itemId}/files`, form, {
    headers: { 'Content-Type': undefined },
  });
  return res.data;
};

export const listItemFiles = async (itemId: number): Promise<SepItemFile[]> => {
  const res = await client.get(`/v1/sep/items/${itemId}/files`);
  return res.data;
};

export const deleteItemFile = async (itemId: number, fileId: number): Promise<void> => {
  await client.delete(`/v1/sep/items/${itemId}/files/${fileId}`);
};

export const projectSepFiles = async (projectId: number): Promise<SepProjectFilesGate[]> => {
  const res = await client.get(`/v1/sep/projects/${projectId}/files`);
  return res.data;
};

/** Absolute href for an `<a download>`, same shape as the change attachments. */
export const itemFileDownloadUrl = (itemId: number, fileId: number): string =>
  `${API_BASE_URL}/v1/sep/items/${itemId}/files/${fileId}/download`;

/** Human size for a file row. */
export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}
