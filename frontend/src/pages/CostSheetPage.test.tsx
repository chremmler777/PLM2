import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, cleanup, fireEvent, waitFor } from '@testing-library/react'
import { toast } from 'sonner'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import CostSheetPage from './CostSheetPage'
import PublishDialog from '../components/costSheet/PublishDialog'
import PlantCurrencies from '../components/costSheet/PlantCurrencies'
import SheetCell from '../components/costSheet/SheetCell'
import { COLUMNS, sortRows, type SheetContext } from '../components/costSheet/columns'
import { diffCount } from '../components/costSheet/DiffPanel'
import { costSheetApi } from '../api/costSheet'
import { NUMBER_INPUT_HINT, NUMBER_INPUT_INVALID, addDaysIso, formatDate, todayIso } from '../lib/format'

vi.mock('../api/costSheet', () => ({
  costSheetApi: {
    overview: vi.fn(), version: vi.fn(), diff: vi.fn(), deleteDraft: vi.fn(),
    createDraft: vi.fn(), exportUrl: () => '#',
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
    expect(screen.getByText(/set by location; Finance to confirm/)).toBeDefined()
    fireEvent.click(screen.getByRole('button', { name: 'Confirm' }))
    expect(onSet).toHaveBeenCalledWith(7, 'USD')
  })

  it('labels sampling labour position as editable', () => {
    expect(COLUMNS.sampling.some((c) => c.key === 'labour_position' && c.kind === 'text')).toBe(true)
  })

  it('sorts rows by department order, then position, then plant', () => {
    const rows = [
      { id: 1, department_id: 2, position: null, plant_id: null },
      { id: 2, department_id: 1, position: 'Engineer', plant_id: null },
      { id: 3, department_id: 1, position: null, plant_id: 7 },
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
