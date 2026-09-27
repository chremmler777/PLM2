/**
 * One tab of the cost sheet as a table. Drafts are edited in place (each cell
 * saves on its own) and get an add line at the bottom; published versions are
 * read-only. Every column sorts and filters like a spreadsheet (ColumnHeader);
 * the filter state belongs to the page, one per tab.
 */
import { useMemo, useRef, useState } from 'react'
import { X } from 'lucide-react'
import ConfirmDialog from '../common/ConfirmDialog'
import ColumnHeader from '../common/ColumnHeader'
import TableFilterBar from '../common/TableFilterBar'
import { btnSm } from '../common/buttonStyles'
import {
  EMPTY_TABLE_STATE, activeFilterCount, applyTableState, ariaSort, nextSort, withFilter,
  type TableState,
} from '../common/tableFilters'
import type { CostSheetRow, CostSheetSection } from '../../types/costSheet'
import { COLUMNS, blankRow, deptName, plantName, type Column, type SheetContext } from './columns'
import { filterColumns } from './filterColumns'
import SheetCell from './SheetCell'

interface Props {
  section: CostSheetSection
  /** The rows to show, in their default order (before the column filters). */
  rows: CostSheetRow[]
  /** Every row of the version's tab, hidden ones included: an added rate is
   * checked against these (one row per department and plant). */
  allRows?: CostSheetRow[]
  ctx: SheetContext
  editable: boolean
  busy?: boolean
  /** Sort and column filters of this tab (kept by the page). */
  tableState?: TableState
  onTableState?: (s: TableState) => void
  /** Extra columns a caller adds (e.g. a second currency), after the defaults. */
  extraColumns?: Column[]
  onUpdate: (rowId: number, changes: CostSheetRow) => void
  onDelete: (rowId: number) => void
  /** true when added; otherwise the reason (shown under the add line). */
  onAdd: (row: CostSheetRow) => Promise<true | string>
}

/** "<Dept> already has a rate at <plant>" when a rate row for the same
 * department and plant exists; null when the pair is free. */
export function duplicateRateMessage(row: CostSheetRow, rows: CostSheetRow[],
  ctx: SheetContext): string | null {
  if (row.department_id == null) return null
  const plant = row.plant_id ?? null
  const hit = rows.some((r) => r.department_id === row.department_id && (r.plant_id ?? null) === plant)
  if (!hit) return null
  const where = plant === null ? 'for all plants' : `at ${plantName(ctx, plant)}`
  return `${deptName(ctx, row.department_id)} already has a rate ${where}. Edit that row instead.`
}

