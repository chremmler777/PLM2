/**
 * Part thumbnails: turning the server's thumbnail_url into a src the app can
 * load under /plm2, uploading a captured image, refreshing the queries that
 * carry thumbnail_url, and the once-per-session guard of the automatic 3D
 * snapshot.
 */
import type { QueryClient } from '@tanstack/react-query';
import client, { API_BASE_URL } from '../api/client';

/** A capture of the current 3D view, or null when nothing could be read. */
export type CaptureFn = () => Promise<Blob | null>;

/** The server answers /api/v1/...; the app reaches the API through API_BASE_URL (/plm2/api). */
export function thumbnailSrc(url: string | null | undefined): string | null {
  if (!url) return null;
  if (url.startsWith('/api/')) return `${API_BASE_URL}${url.slice('/api'.length)}`;
  return url;
}

export async function uploadThumbnail(partId: number, blob: Blob): Promise<unknown> {
  const ext = blob.type === 'image/webp' ? 'webp' : blob.type === 'image/jpeg' ? 'jpg' : 'png';
  const fd = new FormData();
  fd.append('file', blob, `thumbnail-${partId}.${ext}`);
  const res = await client.put(`/v1/parts/${partId}/thumbnail`, fd, { headers: { 'Content-Type': 'multipart/form-data' } });
  return res.data;
}

/** Parts lists, project structures and the part's own detail all carry thumbnail_url. */
export function invalidateThumbnailQueries(queryClient: QueryClient, partId: number): void {
  queryClient.invalidateQueries({ queryKey: ['parts'] });
  queryClient.invalidateQueries({ queryKey: ['project-structure'] });
  queryClient.invalidateQueries({
    predicate: (q) => q.queryKey[0] === 'part' && String(q.queryKey[1]) === String(partId),
  });
}

const autoCaptured = new Set<number>();

/** True the first time a part asks in this session; the automatic snapshot never runs twice. */
export function claimAutoCapture(partId: number): boolean {
  if (autoCaptured.has(partId)) return false;
  autoCaptured.add(partId);
  return true;
}

export function resetAutoCaptureForTests(): void {
  autoCaptured.clear();
}
