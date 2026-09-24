/**
 * WorksheetView - the project overview table: one row per article with the
 * producing tool's values, columns from worksheetColumns.ts. Values are
 * changed where they live (article, tool, paint); here a cell is only read,
 * commented and flagged. Full width while active; the detail pane is hidden.
 */
import { useCallback, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import { setFieldFlag, type FieldFlag } from '../../api/fieldNotes';
import { useProjectFieldNotes, FIELD_NOTES_KEY } from '../../hooks/queries/useFieldNotes';
import { useWorksheet } from '../../hooks/queries/useWorksheet';
import { FOCUS_PARAM } from '../../hooks/useFieldFocus';
import { apiErrorMessage } from '../../lib/apiError';
import { flagTint } from '../../lib/fieldNotes';
import { WORKSHEET_COLUMNS, buildContext, noteFor, notePartId, type WorksheetColumn } from './worksheetColumns';
import {
  applyFilters, enumOptions, frozenOffsets, loadHiddenColumns, offeredFilters, rowKindVisible, saveHiddenColumns,
  sortRows, visibleColumns, type RowKindFilter, type SortState,
} from './worksheetTable';
import WorksheetCell from './WorksheetCell';
import WorksheetCellMenu, { type CellMenuState } from './WorksheetCellMenu';

export interface WorksheetViewProps {
  projectId: number;
  onClose(): void;
}

const GROUPS = ['Identity', 'Revision', 'Material', 'Paint', 'Tool', 'DFM', 'Notes'] as const;

export default function WorksheetView({ projectId, onClose }: WorksheetViewProps) {
  const { data, isLoading, isError } = useWorksheet(projectId);
  const { data: notes } = useProjectFieldNotes(projectId);
  const [hidden, setHidden] = useState<Set<string>>(loadHiddenColumns);
  const [filters, setFilters] = useState<Record<string, string>>({});
  const [sort, setSort] = useState<SortState | null>(null);
  const [onlyOpen, setOnlyOpen] = useState(false);
  const [kinds, setKinds] = useState<RowKindFilter>({ purchased: false, toolOnly: false });
  const [showColumns, setShowColumns] = useState(false);
  const [openNote, setOpenNote] = useState<string | null>(null); // `${row.part_id}|${col.key}`
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [menu, setMenu] = useState<CellMenuState | null>(null);
  const flagMutation = useMutation({
    mutationFn: ({ partId, key, flag }: { partId: number; key: string; flag: FieldFlag | null }) => setFieldFlag(partId, key, flag),
    onSuccess: () => qc.invalidateQueries({ queryKey: [FIELD_NOTES_KEY] }),
    onError: (e) => toast.error(apiErrorMessage(e, 'Could not set the flag')),
  });
  const closeMenu = useCallback(() => setMenu(null), []);

  const ctx = useMemo(() => buildContext(notes), [notes]);
  const menuNote = menu ? noteFor(menu.col, menu.row, ctx) : undefined;
  const cols = useMemo(() => visibleColumns(hidden), [hidden]);
  const offsets = useMemo(() => frozenOffsets(cols), [cols]);
  const kindRows = useMemo(() => (data?.rows ?? []).filter((r) => rowKindVisible(r, kinds)), [data, kinds]);
  const activeFilters = useMemo(() => offeredFilters(filters, cols, kindRows, ctx), [filters, cols, kindRows, ctx]);
  const shown = useMemo(() => {
    const filtered = applyFilters(kindRows, cols, activeFilters, ctx, onlyOpen);
    const sortCol = sort ? cols.find((c) => c.key === sort.key) : undefined;
    return sortRows(filtered, sortCol, sort?.dir ?? 'asc', ctx);
  }, [kindRows, cols, activeFilters, ctx, onlyOpen, sort]);

  const toggleHidden = (key: string) => {
    const next = new Set(hidden);
    if (next.has(key)) next.delete(key); else next.add(key);
    setHidden(next);
    saveHiddenColumns(next);
  };
  const toggleSort = (key: string) =>
    setSort((s) => (!s || s.key !== key ? { key, dir: 'asc' } : s.dir === 'asc' ? { key, dir: 'desc' } : null));
  // Offsets assume exact widths, and table cells grow with their content: pin the cell and clip an inner box.
  const frozenStyle = (c: WorksheetColumn) =>
    offsets.has(c.key) ? { left: offsets.get(c.key), width: c.frozenWidth, minWidth: c.frozenWidth, maxWidth: c.frozenWidth } : undefined;
  const frozenBox = (c: WorksheetColumn) =>
    offsets.has(c.key) ? { width: c.frozenWidth, overflow: 'hidden' as const } : undefined;
  const cellPad = (c: WorksheetColumn) => (c.display === 'thumbnail' ? 'px-0.5' : 'px-2');
  const frozenClass = (c: WorksheetColumn) => (offsets.has(c.key) ? 'sticky z-10 bg-slate-900' : '');

  return (
    <div data-testid="worksheet-view" className="h-full flex flex-col min-h-0">
      <div className="flex-shrink-0 flex flex-wrap items-center gap-3 px-3 py-2 border-b border-slate-800 text-xs text-slate-300">
        <h2 className="font-semibold uppercase tracking-wide text-slate-300">Worksheet</h2>
        {data && !isError && <span data-testid="ws-count" className="text-slate-500">{shown.length} rows</span>}
        <label className="flex items-center gap-1">
          <input type="checkbox" data-testid="ws-only-open" checked={onlyOpen} onChange={(e) => setOnlyOpen(e.target.checked)} />
          Only rows with open flags
        </label>
        <label className="flex items-center gap-1">
          <input type="checkbox" data-testid="ws-kind-purchased" checked={kinds.purchased}
            onChange={(e) => setKinds((k) => ({ ...k, purchased: e.target.checked }))} />
          Purchased parts
        </label>
        <label className="flex items-center gap-1">
          <input type="checkbox" data-testid="ws-kind-tool-only" checked={kinds.toolOnly}
            onChange={(e) => setKinds((k) => ({ ...k, toolOnly: e.target.checked }))} />
          Tools without article
        </label>
        <div className="relative">
          <button type="button" data-testid="ws-columns-toggle" aria-expanded={showColumns} onClick={() => setShowColumns((v) => !v)}
            className="px-2 py-1 rounded bg-slate-700 hover:bg-slate-600 text-slate-100">Columns</button>
          {showColumns && (
            <div className="absolute z-30 mt-1 w-64 max-h-96 overflow-y-auto bg-slate-800 border border-slate-600 rounded shadow-lg p-2">
              {GROUPS.map((g) => (
                <div key={g} className="mb-1">
                  <div className="text-[10px] uppercase text-slate-500">{g}</div>
                  {WORKSHEET_COLUMNS.filter((c) => c.group === g).map((c) => (
                    <label key={c.key} className="flex items-center gap-2 py-0.5">
                      <input type="checkbox" data-testid={`ws-column-${c.key}`} checked={!hidden.has(c.key)} onChange={() => toggleHidden(c.key)} />
                      {c.label}
                    </label>
                  ))}
                </div>
              ))}
            </div>
          )}
        </div>
        {/* Task 15 puts the export button here */}
        <button type="button" data-testid="ws-close" onClick={onClose}
          className="ml-auto px-2 py-1 rounded bg-slate-700 hover:bg-slate-600 text-slate-100">Back to list</button>
      </div>

      <div className="flex-1 min-h-0 overflow-auto">
        {isLoading ? (
          <p className="p-4 text-sm text-slate-500">Loading...</p>
        ) : isError ? (
          <p className="p-4 text-sm text-red-400">Could not load the worksheet</p>
        ) : (
          <table className="text-xs border-separate border-spacing-0">
            <thead className="sticky top-0 z-20 bg-slate-900 text-left text-slate-400">
              <tr>
                {cols.map((c) => (
                  <th key={c.key} style={frozenStyle(c)} className={`p-0 font-medium whitespace-nowrap border-b border-slate-700 ${frozenClass(c)}`}>
                    <div style={frozenBox(c)} className={`${cellPad(c)} py-1 ${offsets.has(c.key) ? 'truncate' : ''}`}>
                      {c.display === 'thumbnail' ? <span className="sr-only">{c.label}</span> : (
                        <button type="button" data-testid={`sort-${c.key}`} onClick={() => toggleSort(c.key)} title={c.label}
                          className="hover:text-slate-100">
                          {c.label}{sort?.key === c.key ? (sort.dir === 'asc' ? ' ▲' : ' ▼') : ''}
                        </button>
                      )}
                    </div>
                  </th>
                ))}
              </tr>
              <tr>
                {cols.map((c) => (
                  <th key={c.key} style={frozenStyle(c)} className={`p-0 border-b border-slate-700 ${frozenClass(c)}`}>
                    <div style={frozenBox(c)} className="px-1 pb-1">
                      {c.filter === 'text' && (
                        <input data-testid={`filter-${c.key}`} aria-label={`Filter ${c.label}`} value={activeFilters[c.key] ?? ''}
                          onChange={(e) => setFilters((f) => ({ ...f, [c.key]: e.target.value }))}
                          className="w-full min-w-[4rem] bg-slate-800 border border-slate-700 rounded px-1 py-0.5 text-slate-100 font-normal" />
                      )}
                      {c.filter === 'enum' && (
                        <select data-testid={`filter-${c.key}`} aria-label={`Filter ${c.label}`} value={activeFilters[c.key] ?? ''}
                          onChange={(e) => setFilters((f) => ({ ...f, [c.key]: e.target.value }))}
                          className="w-full bg-slate-800 border border-slate-700 rounded px-1 py-0.5 text-slate-100 font-normal">
                          <option value="">All</option>
                          {enumOptions(c, kindRows, ctx).map((o) => <option key={o} value={o}>{o}</option>)}
                        </select>
                      )}
                    </div>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {shown.map((row) => (
                <tr key={row.part_id} data-testid={`ws-row-${row.part_id}`} className="hover:bg-slate-800/40">
                  {cols.map((c) => {
                    const note = noteFor(c, row, ctx);
                    const id = `${row.part_id}|${c.key}`;
                    return (
                      <td key={c.key} data-testid={`ws-cell-${row.part_id}-${c.key}`} data-flag={note?.flag_status ?? ''}
                        style={frozenStyle(c)}
                        onContextMenu={(e) => { e.preventDefault(); setMenu({ x: e.clientX, y: e.clientY, row, col: c }); }}
                        className={`group p-0 border-b border-slate-800 whitespace-nowrap ${frozenClass(c)}`}>
                        <div data-testid={`ws-tint-${row.part_id}-${c.key}`} style={frozenBox(c)}
                          className={`${cellPad(c)} py-1 ${flagTint(note?.flag_status)}`}>
                          <WorksheetCell row={row} col={c} ctx={ctx} note={note}
                            noteOpen={openNote === id}
                            onNoteOpenChange={(open) => setOpenNote(open ? id : null)}
                            onMenu={(rect) => setMenu({ x: rect.left, y: rect.bottom, row, col: c })} />
                        </div>
                      </td>
                    );
                  })}
                </tr>
              ))}
              {shown.length === 0 && (
                <tr><td colSpan={cols.length} className="p-4 text-sm text-slate-500">No rows match</td></tr>
              )}
            </tbody>
          </table>
        )}
      </div>
      <WorksheetCellMenu
        menu={menu}
        flag={menuNote?.flag_status ?? null}
        onClose={closeMenu}
        onEdit={() => {
          const target = menu?.col.edit(menu.row);
          if (target) navigate(`/parts/${target.partId}?${FOCUS_PARAM}=${encodeURIComponent(target.focus)}`);
        }}
        onComment={() => { if (menu) setOpenNote(`${menu.row.part_id}|${menu.col.key}`); }}
        onFlag={(flag) => {
          const partId = menu ? notePartId(menu.col, menu.row) : null;
          if (menu && partId !== null) flagMutation.mutate({ partId, key: menu.col.key, flag });
        }}
      />
    </div>
  );
}
