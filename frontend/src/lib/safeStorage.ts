/**
 * localStorage that never throws. Private windows, blocked site data and full
 * quotas make the Storage API throw; a remembered layout choice is a
 * convenience, so every failure falls back to the caller's default.
 */

export function readStored(key: string): string | null {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

export function writeStored(key: string, value: string): void {
  try {
    window.localStorage.setItem(key, value);
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
