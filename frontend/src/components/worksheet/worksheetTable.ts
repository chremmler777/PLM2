/** Pure worksheet table logic: row kinds, filters, sort, hidden columns, frozen offsets. */
import type { WorksheetExportPayload, WorksheetRow } from '../../api/worksheet';
import { comparePartNumbers } from '../../lib/partDisplay';
import { readStored, writeStored } from '../../lib/safeStorage';
import { WORKSHEET_COLUMNS, noteFor, rowNotes, type WorksheetColumn, type WorksheetContext } from './worksheetColumns';

export const HIDDEN_COLUMNS_KEY = 'plm2.worksheet.hiddenColumns';

export type SortState = { key: string; dir: 'asc' | 'desc' };
export type RowKindFilter = { purchased: boolean; toolOnly: boolean };

const DEFAULT_HIDDEN = () => new Set(WORKSHEET_COLUMNS.filter((c) => !c.defaultVisible).map((c) => c.key));

export function loadHiddenColumns(): Set<string> {
  const raw = readStored(HIDDEN_COLUMNS_KEY);
  if (raw === null) return DEFAULT_HIDDEN();
  try {
    const parsed: unknown = JSON.parse(raw);
    if (Array.isArray(parsed) && parsed.every((k) => typeof k === 'string')) return new Set(parsed);
  } catch {
    // corrupt value: defaults below
  }
  return DEFAULT_HIDDEN();
}

export function saveHiddenColumns(hidden: Set<string>): void {
  writeStored(HIDDEN_COLUMNS_KEY, JSON.stringify([...hidden]));
}

export function visibleColumns(hidden: Set<string>): WorksheetColumn[] {
  return WORKSHEET_COLUMNS.filter((c) => !hidden.has(c.key));
}

export function rowKindVisible(row: WorksheetRow, kinds: RowKindFilter): boolean {
  if (row.row_kind === 'purchased') return kinds.purchased;
  if (row.row_kind === 'tool_only') return kinds.toolOnly;
  return true;
}

/** Empty values last; numbers numerically; text with embedded numbers naturally. */
export function compareValues(a: string | number | null, b: string | number | null): number {
  const ea = a === null || a === '';
  const eb = b === null || b === '';
  if (ea || eb) return ea === eb ? 0 : ea ? 1 : -1;
  if (typeof a === 'number' && typeof b === 'number') return a - b;
  return String(a).localeCompare(String(b), undefined, { numeric: true, sensitivity: 'base' });
}

export function applyFilters(
  rows: WorksheetRow[], cols: WorksheetColumn[], filters: Record<string, string>,
  ctx: WorksheetContext, onlyOpenFlags: boolean,
): WorksheetRow[] {
  const active = cols
    .map((c) => ({ c, f: (filters[c.key] ?? '').trim() }))
    .filter(({ c, f }) => f !== '' && c.filter !== 'none');
  return rows.filter((row) => {
    if (onlyOpenFlags && !rowNotes(row, ctx).some((n) => n.flag_status === 'open')) return false;
    return active.every(({ c, f }) => {
      const v = c.value(row, ctx);
      const text = v === null ? '' : String(v);
      return c.filter === 'enum' ? text === f : text.toLowerCase().includes(f.toLowerCase());
    });
  });
}

export function sortRows(
  rows: WorksheetRow[], col: WorksheetColumn | undefined, dir: 'asc' | 'desc', ctx: WorksheetContext,
): WorksheetRow[] {
  const out = [...rows];
  if (!col) return out.sort((x, y) => comparePartNumbers(x.part_number, y.part_number));
  const sign = dir === 'asc' ? 1 : -1;
  return out.sort((x, y) => {
    const vx = col.value(x, ctx);
    const vy = col.value(y, ctx);
    const emptyX = vx === null || vx === '';
    const emptyY = vy === null || vy === '';
    if (emptyX || emptyY) return compareValues(vx, vy); // empties stay last in both directions
    return sign * compareValues(vx, vy) || comparePartNumbers(x.part_number, y.part_number);
  });
}

export function enumOptions(col: WorksheetColumn, rows: WorksheetRow[], ctx: WorksheetContext): string[] {
  const values = new Set<string>();
  for (const r of rows) {
    const v = col.value(r, ctx);
    if (v !== null && v !== '') values.add(String(v));
  }
  return [...values].sort((x, y) => compareValues(x, y));
}

/** Enum choices for a column: the values of the rows every other filter leaves (Excel style), plus the current choice. */
export function filterOptions(
  col: WorksheetColumn, rows: WorksheetRow[], cols: WorksheetColumn[], filters: Record<string, string>,
  ctx: WorksheetContext, onlyOpenFlags: boolean,
): string[] {
  const others = Object.fromEntries(Object.entries(filters).filter(([key]) => key !== col.key));
  const options = enumOptions(col, applyFilters(rows, cols, others, ctx, onlyOpenFlags), ctx);
  const chosen = (filters[col.key] ?? '').trim();
  return chosen && !options.includes(chosen) ? [...options, chosen].sort((x, y) => compareValues(x, y)) : options;
}

/** The filters without enum values the rows no longer offer, so a stale choice cannot hide every row behind "All". */
export function offeredFilters(
  filters: Record<string, string>, cols: WorksheetColumn[], rows: WorksheetRow[], ctx: WorksheetContext,
): Record<string, string> {
  const out: Record<string, string> = {};
  for (const [key, value] of Object.entries(filters)) {
    const c = cols.find((x) => x.key === key);
    if (c?.filter === 'enum' && value !== '' && !enumOptions(c, rows, ctx).includes(value)) continue;
    out[key] = value;
  }
  return out;
}

/** What the xlsx gets: the visible columns (no images) and rows, in order, typed, with flags. */
export function buildExportPayload(
  cols: WorksheetColumn[], rows: WorksheetRow[], ctx: WorksheetContext,
): WorksheetExportPayload {
  const exported = cols.filter((c) => c.display !== 'thumbnail');
  return {
    columns: exported.map((c) => ({ key: c.key, label: c.label, type: c.exportType })),
    rows: rows.map((row) => ({
      cells: exported.map((c) => {
        const note = noteFor(c, row, ctx);
        return { value: c.value(row, ctx), flag: note?.flag_status ?? null, comments: note?.comment_count ?? 0 };
      }),
    })),
    frozen_columns: exported.filter((c) => c.frozenWidth).length,
  };
}

export function frozenOffsets(cols: WorksheetColumn[]): Map<string, number> {
  const out = new Map<string, number>();
  let left = 0;
  for (const c of cols) {
    if (!c.frozenWidth) continue;
    out.set(c.key, left);
    left += c.frozenWidth;
  }
  return out;
}
