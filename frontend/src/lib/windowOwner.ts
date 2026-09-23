/**
 * An id for this browser tab, so a project window recognises its own pop-out
 * on the shared project channel and ignores the pop-out of another tab on the
 * same project. Kept in sessionStorage: it survives a reload of the tab, and
 * each tab has its own.
 */
import { readStored, writeStored } from './safeStorage';

const KEY = 'plm2.project.windowOwner';

// Used when sessionStorage is unavailable, so the id stays stable for this page.
let memo: string | null = null;

function newId(): string {
  // crypto.randomUUID needs a secure context; the app is also served over plain http.
  const random = Math.random().toString(36).slice(2, 10).padEnd(8, '0');
  return `${Date.now().toString(36)}-${random}`;
}

export function windowOwnerId(): string {
  const stored = readStored(KEY, 'session');
  if (stored) return stored;
  const id = memo ?? newId();
  memo = id;
  writeStored(KEY, id, 'session');
  return id;
}
