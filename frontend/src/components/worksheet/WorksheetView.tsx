/**
 * WorksheetView - the project overview table: one row per article with the
 * producing tool's values, columns from worksheetColumns.ts. Values are
 * changed where they live (article, tool, paint); here a cell is only read,
 * commented and flagged. Full width while active; the detail pane is hidden.
 */
import { useMemo, useState } from 'react';
import { useProjectFieldNotes } from '../../hooks/queries/useFieldNotes';
import { useWorksheet } from '../../hooks/queries/useWorksheet';
import { flagTint } from '../../lib/fieldNotes';
import { WORKSHEET_COLUMNS, buildContext, noteFor, type WorksheetColumn } from './worksheetColumns';
import {
  applyFilters, enumOptions, frozenOffsets, loadHiddenColumns, rowKindVisible, saveHiddenColumns,
  sortRows, visibleColumns, type RowKindFilter, type SortState,
} from './worksheetTable';
import WorksheetCell from './WorksheetCell';

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

  const ctx = useMemo(() => buildContext(notes), [notes]);
  const cols = useMemo(() => visibleColumns(hidden), [hidden]);
  const offsets = useMemo(() => frozenOffsets(cols), [cols]);
  const kindRows = useMemo(() => (data?.rows ?? []).filter((r) => rowKindVisible(r, kinds)), [data, kinds]);
  const shown = useMemo(() => {
    const filtered = applyFilters(kindRows, cols, filters, ctx, onlyOpen);
    const sortCol = sort ? cols.find((c) => c.key === sort.key) : undefined;
    return sortRows(filtered, sortCol, sort?.dir ?? 'asc', ctx);
  }, [kindRows, cols, filters, ctx, onlyOpen, sort]);

  const toggleHidden = (key: string) => {
    const next = new Set(hidden);
    if (next.has(key)) next.delete(key); else next.add(key);
    setHidden(next);
    saveHiddenColumns(next);
  };
  const toggleSort = (key: string) =>
    setSort((s) => (!s || s.key !== key ? { key, dir: 'asc' } : s.dir === 'asc' ? { key, dir: 'desc' } : null));
  const frozenStyle = (c: WorksheetColumn) =>
    offsets.has(c.key) ? { left: offsets.get(c.key), minWidth: c.frozenWidth, maxWidth: c.frozenWidth } : undefined;
  const frozenClass = (c: WorksheetColumn) => (offsets.has(c.key) ? 'sticky z-10 bg-slate-900' : '');

  return (
    <div data-testid="worksheet-view" className="h-full flex flex-col min-h-0">
      <div className="flex-shrink-0 flex flex-wrap items-center gap-3 px-3 py-2 border-b border-slate-800 text-xs text-slate-300">
        <h2 className="font-semibold uppercase tracking-wide text-slate-300">Worksheet</h2>
        <span data-testid="ws-count" className="text-slate-500">{shown.length} rows</span>
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
                  <th key={c.key} style={frozenStyle(c)} className={`px-2 py-1 font-medium whitespace-nowrap border-b border-slate-700 ${frozenClass(c)}`}>
                    {c.display === 'thumbnail' ? <span className="sr-only">{c.label}</span> : (
                      <button type="button" data-testid={`sort-${c.key}`} onClick={() => toggleSort(c.key)} className="hover:text-slate-100">
                        {c.label}{sort?.key === c.key ? (sort.dir === 'asc' ? ' ▲' : ' ▼') : ''}
                      </button>
                    )}
                  </th>
                ))}
              </tr>
              <tr>
                {cols.map((c) => (
                  <th key={c.key} style={frozenStyle(c)} className={`px-1 pb-1 border-b border-slate-700 ${frozenClass(c)}`}>
                    {c.filter === 'text' && (
                      <input data-testid={`filter-${c.key}`} aria-label={`Filter ${c.label}`} value={filters[c.key] ?? ''}
                        onChange={(e) => setFilters((f) => ({ ...f, [c.key]: e.target.value }))}
                        className="w-full min-w-[4rem] bg-slate-800 border border-slate-700 rounded px-1 py-0.5 text-slate-100 font-normal" />
                    )}
                    {c.filter === 'enum' && (
                      <select data-testid={`filter-${c.key}`} aria-label={`Filter ${c.label}`} value={filters[c.key] ?? ''}
                        onChange={(e) => setFilters((f) => ({ ...f, [c.key]: e.target.value }))}
                        className="w-full bg-slate-800 border border-slate-700 rounded px-1 py-0.5 text-slate-100 font-normal">
                        <option value="">All</option>
                        {enumOptions(c, kindRows, ctx).map((o) => <option key={o} value={o}>{o}</option>)}
                      </select>
                    )}
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
                        className={`group p-0 border-b border-slate-800 whitespace-nowrap ${frozenClass(c)}`}>
                        <div data-testid={`ws-tint-${row.part_id}-${c.key}`} className={`px-2 py-1 ${flagTint(note?.flag_status)}`}>
                          <WorksheetCell row={row} col={c} ctx={ctx} note={note}
                            noteOpen={openNote === id}
                            onNoteOpenChange={(open) => setOpenNote(open ? id : null)}
                            onMenu={() => { /* Task 14 opens the cell menu */ }} />
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
    </div>
  );
}
