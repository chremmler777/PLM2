/**
 * The worksheet's column registry. key is the field_key used by field notes
 * (backend rule: <group>.<field>, lower case), so a comment or flag set in
 * the worksheet is the same note the article, tool and paint pages show.
 * Values are only read here; edit() says where the value is changed. A
 * column whose value lives in different places per row (Colour: the paint on
 * a painted article, the article's colour code otherwise) names the note key
 * per row with noteKey(); the column key then only identifies the column.
 */
import { PARTY_LABELS } from '../../api/dfm';
import type { FieldNoteSummary } from '../../api/fieldNotes';
import type { WorksheetDfm, WorksheetRow } from '../../api/worksheet';
import { fieldKeyAllowed, noteKey } from '../../lib/fieldNotes';
import { materialText } from '../../lib/material';
import { shortName } from '../../lib/partDisplay';

export type ColumnGroup = 'Identity' | 'Revision' | 'Material' | 'Paint' | 'Tool' | 'DFM' | 'Notes';
export type CellDisplay = 'thumbnail' | 'text' | 'mono' | 'number' | 'revision' | 'material' | 'colour' | 'dfm' | 'notes';

export interface WorksheetContext {
  byKey: Map<string, FieldNoteSummary>;
  byPart: Map<number, FieldNoteSummary[]>;
  projectCode: string | null;
}

export interface EditTarget {
  partId: number;
  focus: string;
}

export interface WorksheetColumn {
  key: string;
  label: string;
  group: ColumnGroup;
  filter: 'text' | 'enum' | 'none';
  exportType: 'text' | 'number';
  display: CellDisplay;
  noteOwner: 'row' | 'tool' | null;
  editableOn: 'article' | 'tool' | 'paint' | null;
  defaultVisible: boolean;
  frozenWidth?: number;
  value(row: WorksheetRow, ctx: WorksheetContext): string | number | null;
  /** Tooltip when the shown value is shortened. */
  title?(row: WorksheetRow): string | null;
  edit(row: WorksheetRow): EditTarget | null;
  /** The field key of this row's note when it is not the column key; null: no note on this row. */
  noteKey?(row: WorksheetRow): string | null;
}

export function buildContext(notes: FieldNoteSummary[] | undefined, projectCode: string | null = null): WorksheetContext {
  const byKey = new Map<string, FieldNoteSummary>();
  const byPart = new Map<number, FieldNoteSummary[]>();
  for (const n of Array.isArray(notes) ? notes : []) {
    byKey.set(noteKey(n.part_id, n.field_key), n);
    byPart.set(n.part_id, [...(byPart.get(n.part_id) ?? []), n]);
  }
  return { byKey, byPart, projectCode };
}

const TOOL_KEY = /^(tool|dfm)\./;

/** The field key a cell's note uses on this row (the same key the article, tool and paint pages show), or null. */
export function cellNoteKey(col: WorksheetColumn, row: WorksheetRow): string | null {
  return col.noteKey ? col.noteKey(row) : col.key;
}

/** The part a cell's note lives on, or null where the backend would refuse the field key for that part. */
export function notePartId(col: WorksheetColumn, row: WorksheetRow): number | null {
  const key = cellNoteKey(col, row);
  if (key === null) return null;
  if (col.noteOwner === 'row') return fieldKeyAllowed(key, row.item_category) ? row.part_id : null;
  if (col.noteOwner === 'tool') return row.tool && fieldKeyAllowed(key, 'tool') ? row.tool.part_id : null;
  return null;
}

/**
 * The active key's own note: what its marker's popover opens (a comment/flag write always targets
 * this key) and what the main marker's dot, count and tooltip show. Never the Colour column's
 * combined note - see noteFor for that.
 */
export function activeNoteFor(col: WorksheetColumn, row: WorksheetRow, ctx: WorksheetContext): FieldNoteSummary | undefined {
  const partId = notePartId(col, row);
  const key = cellNoteKey(col, row);
  return partId === null || key === null ? undefined : ctx.byKey.get(noteKey(partId, key));
}

