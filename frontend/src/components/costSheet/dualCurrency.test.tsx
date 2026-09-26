/**
 * Two-currency plants (Silao: USD and MXN): the version's exchange rate strip,
 * the local-currency rate column (typed in either, the other calculated and
 * captioned), the plant's local currency, the actual-cost currency choice and
 * the P&L's conversion notes.
 */
import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, cleanup, fireEvent, waitFor, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import FxRates, { inverse, readFxInput } from './FxRates'
import { NUMBER_INPUT_HINT, NUMBER_INPUT_INVALID } from '../../lib/format'
import CurrencyMismatch, { mismatchLines } from './CurrencyMismatch'
import type { CurrencyMismatchRow } from '../../types/costSheet'
import SectionTable from './SectionTable'
import PlantCurrencies from './PlantCurrencies'
import { localRateColumn, localRateLabel, type SheetContext } from './columns'
import ActualCostsPanel from '../changes/pnl/ActualCostsPanel'
import { changesApi } from '../../api/changes'
import { actualCostsApi } from '../../api/actualCosts'

vi.mock('../../api/changes', () => ({ changesApi: { costingContext: vi.fn() } }))
vi.mock('../../api/actualCosts', () => ({
  actualCostsApi: { list: vi.fn(), add: vi.fn(), remove: vi.fn() },
}))

afterEach(() => { cleanup(); vi.clearAllMocks() })

const ctx: SheetContext = {
  departments: [{ id: 1, name: 'Tooling', is_active: true }],
  plants: [
    { id: 7, name: 'Silao', code: 'SIL', is_active: true, currency: 'USD', local_currency: 'MXN',
      currency_confirmed: true },
    { id: 8, name: 'Toccoa', code: 'TOC', is_active: true, currency: 'USD', local_currency: null,
      currency_confirmed: true },
  ],
  machineClasses: [],
  currencies: ['EUR', 'USD', 'MXN'],
}

const rows = [
  { id: 1, department_id: 1, plant_id: 7, hourly_rate: 57.8, currency: 'USD', effective_rate: 57.8,
    overhead: null, note: null, local_currency: 'MXN', local_rate: 1000, entered_in: 'local',
    entered_rate: 1000, entered_currency: 'MXN' },
  { id: 2, department_id: 1, plant_id: 8, hourly_rate: 40, currency: 'USD', effective_rate: 40,
    overhead: null, note: null, local_currency: null, local_rate: null, entered_in: null },
]

