/**
 * Excel-like sort and filter for plain tables: pure helpers plus a small
 * local-state hook. A table describes its columns once (FilterColumnDef) and
 * keeps one TableState; ColumnHeader renders the controls, applyTableState
 * produces the rows to show. The state can live in React state
 * (useTableState) or in the URL (writeTableState / readTableState).
 */
import { useCallback, useMemo, useState } from 'react'
import { readNumberInput } from '../../lib/format'

export interface FilterColumnDef<Row> {
  key: string
  label: string
  /** values: a checkbox list of distinct values; number: a from/to range. */
  kind: 'values' | 'number'
  value: (row: Row) => string | number | null | undefined
  /** Text shown in the value list and matched by a values filter; default String(value). */
  display?: (row: Row) => string
  /** Sort key; default value. */
  sortValue?: (row: Row) => string | number | null | undefined
  /** Default true. */
  sortable?: boolean
  /** Default true. */
  filterable?: boolean
}

export interface ColumnFilter {
  /** Selected display values; undefined = no values filter. [] matches nothing. */
  values?: string[]
  min?: number | null
  max?: number | null
}

export type SortDir = 'asc' | 'desc'

export interface TableState {
  sort: { key: string; dir: SortDir } | null
  filters: Record<string, ColumnFilter>
}

export const EMPTY_TABLE_STATE: TableState = { sort: null, filters: {} }

/** How an empty cell reads in a value list. */
export const BLANK_LABEL = '(Blank)'

const isBlank = (v: unknown) => v === null || v === undefined || v === ''

/** The text a row shows for a column in the value list ('(Blank)' when empty). */
export function displayOf<Row>(row: Row, col: FilterColumnDef<Row>): string {
  if (col.display) {
    const d = col.display(row)
    return isBlank(d) ? BLANK_LABEL : d
  }
  const v = col.value(row)
  return isBlank(v) ? BLANK_LABEL : String(v)
}

/** A filter that actually narrows something. */
export function isFilterActive(f: ColumnFilter | undefined | null): boolean {
  if (!f) return false
  return f.values !== undefined || (f.min !== undefined && f.min !== null)
    || (f.max !== undefined && f.max !== null)
}

export function activeFilterCount(state: TableState): number {
  return Object.values(state.filters).filter(isFilterActive).length
}

function matches<Row>(row: Row, col: FilterColumnDef<Row>, f: ColumnFilter,
  selected?: Set<string>): boolean {
  if (f.values !== undefined
      && !(selected ?? new Set(f.values)).has(displayOf(row, col))) return false
  const hasMin = f.min !== undefined && f.min !== null
  const hasMax = f.max !== undefined && f.max !== null
  if (hasMin || hasMax) {
    const raw = col.value(row)
    const n = typeof raw === 'number' ? raw : isBlank(raw) ? NaN : Number(raw)
    if (!Number.isFinite(n)) return false
    if (hasMin && n < (f.min as number)) return false
    if (hasMax && n > (f.max as number)) return false
  }
  return true
}

/** Rows passing every active filter, optionally ignoring one column's own
 * filter (Excel lists a column's values from the rows the OTHER filters leave). */
export function filterRows<Row>(rows: Row[], cols: FilterColumnDef<Row>[],
  filters: Record<string, ColumnFilter>, exceptKey?: string): Row[] {
  const active = cols.filter((c) => c.key !== exceptKey && isFilterActive(filters[c.key]))
  if (active.length === 0) return rows
  // one Set per column, built once: a lookup per row, not a scan of the list
  const sets = new Map(active.map((c) => [c.key, filters[c.key].values !== undefined
    ? new Set(filters[c.key].values) : undefined]))
  return rows.filter((r) => active.every((c) => matches(r, c, filters[c.key], sets.get(c.key))))
}

const collator = new Intl.Collator(undefined, { numeric: true, sensitivity: 'base' })

/** Ascending compare; blanks are handled by the caller. */
function compareValues(a: string | number, b: string | number): number {
  if (typeof a === 'number' && typeof b === 'number') return a - b
  return collator.compare(String(a), String(b))
}

/** Stable sort by one column; blanks last in both directions. */
export function sortRows<Row>(rows: Row[], col: FilterColumnDef<Row>, dir: SortDir): Row[] {
  const key = col.sortValue ?? col.value
  const sign = dir === 'asc' ? 1 : -1
  return rows
    .map((row, i) => ({ row, i, k: key(row) }))
    .sort((a, b) => {
      const ab = isBlank(a.k), bb = isBlank(b.k)
      if (ab || bb) return ab === bb ? a.i - b.i : ab ? 1 : -1
      return sign * compareValues(a.k as string | number, b.k as string | number) || a.i - b.i
    })
    .map((x) => x.row)
}

/** Filter, then sort. Rows keep their incoming order where the sort ties. */
export function applyTableState<Row>(rows: Row[], cols: FilterColumnDef<Row>[],
  state: TableState): Row[] {
  const shown = filterRows(rows, cols, state.filters)
  const col = state.sort ? cols.find((c) => c.key === state.sort!.key) : undefined
  return col && col.sortable !== false ? sortRows(shown, col, state.sort!.dir) : shown
}

/** The column's distinct display values, sorted, '(Blank)' last. */
export function distinctValues<Row>(rows: Row[], col: FilterColumnDef<Row>): string[] {
  const set = new Set(rows.map((r) => displayOf(r, col)))
  const blank = set.delete(BLANK_LABEL)
  return [...[...set].sort((a, b) => collator.compare(a, b)), ...(blank ? [BLANK_LABEL] : [])]
}