/**
 * The note driving a cell's tint and export flag/comment count (and the CSV/data-flag attribute).
 * For the Colour column this is the combined note of both possible keys (part.colour_code and
 * paint.colour), so a note on the key the cell is not currently showing still tints the cell and
 * counts toward the export - see otherColourKey. Never used for a marker's own popover: a flag or
 * comment written from a marker must land on the key whose thread it opened, so a marker's `note`
 * prop and a menu's current flag must come from activeNoteFor, not this combined one.
 */
export function noteFor(col: WorksheetColumn, row: WorksheetRow, ctx: WorksheetContext): FieldNoteSummary | undefined {
  const primary = activeNoteFor(col, row, ctx);
  if (col.key !== 'part.colour') return primary;
  const partId = notePartId(col, row);
  const otherKey = otherColourKey(row);
  const other = partId !== null && otherKey ? ctx.byKey.get(noteKey(partId, otherKey)) : undefined;
  return combineNotes(primary, other);
}

/** Where a row's colour comes from: the paint (painted), the article's MIC colour code, or nowhere. */
export function colourSource(row: WorksheetRow): 'paint' | 'mic' | null {
  if (row.paint.painted) return row.paint.colour || row.paint.paint_system ? 'paint' : null;
  return row.colour_code ? 'mic' : null;
}

function colourValue(row: WorksheetRow): string | null {
  switch (colourSource(row)) {
    case 'paint': return [row.paint.colour, row.paint.paint_system].filter(Boolean).join(' / ');
    case 'mic': return row.colour_code;
    default: return null;
  }
}

/** Painted rows keep the paint section's key; unpainted rows the article's colour code. */
const colourKey = (row: WorksheetRow): string | null =>
  row.row_kind === 'tool_only' ? null : row.paint.painted ? 'paint.colour' : 'part.colour_code';

/** The colour key not currently shown: the article's colour code on a painted row, the paint on an unpainted row. */
export const otherColourKey = (row: WorksheetRow): string | null =>
  row.row_kind === 'tool_only' ? null : row.paint.painted ? 'part.colour_code' : 'paint.colour';

const FLAG_RANK: Record<string, number> = { open: 0, rejected: 1, confirmed: 2 };

/** The more attention-worthy of two flags: open, then rejected, then confirmed, then none. */
function worseFlag(a: FieldNoteSummary['flag_status'], b: FieldNoteSummary['flag_status']): FieldNoteSummary['flag_status'] {
  const ra = a ? FLAG_RANK[a] : 3;
  const rb = b ? FLAG_RANK[b] : 3;
  return ra <= rb ? (a ?? null) : (b ?? null);
}

/** Merges the notes of the Colour cell's two possible keys: the worst flag, the total comment count. */
function combineNotes(primary: FieldNoteSummary | undefined, other: FieldNoteSummary | undefined): FieldNoteSummary | undefined {
  if (!primary && !other) return undefined;
  const base = primary ?? other!;
  return { ...base, flag_status: worseFlag(primary?.flag_status ?? null, other?.flag_status ?? null),
    comment_count: (primary?.comment_count ?? 0) + (other?.comment_count ?? 0) };
}

const articleOnlyKey = (key: string) => (row: WorksheetRow): string | null => (row.row_kind === 'tool_only' ? null : key);

/** The row's own notes plus its tool's tool./dfm. notes. */
export function rowNotes(row: WorksheetRow, ctx: WorksheetContext): FieldNoteSummary[] {
  const own = ctx.byPart.get(row.part_id) ?? [];
  const toolId = row.tool?.part_id;
  const fromTool = toolId !== undefined && toolId !== row.part_id
    ? (ctx.byPart.get(toolId) ?? []).filter((n) => TOOL_KEY.test(n.field_key))
    : [];
  return [...own, ...fromTool];
}

