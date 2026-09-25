/**
 * The table half of the Gantt: configurable columns, one row per group /
 * task at the same height as the chart rows, inline cell editing and the
 * drag handle for row reorder. Virtualised like the chart.
 */
import { memo, useEffect, useRef, useState, type ReactNode, type PointerEvent as ReactPointerEvent } from 'react'
import { key } from './engine/tree'
import type { GanttTask } from './engine/types'
import { HEADER_H } from './GanttChart'
import { gridTiming, gridWidth, type CellContext, type EditKind, type GanttColumn } from './columns'
import { DATE_PLACEHOLDER, formatDateInput, parseDateInput } from './dateText'
import { textWidth, type Row } from './layout'
import { v } from './theme'

export interface GridProps {
  columns: GanttColumn[]
  rows: Row[]
  rowH: number
  first: number
  last: number
  selected: Set<string>
  flashKey: string | null
  flagged: Set<string>
  pending: Set<string>
  ctx: (t: GanttTask) => CellContext
  canEdit: (t: GanttTask, col: GanttColumn) => boolean
  canReorder: boolean
  editing: { key: string; col: string } | null
  /** The active row: a click on one of its editable cells edits it (spreadsheet style). */
  activeKey?: string | null
  dropLine: { index: number; where: 'before' | 'after' } | null
  onRowClick: (e: React.MouseEvent, t: GanttTask) => void
  onRowDoubleClick: (t: GanttTask, col: GanttColumn) => void
  onRowContext: (e: React.MouseEvent, t: GanttTask) => void
  onToggle: (rowKey: string) => void
  onStartEdit: (t: GanttTask, col: string) => void
  onCommitEdit: (t: GanttTask, col: GanttColumn, value: string) => void
  onCancelEdit: () => void
  onReorderDown: (e: ReactPointerEvent, t: GanttTask) => void
}


export function GridHeader({ columns, height = HEADER_H, extra }: { columns: GanttColumn[]; height?: number; extra?: ReactNode }) {
  // All short or none: "Base start" next to "B. finish" reads as two things.
  // Measured at the header's own 11 px.
  const abbreviate = columns.some((c) => c.short && textWidth(c.title.toUpperCase(), 11) + 12 > c.width)
  return (
    <div className="relative flex items-end border-b text-[11px] uppercase tracking-wide"
      style={{ height, width: gridWidth(columns), background: v('headerBg'), borderColor: v('gridLine'), color: v('textFaint') }}
      role="row" data-testid="gantt-grid-header">
      {extra && <div className="absolute left-1 top-1 normal-case tracking-normal">{extra}</div>}
      {columns.map((c) => (
        <div key={c.key} role="columnheader" className={`truncate px-1.5 pb-1.5 ${c.align === 'right' ? 'text-right' : ''}`}
          title={c.title} style={{ width: c.width, flex: `0 0 ${c.width}px` }}>
          {c.short && abbreviate ? c.short : c.title}
        </div>
      ))}
    </div>
  )
}

/**
 * Which columns the grid shows. Columns that did not fit are listed (and
 * counted on the button, "+3 columns"); ticking one keeps it, the grid then
 * takes the room it needs.
 */
export function ColumnPicker({ all, shown, dropped, open, onOpen, onToggle }: {
  all: GanttColumn[]; shown: GanttColumn[]; dropped: string[]; open: boolean
  onOpen: (open: boolean) => void; onToggle: (key: string, on: boolean) => void
}) {
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!open) return
    const down = (e: Event) => { if (ref.current && !ref.current.contains(e.target as Node)) onOpen(false) }
    document.addEventListener('pointerdown', down, true)
    return () => document.removeEventListener('pointerdown', down, true)
  }, [open, onOpen])
  const on = new Set(shown.map((c) => c.key))
  const n = dropped.length
  return (
    <div ref={ref} className="relative">
      <button type="button" data-testid="gantt-columns" aria-expanded={open} aria-haspopup="dialog"
        title={n ? `${n} column${n === 1 ? '' : 's'} did not fit: choose the columns` : 'Choose the columns'}
        className="rounded border px-1.5 py-0.5 text-[11px] hover:brightness-125"
        style={{ borderColor: n ? v('accent') : v('gridLine'), color: n ? v('accent') : v('textFaint'), background: v('panel') }}
        onClick={(e) => { e.stopPropagation(); onOpen(!open) }}>
        {n ? `+${n} column${n === 1 ? '' : 's'}` : 'Columns'}
      </button>
      {open && (
        <div role="dialog" aria-label="Columns" data-testid="gantt-columns-picker"
          className="absolute left-0 top-full z-30 mt-1 w-52 space-y-0.5 rounded-md border p-2 text-xs shadow-xl"
          style={{ background: v('panel'), borderColor: v('gridLine'), color: v('text') }}
          onKeyDown={(e) => { if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); onOpen(false) } }}>
          {all.map((c) => (
            <label key={c.key} className="flex items-center gap-2">
              <input type="checkbox" checked={on.has(c.key)} disabled={c.key === 'name'}
                onChange={(e) => onToggle(c.key, e.target.checked)} />
              <span className="flex-1">{c.title || c.key}</span>
              {dropped.includes(c.key) && <span className="text-[11px]" style={{ color: v('textFaint') }}>no room</span>}
            </label>
          ))}
        </div>
      )}
    </div>
  )
}

