/**
 * Words, labels and links for the worksheet audit log (the part changelog of
 * the project's parts, backend services/worksheet_audit.py). Field labels
 * come from the column registry, so the log names a field as its column does.
 */
import { API_BASE_URL } from '../../api/client';
import type { AuditGroup, WorksheetAuditEntry, WorksheetAuditFilters } from '../../api/worksheet';
import { auditParams } from '../../api/worksheet';
import { FOCUS_PARAM } from '../../hooks/useFieldFocus';
import { FLAG_LABELS, FLAGS } from '../../lib/fieldNotes';
import type { FieldFlag } from '../../api/fieldNotes';
import { WORKSHEET_COLUMNS, type WorksheetColumn } from './worksheetColumns';

export const AUDIT_GROUPS: AuditGroup[] = ['comments', 'flags', 'material', 'values', 'other'];

export const AUDIT_GROUP_LABELS: Record<AuditGroup, string> = {
  comments: 'Comment', flags: 'Flag', material: 'Material', values: 'Value', other: 'Other',
};

export const AUDIT_GROUP_BADGE: Record<AuditGroup, string> = {
  comments: 'bg-sky-500/20 text-sky-200',
  flags: 'bg-yellow-500/20 text-yellow-200',
  material: 'bg-violet-500/20 text-violet-200',
  values: 'bg-emerald-500/20 text-emerald-200',
  other: 'bg-slate-600/40 text-slate-300',
};

/** Note keys a column shows under another column key (Colour: paint colour or the article's MIC colour code). */
const KEY_ALIASES: Record<string, string> = { 'part.colour_code': 'part.colour', 'paint.colour': 'part.colour' };

function columnFor(fieldKey: string | null): WorksheetColumn | undefined {
  if (!fieldKey) return undefined;
  const key = KEY_ALIASES[fieldKey] ?? fieldKey;
  return WORKSHEET_COLUMNS.find((c) => c.key === key);
}

export function auditFieldLabel(fieldKey: string | null): string {
  return columnFor(fieldKey)?.label ?? fieldKey ?? '';
}

const ACTION_TEXT: Record<string, string> = {
  field_comment_added: 'Commented',
  material_set: 'Material changed',
  material_refreshed: 'Material refreshed',
  metadata_updated: 'Value changed',
  field_updated: 'Value changed',
  renumbered: 'Renumbered',
  lifecycle_phase: 'Phase changed',
  paint_updated: 'Paint changed',
  dfm_topic_opened: 'DFM topic opened',
  dfm_topic_closed: 'DFM topic closed',
  dfm_topic_reopened: 'DFM topic reopened',
  dfm_entry_recorded: 'DFM entry recorded',
};

const isFlag = (v: string | null): v is FieldFlag => !!v && (FLAGS as string[]).includes(v);

export function auditActionText(e: WorksheetAuditEntry): string {
  if (e.action === 'field_flag_set') {
    return isFlag(e.new_value) ? `Flag set to ${FLAG_LABELS[e.new_value]}` : 'Flag cleared';
  }
  return ACTION_TEXT[e.action] ?? e.action.replace(/_/g, ' ');
}

export function excerpt(text: string | null, max: number): string {
  if (!text) return '';
  return text.length > max ? `${text.slice(0, max - 3).trimEnd()}...` : text;
}

const VALUE_EXCERPT = 60;

/** "old -> new" for value, material and flag changes; comments and events have none. */
export function auditValueChange(e: WorksheetAuditEntry): string {
  if (e.action === 'field_comment_added' || e.action_group === 'comments' || e.action_group === 'other') return '';
  if (e.old_value === null && e.new_value === null) return '';
  return `${excerpt(e.old_value, VALUE_EXCERPT) || 'none'} -> ${excerpt(e.new_value, VALUE_EXCERPT) || 'none'}`;
}

/**
 * Where the cell menu's Edit would go for this field: the part holding the
 * value with the field in focus; the part page where the field is not
 * edited on a page (or the entry names no field).
 */
export function auditEditPath(e: WorksheetAuditEntry): string {
  const col = columnFor(e.field_key);
  if (!col || !col.editableOn || !e.field_key) return `/parts/${e.part.id}`;
  return `/parts/${e.part.id}?${FOCUS_PARAM}=${encodeURIComponent(e.field_key)}`;
}

/** A plain link (the session cookie authenticates it), under the app's API base so it works below /plm2. */
export function worksheetAuditCsvUrl(projectId: number, filters: WorksheetAuditFilters): string {
  const params = new URLSearchParams(Object.entries(auditParams(filters)).map(([k, v]) => [k, String(v)])).toString();
  return `${API_BASE_URL}/v1/projects/${projectId}/worksheet/audit.csv${params ? `?${params}` : ''}`;
}
