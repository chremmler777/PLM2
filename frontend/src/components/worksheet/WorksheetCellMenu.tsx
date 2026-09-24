/** Right-click (or "..." button) menu on a worksheet cell: Edit where the value lives, Comment, Flag. */
import { useEffect, useRef } from 'react';
import type { FieldFlag } from '../../api/fieldNotes';
import type { WorksheetRow } from '../../api/worksheet';
import { FLAG_LABELS, FLAGS } from '../../lib/fieldNotes';
import { notePartId, type WorksheetColumn } from './worksheetColumns';

export interface CellMenuState {
  x: number;
  y: number;
  row: WorksheetRow;
  col: WorksheetColumn;
}

export interface WorksheetCellMenuProps {
  menu: CellMenuState | null;
  flag: FieldFlag | null;
  onClose(): void;
  onEdit(): void;
  onComment(): void;
  onFlag(flag: FieldFlag | null): void;
}

const item = 'w-full text-left px-3 py-1.5 text-sm text-slate-200 hover:bg-slate-600 disabled:text-slate-500 disabled:hover:bg-transparent';

export default function WorksheetCellMenu({ menu, flag, onClose, onEdit, onComment, onFlag }: WorksheetCellMenuProps) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!menu) return;
    const onDown = (e: MouseEvent) => { if (!ref.current?.contains(e.target as Node)) onClose(); };
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    document.addEventListener('mousedown', onDown);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onDown);
      document.removeEventListener('keydown', onKey);
    };
  }, [menu, onClose]);
  if (!menu) return null;

  const canEdit = !!menu.col.edit(menu.row);
  const canNote = notePartId(menu.col, menu.row) !== null;
  const act = (fn: () => void) => () => { fn(); onClose(); };

  return (
    <div ref={ref} role="menu" data-testid="ws-menu" aria-label={`${menu.col.label} actions`}
      className="fixed z-50 min-w-[11rem] bg-slate-700 border border-slate-600 rounded-lg shadow-lg py-1"
      style={{ top: menu.y, left: menu.x }}>
      <button role="menuitem" type="button" data-testid="ws-menu-edit" disabled={!canEdit} onClick={act(onEdit)} className={item}
        title={canEdit ? 'Open the page where this value is changed' : 'This value is not changed on a page'}>
        Edit
      </button>
      <button role="menuitem" type="button" data-testid="ws-menu-comment" disabled={!canNote} onClick={act(onComment)} className={item}>
        Comment
      </button>
      <div className="border-t border-slate-600 my-1" />
      {FLAGS.map((f) => (
        <button key={f} role="menuitem" type="button" data-testid={`ws-menu-flag-${f}`} disabled={!canNote || flag === f}
          onClick={act(() => onFlag(f))} className={item}>
          Flag {FLAG_LABELS[f].toLowerCase()}
        </button>
      ))}
      <button role="menuitem" type="button" data-testid="ws-menu-flag-clear" disabled={!canNote || !flag}
        onClick={act(() => onFlag(null))} className={item}>
        Clear flag
      </button>
    </div>
  );
}