/** The next sort for a click on key: asc, then desc, then none. */
export function nextSort(sort: TableState['sort'], key: string): TableState['sort'] {
  if (!sort || sort.key !== key) return { key, dir: 'asc' }
  return sort.dir === 'asc' ? { key, dir: 'desc' } : null
}

/** aria-sort for a column header. */
export function ariaSort(state: TableState, key: string): 'ascending' | 'descending' | 'none' {
  if (state.sort?.key !== key) return 'none'
  return state.sort.dir === 'asc' ? 'ascending' : 'descending'
}

/** A typed filter bound, read like every number input in the app
 * (lib/format readNumberInput, en-US: "1,234.5", "12.5"); an ambiguous
 * "7,5" or anything else that is not a number is 'invalid'. */
export function parseLooseNumber(raw: string): number | null | 'invalid' {
  const r = readNumberInput(raw)
  if (r.error) return 'invalid'
  return r.value
}

// ---------------------------------------------------------------- URL

/** URL keys: `<prefix>csort=key:asc`, `<prefix>f.<key>` once per selected
 * value (an empty `<prefix>f.<key>=` alone = nothing selected), and
 * `<prefix>n.<key>=min..max` (either side may be empty). */
export function tableParamKeys(params: URLSearchParams, prefix = ''): string[] {
  return [...new Set([...params.keys()].filter((k) =>
    k === `${prefix}csort` || k.startsWith(`${prefix}f.`) || k.startsWith(`${prefix}n.`)))]
}

/** Replace the table state keys in params (a copy is returned). */
export function writeTableState(params: URLSearchParams, state: TableState,
  prefix = ''): URLSearchParams {
  const next = new URLSearchParams(params)
  for (const k of tableParamKeys(next, prefix)) next.delete(k)
  if (state.sort) next.set(`${prefix}csort`, `${state.sort.key}:${state.sort.dir}`)
  for (const [key, f] of Object.entries(state.filters)) {
    if (!isFilterActive(f)) continue
    if (f.values !== undefined) {
      if (f.values.length === 0) next.append(`${prefix}f.${key}`, '')
      for (const v of f.values) next.append(`${prefix}f.${key}`, v)
    }
    const hasMin = f.min !== undefined && f.min !== null
    const hasMax = f.max !== undefined && f.max !== null
    if (hasMin || hasMax) {
      next.set(`${prefix}n.${key}`, `${hasMin ? f.min : ''}..${hasMax ? f.max : ''}`)
    }
  }
  return next
}

/** The table state held in params; keys of unknown columns are ignored. */
export function readTableState<Row>(params: URLSearchParams, cols: FilterColumnDef<Row>[],
  prefix = ''): TableState {
  const byKey = new Map(cols.map((c) => [c.key, c]))
  let sort: TableState['sort'] = null
  const rawSort = params.get(`${prefix}csort`)
  if (rawSort) {
    const at = rawSort.lastIndexOf(':')
    const key = at > 0 ? rawSort.slice(0, at) : rawSort
    const dir = at > 0 ? rawSort.slice(at + 1) : 'asc'
    const col = byKey.get(key)
    if (col && col.sortable !== false && (dir === 'asc' || dir === 'desc')) sort = { key, dir }
  }
  const filters: Record<string, ColumnFilter> = {}
  for (const k of tableParamKeys(params, prefix)) {
    if (k.startsWith(`${prefix}f.`)) {
      const key = k.slice(prefix.length + 2)
      const col = byKey.get(key)
      if (!col || col.filterable === false) continue
      const vals = params.getAll(k).filter((v) => v !== '')
      filters[key] = { ...filters[key], values: vals }
    } else if (k.startsWith(`${prefix}n.`)) {
      const key = k.slice(prefix.length + 2)
      const col = byKey.get(key)
      if (!col || col.filterable === false) continue
      const [lo = '', hi = ''] = (params.get(k) ?? '').split('..')
      const min = lo === '' ? null : Number(lo)
      const max = hi === '' ? null : Number(hi)
      const range: ColumnFilter = {}
      if (min !== null && Number.isFinite(min)) range.min = min
      if (max !== null && Number.isFinite(max)) range.max = max
      filters[key] = { ...filters[key], ...range }
    }
  }
  for (const k of Object.keys(filters)) if (!isFilterActive(filters[k])) delete filters[k]
  return { sort, filters }
}

// ---------------------------------------------------------------- hook

export interface TableStateApi {
  state: TableState
  setState: (s: TableState) => void
  toggleSort: (key: string) => void
  setFilter: (key: string, f: ColumnFilter | null) => void
  clearFilters: () => void
  activeCount: number
}

/** Pure state transitions, shared by the hook and URL-backed callers. */
export function withFilter(state: TableState, key: string, f: ColumnFilter | null): TableState {
  const filters = { ...state.filters }
  if (f && isFilterActive(f)) filters[key] = f
  else delete filters[key]
  return { ...state, filters }
}

/** Local (non-URL) table state. */
export function useTableState(initial: TableState = EMPTY_TABLE_STATE): TableStateApi {
  const [state, setState] = useState<TableState>(initial)
  const toggleSort = useCallback((key: string) =>
    setState((s) => ({ ...s, sort: nextSort(s.sort, key) })), [])
  const setFilter = useCallback((key: string, f: ColumnFilter | null) =>
    setState((s) => withFilter(s, key, f)), [])
  const clearFilters = useCallback(() => setState((s) => ({ ...s, filters: {} })), [])
  const activeCount = useMemo(() => activeFilterCount(state), [state])
  return { state, setState, toggleSort, setFilter, clearFilters, activeCount }
}
