import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, cleanup, fireEvent, waitFor, within } from '@testing-library/react'
import { toast } from 'sonner'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import CostSheetPage from './CostSheetPage'
import PublishDialog from '../components/costSheet/PublishDialog'
import PlantCurrencies from '../components/costSheet/PlantCurrencies'
import SheetCell from '../components/costSheet/SheetCell'
import { COLUMNS, SECTION_LABELS, sortRows, type SheetContext } from '../components/costSheet/columns'
import { diffCount } from '../components/costSheet/DiffPanel'
import { costSheetApi } from '../api/costSheet'
import { NUMBER_INPUT_HINT, NUMBER_INPUT_INVALID, addDaysIso, formatDate, todayIso } from '../lib/format'

vi.mock('../api/costSheet', () => ({
  costSheetApi: {
    overview: vi.fn(), version: vi.fn(), diff: vi.fn(), deleteDraft: vi.fn(),
    createDraft: vi.fn(), addMissingDepartments: vi.fn(), addRow: vi.fn(), exportUrl: () => '#',
  },
}))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

const ctx: SheetContext = {
  departments: [{ id: 1, name: 'Tooling', is_active: true }, { id: 2, name: 'Quality', is_active: true }],
  plants: [{ id: 7, name: 'Toccoa', code: 'us', is_active: true, currency: 'USD', currency_confirmed: false }],
  machineClasses: [{ id: 3, name: 'big', tonnage_min: 800, tonnage_max: null, sort_order: 0, is_active: true }],
  currencies: ['EUR', 'USD'],
}

const overview = {
  versions: [{ id: 9, version: 2, status: 'draft', valid_from: null, valid_to: null, note: null,
               based_on_version_id: null, created_at: null, published_at: null, published_by: null }],
  current_version_id: null, draft_version_id: 9, can_edit: true,
  stale: { stale: false, review_months: 12, latest_version: 1, reviewed_on: null, due_on: null, reason: null },
  departments: ctx.departments, plants: ctx.plants, currencies: ctx.currencies,
  machine_classes: ctx.machineClasses,
}

const wrap = (ui: React.ReactNode) => render(
  <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <MemoryRouter>{ui}</MemoryRouter>
  </QueryClientProvider>)

describe('CostSheetPage', () => {
  afterEach(cleanup)

  it('offers Discard draft when a draft fails to load', async () => {
    vi.mocked(costSheetApi.overview).mockResolvedValue(overview as never)
    vi.mocked(costSheetApi.version).mockRejectedValue({ response: { data: { detail: 'boom' } } })
    wrap(<CostSheetPage />)
    expect(await screen.findByText('This version could not be loaded.')).toBeDefined()
    expect(screen.getByText('boom')).toBeDefined()
    fireEvent.click(screen.getAllByRole('button', { name: 'Discard draft' })[0])
    expect(await screen.findByText('Discard draft version 2?')).toBeDefined()
  })
})

