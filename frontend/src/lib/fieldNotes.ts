/** Flag colours, lookup keys and popover placement for field notes. */
import type { FieldFlag, FieldNoteSummary } from '../api/fieldNotes';

export const FLAGS: FieldFlag[] = ['open', 'confirmed', 'rejected'];
export const FLAG_LABELS: Record<FieldFlag, string> = { open: 'Open', confirmed: 'Confirmed', rejected: 'Rejected' };
export const FLAG_DOT: Record<FieldFlag, string> = { open: 'bg-yellow-400', confirmed: 'bg-emerald-500', rejected: 'bg-red-500' };
export const FLAG_TINT: Record<FieldFlag, string> = { open: 'bg-yellow-500/20', confirmed: 'bg-emerald-500/20', rejected: 'bg-red-500/25' };
export const FLAG_BUTTON: Record<FieldFlag, string> = {
  open: 'border-yellow-400 bg-yellow-500/20 text-yellow-200',
  confirmed: 'border-emerald-500 bg-emerald-500/20 text-emerald-200',
  rejected: 'border-red-500 bg-red-500/20 text-red-200',
};

/** Same rule as the backend (field_note_service.FIELD_KEY_RE). */
export const FIELD_KEY_RE = /^[a-z][a-z0-9_]{0,30}\.[a-z][a-z0-9_]{0,30}$/;

/** Same limit as the backend (field_note_service.MAX_COMMENT_LENGTH). */
export const MAX_COMMENT_LENGTH = 4000;

const TOOL_ONLY_PREFIXES = ['tool', 'dfm'];
const NOT_ON_TOOL_PREFIXES = ['paint', 'revision'];

/** Same rule as the backend (field_note_service.check_field_key): tool. and dfm. only on tools, paint. and revision. never on tools. */
export function fieldKeyAllowed(fieldKey: string, itemCategory: string | null | undefined): boolean {
  const prefix = fieldKey.split('.', 1)[0];
  const isTool = itemCategory === 'tool';
  if (TOOL_ONLY_PREFIXES.includes(prefix)) return isTool;
  if (NOT_ON_TOOL_PREFIXES.includes(prefix)) return !isTool;
  return true;
}

const pad = (n: number) => String(n).padStart(2, '0');

/** The backend sends naive UTC ("2026-09-24T14:54:27"): read it as UTC, whatever offset marker it has or lacks. */
function parseUtc(iso: string): Date | null {
  const d = new Date(/(Z|[+-]\d{2}:?\d{2})$/.test(iso) ? iso : `${iso}Z`);
  return Number.isNaN(d.getTime()) ? null : d;
}

/** "2026-09-24" in the viewer's local time. */
export function localDate(iso: string): string {
  const d = parseUtc(iso);
  return d ? `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}` : iso;
}

/** "2026-09-24 16:54" in the viewer's local time. */
export function localDateTime(iso: string): string {
  const d = parseUtc(iso);
  return d ? `${localDate(iso)} ${pad(d.getHours())}:${pad(d.getMinutes())}` : iso;
}

export function flagTint(flag: FieldFlag | null | undefined): string {
  return flag ? FLAG_TINT[flag] : '';
}

export function noteKey(partId: number, fieldKey: string): string {
  return `${partId}:${fieldKey}`;
}

export function indexByField(notes: FieldNoteSummary[] | undefined): Map<string, FieldNoteSummary> {
  const map = new Map<string, FieldNoteSummary>();
  for (const n of notes ?? []) map.set(n.field_key, n);
  return map;
}

const VIEWPORT_MARGIN = 8;

/** Keep a fixed-position menu on screen: flip to the other side of the click point when there is no room, then clamp. */
export function clampMenuPosition(
  x: number, y: number, size: { width: number; height: number }, viewport: { width: number; height: number },
): { top: number; left: number } {
  let left = x;
  let top = y;
  if (left + size.width > viewport.width - VIEWPORT_MARGIN) left = x - size.width;
  if (top + size.height > viewport.height - VIEWPORT_MARGIN) top = y - size.height;
  left = Math.max(VIEWPORT_MARGIN, Math.min(left, viewport.width - size.width - VIEWPORT_MARGIN));
  top = Math.max(VIEWPORT_MARGIN, Math.min(top, viewport.height - size.height - VIEWPORT_MARGIN));
  return { top, left };
}

export const POPOVER_SIZE = { width: 320, height: 360 };

/** Below the anchor, above it when there is no room, never past the right edge. */
export function popoverPosition(
  rect: { top: number; bottom: number; left: number; right: number },
  viewport: { width: number; height: number },
  size: { width: number; height: number } = POPOVER_SIZE,
): { top: number; left: number } {
  let top = rect.bottom + 4;
  if (top + size.height > viewport.height) top = Math.max(4, rect.top - size.height - 4);
  const left = Math.max(8, Math.min(rect.left, viewport.width - size.width - 8));
  return { top, left };
}
