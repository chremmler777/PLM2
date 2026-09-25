import { toast } from 'sonner';

/**
 * Safe extraction of a human-readable message from an axios/FastAPI error.
 *
 * FastAPI returns `detail` as a plain string for HTTPException, but as an ARRAY
 * of error objects ({type, loc, msg, ...}) for request-validation (422) errors.
 * Passing that array straight to toast.error() makes React try to render an
 * object as a child and crashes the whole app (the Toaster lives at the root).
 * Some endpoints send a structured detail with a `message` (plus a code or a
 * blocker list); that message is used too. This helper always returns a string.
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

  if (detail && typeof detail === 'object') {
    if ('msg' in detail) return String((detail as { msg: unknown }).msg);
    const message = (detail as { message?: unknown }).message;
    if (typeof message === 'string' && message.trim()) return message;
  }

  return fallback;
}

/**
 * Show an API failure as an error toast: the backend's reason when it sent
 * one, else `fallback`. Always a string, so a 422 array never reaches the
 * Toaster. Returns the message shown (handy for inline error text too).
 *
 * Fallbacks name the action that failed ("Could not send the offer"),
 * never "Failed" or "Request failed".
 */
export function toastError(e: unknown, fallback: string): string {
  const msg = apiErrorMessage(e, fallback);
  toast.error(msg);
  return msg;
}
