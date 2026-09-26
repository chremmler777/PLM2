/**
 * The inside of a sortable, filterable table header cell (the caller keeps
 * its own <th> and sets aria-sort={ariaSort(state, col.key)}).
 *
 * The label is a sort button (ascending, descending, off). The funnel opens a
 * filter popover: a searchable checkbox list of the column's values, or a
 * from/to range for number columns. The popover is portalled to <body> with
 * fixed positioning, so an overflow-x-auto table wrapper never clips it, and
 * it only listens to keys inside itself, so cells being edited keep theirs.
 */
import { useEffect, useId, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { ArrowDown, ArrowUp, ArrowUpDown, Filter, Search } from 'lucide-react'
import { btnSm } from './buttonStyles'
import {
  type ColumnFilter, type FilterColumnDef, type TableState,
  distinctValues, filterRows, isFilterActive, parseLooseNumber,
} from './tableFilters'

export interface ColumnHeaderProps<Row> {
  col: FilterColumnDef<Row>
  /** Every row of the table (unfiltered); the value list shows the values
   * the other columns' filters leave, plus the ones selected here. */
  rows: Row[]
  /** All filterable columns, so the value list respects the other filters. */
  cols: FilterColumnDef<Row>[]
  state: TableState
  onToggleSort: (key: string) => void
  onFilter: (key: string, filter: ColumnFilter | null) => void
  /** Right-aligns the label (number columns). */
  align?: 'left' | 'right'
  /** Tooltip on the label. */
  title?: string
}

const FOCUS = 'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400'
const INPUT =
  'w-full rounded border border-slate-600 bg-slate-900 px-2 py-1 text-sm text-slate-100 ' +
  'placeholder:text-slate-500 focus:border-sky-500 focus:outline-none focus:ring-1 focus:ring-sky-500/40'

export default function ColumnHeader<Row>({
  col, rows, cols, state, onToggleSort, onFilter, align = 'left', title,
}: ColumnHeaderProps<Row>) {
  const [open, setOpen] = useState(false)
  const btnRef = useRef<HTMLButtonElement>(null)
  const sortable = col.sortable !== false
  const filterable = col.filterable !== false
  const filter = state.filters[col.key]
  const active = isFilterActive(filter)
  const dir = state.sort?.key === col.key ? state.sort.dir : null
  const SortIcon = dir === 'asc' ? ArrowUp : dir === 'desc' ? ArrowDown : ArrowUpDown

  const close = (refocus: boolean) => {
    setOpen(false)
    if (refocus) btnRef.current?.focus()
  }

  return (
    <span className={`inline-flex items-center gap-0.5 ${align === 'right' ? 'flex-row-reverse' : ''}`}>
      {sortable ? (
        <button type="button" onClick={() => onToggleSort(col.key)} title={title}
          className={`inline-flex items-center gap-1 rounded px-0.5 [text-transform:inherit] hover:text-slate-200 ${FOCUS} ${dir ? 'text-sky-300' : ''}`}>
          <span>{col.label}</span>
          <SortIcon aria-hidden="true" size={12}
            className={dir ? 'text-sky-300' : 'text-slate-500'} />
        </button>
      ) : <span title={title}>{col.label}</span>}
      {filterable && (
        <button ref={btnRef} type="button"
          aria-label={active ? `Filter ${col.label}, filtered: ${describe(filter)}` : `Filter ${col.label}`}
          aria-haspopup="dialog" aria-expanded={open}
          data-active={active ? 'true' : undefined}
          title={active ? `Filtered: ${describe(filter)}` : `Filter ${col.label}`}
          onClick={() => setOpen((o) => !o)}
          className={`inline-flex h-6 w-6 items-center justify-center rounded ${FOCUS} ${
            active ? 'bg-sky-500/20 text-sky-300' : 'text-slate-500 hover:bg-slate-700/60 hover:text-slate-200'}`}>
          <Filter aria-hidden="true" size={11} strokeWidth={active ? 2.5 : 2} />
        </button>
      )}
      {open && filterable && (
        <FilterPopover col={col} rows={rows} cols={cols} state={state} anchor={btnRef}
          onApply={(f) => { onFilter(col.key, f); close(true) }}
          onClose={close} />
      )}
    </span>
  )
}

function describe(f: ColumnFilter | undefined): string {
  if (!f) return ''
  const parts: string[] = []
  if (f.values !== undefined) parts.push(`${f.values.length} selected`)
  if (f.min != null || f.max != null) parts.push(`${f.min ?? ''} to ${f.max ?? ''}`.trim())
  return parts.join(', ')
}

interface PopoverProps<Row> {
  col: FilterColumnDef<Row>
  rows: Row[]
  cols: FilterColumnDef<Row>[]
  state: TableState
  anchor: React.RefObject<HTMLButtonElement | null>
  onApply: (f: ColumnFilter | null) => void
  onClose: (refocus: boolean) => void
}

const WIDTH = 256

function FilterPopover<Row>({ col, rows, cols, state, anchor, onApply, onClose }: PopoverProps<Row>) {
  const ref = useRef<HTMLDivElement>(null)
  const [pos, setPos] = useState<{ top: number; left: number } | null>(null)
  const current = state.filters[col.key]

  // Anchored to the funnel; follows scrolling and resizing.
  useLayoutEffect(() => {
    const place = () => {
      const r = anchor.current?.getBoundingClientRect()
      if (!r) return
      const vw = window.innerWidth || 1024
      setPos({ top: r.bottom + 4, left: Math.max(8, Math.min(r.left, vw - WIDTH - 8)) })
    }
    place()
    window.addEventListener('resize', place)
    window.addEventListener('scroll', place, true)
    return () => {
      window.removeEventListener('resize', place)
      window.removeEventListener('scroll', place, true)
    }
  }, [anchor])

  // A press outside closes it (without stealing focus from where it went).
  useEffect(() => {
    const onDown = (e: MouseEvent) => {
      const t = e.target as Node
      if (ref.current?.contains(t) || anchor.current?.contains(t)) return
      onClose(false)
    }
    document.addEventListener('mousedown', onDown)
    return () => document.removeEventListener('mousedown', onDown)
  }, [anchor, onClose])

  // Focus moves into the popover.
  useEffect(() => {
    const first = ref.current?.querySelector<HTMLElement>('input, button')
    first?.focus()
  }, [])

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Escape') {
      e.preventDefault()
      e.stopPropagation()
      onClose(true)
      return
    }
    if (e.key === 'Tab' && ref.current) {
      // Tab cycles inside the popover.
      const items = [...ref.current.querySelectorAll<HTMLElement>(
        'input:not(:disabled), button:not(:disabled)')]
      if (items.length === 0) return
      const first = items[0], last = items[items.length - 1]
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus() }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus() }
    }
  }

  return createPortal(
    <div ref={ref} role="dialog" aria-label={`Filter ${col.label}`} onKeyDown={onKeyDown}
      data-testid={`column-filter-${col.key}`}
      style={{ position: 'fixed', top: pos?.top ?? 0, left: pos?.left ?? 0, width: WIDTH,
        visibility: pos ? 'visible' : 'hidden' }}
      className="z-50 rounded-lg border border-slate-600 bg-slate-800 p-3 text-left text-sm normal-case tracking-normal text-slate-200 shadow-xl shadow-black/40">
      {col.kind === 'number'
        ? <RangeForm current={current} onApply={onApply} />
        : <ValuesForm col={col} rows={rows} cols={cols} state={state} current={current} onApply={onApply} />}
    </div>,
    document.body,
  )
}

