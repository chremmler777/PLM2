/** One worksheet cell: the value by display kind, the field note marker, and a "..." menu button for touch and keyboard. */
import PartThumbnail from '../parts/PartThumbnail';
import RevisionLabel from '../parts/RevisionLabel';
import MaterialValue from '../materials/MaterialValue';
import FieldNoteMarker from '../fieldNotes/FieldNoteMarker';
import type { FieldNoteSummary } from '../../api/fieldNotes';
import type { WorksheetRow } from '../../api/worksheet';
import { notePartId, type WorksheetColumn, type WorksheetContext } from './worksheetColumns';

export interface WorksheetCellProps {
  row: WorksheetRow;
  col: WorksheetColumn;
  ctx: WorksheetContext;
  note?: FieldNoteSummary;
  noteOpen: boolean;
  onNoteOpenChange(open: boolean): void;
  onMenu(rect: DOMRect): void;
}

const DFM_TONE: Record<string, string> = { waiting: 'text-amber-300', all_answered: 'text-emerald-300', finished: 'text-slate-400' };

export default function WorksheetCell({ row, col, ctx, note, noteOpen, onNoteOpenChange, onMenu }: WorksheetCellProps) {
  const value = col.value(row, ctx);
  const partId = notePartId(col, row);
  let body: React.ReactNode;
  switch (col.display) {
    case 'thumbnail':
      body = <PartThumbnail url={row.thumbnail_url} name={row.name} />;
      break;
    case 'revision':
      body = row.revision ? <RevisionLabel name={row.revision.revision_name} index={row.revision.customer_index} /> : null;
      break;
    case 'material':
      body = row.row_kind === 'tool_only' ? null : <MaterialValue material={row.material} testId={`ws-material-${row.part_id}`} />;
      break;
    case 'dfm':
      body = value === null ? null : <span className={DFM_TONE[row.dfm?.status ?? ''] ?? 'text-slate-300'}>{value}</span>;
      break;
    case 'notes':
      body = value === null ? null : <span className="text-slate-400">{value}</span>;
      break;
    default:
      body = value === null ? null : (
        <span className={col.display === 'mono' ? 'font-mono text-slate-200' : col.display === 'number' ? 'tabular-nums text-slate-200' : 'text-slate-100'}>
          {value}
        </span>
      );
  }
  return (
    <span className="inline-flex items-center gap-0.5">
      {body}
      {partId !== null && (
        <FieldNoteMarker partId={partId} fieldKey={col.key} label={col.label} note={note}
          open={noteOpen} onOpenChange={onNoteOpenChange} quietWhenEmpty />
      )}
      <button
        type="button"
        aria-label={`Actions for ${col.label}`}
        data-testid={`cell-menu-${row.part_id}-${col.key}`}
        onClick={(e) => { e.stopPropagation(); onMenu((e.currentTarget as HTMLElement).getBoundingClientRect()); }}
        className="ml-0.5 px-0.5 text-slate-500 hover:text-slate-200 opacity-0 group-hover:opacity-100 focus:opacity-100"
      >
        ⋯
      </button>
    </span>
  );
}