describe('CostSheetPage rates tab (one rate per department and plant)', () => {
  afterEach(cleanup)
  const depts = [...ctx.departments, { id: 5, name: 'Logistics', is_active: false }]
  const rate = (id: number, department_id: number, plant_id: number | null, hourly_rate: number | null) => ({
    id, department_id, plant_id, hourly_rate, position: null, currency: 'USD', min_factor: null, note: null,
    effective_rate: hourly_rate, overhead: null,
  })
  const draft = {
    id: 9, version: 2, status: 'draft', valid_from: null, valid_to: null, note: null,
    based_on_version_id: null, created_at: null, published_at: null, published_by: null,
    rates: [rate(1, 1, null, 50), rate(2, 2, 7, null), rate(3, 5, 7, 40), rate(4, 1, 7, null)],
    machine_rates: [], sampling_rates: [], overheads: [],
  }
  const open = async () => {
    vi.mocked(costSheetApi.overview).mockResolvedValue({ ...overview, departments: depts } as never)
    vi.mocked(costSheetApi.version).mockResolvedValue(draft as never)
    wrap(<CostSheetPage />)
    await screen.findByTestId('missing-rate-count')
  }
  const rowCount = () => screen.getAllByRole('row').length - 1     // minus the header

  it('hides retired departments until asked, and counts the rows without a rate', async () => {
    await open()
    expect(screen.getByRole('tab', { name: /Rates/ })).toBeDefined()
    expect(rowCount()).toBe(3)
    expect(screen.getByTestId('missing-rate-count').textContent).toContain('2 rows have no rate yet')
    fireEvent.click(within(screen.getByTestId('show-retired')).getByRole('checkbox'))
    expect(rowCount()).toBe(4)
    expect(screen.getAllByText('Retired').length).toBe(1)
    // Only the rows still to fill.
    fireEvent.click(within(screen.getByTestId('missing-rate-count')).getByRole('checkbox'))
    expect(rowCount()).toBe(2)
  })

  it('adds the missing departments with empty rates', async () => {
    await open()
    vi.mocked(costSheetApi.addMissingDepartments).mockResolvedValue({ ...draft, added: 2 } as never)
    fireEvent.click(screen.getByTestId('add-missing-departments'))
    await waitFor(() => expect(toast.success).toHaveBeenCalledWith('2 rows added, rates empty'))
    expect(costSheetApi.addMissingDepartments).toHaveBeenCalledWith(9)
  })

  it('says a department and plant already has a row before sending the add', async () => {
    await open()
    fireEvent.click(screen.getByRole('button', { name: '+ Add row' }))
    // The blank line starts at the first active department (Tooling), all plants: taken.
    expect(screen.getByTestId('sheet-add-error').textContent)
      .toBe('Tooling already has a rate for all plants. Edit that row instead.')
    expect((screen.getByRole('button', { name: 'Add row' }) as HTMLButtonElement).disabled).toBe(true)
    expect(costSheetApi.addRow).not.toHaveBeenCalled()
  })

  it('filters by department and sorts by rate like a spreadsheet', async () => {
    await open()
    fireEvent.click(screen.getByRole('button', { name: 'Filter Department' }))
    const d = screen.getByRole('dialog')
    fireEvent.change(within(d).getByRole('searchbox'), { target: { value: 'Quality' } })
    fireEvent.click(within(d).getByRole('button', { name: 'Apply' }))
    expect(rowCount()).toBe(1)
    expect(screen.getByTestId('table-filter-bar').textContent).toContain('1 filter active')
    fireEvent.click(screen.getByRole('button', { name: 'Clear filters' }))
    expect(rowCount()).toBe(3)
    const sortBtn = screen.getByRole('button', { name: 'Rate / h' })
    fireEvent.click(sortBtn)
    expect(sortBtn.closest('th')!.getAttribute('aria-sort')).toBe('ascending')
  })
})

describe('CostSheetPage new draft', () => {
  afterEach(cleanup)

  it('says which version the draft was copied from, not "the current rates"', async () => {
    // The latest published version (v3) is valid only from next month: the
    // draft copies it, so the toast names it.
    const published = [
      { id: 5, version: 3, status: 'published', valid_from: addDaysIso(todayIso(), 30), valid_to: null, note: null,
        based_on_version_id: null, created_at: null, published_at: null, published_by: null },
      { id: 4, version: 2, status: 'published', valid_from: '2026-01-01', valid_to: null, note: null,
        based_on_version_id: null, created_at: null, published_at: null, published_by: null },
    ]
    vi.mocked(costSheetApi.overview).mockResolvedValue({ ...overview, versions: published,
      current_version_id: 4, draft_version_id: null } as never)
    vi.mocked(costSheetApi.version).mockResolvedValue({ id: 4, version: 2, status: 'published', rates: [], machine_rates: [], sampling_rates: [], overheads: [] } as never)
    vi.mocked(costSheetApi.createDraft).mockResolvedValue({ id: 6, version: 4, status: 'draft',
      based_on_version_id: 5, rates: [], machine_rates: [], sampling_rates: [], overheads: [] } as never)
    wrap(<CostSheetPage />)
    fireEvent.click(await screen.findByRole('button', { name: 'New draft' }))
    await waitFor(() => expect(toast.success).toHaveBeenCalledWith('Draft version 4 started from v3'))
  })
})