function CellEditor({ initial, type, onCommit, onCancel, label, placeholder }: {
  initial: string; type: EditKind; onCommit: (v: string) => void; onCancel: () => void; label: string; placeholder?: string
}) {
  // Dates show as 25 Sep 2026, are typed in any form dateText reads (never the locale's native picker) and go out as ISO.
  const [val, setVal] = useState(type === 'date' ? formatDateInput(initial) : initial)
  const ref = useRef<HTMLInputElement>(null)
  const done = useRef(false)
  useEffect(() => { ref.current?.focus(); ref.current?.select?.() }, [])
  const commit = () => {
    if (done.current) return
    done.current = true
    onCommit(type === 'date' ? (parseDateInput(val) ?? val) : val)
  }
  return (
    <input ref={ref} aria-label={label} data-testid="gantt-cell-editor"
      type={type === 'number' ? 'number' : 'text'}
      className="h-full w-full rounded-sm border px-1 text-xs outline-none [color-scheme:dark]"
      style={{ background: v('bg'), color: v('text'), borderColor: v('accent') }}
      value={val} placeholder={placeholder ?? (type === 'date' ? DATE_PLACEHOLDER : undefined)} onChange={(e) => setVal(e.target.value)}
      onClick={(e) => e.stopPropagation()}
      onDoubleClick={(e) => e.stopPropagation()}
      onKeyDown={(e) => {
        // The full-screen shortcut still reaches the Gantt (the draft stays open).
        if ((e.ctrlKey || e.metaKey) && e.shiftKey && (e.key === 'f' || e.key === 'F')) return
        e.stopPropagation()
        if (e.key === 'Enter') { e.preventDefault(); commit() }
        if (e.key === 'Escape') { e.preventDefault(); done.current = true; onCancel() }
        if (e.key === 'Tab') { commit() }
      }}
      onBlur={commit} />
  )
}

