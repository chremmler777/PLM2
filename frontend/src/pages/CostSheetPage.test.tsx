import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, cleanup, fireEvent } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import CostSheetPage from './CostSheetPage'
import PublishDialog from '../components/costSheet/PublishDialog'
import PlantCurrencies from '../components/costSheet/PlantCurrencies'
import SheetCell from '../components/costSheet/SheetCell'
import { COLUMNS, sortRows, type SheetContext } from '../components/costSheet/columns'
import { diffCount } from '../components/costSheet/DiffPanel'
import { costSheetApi } from '../api/costSheet'
import { addDaysIso, formatDate, todayIso } from '../lib/format'

vi.mock('../api/costSheet', () => ({
  costSheetApi: {
    overview: vi.fn(), version: vi.fn(), diff: vi.fn(), deleteDraft: vi.fn(),
    exportUrl: () => '#',
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
    fireEvent.change(input, { target: { value: '7,5' } })
    fireEvent.blur(input)
    expect(onCommit).toHaveBeenCalledWith(7.5)
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
