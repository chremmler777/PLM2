/**
 * localStorage (or, when asked, sessionStorage) that never throws. Private windows, blocked site data and full
 * quotas make the Storage API throw; a remembered layout choice is a
 * convenience, so every failure falls back to the caller's default.
 */

export type StorageArea = 'local' | 'session';

// Resolved inside the callers' try: merely touching window.localStorage throws
// when site data is blocked.
function storageFor(area: StorageArea): Storage {
  return area === 'session' ? window.sessionStorage : window.localStorage;
}

export function readStored(key: string, area: StorageArea = 'local'): string | null {
  try {
    return storageFor(area).getItem(key);
  } catch {
    return null;
  }
}

export function writeStored(key: string, value: string, area: StorageArea = 'local'): void {
  try {
    storageFor(area).setItem(key, value);
  } catch {
    // Storage unavailable: the in-memory state still applies for this visit.
  }
}

/** A stored number clamped to [min, max]; the fallback when missing or not a number. */
export function readStoredNumber(key: string, fallback: number, min: number, max: number): number {
  const raw = readStored(key);
  const n = raw === null || raw.trim() === '' ? NaN : Number(raw);
  if (!Number.isFinite(n)) return fallback;
  return Math.round(Math.min(max, Math.max(min, n)));
}