describe('FxRates', () => {
  it('reads like every number input and keeps the digits as typed', () => {
    expect(readFxInput('17.30')).toEqual({ value: '17.30' })
    // "17,30" is German for 17.30 or en-US grouping gone wrong: refused, not guessed
    expect(readFxInput('17,30')).toEqual({ refused: NUMBER_INPUT_HINT })
    expect(readFxInput('1,500')).toEqual({ value: '1500' })
    expect(readFxInput('1,730.5')).toEqual({ value: '1730.5' })
    expect(readFxInput('')).toEqual({ value: null })
    expect('refused' in readFxInput('0')).toBe(true)
    expect(readFxInput('abc')).toEqual({ refused: NUMBER_INPUT_INVALID })
  })

  it('edits the pair a plant needs on a draft and says when it is missing', () => {
    const onSet = vi.fn()
    render(<FxRates rates={[]} needed={[{ pair: 'USD/MXN', base: 'USD', quote: 'MXN' }]}
      editable version={3} onSet={onSet} />)
    expect(screen.getByText('Rates typed in MXN cannot be priced until it is set.')).toBeDefined()
    const input = screen.getByLabelText('MXN per USD') as HTMLInputElement
    fireEvent.change(input, { target: { value: '17.30' } })
    fireEvent.keyDown(input, { key: 'Enter' })
    fireEvent.blur(input)
    expect(onSet).toHaveBeenCalledWith('USD', 'MXN', '17.30')
    fireEvent.change(input, { target: { value: 'x' } })
    fireEvent.blur(input)
    expect(screen.getByRole('alert')).toBeDefined()
    expect(onSet).toHaveBeenCalledTimes(1)
  })

  it('refuses "17,30", puts the saved rate back and says why inline; the reverse follows the field', () => {
    const onSet = vi.fn()
    render(<FxRates rates={[{ pair: 'USD/MXN', base: 'USD', quote: 'MXN', rate: '17.30' }]}
      needed={[]} editable version={3} onSet={onSet} />)
    const input = screen.getByLabelText('MXN per USD') as HTMLInputElement
    fireEvent.change(input, { target: { value: '20' } })
    expect(screen.getByTestId('fx-inverse-USD/MXN').textContent).toBe('(1 MXN = 0.0500 USD)')
    fireEvent.change(input, { target: { value: '17,30' } })
    fireEvent.blur(input)
    expect(onSet).not.toHaveBeenCalled()
    expect(input.value).toBe('17.30')
    const msg = screen.getByTestId('fx-refused-USD/MXN')
    expect(msg.getAttribute('role')).toBe('alert')
    expect(msg.textContent).toBe(`"17,30" not saved. ${NUMBER_INPUT_HINT}`)
    expect(input.getAttribute('aria-describedby')).toBe(msg.id)
    expect(screen.getByTestId('fx-inverse-USD/MXN').textContent).toBe('(1 MXN = 0.0578 USD)')
  })

  it('shows a published version rate read-only, and nothing without pairs', () => {
    const { container } = render(<FxRates rates={[{ pair: 'USD/MXN', base: 'USD', quote: 'MXN', rate: '17.30' }]}
      needed={[]} editable={false} version={3} onSet={vi.fn()} />)
    expect(screen.getByTestId('fx-value-USD/MXN').textContent).toBe('17.30')
    expect(screen.getByText(/Frozen with version 3/)).toBeDefined()
    cleanup()
    const empty = render(<FxRates rates={[]} needed={[]} editable version={1} onSet={vi.fn()} />)
    expect(empty.container.textContent).toBe('')
    expect(container).toBeDefined()
  })
})

describe('local-currency rate column', () => {
  const table = (editable: boolean, onUpdate = vi.fn()) => render(
    <SectionTable section="rates" rows={rows} ctx={ctx} editable={editable}
      extraColumns={[localRateColumn()]} onUpdate={onUpdate} onDelete={vi.fn()}
      onAdd={async () => true as const} />)

  it('shows both currencies and captions the calculated one', () => {
    table(false)
    const silao = screen.getAllByRole('row')[1]
    expect(within(silao).getByText('1,000.00 MXN')).toBeDefined()
    // typed in MXN: the USD rate is the calculated one
    expect(within(silao).getByTestId('sheet-cell-hint-hourly_rate').textContent).toBe('calculated')
    expect(within(silao).queryByTestId('sheet-cell-hint-local_rate')).toBeNull()
    // a one-currency plant has no local rate
    const toccoa = screen.getAllByRole('row')[2]
    expect(within(toccoa).queryByText(/MXN/)).toBeNull()
  })

  it('names the local currency in the header', () => {
    expect(localRateColumn(['MXN', null, 'MXN']).label).toBe('Local / h (MXN)')
    expect(localRateLabel(['MXN', 'BRL'])).toBe('Local / h (BRL, MXN)')
    expect(localRateLabel([])).toBe('Local / h')
  })

  it('sends a local rate as typed in the local currency', () => {
    const onUpdate = vi.fn()
    table(true, onUpdate)
    const inputs = screen.getAllByLabelText('Local / h') as HTMLInputElement[]
    expect(inputs[1].disabled).toBe(true)          // Toccoa: one currency
    fireEvent.focus(inputs[0])
    fireEvent.change(inputs[0], { target: { value: '1730' } })
    fireEvent.blur(inputs[0])
    expect(onUpdate).toHaveBeenCalledWith(1, { entered_rate: 1730, entered_currency: 'MXN' })
    const usd = screen.getAllByLabelText('Rate / h')[0]
    fireEvent.focus(usd)
    fireEvent.change(usd, { target: { value: '60' } })
    fireEvent.blur(usd)
    expect(onUpdate).toHaveBeenLastCalledWith(1, { hourly_rate: 60 })
  })
})