export const GridBody = memo(function GridBody(p: GridProps) {
  const width = gridWidth(p.columns)
  // Was the row active (and selected) before this press? Set on pointer down.
  const armed = useRef<string | null>(null)
  const editTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const cancelEdit = () => { if (editTimer.current) { clearTimeout(editTimer.current); editTimer.current = null } }
  useEffect(() => cancelEdit, [])
  const height = Math.max(p.rows.length, 1) * p.rowH
  const out: JSX.Element[] = []
  for (let i = p.first; i <= p.last && i < p.rows.length; i++) {
    const r = p.rows[i]
    const top = i * p.rowH
    if (r.type === 'group') {
      out.push(
        <button key={r.key} type="button" data-testid={`gantt-group-${r.label}`} aria-rowindex={i + 1}
          className="absolute left-0 flex items-center gap-1.5 border-b px-2 text-left"
          style={{ top, height: p.rowH, width, background: v('groupBg'), borderColor: v('gridLine') }}
          aria-expanded={!r.collapsed} aria-label={`${r.collapsed ? 'Expand' : 'Collapse'} ${r.label}`}
          onClick={() => p.onToggle(r.key)}>
          <span className={`text-[11px] transition-transform ${r.collapsed ? '' : 'rotate-90'}`} style={{ color: v('textFaint') }}>&#9656;</span>
          <span className="truncate text-[11px] font-semibold uppercase tracking-wide" style={{ color: v('text') }}>{r.label}</span>
          <span className="text-[11px]" style={{ color: v('textFaint') }}>{r.count}</span>
        </button>,
      )
      continue
    }
    const t = r.task
    const k = key(t.id)
    const sel = p.selected.has(k)
    const c = p.ctx(t)
    out.push(
      <div key={k} role="row" aria-selected={sel} aria-rowindex={i + 1} data-testid={`gantt-row-${k}`} data-row-index={i}
        className="absolute left-0 flex cursor-default select-none items-center border-b text-xs"
        style={{
          top, height: p.rowH, width, borderColor: v('rowLine'),
          background: sel ? v('selectBg') : undefined, color: v('text'),
          boxShadow: p.flashKey === k ? `inset 0 0 0 1px ${'var(--g-focus)'}` : undefined,
          opacity: p.pending.has(k) ? 0.8 : 1,
        }}
        onClick={(e) => p.onRowClick(e, t)}
        onContextMenu={(e) => p.onRowContext(e, t)}>
        {p.columns.map((col, ci) => {
          const editing = p.editing?.key === k && p.editing.col === col.key
          const editable = !!col.edit && p.canEdit(t, col)
          const isHandle = ci === 0 && p.canReorder
          let content: ReactNode
          if (editing && col.edit) {
            content = (
              <CellEditor initial={(col.editValue ?? col.text ?? (() => ''))(t, c)} type={col.edit}
                placeholder={col.key === 'name' ? 'Task name, Enter to add' : undefined}
                label={`${col.title} of ${t.name}`}
                onCommit={(val) => p.onCommitEdit(t, col, val)} onCancel={p.onCancelEdit} />
            )
          } else if (col.key === 'name') {
            content = (
              <span className="flex min-w-0 items-center gap-1" style={{ paddingLeft: r.depth * 14 }}>
                {r.summary ? (
                  <button type="button" className="w-3 shrink-0 text-[11px]" style={{ color: v('textFaint') }}
                    aria-label={`${r.collapsed ? 'Expand' : 'Collapse'} ${t.name}`} aria-expanded={!r.collapsed}
                    data-testid={`gantt-toggle-${k}`}
                    onClick={(e) => { e.stopPropagation(); p.onToggle(k) }}>
                    <span className={`inline-block transition-transform ${r.collapsed ? '' : 'rotate-90'}`}>&#9656;</span>
                  </button>
                ) : <span className="w-3 shrink-0" />}
                {p.flagged.has(k) && <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-red-400" aria-label="Has a plan issue" />}
                {t.isIdea && (
                  <span className="shrink-0 rounded border border-dashed px-1 text-[11px] font-semibold uppercase"
                    style={{ borderColor: v('idea'), color: v('idea') }}>idea</span>
                )}
                <span className={`truncate ${r.summary ? 'font-semibold' : ''}`} title={t.name}>
                  {t.name || <em style={{ color: v('textFaint') }}>unnamed</em>}
                </span>
              </span>
            )
          } else content = col.render ? col.render(t, c) : (col.text?.(t, c) ?? '')
          return (
            <div key={col.key} role="gridcell" data-col={col.key}
              className={`h-full truncate px-1.5 tabular-nums ${editing ? 'p-0.5' : 'flex items-center'} ${col.align === 'right' ? 'justify-end text-right' : ''} ${isHandle ? 'cursor-grab' : ''}`}
              style={{ width: col.width, flex: `0 0 ${col.width}px`, color: col.key === 'name' ? v('text') : v('textMuted') }}
              title={isHandle ? 'Drag to move the row' : undefined}
              onPointerDown={(e) => {
                const mods = e.ctrlKey || e.metaKey || e.shiftKey || e.altKey
                armed.current = !mods && e.button === 0 && p.activeKey === k && sel ? `${k}|${col.key}` : null
                if (isHandle) p.onReorderDown(e, t)
              }}
              onClick={(e) => {
                // A plain click on a cell of the row that was already active edits
                // it in place (F2 edits the name). Modifier clicks only change the
                // selection; the second click of a double-click never edits.
                const was = armed.current
                armed.current = null
                if (!editable || editing || e.ctrlKey || e.metaKey || e.shiftKey || e.altKey || e.detail > 1) return
                // No pointer down seen (keyboard, synthetic click): the row's state now.
                const ok = was != null ? was === `${k}|${col.key}` : p.activeKey === k && sel
                if (!ok) return
                e.stopPropagation()
                cancelEdit()
                if (gridTiming.editDelay <= 0) { p.onStartEdit(t, col.key); return }
                editTimer.current = setTimeout(() => { editTimer.current = null; p.onStartEdit(t, col.key) }, gridTiming.editDelay)
              }}
              onDoubleClick={(e) => {
                // Double-click anywhere on a row opens the task (MS Project "Task Information").
                e.stopPropagation()
                cancelEdit()
                p.onRowDoubleClick(t, col)
              }}>
              {content}
            </div>
          )
        })}
      </div>,
    )
  }
  return (
    <div className="relative" style={{ width, height }} data-testid="gantt-grid" role="grid" aria-rowcount={p.rows.length}>
      {out}
      {p.dropLine && (
        <div className="pointer-events-none absolute left-0 h-0.5" data-testid="gantt-drop-line"
          style={{ width, top: (p.dropLine.index + (p.dropLine.where === 'after' ? 1 : 0)) * p.rowH - 1, background: v('accent') }} />
      )}
    </div>
  )
})
