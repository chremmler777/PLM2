/**
 * The worksheet's column registry. key is the field_key used by field notes
 * (backend rule: <group>.<field>, lower case), so a comment or flag set in
 * the worksheet is the same note the article, tool and paint pages show.
 * Values are only read here; edit() says where the value is changed.
 */
import { PARTY_LABELS } from '../../api/dfm';
import type { FieldNoteSummary } from '../../api/fieldNotes';
import type { WorksheetDfm, WorksheetRow } from '../../api/worksheet';
import { fieldKeyAllowed, noteKey } from '../../lib/fieldNotes';
import { materialText } from '../../lib/material';
import { shortName } from '../../lib/partDisplay';

export type ColumnGroup = 'Identity' | 'Revision' | 'Material' | 'Paint' | 'Tool' | 'DFM' | 'Notes';
export type CellDisplay = 'thumbnail' | 'text' | 'mono' | 'number' | 'revision' | 'material' | 'dfm' | 'notes';

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

/** The part a cell's note lives on, or null where the backend would refuse the field key for that part. */
export function notePartId(col: WorksheetColumn, row: WorksheetRow): number | null {
  if (col.noteOwner === 'row') return fieldKeyAllowed(col.key, row.item_category) ? row.part_id : null;
  if (col.noteOwner === 'tool') return row.tool && fieldKeyAllowed(col.key, 'tool') ? row.tool.part_id : null;
  return null;
}

export function noteFor(col: WorksheetColumn, row: WorksheetRow, ctx: WorksheetContext): FieldNoteSummary | undefined {
  const partId = notePartId(col, row);
  return partId === null ? undefined : ctx.byKey.get(noteKey(partId, col.key));
}

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
  def({ key: 'paint.colour', label: 'Colour / paint system', group: 'Paint', noteOwner: 'row', editableOn: 'paint',
    value: (r) => [r.paint.colour, r.paint.paint_system].filter(Boolean).join(' / ') || null, edit: onArticle('paint.colour') }),
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