export default function SectionTable({
  section, rows, allRows, ctx, editable, busy, tableState, onTableState, extraColumns,
  onUpdate, onDelete, onAdd,
}: Props) {
  const cols = useMemo(() => [...COLUMNS[section], ...(extraColumns ?? [])], [section, extraColumns])
  const fcols = useMemo(() => filterColumns(cols, ctx), [cols, ctx])
  const [localState, setLocalState] = useState<TableState>(EMPTY_TABLE_STATE)
  const state = tableState ?? localState
  const setState = onTableState ?? setLocalState
  const shown = useMemo(() => applyTableState(rows, fcols, state), [rows, fcols, state])
  const filterCount = activeFilterCount(state)
  const retired = useMemo(() => new Set(ctx.departments.filter((d) => !d.is_active).map((d) => d.id)), [ctx])
  const [addError, setAddError] = useState<string | null>(null)
  // Sampling has the most columns: tighter cell padding keeps it on screen.
  const px = section === 'sampling' ? 'px-1.5 first:pl-3' : 'px-3'
  const [adding, setAddingState] = useState<CostSheetRow | null>(null)
  // The add button is clicked right after an input's blur wrote its value;
  // the ref holds that value before React re-renders the click handler.
  const addingRef = useRef<CostSheetRow | null>(null)
  const setAdding = (next: CostSheetRow | null | ((a: CostSheetRow | null) => CostSheetRow)) => {
    const value = typeof next === 'function' ? next(addingRef.current) : next
    addingRef.current = value
    setAddingState(value)
  }

  // A draft row goes on a confirm: one stray click must not cost a rate.
  const [deleting, setDeleting] = useState<number | null>(null)
  const startAdd = () => { setAddError(null); setAdding(blankRow(section, ctx)) }
  const duplicate = section === 'rates' && adding
    ? duplicateRateMessage(adding, allRows ?? rows, ctx) : null
  const submitAdd = async () => {
    const row = addingRef.current
    if (!row) return
    if (section === 'rates') {
      const dup = duplicateRateMessage(row, allRows ?? rows, ctx)
      if (dup) { setAddError(dup); return }
    }
    const clean = Object.fromEntries(Object.entries(row).filter(([, v]) => v !== undefined))
    const res = await onAdd(clean)
    if (res === true) { setAdding(null); setAddError(null) } else setAddError(res)
  }
  const addMessage = duplicate ?? addError

  return (
    <div className="space-y-2">
      <TableFilterBar count={filterCount} shown={shown.length} total={rows.length}
        onClear={() => setState({ ...state, filters: {} })} />
    <div className="overflow-x-auto rounded-lg border border-slate-700/80">
      <table className="w-full text-sm">
        <thead className="bg-slate-800/80 text-[11px] uppercase tracking-wide text-slate-400">
          <tr>
            {cols.map((c, i) => (
              <th key={c.key} aria-sort={ariaSort(state, c.key)}
                  className={`${px} py-2 font-medium whitespace-nowrap ${c.width ?? ''} ${c.numeric ? 'text-right' : 'text-left'}`}>
                <ColumnHeader col={fcols[i]} rows={rows} cols={fcols} state={state} title={c.title}
                  align={c.numeric ? 'right' : 'left'}
                  onToggleSort={(key) => setState({ ...state, sort: nextSort(state.sort, key) })}
                  onFilter={(key, f) => setState(withFilter(state, key, f))} />
              </th>
            ))}
            {editable && <th className="w-10" aria-label="Actions" />}
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-800">
          {shown.length === 0 && !adding && (
            <tr>
              <td colSpan={cols.length + (editable ? 1 : 0)} className="px-3 py-8 text-center text-slate-500">
                {rows.length > 0 ? 'No rows match the filters.'
                  : editable ? 'No rows yet. Add the first one below.' : 'No rows in this version.'}
              </td>
            </tr>
          )}
          {shown.map((row) => (
            <tr key={row.id as number} className="group hover:bg-slate-800/40">
              {cols.map((c) => (
                <td key={c.key} className={`${px} ${editable ? 'py-1.5' : 'py-2'} align-middle ${c.numeric ? 'text-right' : ''}`}>
                  <SheetCell col={c} row={row} ctx={ctx} editable={editable}
                             onCommit={(v) => onUpdate(row.id as number,
                               c.toChanges ? c.toChanges(v, row) : { [c.key]: v })} />
                  {c.key === 'department_id' && retired.has(row.department_id as number) && (
                    <span className="mt-0.5 inline-block rounded bg-slate-700 px-1.5 text-[10px] font-medium uppercase tracking-wide text-slate-300">
                      Retired
                    </span>
                  )}
                </td>
              ))}
              {editable && (
                <td className="px-2 text-right">
                  <button type="button" onClick={() => setDeleting(row.id as number)} disabled={busy}
                          aria-label="Delete row" title="Delete row"
                          className="inline-flex h-7 w-7 items-center justify-center rounded text-slate-500 opacity-60 hover:bg-red-500/10 hover:text-red-300 group-hover:opacity-100 focus:opacity-100">
                    <X aria-hidden="true" size={14} />
                  </button>
                </td>
              )}
            </tr>
          ))}
          {editable && adding && (
            <tr className="bg-sky-500/5">
              {cols.map((c) => (
                <td key={c.key} className={`${px} py-1.5 ${c.numeric ? 'text-right' : ''}`}>
                  {c.derived ? <span className="text-slate-600">-</span> : (
                    <SheetCell col={c} row={adding} ctx={ctx} editable
                               onCommit={(v) => { setAddError(null); setAdding((a) => ({ ...(a ?? {}), [c.key]: v })) }} />
                  )}
                </td>
              ))}
              <td />
            </tr>
          )}
        </tbody>
      </table>
      {editable && (
        <div className="flex items-center gap-2 border-t border-slate-700/80 bg-slate-800/40 px-3 py-2">
          {adding ? (
            <>
              <button type="button" onClick={submitAdd} disabled={busy || !!duplicate}
                      className={btnSm.primary}>
                Add row
              </button>
              <button type="button" onClick={() => { setAdding(null); setAddError(null) }}
                      className={btnSm.ghost}>
                Cancel
              </button>
              {addMessage ? (
                <span role="alert" data-testid="sheet-add-error" className="text-xs text-rose-300">{addMessage}</span>
              ) : (
                <span className="text-xs text-slate-500">Fill the line above, then add it.</span>
              )}
            </>
          ) : (
            <button type="button" onClick={startAdd}
                    className="rounded-md px-2 py-1 text-sm font-medium text-sky-300 hover:bg-sky-500/10">
              + Add row
            </button>
          )}
        </div>
      )}
      <ConfirmDialog open={deleting !== null} danger data-testid="sheet-row-delete-confirm"
        title="Delete this row from the draft?"
        body="The row leaves this draft. Published versions keep theirs."
        confirmLabel="Delete row"
        onConfirm={() => { if (deleting !== null) onDelete(deleting) }}
        onClose={() => setDeleting(null)} />
    </div>
    </div>
  )
}