const EXCERPT = 40;

export function notesSummary(row: WorksheetRow, ctx: WorksheetContext): string | null {
  const notes = rowNotes(row, ctx);
  const open = notes.filter((n) => n.flag_status === 'open').length;
  const last = notes
    .map((n) => n.last_comment)
    .filter((c): c is NonNullable<FieldNoteSummary['last_comment']> => !!c)
    .sort((a, b) => b.created_at.localeCompare(a.created_at))[0];
  const parts: string[] = [];
  if (open) parts.push(`${open} open`);
  if (last) parts.push(last.body.length > EXCERPT ? `${last.body.slice(0, EXCERPT - 3).trimEnd()}...` : last.body);
  return parts.length ? parts.join(' · ') : null;
}

export function dfmLabel(dfm: WorksheetDfm | null): string | null {
  if (!dfm) return null;
  switch (dfm.status) {
    case 'waiting': return `Waiting on ${dfm.waiting_on.map((p) => PARTY_LABELS[p]).join(', ')}`;
    case 'all_answered': return 'All answered';
    case 'no_topic': return 'No topic';
    case 'finished': return 'Finished';
    default: return 'Open';
  }
}

const onRow = (key: string) => (row: WorksheetRow): EditTarget => ({ partId: row.part_id, focus: key });
const onArticle = (key: string) => (row: WorksheetRow): EditTarget | null =>
  row.row_kind === 'tool_only' ? null : { partId: row.part_id, focus: key };
const onTool = (key: string) => (row: WorksheetRow): EditTarget | null =>
  row.tool ? { partId: row.tool.part_id, focus: key } : null;
const nowhere = (): EditTarget | null => null;

type Def = Omit<WorksheetColumn, 'defaultVisible' | 'exportType' | 'display' | 'filter'>
  & Partial<Pick<WorksheetColumn, 'defaultVisible' | 'exportType' | 'display' | 'filter'>>;

const def = (d: Def): WorksheetColumn => ({
  defaultVisible: true, exportType: 'text', display: 'text', filter: 'text', ...d,
});