function ValuesForm<Row>({ col, rows, cols, state, current, onApply }: {
  col: FilterColumnDef<Row>; rows: Row[]; cols: FilterColumnDef<Row>[]; state: TableState
  current: ColumnFilter | undefined; onApply: (f: ColumnFilter | null) => void
}) {
  const values = useMemo(() => {
    const base = distinctValues(filterRows(rows, cols, state.filters, col.key), col)
    const extra = (current?.values ?? []).filter((v) => !base.includes(v))
    return [...base, ...extra]
  }, [rows, cols, state.filters, col, current])
  const [checked, setChecked] = useState<Set<string>>(
    () => new Set(current?.values ?? values))
  const [q, setQ] = useState('')
  const searchId = useId()
  const visible = q.trim()
    ? values.filter((v) => v.toLowerCase().includes(q.trim().toLowerCase()))
    : values
  const allVisible = visible.length > 0 && visible.every((v) => checked.has(v))

  const toggle = (v: string) => setChecked((s) => {
    const n = new Set(s)
    if (n.has(v)) n.delete(v); else n.add(v)
    return n
  })
  const toggleAll = () => setChecked((s) => {
    const n = new Set(s)
    for (const v of visible) { if (allVisible) n.delete(v); else n.add(v) }
    return n
  })
  const apply = () => {
    // With a search, Excel keeps what the search found and was ticked.
    const pick = q.trim() ? visible.filter((v) => checked.has(v)) : values.filter((v) => checked.has(v))
    onApply(pick.length === values.length && !q.trim() ? null : { values: pick })
  }

  return (
    <form onSubmit={(e) => { e.preventDefault(); apply() }}>
      <label htmlFor={searchId} className="sr-only">Search values</label>
      <div className="relative">
        <Search aria-hidden="true" size={13} className="pointer-events-none absolute left-2 top-1/2 -translate-y-1/2 text-slate-500" />
        <input id={searchId} type="search" value={q} onChange={(e) => setQ(e.target.value)}
          placeholder="Search" className={`${INPUT} pl-7`} />
      </div>
      <div className="mt-2 max-h-56 overflow-y-auto rounded border border-slate-700 bg-slate-900/60 py-1">
        {visible.length === 0 ? (
          <p className="px-2 py-2 text-xs text-slate-500">No matching values</p>
        ) : (
          <>
            <label className="flex cursor-pointer items-center gap-2 border-b border-slate-700/70 px-2 py-1 font-medium hover:bg-slate-700/40">
              <input type="checkbox" checked={allVisible} onChange={toggleAll}
                className="h-3.5 w-3.5 accent-sky-500" />
              {q.trim() ? 'Select all matches' : 'Select all'}
            </label>
            {visible.map((v) => (
              <label key={v} className="flex cursor-pointer items-center gap-2 px-2 py-1 hover:bg-slate-700/40">
                <input type="checkbox" checked={checked.has(v)} onChange={() => toggle(v)}
                  className="h-3.5 w-3.5 accent-sky-500" />
                <span className="truncate" title={v}>{v}</span>
              </label>
            ))}
          </>
        )}
      </div>
      <div className="mt-3 flex items-center justify-end gap-2">
        <button type="button" onClick={() => onApply(null)} className={btnSm.ghost}>Clear</button>
        <button type="submit" className={btnSm.primary}>Apply</button>
      </div>
    </form>
  )
}

