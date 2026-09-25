/**
 * One tab of the cost sheet as a table. Drafts are edited in place (each cell
 * saves on its own) and get an add line at the bottom; published versions are
 * read-only.
 */
import { useRef, useState } from 'react'
import type { CostSheetRow, CostSheetSection } from '../../types/costSheet'
import { COLUMNS, blankRow, type SheetContext } from './columns'
import SheetCell from './SheetCell'

interface Props {
  section: CostSheetSection
  rows: CostSheetRow[]
  ctx: SheetContext
  editable: boolean
  busy?: boolean
  onUpdate: (rowId: number, changes: CostSheetRow) => void
  onDelete: (rowId: number) => void
  onAdd: (row: CostSheetRow) => Promise<boolean>
}

export default function SectionTable({ section, rows, ctx, editable, busy, onUpdate, onDelete, onAdd }: Props) {
  const cols = COLUMNS[section]
  const [adding, setAddingState] = useState<CostSheetRow | null>(null)
  // The add button is clicked right after an input's blur wrote its value;
  // the ref holds that value before React re-renders the click handler.
  const addingRef = useRef<CostSheetRow | null>(null)
  const setAdding = (next: CostSheetRow | null | ((a: CostSheetRow | null) => CostSheetRow)) => {
    const value = typeof next === 'function' ? next(addingRef.current) : next
    addingRef.current = value
    setAddingState(value)
  }

  const startAdd = () => setAdding(blankRow(section, ctx))
  const submitAdd = async () => {
    const row = addingRef.current
    if (!row) return
    const clean = Object.fromEntries(Object.entries(row).filter(([, v]) => v !== undefined))
    if (await onAdd(clean)) setAdding(null)
  }

  return (
    <div className="overflow-x-auto rounded-lg border border-slate-700/80">
      <table className="w-full text-sm">
        <thead className="bg-slate-800/80 text-[11px] uppercase tracking-wide text-slate-400">
          <tr>
            {cols.map((c) => (
              <th key={c.key} title={c.title}
                  className={`px-3 py-2 font-medium whitespace-nowrap ${c.width ?? ''} ${c.numeric ? 'text-right' : 'text-left'}`}>
                {c.label}
              </th>
            ))}
            {editable && <th className="w-10" aria-label="Actions" />}
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-800">
          {rows.length === 0 && !adding && (
            <tr>
              <td colSpan={cols.length + (editable ? 1 : 0)} className="px-3 py-8 text-center text-slate-500">
                {editable ? 'No rows yet. Add the first one below.' : 'No rows in this version.'}
              </td>
            </tr>
          )}
          {rows.map((row) => (
            <tr key={row.id as number} className="group hover:bg-slate-800/40">
              {cols.map((c) => (
                <td key={c.key} className={`px-3 ${editable ? 'py-1.5' : 'py-2'} align-middle ${c.numeric ? 'text-right' : ''}`}>
                  <SheetCell col={c} row={row} ctx={ctx} editable={editable}
                             onCommit={(v) => onUpdate(row.id as number, { [c.key]: v })} />
                </td>
              ))}
              {editable && (
                <td className="px-2 text-right">
                  <button type="button" onClick={() => onDelete(row.id as number)} disabled={busy}
                          aria-label="Delete row" title="Delete row"
                          className="rounded px-1.5 py-0.5 text-slate-500 opacity-60 hover:bg-red-500/10 hover:text-red-300 group-hover:opacity-100 focus:opacity-100">
                    ✕
                  </button>
                </td>
              )}
            </tr>
          ))}
          {editable && adding && (
            <tr className="bg-sky-500/5">
              {cols.map((c) => (
                <td key={c.key} className={`px-3 py-1.5 ${c.numeric ? 'text-right' : ''}`}>
                  {c.derived ? <span className="text-slate-600">-</span> : (
                    <SheetCell col={c} row={adding} ctx={ctx} editable
                               onCommit={(v) => setAdding((a) => ({ ...(a ?? {}), [c.key]: v }))} />
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
              <button type="button" onClick={submitAdd} disabled={busy}
                      className="rounded-md bg-sky-600 px-3 py-1 text-sm font-medium text-white hover:bg-sky-500 disabled:opacity-50">
                Add row
              </button>
              <button type="button" onClick={() => setAdding(null)}
                      className="rounded-md px-3 py-1 text-sm text-slate-400 hover:text-slate-200">
                Cancel
              </button>
              <span className="text-xs text-slate-500">Fill the line above, then add it.</span>
            </>
          ) : (
            <button type="button" onClick={startAdd}
                    className="rounded-md px-2 py-1 text-sm font-medium text-sky-300 hover:bg-sky-500/10">
              + Add row
            </button>
          )}
        </div>
      )}
    </div>
  )
}