describe('PublishDialog', () => {
  afterEach(cleanup)

  it('needs a confirmation for a backdated valid-from', () => {
    const onPublish = vi.fn()
    const past = addDaysIso(todayIso(), -3)
    render(<PublishDialog open version={2} defaultValidFrom={past} defaultNote={null}
                          latestValidFrom={null} latestVersion={null} changeCount={1} busy={false}
                          onCancel={() => {}} onPublish={onPublish} />)
    const publish = screen.getByRole('button', { name: 'Publish' }) as HTMLButtonElement
    expect(publish.disabled).toBe(true)
    fireEvent.click(screen.getByLabelText('Publish backdated anyway'))
    expect(publish.disabled).toBe(false)
    fireEvent.click(publish)
    expect(onPublish).toHaveBeenCalledWith(past, '', true)
  })

  it('shows the date as d MMM yyyy and needs no confirmation for a future date', () => {
    const onPublish = vi.fn()
    const future = addDaysIso(todayIso(), 10)
    render(<PublishDialog open version={2} defaultValidFrom={future} defaultNote={null}
                          latestValidFrom={null} latestVersion={null} changeCount={1} busy={false}
                          onCancel={() => {}} onPublish={onPublish} />)
    expect((screen.getByLabelText('Valid from') as HTMLInputElement).value).toBe(formatDate(future))
    fireEvent.click(screen.getByRole('button', { name: 'Publish' }))
    expect(onPublish).toHaveBeenCalledWith(future, '', false)
  })

  it('updates its hints while the date is typed, and tells the truth about backdating', () => {
    const past = addDaysIso(todayIso(), -3)
    const future = addDaysIso(todayIso(), 10)
    render(<PublishDialog open version={3} defaultValidFrom={future} defaultNote={null}
                          latestValidFrom="2026-01-01" latestVersion={2} changeCount={1} busy={false}
                          onCancel={() => {}} onPublish={() => {}} />)
    expect(screen.getByTestId('publish-ends-on').textContent).toContain(formatDate(addDaysIso(future, -1)))
    // Typed, not blurred: the hint follows at once.
    fireEvent.change(screen.getByLabelText('Valid from'), { target: { value: past } })
    expect(screen.getByTestId('publish-ends-on').textContent).toContain(formatDate(addDaysIso(past, -1)))
    const warn = screen.getByTestId('publish-backdated').textContent ?? ''
    expect(warn).toContain('already priced keep the rate')
    expect(warn).toContain('Changes created since then are priced with this version')
    expect(warn).not.toMatch(/will be priced with this version\.$/)
  })
})

