import { describe, it, expect } from 'vitest'
import {
  BLANK_LABEL, EMPTY_TABLE_STATE, activeFilterCount, applyTableState, ariaSort, distinctValues,
  nextSort, parseLooseNumber, readTableState, withFilter, writeTableState,
  type FilterColumnDef, type TableState,
} from './tableFilters'

interface R { id: number; name: string | null; rate: number | null }
const rows: R[] = [
  { id: 1, name: 'Tool 10', rate: 50 },
  { id: 2, name: 'tool 9', rate: null },
  { id: 3, name: null, rate: 20 },
  { id: 4, name: 'Quality', rate: 75.5 },
]
const cols: FilterColumnDef<R>[] = [
  { key: 'name', label: 'Name', kind: 'values', value: (r) => r.name },
  { key: 'rate', label: 'Rate', kind: 'number', value: (r) => r.rate },
]
const ids = (rs: R[]) => rs.map((r) => r.id)

describe('tableFilters', () => {
  it('sorts numeric-aware and case-blind, blanks last both ways, stable', () => {
    const asc = applyTableState(rows, cols, { sort: { key: 'name', dir: 'asc' }, filters: {} })
    expect(ids(asc)).toEqual([4, 2, 1, 3])
    const desc = applyTableState(rows, cols, { sort: { key: 'name', dir: 'desc' }, filters: {} })
    expect(ids(desc)).toEqual([1, 2, 4, 3])
    const byRate = applyTableState(rows, cols, { sort: { key: 'rate', dir: 'desc' }, filters: {} })
    expect(ids(byRate)).toEqual([4, 1, 3, 2])
    // no sort: incoming order
    expect(ids(applyTableState(rows, cols, EMPTY_TABLE_STATE))).toEqual([1, 2, 3, 4])
  })

  it('filters by values (blank included) and by an inclusive number range', () => {
    let s: TableState = withFilter(EMPTY_TABLE_STATE, 'name', { values: ['Quality', BLANK_LABEL] })
    expect(ids(applyTableState(rows, cols, s))).toEqual([3, 4])
    s = withFilter(EMPTY_TABLE_STATE, 'rate', { min: 20, max: 50 })
    expect(ids(applyTableState(rows, cols, s))).toEqual([1, 3])
    s = withFilter(s, 'name', { values: [] })
    expect(applyTableState(rows, cols, s)).toEqual([])
    expect(activeFilterCount(s)).toBe(2)
    expect(activeFilterCount(withFilter(s, 'rate', null))).toBe(1)
  })

  it('lists distinct values sorted with (Blank) last', () => {
    expect(distinctValues(rows, cols[0])).toEqual(['Quality', 'tool 9', 'Tool 10', BLANK_LABEL])
  })

  it('cycles the sort asc, desc, off and reports aria-sort', () => {
    let sort = nextSort(null, 'name')
    expect(sort).toEqual({ key: 'name', dir: 'asc' })
    sort = nextSort(sort, 'name')
    expect(sort).toEqual({ key: 'name', dir: 'desc' })
    expect(ariaSort({ sort, filters: {} }, 'name')).toBe('descending')
    expect(ariaSort({ sort, filters: {} }, 'rate')).toBe('none')
    expect(nextSort(sort, 'name')).toBeNull()
    expect(nextSort(sort, 'rate')).toEqual({ key: 'rate', dir: 'asc' })
  })

  it('reads dot and comma decimals', () => {
    expect(parseLooseNumber('7,5')).toBe(7.5)
    expect(parseLooseNumber('1,234.5')).toBe(1234.5)
    expect(parseLooseNumber(' 12 ')).toBe(12)
    expect(parseLooseNumber('')).toBeNull()
    expect(parseLooseNumber('abc')).toBe('invalid')
  })

  it('round-trips through the URL, keeps other params, ignores unknown keys', () => {
    const state: TableState = {
      sort: { key: 'rate', dir: 'desc' },
      filters: { name: { values: ['a, b', 'x|y', BLANK_LABEL] }, rate: { min: 1.5, max: null } },
    }
    const params = writeTableState(new URLSearchParams('q=keep&sort=recent&f.old=1'), state)
    expect(params.get('q')).toBe('keep')
    expect(params.get('sort')).toBe('recent')
    expect(params.has('f.old')).toBe(false)
    const back = readTableState(new URLSearchParams(params.toString()), cols)
    expect(back).toEqual({ sort: { key: 'rate', dir: 'desc' },
      filters: { name: { values: ['a, b', 'x|y', BLANK_LABEL] }, rate: { min: 1.5 } } })
    // nothing selected survives as an empty selection
    const none = writeTableState(new URLSearchParams(), withFilter(EMPTY_TABLE_STATE, 'name', { values: [] }))
    expect(readTableState(none, cols).filters.name).toEqual({ values: [] })
    const junk = readTableState(new URLSearchParams('csort=bogus:asc&f.bogus=1&n.rate=x..'), cols)
    expect(junk).toEqual({ sort: null, filters: {} })
    // a prefix keeps two tables apart
    const p = writeTableState(new URLSearchParams(), state, 'm.')
    expect(readTableState(p, cols, 'm.').sort).toEqual(state.sort)
    expect(readTableState(p, cols).sort).toBeNull()
  })
})