function RangeForm({ current, onApply }: {
  current: ColumnFilter | undefined; onApply: (f: ColumnFilter | null) => void
}) {
  const [lo, setLo] = useState(current?.min != null ? String(current.min) : '')
  const [hi, setHi] = useState(current?.max != null ? String(current.max) : '')
  const loId = useId(), hiId = useId(), errId = useId()
  const min = parseLooseNumber(lo), max = parseLooseNumber(hi)
  const invalid = min === 'invalid' || max === 'invalid'
  const reversed = !invalid && min !== null && max !== null && min > max
  const error = invalid ? 'Enter a number, for example 12.5' : reversed ? 'From is above To' : null
  const apply = () => {
    if (error) return
    onApply(min === null && max === null ? null : { min: min as number | null, max: max as number | null })
  }
  return (
    <form onSubmit={(e) => { e.preventDefault(); apply() }}>
      <div className="grid grid-cols-2 gap-2">
        <div>
          <label htmlFor={loId} className="text-xs text-slate-400">From</label>
          <input id={loId} inputMode="decimal" value={lo} onChange={(e) => setLo(e.target.value)}
            aria-invalid={min === 'invalid' || reversed ? true : undefined}
            aria-describedby={error ? errId : undefined}
            className={`${INPUT} mt-0.5 text-right tabular-nums`} />
        </div>
        <div>
          <label htmlFor={hiId} className="text-xs text-slate-400">To</label>
          <input id={hiId} inputMode="decimal" value={hi} onChange={(e) => setHi(e.target.value)}
            aria-invalid={max === 'invalid' || reversed ? true : undefined}
            aria-describedby={error ? errId : undefined}
            className={`${INPUT} mt-0.5 text-right tabular-nums`} />
        </div>
      </div>
      <p className="mt-1 text-xs text-slate-500">Both ends included; leave one empty for open.</p>
      {error && <p id={errId} role="alert" className="mt-1 text-xs text-rose-300">{error}</p>}
      <div className="mt-3 flex items-center justify-end gap-2">
        <button type="button" onClick={() => onApply(null)} className={btnSm.ghost}>Clear</button>
        <button type="submit" disabled={!!error} className={btnSm.primary}>Apply</button>
      </div>
    </form>
  )
}
