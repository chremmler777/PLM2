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
