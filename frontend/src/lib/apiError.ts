/**
 * Safe extraction of a human-readable message from an axios/FastAPI error.
 *
 * FastAPI returns `detail` as a plain string for HTTPException, but as an ARRAY
 * of error objects ({type, loc, msg, ...}) for request-validation (422) errors.
 * Passing that array straight to toast.error() makes React try to render an
 * object as a child and crashes the whole app (the Toaster lives at the root).
 * This helper always returns a string.
 */
export function apiErrorMessage(e: unknown, fallback = 'Request failed'): string {
  const detail = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;

  if (typeof detail === 'string' && detail.trim()) return detail;

  // 422 validation error: array of { msg, loc, ... }. Join the messages.
  if (Array.isArray(detail)) {
    const msgs = detail
      .map((d) => (d && typeof d === 'object' && 'msg' in d ? String((d as { msg: unknown }).msg) : null))
      .filter((m): m is string => !!m);
    if (msgs.length) return msgs.join('; ');
  }

  if (detail && typeof detail === 'object' && 'msg' in detail) {
    return String((detail as { msg: unknown }).msg);
  }

  return fallback;
}