export const WORKSHEET_COLUMNS: WorksheetColumn[] = [
  def({ key: 'part.thumbnail', label: 'Image', group: 'Identity', display: 'thumbnail', filter: 'none',
    noteOwner: null, editableOn: null, frozenWidth: 44, value: () => null, edit: nowhere }),
  def({ key: 'part.part_number', label: 'KTX no.', group: 'Identity', display: 'mono', noteOwner: 'row',
    editableOn: 'article', frozenWidth: 170, value: (r) => r.part_number, edit: onRow('part.part_number') }),
  def({ key: 'part.customer_part_number', label: 'OEM no.', group: 'Identity', display: 'mono', noteOwner: 'row',
    editableOn: 'article', frozenWidth: 170, value: (r) => r.customer_part_number, edit: onArticle('part.customer_part_number') }),
  def({ key: 'part.tier1_part_number', label: 'Tier 1 no.', group: 'Identity', display: 'mono', noteOwner: 'row',
    editableOn: 'article', value: (r) => r.tier1_part_number, edit: onArticle('part.tier1_part_number') }),
  def({ key: 'part.name', label: 'Name', group: 'Identity', noteOwner: 'row', editableOn: 'article',
    value: (r, ctx) => shortName(r.name, ctx.projectCode, r.customer_part_number), title: (r) => r.name,
    edit: onRow('part.name') }),
  def({ key: 'part.part_type', label: 'Type', group: 'Identity', filter: 'enum', noteOwner: 'row', editableOn: 'article',
    value: (r) => r.part_type.replace(/_/g, ' '), edit: onArticle('part.part_type') }),
  def({ key: 'part.mirror_of', label: 'Mirror of', group: 'Identity', display: 'mono', noteOwner: 'row', editableOn: null,
    defaultVisible: false, value: (r) => r.mirror_of ? (r.mirror_of.customer_part_number ?? r.mirror_of.part_number) : null,
    edit: nowhere }),
  def({ key: 'revision.level', label: 'E level', group: 'Revision', display: 'revision', noteOwner: 'row', editableOn: 'article',
    value: (r) => r.revision ? `${r.revision.revision_name}${r.revision.customer_index ? ` · ${r.revision.customer_index}` : ''}` : null,
    edit: onArticle('revision.level') }),
  def({ key: 'part.lifecycle_phase', label: 'Phase', group: 'Revision', filter: 'enum', noteOwner: 'row', editableOn: 'article',
    value: (r) => r.lifecycle_phase, edit: onRow('part.lifecycle_phase') }),
  def({ key: 'part.material', label: 'Material', group: 'Material', display: 'material', noteOwner: 'row', editableOn: 'article',
    value: (r) => materialText(r.material), edit: onArticle('part.material') }),
  def({ key: 'paint.painted', label: 'Painted', group: 'Paint', filter: 'enum', noteOwner: 'row', editableOn: 'paint',
    value: (r) => r.row_kind === 'tool_only' ? null : (r.paint.painted ? 'yes' : 'no'), edit: onArticle('paint.painted') }),
  // Painted: the paint colour / system (edited in the paint section); unpainted: the MIC colour code on the article.
  def({ key: 'part.colour', label: 'Colour', group: 'Paint', display: 'colour', noteOwner: 'row', editableOn: 'article',
    value: colourValue, noteKey: colourKey,
    edit: (r) => (r.row_kind === 'tool_only' ? null : { partId: r.part_id, focus: colourKey(r)! }) }),
  def({ key: 'part.grain', label: 'Grain', group: 'Material', noteOwner: 'row', editableOn: 'article',
    value: (r) => r.grain, noteKey: articleOnlyKey('part.grain'), edit: onArticle('part.grain') }),
  def({ key: 'tool.number', label: 'Tool no.', group: 'Tool', display: 'mono', noteOwner: 'tool', editableOn: 'tool',
    value: (r) => r.tool ? [r.tool.part_number, ...r.other_tools].join(', ') : null, edit: onTool('tool.number') }),
  def({ key: 'tool.cavities', label: 'Cavities', group: 'Tool', display: 'number', exportType: 'number', noteOwner: 'tool',
    editableOn: 'tool', value: (r) => r.tool?.cavities ?? null, edit: onTool('tool.cavities') }),
  def({ key: 'tool.toolmaker', label: 'Toolmaker', group: 'Tool', filter: 'enum', noteOwner: 'tool', editableOn: 'tool',
    value: (r) => r.tool?.toolmaker_name ?? null, edit: onTool('tool.toolmaker') }),
  def({ key: 'tool.cycle_time_s', label: 'Cycle time (s)', group: 'Tool', display: 'number', exportType: 'number',
    noteOwner: 'tool', editableOn: 'tool', value: (r) => r.tool?.cycle_time_s ?? null, edit: onTool('tool.cycle_time_s') }),
  def({ key: 'tool.tonnage_class', label: 'Tonnage (t)', group: 'Tool', display: 'number', exportType: 'number',
    noteOwner: 'tool', editableOn: 'tool', defaultVisible: false, value: (r) => r.tool?.tonnage_class ?? null,
    edit: onTool('tool.tonnage_class') }),
  def({ key: 'dfm.status', label: 'DFM', group: 'DFM', display: 'dfm', filter: 'enum', noteOwner: 'tool', editableOn: 'tool',
    value: (r) => dfmLabel(r.dfm), edit: onTool('dfm.status') }),
  def({ key: 'notes.summary', label: 'Notes', group: 'Notes', display: 'notes', noteOwner: null, editableOn: null,
    value: (r, ctx) => notesSummary(r, ctx), edit: nowhere }),
];
