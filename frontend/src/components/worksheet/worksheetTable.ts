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
  if (!col) return groupByTool(out.sort((x, y) => comparePartNumbers(x.part_number, y.part_number)));
  const sign = dir === 'asc' ? 1 : -1;
  // On a tool column, ties stay together per tool, so the tool's articles stay one group.
  const byTool = (x: WorksheetRow, y: WorksheetRow) =>
    col.editableOn === 'tool' ? comparePartNumbers(x.tool?.part_number ?? '', y.tool?.part_number ?? '') : 0;
  return out.sort((x, y) => {
    const vx = col.value(x, ctx);
    const vy = col.value(y, ctx);
    const emptyX = vx === null || vx === '';
    const emptyY = vy === null || vy === '';
    if (emptyX || emptyY) return compareValues(vx, vy) || byTool(x, y); // empties stay last in both directions
    return sign * compareValues(vx, vy) || byTool(x, y) || comparePartNumbers(x.part_number, y.part_number);
  });
}

/** Articles made by the same tool next to each other, groups in the order of their first article. */
export function groupByTool(rows: WorksheetRow[]): WorksheetRow[] {
  const groups = new Map<number | string, WorksheetRow[]>();
  for (const r of rows) {
    const key = r.tool?.part_id ?? `row-${r.part_id}`;
    const g = groups.get(key);
    if (g) g.push(r); else groups.set(key, [r]);
  }
  return [...groups.values()].flat();
}

/**
 * Row spans for tool cells: consecutive rows of the same tool show a tool column once.
 * Key `${index}|${colKey}`: the first row of a run gets the run length, the rows it covers 0.
 * Absent: a plain cell.
 */
export function toolCellSpans(rows: WorksheetRow[], cols: WorksheetColumn[], ctx: WorksheetContext): Map<string, number> {
  const spans = new Map<string, number>();
  const toolCols = cols.filter((c) => c.editableOn === 'tool');
  let start = 0;
  while (start < rows.length) {
    const tool = rows[start].tool?.part_id;
    let end = start + 1;
    while (tool !== undefined && end < rows.length && rows[end].tool?.part_id === tool) end++;
    if (end - start > 1) {
      for (const c of toolCols) {
        // Only one cell when every row shows the same value (Tool no. can differ by a second tool).
        const first = String(c.value(rows[start], ctx));
        if (rows.slice(start + 1, end).some((r) => String(c.value(r, ctx)) !== first)) continue;
        spans.set(`${start}|${c.key}`, end - start);
        for (let i = start + 1; i < end; i++) spans.set(`${i}|${c.key}`, 0);
      }
    }
    start = end;
  }
  return spans;
}

/** Index of the rows that start a new tool group (for a divider line). */
export function toolGroupStarts(rows: WorksheetRow[]): Set<number> {
  const starts = new Set<number>();
  rows.forEach((r, i) => {
    if (i > 0 && (r.tool?.part_id === undefined || r.tool.part_id !== rows[i - 1].tool?.part_id)) starts.add(i);
  });
  return starts;
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

/**
 * What the xlsx gets: the visible columns and rows, in order, typed, with flags. A picture
 * column sends the row's part id (null without a picture); the backend places the image in the cell.
 */
export function buildExportPayload(
  cols: WorksheetColumn[], rows: WorksheetRow[], ctx: WorksheetContext,
): WorksheetExportPayload {
  const exported = cols;
  return {
    columns: exported.map((c) => ({ key: c.key, label: c.label, type: c.exportType })),
    rows: rows.map((row) => ({
      cells: exported.map((c) => {
        if (c.exportType === 'image') return { value: row.thumbnail_url ? row.part_id : null, flag: null, comments: 0 };
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
