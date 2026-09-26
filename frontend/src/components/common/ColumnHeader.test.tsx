import { describe, it, expect, afterEach } from 'vitest'
import { render, screen, cleanup, fireEvent, within } from '@testing-library/react'
import ColumnHeader from './ColumnHeader'
import TableFilterBar from './TableFilterBar'
import { applyTableState, ariaSort, useTableState, type FilterColumnDef } from './tableFilters'

interface R { id: number; dept: string; rate: number | null }
const ROWS: R[] = [
  { id: 1, dept: 'Tool Engineer', rate: 65 },
  { id: 2, dept: 'Quality', rate: 45 },
  { id: 3, dept: 'Sales', rate: null },
  { id: 4, dept: 'Quality', rate: 21.5 },
]
const COLS: FilterColumnDef<R>[] = [
  { key: 'dept', label: 'Department', kind: 'values', value: (r) => r.dept },
  { key: 'rate', label: 'Rate', kind: 'number', value: (r) => r.rate },
]

function Table() {
  const t = useTableState()
  const shown = applyTableState(ROWS, COLS, t.state)
  return (
    <div>
      <TableFilterBar count={t.activeCount} onClear={t.clearFilters} shown={shown.length} total={ROWS.length} />
      <table>
        <thead><tr>
          {COLS.map((c) => (
            <th key={c.key} aria-sort={ariaSort(t.state, c.key)}>
              <ColumnHeader col={c} rows={ROWS} cols={COLS} state={t.state}
                onToggleSort={t.toggleSort} onFilter={t.setFilter} />
            </th>
          ))}
        </tr></thead>
        <tbody>
          {shown.map((r) => (
            <tr key={r.id} data-testid="row"><td>{r.dept}</td><td>{r.rate ?? ''}</td></tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

const ids = () => screen.getAllByTestId('row').map((r) => r.textContent)
const dialog = () => screen.getByRole('dialog')

describe('ColumnHeader', () => {
  afterEach(cleanup)

  it('cycles the sort asc, desc, off by click and says so in aria-sort', () => {
    render(<Table />)
    const btn = screen.getByRole('button', { name: 'Rate' })
    const th = btn.closest('th')!
    expect(th.getAttribute('aria-sort')).toBe('none')
    fireEvent.click(btn)
    expect(th.getAttribute('aria-sort')).toBe('ascending')
    expect(ids()).toEqual(['Quality21.5', 'Quality45', 'Tool Engineer65', 'Sales'])
    fireEvent.click(btn)
    expect(th.getAttribute('aria-sort')).toBe('descending')
    expect(ids()[0]).toBe('Tool Engineer65')
    expect(ids()[3]).toBe('Sales')
    fireEvent.click(btn)
    expect(th.getAttribute('aria-sort')).toBe('none')
    expect(ids()[0]).toBe('Tool Engineer65')
  })

  it('filters by ticked values, with a search, and clears', () => {
    render(<Table />)
    const funnel = screen.getByRole('button', { name: 'Filter Department' })
    fireEvent.click(funnel)
    expect(funnel.getAttribute('aria-expanded')).toBe('true')
    const d = dialog()
    // focus moved into the popover (the search box)
    expect(document.activeElement).toBe(within(d).getByRole('searchbox'))
    // distinct values, sorted
    expect(within(d).getAllByRole('checkbox').slice(1).map((c) => c.closest('label')!.textContent))
      .toEqual(['Quality', 'Sales', 'Tool Engineer'])
    fireEvent.change(within(d).getByRole('searchbox'), { target: { value: 'qual' } })
    expect(within(d).getAllByRole('checkbox')).toHaveLength(2)     // select all + Quality
    fireEvent.click(within(d).getByRole('button', { name: 'Apply' }))
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(document.activeElement).toBe(funnel)
    expect(ids()).toEqual(['Quality45', 'Quality21.5'])
    expect(funnel.getAttribute('data-active')).toBe('true')
    expect(screen.getByTestId('table-filter-bar').textContent).toContain('1 filter active')
    expect(screen.getByTestId('table-filter-bar').textContent).toContain('2 of 4 rows')

    // untick one value without a search
    fireEvent.click(funnel)
    fireEvent.click(within(dialog()).getByRole('checkbox', { name: 'Quality' }))
    fireEvent.click(within(dialog()).getByRole('button', { name: 'Apply' }))
    expect(screen.queryAllByTestId('row')).toHaveLength(0)

    fireEvent.click(screen.getByRole('button', { name: 'Clear filters' }))
    expect(ids()).toHaveLength(4)
    expect(screen.queryByTestId('table-filter-bar')).toBeNull()
  })

  it('filters a number range read like every number input and refuses nonsense', () => {
    render(<Table />)
    fireEvent.click(screen.getByRole('button', { name: 'Filter Rate' }))
    const d = dialog()
    fireEvent.change(within(d).getByLabelText('From'), { target: { value: 'abc' } })
    expect(within(d).getByRole('alert').textContent).toContain('Enter a number')
    expect((within(d).getByRole('button', { name: 'Apply' }) as HTMLButtonElement).disabled).toBe(true)
    // "21,5" is ambiguous in en-US (lib/format readNumberInput): refused
    fireEvent.change(within(d).getByLabelText('From'), { target: { value: '21,5' } })
    expect((within(d).getByRole('button', { name: 'Apply' }) as HTMLButtonElement).disabled).toBe(true)
    fireEvent.change(within(d).getByLabelText('From'), { target: { value: '21.5' } })
    fireEvent.change(within(d).getByLabelText('To'), { target: { value: '50' } })
    fireEvent.submit(within(d).getByLabelText('To').closest('form')!)
    expect(ids()).toEqual(['Quality45', 'Quality21.5'])
    // the button's accessible name says the column is filtered, and how
    const funnel = screen.getByRole('button', { name: /^Filter Rate, filtered: / })
    expect(funnel.getAttribute('aria-label')).toBe('Filter Rate, filtered: 21.5 to 50')
    // Clear in the popover removes the range
    fireEvent.click(funnel)
    fireEvent.click(within(dialog()).getByRole('button', { name: 'Clear' }))
    expect(ids()).toHaveLength(4)
  })

  it('closes on Escape without applying and returns focus; Tab stays inside', () => {
    render(<Table />)
    const funnel = screen.getByRole('button', { name: 'Filter Department' })
    fireEvent.click(funnel)
    const d = dialog()
    fireEvent.click(within(d).getByRole('checkbox', { name: 'Sales' }))
    const apply = within(d).getByRole('button', { name: 'Apply' })
    apply.focus()
    fireEvent.keyDown(apply, { key: 'Tab' })
    expect(document.activeElement).toBe(within(d).getByRole('searchbox'))
    fireEvent.keyDown(d, { key: 'Escape' })
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(document.activeElement).toBe(funnel)
    expect(ids()).toHaveLength(4)
  })

  it('closes on Escape while focus is still on the funnel, and at document level', () => {
    render(<Table />)
    const funnel = screen.getByRole('button', { name: 'Filter Department' })
    fireEvent.click(funnel)
    funnel.focus()                          // focus not yet moved into the popover
    fireEvent.keyDown(funnel, { key: 'Escape' })
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(document.activeElement).toBe(funnel)
    expect(funnel.getAttribute('aria-expanded')).toBe('false')

    fireEvent.click(funnel)
    ;(document.activeElement as HTMLElement | null)?.blur()
    fireEvent.keyDown(document, { key: 'Escape' })
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(document.activeElement).toBe(funnel)
  })

  it('leaves Escape in another field alone', () => {
    render(<><input aria-label="cell" /><Table /></>)
    fireEvent.click(screen.getByRole('button', { name: 'Filter Department' }))
    const cell = screen.getByLabelText('cell')
    cell.focus()
    fireEvent.keyDown(cell, { key: 'Escape' })
    expect(screen.getByRole('dialog')).toBeDefined()
  })

  it('closes on a press outside', () => {
    render(<Table />)
    fireEvent.click(screen.getByRole('button', { name: 'Filter Rate' }))
    expect(dialog()).toBeDefined()
    fireEvent.mouseDown(document.body)
    expect(screen.queryByRole('dialog')).toBeNull()
  })
})