describe('PlantCurrencies local currency', () => {
  it('shows and sets a second currency', () => {
    const onSet = vi.fn()
    render(<PlantCurrencies plants={ctx.plants} currencies={ctx.currencies} canEdit onSet={onSet} />)
    expect(screen.getByTestId('plant-currency-7').textContent).toContain('USD + MXN')
    fireEvent.click(screen.getByLabelText('Change currency of Toccoa'))
    fireEvent.change(screen.getByLabelText('Local currency of Toccoa'), { target: { value: 'MXN' } })
    expect(onSet).toHaveBeenCalledWith(8, 'USD', 'MXN')
    fireEvent.change(screen.getByLabelText('Local currency of Toccoa'), { target: { value: '' } })
    expect(onSet).toHaveBeenLastCalledWith(8, 'USD', null)
  })
})

describe('actual costs at a two-currency plant', () => {
  const list = { items: [], total: 0, currency: 'USD', can_write: true, writable_department_ids: null, cost_role: true }

  it('lets the cost be entered in the local currency', async () => {
    vi.mocked(actualCostsApi.list).mockResolvedValue(list as never)
    vi.mocked(changesApi.costingContext).mockResolvedValue({ currency: 'USD', local_currency: 'MXN' } as never)
    vi.mocked(actualCostsApi.add).mockResolvedValue({} as never)
    render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <ActualCostsPanel changeId={21} />
    </QueryClientProvider>)
    fireEvent.click(await screen.findByTestId('actual-cost-open'))
    await screen.findByTestId('actual-cost-currency')
    fireEvent.change(screen.getByTestId('actual-cost-currency'), { target: { value: 'MXN' } })
    expect(screen.getByText('Amount (MXN)')).toBeDefined()
    fireEvent.change(screen.getByLabelText('Amount'), { target: { value: '1730' } })
    fireEvent.click(screen.getByTestId('actual-cost-save'))
    await waitFor(() => expect(actualCostsApi.add).toHaveBeenCalled())
    expect(vi.mocked(actualCostsApi.add).mock.calls[0][1]).toMatchObject({ amount: 1730, currency: 'MXN' })
  })

  it('offers no choice at a one-currency plant', async () => {
    vi.mocked(actualCostsApi.list).mockResolvedValue(list as never)
    vi.mocked(changesApi.costingContext).mockResolvedValue({ currency: 'USD' } as never)
    render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <ActualCostsPanel changeId={21} />
    </QueryClientProvider>)
    fireEvent.click(await screen.findByTestId('actual-cost-open'))
    expect(screen.queryByTestId('actual-cost-currency')).toBeNull()
  })
})


describe('exchange rate direction and rows off their plant currency', () => {
  it('shows the rate the other way round, 4 decimals', () => {
    render(<FxRates rates={[{ pair: 'USD/MXN', base: 'USD', quote: 'MXN', rate: '17.30' }]}
      needed={[]} editable={false} version={3} onSet={vi.fn()} />)
    expect(screen.getByTestId('fx-inverse-USD/MXN').textContent).toBe('(1 MXN = 0.0578 USD)')
    expect(inverse('abc')).toBeNull()
  })

  it('lists rows not in their plant quote currency, per plant and currency', () => {
    const rows = [
      { section: 'rates', row_id: 1, plant_id: 8, plant_name: 'Silao', currency: 'EUR', plant_currency: 'USD' },
      { section: 'machines', row_id: 2, plant_id: 8, plant_name: 'Silao', currency: 'EUR', plant_currency: 'USD' },
    ] as CurrencyMismatchRow[]
    expect(mismatchLines(rows)).toEqual(['Silao (quote currency USD): 2 rows in EUR'])
    render(<CurrencyMismatch rows={rows} publishing />)
    const box = screen.getByTestId('currency-mismatch')
    expect(box.textContent).toContain('2 rows are not in their plant')
    expect(box.textContent).toContain('published as they are')
    cleanup()
    const none = render(<CurrencyMismatch rows={[]} />)
    expect(none.container.textContent).toBe('')
  })
})