describe('cost sheet pieces', () => {
  afterEach(cleanup)

  it('never commits a non-finite number', () => {
    const onCommit = vi.fn()
    const col = COLUMNS.rates.find((c) => c.key === 'hourly_rate')!
    render(<SheetCell col={col} row={{ id: 1, hourly_rate: 5, currency: 'EUR' }} ctx={ctx} editable
                      onCommit={onCommit} />)
    const input = screen.getByLabelText('Rate / h')
    fireEvent.change(input, { target: { value: 'Infinity' } })
    fireEvent.blur(input)
    fireEvent.change(input, { target: { value: 'abc' } })
    fireEvent.blur(input)
    expect(onCommit).not.toHaveBeenCalled()
    expect(input.getAttribute('aria-invalid')).toBe('true')
    // "7,5" is German for 7.5 but a comma only groups thousands: refused, flagged.
    fireEvent.change(input, { target: { value: '7,5' } })
    fireEvent.blur(input)
    expect(onCommit).not.toHaveBeenCalled()
    expect(input.getAttribute('aria-invalid')).toBe('true')
    expect((input as HTMLInputElement).value).toBe('7,5')
    fireEvent.change(input, { target: { value: '7.5' } })
    fireEvent.blur(input)
    expect(onCommit).toHaveBeenCalledWith(7.5)
    expect(input.getAttribute('aria-invalid')).toBeNull()
    fireEvent.change(input, { target: { value: '12,500' } })
    fireEvent.blur(input)
    expect(onCommit).toHaveBeenLastCalledWith(12500)
  })

  it('says visibly why a typed number was refused: ambiguous or not a number', () => {
    const onCommit = vi.fn()
    const col = COLUMNS.rates.find((c) => c.key === 'hourly_rate')!
    render(<SheetCell col={col} row={{ id: 1, hourly_rate: 5, currency: 'EUR' }} ctx={ctx} editable
                      onCommit={onCommit} />)
    const input = screen.getByLabelText('Rate / h')
    fireEvent.change(input, { target: { value: '1.234' } })
    fireEvent.blur(input)
    expect(screen.getByTestId('sheet-cell-refused').textContent).toBe(`Not saved. ${NUMBER_INPUT_HINT}`)
    expect(input.getAttribute('title')).toBe(`Not saved. ${NUMBER_INPUT_HINT}`)
    fireEvent.change(input, { target: { value: 'abc' } })
    expect(screen.queryByTestId('sheet-cell-refused')).toBeNull()
    fireEvent.blur(input)
    expect(screen.getByTestId('sheet-cell-refused').textContent).toBe(`Not saved. ${NUMBER_INPUT_INVALID}`)
    expect(onCommit).not.toHaveBeenCalled()
  })

  it.each([1.234, 1e-7, 2e21])('never refuses a stored %s on a plain focus and blur', (v) => {
    const onCommit = vi.fn()
    const col = COLUMNS.machines.find((c) => c.key === 'tonnage_min')!
    render(<SheetCell col={col} row={{ id: 1, [col.key]: v }} ctx={ctx} editable onCommit={onCommit} />)
    const input = screen.getByLabelText(col.label) as HTMLInputElement
    fireEvent.focus(input)
    fireEvent.blur(input)
    expect(input.getAttribute('aria-invalid')).toBeNull()
    expect(screen.queryByTestId('sheet-cell-refused')).toBeNull()
    expect(onCommit).not.toHaveBeenCalled()
    // The edit text itself reads back to the stored number.
    fireEvent.focus(input)
    fireEvent.change(input, { target: { value: `${input.value} ` } })
    fireEvent.blur(input)
    expect(input.getAttribute('aria-invalid')).toBeNull()
    expect(onCommit).not.toHaveBeenCalled()
  })

  it('flags plant currencies Finance has not confirmed', () => {
    const onSet = vi.fn()
    render(<PlantCurrencies plants={ctx.plants} currencies={ctx.currencies} canEdit onSet={onSet} />)
    expect(screen.getByText(/set by location; Sales or Finance to confirm/)).toBeDefined()
    fireEvent.click(screen.getByRole('button', { name: 'Confirm' }))
    expect(onSet).toHaveBeenCalledWith(7, 'USD')
  })

  it('offers no positions: one rate per department and plant', () => {
    expect(COLUMNS.rates.map((c) => c.key)).not.toContain('position')
    expect(COLUMNS.sampling.map((c) => c.key)).not.toContain('labour_position')
    expect(SECTION_LABELS.rates).toBe('Rates')
  })

  it('sorts rows by department order, then plant (all plants first)', () => {
    const rows = [
      { id: 1, department_id: 2, plant_id: null },
      { id: 2, department_id: 1, plant_id: 7 },
      { id: 3, department_id: 1, plant_id: null },
    ]
    expect(sortRows(rows, ctx).map((r) => r.id)).toEqual([3, 2, 1])
  })

  it('counts diff rows', () => {
    const empty = { added: [], removed: [], changed: [] }
    expect(diffCount(undefined)).toBeNull()
    expect(diffCount({ from_version: 1, from_version_id: 1, to_version: 2, to_version_id: 2,
      rates: { ...empty, added: [{}] }, machines: empty, sampling: empty,
      overheads: { ...empty, changed: [{ changes: {} }] } })).toBe(2)
  })
})
