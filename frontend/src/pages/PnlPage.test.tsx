import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, cleanup, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import PnlPage from './PnlPage'
import { formatDays } from '../lib/format'

const summaryFixture = {
  totals: { revenue: 100000, internal_cost: 20000, external_cost: 10000, total_cost: 30000, margin: 70000, margin_pct: 70,
    offer_revenue: 100000, planned_cost: 30000, planned_margin: 70000, actual_cost: 12000, actual_margin: 8000,
    actual_count: 1, variance: -2000, late_count: 1, max_slip_days: 4 },
  pipeline: { revenue: 40000, internal_cost: 8000, external_cost: 2000, total_cost: 10000, margin: 30000, margin_pct: 75 },
  realized: { revenue: 60000, internal_cost: 12000, external_cost: 8000, total_cost: 20000, margin: 40000, margin_pct: 66.67 },
  by_project: [{ project_id: 1, name: 'Project X', revenue: 100000, total_cost: 30000, margin: 70000 }],
  by_branch: {
    customer: { revenue: 90000, internal_cost: 18000, external_cost: 9000, total_cost: 27000, margin: 63000, margin_pct: 70 },
    internal: { revenue: 10000, internal_cost: 2000, external_cost: 1000, total_cost: 3000, margin: 7000, margin_pct: 70 },
  },
  count: 2,
}

const rowsFixture = [
  {
    change_id: 1, change_number: 'GB-CM-0001', title: 'Positive margin change',
    project_id: 1, project_name: 'Project X', branch: 'customer', status: 'quoted',
    revenue: 50000, internal_cost: 8000, external_cost: 2000, total_cost: 10000,
    margin: 40000, margin_pct: 80, effort_hours: 12, pending_price: false, realized: false,
    phase: 'actual', offer_revenue: 50000, planned_cost: 10000, planned_margin: 40000,
    actual_cost: 12000, actual_margin: 38000, variance: -2000, slip_days: 4, slip_unit: 'working days',
  },
  {
    change_id: 2, change_number: 'GB-CM-0002', title: 'Pending price change',
    project_id: 1, project_name: 'Project X', branch: 'customer', status: 'costing',
    revenue: null, internal_cost: 5000, external_cost: 1000, total_cost: 6000,
    margin: null, margin_pct: null, effort_hours: 4, pending_price: true, realized: false,
    phase: 'plan', offer_revenue: null, planned_cost: 6000, planned_margin: null,
    actual_cost: null, actual_margin: null, variance: null, slip_days: null,
  },
]

const changesMock = vi.fn().mockResolvedValue({ rows: rowsFixture })
const summaryMock = vi.fn().mockResolvedValue(summaryFixture)

vi.mock('../api/pnl', () => ({
  pnlApi: {
    changes: (...args: unknown[]) => changesMock(...args),
    summary: (...args: unknown[]) => summaryMock(...args),
  },
}))

vi.mock('../api/client', () => ({
  default: {
    get: vi.fn((url: string) => {
      if (url === '/v1/plants') {
        return Promise.resolve({ data: [{ id: 9, name: 'Plant A', code: 'PA' }] })
      }
      return Promise.resolve({ data: [{ id: 1, name: 'Project X' }] })
    }),
  },
}))

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <PnlPage />
      </MemoryRouter>
    </QueryClientProvider>
  )
}

describe('PnlPage', () => {
  afterEach(() => cleanup())

  it('renders summary tiles from summary data', async () => {
    renderPage()
    expect(await screen.findByText(/100[.,]000/)).toBeDefined()
    expect(screen.getAllByText(/70[.,]000/).length).toBeGreaterThan(0)
    expect(screen.getByText('on the plan frozen at acceptance')).toBeDefined()
    expect(screen.getByText('worst slip 4 days')).toBeDefined()
  })

  it('renders a row with an emerald margin badge for positive margin', async () => {
    renderPage()
    const link = await screen.findByRole('link', { name: 'GB-CM-0001' })
    expect(link.getAttribute('href')).toBe('/changes/1?tab=costing')
    const row = link.closest('tr') as HTMLElement
    const badge = row.querySelector('.text-emerald-400, .bg-emerald-900, [class*="emerald"]')
    expect(badge).not.toBeNull()
  })

  it('shows a "price pending" chip and dash revenue for pending_price rows', async () => {
    renderPage()
    const link = await screen.findByRole('link', { name: 'GB-CM-0002' })
    const row = link.closest('tr') as HTMLElement
    expect(row.textContent).toMatch(/price pending/i)
    expect(row.textContent).toContain('-')
    expect(row.textContent).not.toContain('\u2014')
  })

  it('triggers a refetch with the branch param when the branch filter changes', async () => {
    renderPage()
    await screen.findByRole('link', { name: 'GB-CM-0001' })
    changesMock.mockClear()
    summaryMock.mockClear()

    fireEvent.click(screen.getByRole('button', { name: /internal/i }))

    await waitFor(() => {
      expect(changesMock).toHaveBeenCalledWith(expect.objectContaining({ branch: 'internal' }))
    })
  })

  it('triggers a refetch with the plant_id param when the plant filter changes', async () => {
    renderPage()
    await screen.findByRole('link', { name: 'GB-CM-0001' })
    changesMock.mockClear()
    summaryMock.mockClear()

    const select = await screen.findByLabelText(/plant/i)
    fireEvent.change(select, { target: { value: '9' } })

    await waitFor(() => {
      expect(changesMock).toHaveBeenCalledWith(expect.objectContaining({ plant_id: 9 }))
    })
  })

  it('triggers a refetch with date_from/date_to params when the date filters change', async () => {
    renderPage()
    await screen.findByRole('link', { name: 'GB-CM-0001' })
    changesMock.mockClear()
    summaryMock.mockClear()

    // A typed date (dd.mm.yyyy here), applied as soon as the date is complete (no blur needed).
    fireEvent.change(screen.getByLabelText(/from/i), { target: { value: '01.01.2026' } })
    await waitFor(() => {
      expect(changesMock).toHaveBeenCalledWith(expect.objectContaining({ date_from: '2026-01-01' }))
    })

    fireEvent.change(screen.getByLabelText(/to/i), { target: { value: '31.01.2026' } })
    await waitFor(() => {
      expect(changesMock).toHaveBeenCalledWith(
        expect.objectContaining({ date_from: '2026-01-01', date_to: '2026-01-31' })
      )
    })
  })

  it('shows the offer-vs-actual columns with a rose variance chip and the slip', async () => {
    renderPage()
    const link = await screen.findByRole('link', { name: 'GB-CM-0001' })
    const row = link.closest('tr') as HTMLElement
    expect(row.textContent).toContain(formatDays(4, { sign: true }))
    expect(row.querySelector('[class*="rose"], [class*="amber"]')).not.toBeNull()
    for (const h of ['Offer revenue', 'Planned cost', 'Actual cost', 'Planned margin', 'Actual margin', 'Variance', 'Slip']) {
      expect(screen.getByRole('button', { name: new RegExp(`^${h}`) })).toBeDefined()
    }
  })

  it('sorts by a column when its header is clicked', async () => {
    renderPage()
    await screen.findByRole('link', { name: 'GB-CM-0001' })
    const order = () => screen.getAllByRole('link').map((a) => a.textContent)
    fireEvent.click(screen.getByRole('button', { name: /^Planned cost/ }))
    expect(order()).toEqual(['GB-CM-0001', 'GB-CM-0002'])       // 10000 before 6000 (desc)
    fireEvent.click(screen.getByRole('button', { name: /^Planned cost/ }))
    expect(order()).toEqual(['GB-CM-0002', 'GB-CM-0001'])
  })

  it('shows priced and unpriced counts, the forecast cost, actual revenue and forecast cost per row', async () => {
    summaryMock.mockResolvedValueOnce({ ...summaryFixture,
      totals: { ...summaryFixture.totals, priced_count: 2, unpriced_count: 5, actual_revenue: 26892, forecast_cost: 28692 } })
    changesMock.mockResolvedValueOnce({ rows: [
      { ...rowsFixture[0], actual_revenue: 53000, forecast_cost: 14000 },
      { ...rowsFixture[1], actual_revenue: null, forecast_cost: null },
    ] })
    renderPage()
    expect(await screen.findByText('2 priced, 5 price pending, incl. internal budgets')).toBeDefined()
    expect(screen.getByText(/^forecast 28[.,]692/)).toBeDefined()
    expect(screen.getByText(/on 26[.,]892/)).toBeDefined()
    expect((await screen.findByTestId('pnl-actual-revenue-1')).textContent).toMatch(/actual 53[.,]000/)
    expect(screen.getByTestId('pnl-forecast-cost-1').textContent).toMatch(/forecast 14[.,]000/)
    expect(screen.queryByTestId('pnl-actual-revenue-2')).toBeNull()
    expect(screen.queryByTestId('pnl-forecast-cost-2')).toBeNull()
  })

  it('never offers a native (locale mm/dd) date picker for the filters', async () => {
    const { container } = renderPage()
    await screen.findByRole('link', { name: 'GB-CM-0001' })
    expect(container.querySelector('input[type="date"]')).toBeNull()
    expect((screen.getByLabelText(/from/i) as HTMLInputElement).placeholder).toBe('e.g. 25 Sep 2026')
  })

  it('reads the Pipeline and Realized cards from the offer-vs-doing fields, like the tiles', async () => {
    summaryMock.mockResolvedValueOnce({
      ...summaryFixture,
      pipeline: { ...summaryFixture.pipeline, offer_revenue: 5000, planned_cost: 4000, planned_margin: 1000,
        actual_count: 0, actual_cost: 0 },
      realized: { ...summaryFixture.realized, offer_revenue: 42342, planned_cost: 37521.5, planned_margin: 4820.5,
        actual_count: 1, actual_cost: 7300, actual_margin: 19592, forecast_margin: -1800 },
    })
    renderPage()
    const pipeline = await screen.findByTestId('split-pipeline')
    expect(pipeline.textContent).toMatch(/Offer revenue5[.,]000/)
    expect(pipeline.textContent).toMatch(/Planned cost4[.,]000/)
    expect(pipeline.textContent).toContain('(20.0%)')
    expect(pipeline.textContent).toContain('No actuals booked yet')
    const realized = screen.getByTestId('split-realized')
    expect(realized.textContent).toMatch(/Planned cost37[.,]521/)
    expect(realized.textContent).toMatch(/Actual cost7[.,]300/)
    expect(realized.textContent).toMatch(/Actual margin-1[.,]800/)
    // Not the old total_cost (0 on the live data).
    expect(realized.textContent).not.toMatch(/Total cost/)
  })

  it('an older summary without counts keeps the change count line', async () => {
    renderPage()
    expect(await screen.findByText('2 changes, incl. internal budgets')).toBeDefined()
  })

  it('shows every amount in its own currency, no margin across currencies', async () => {
    changesMock.mockResolvedValueOnce({ rows: [
      { ...rowsFixture[0], change_id: 15, change_number: 'CR-15', currency: 'USD',
        revenue_currency: 'USD', offer_revenue: null, revenue: null, pending_price: true,
        planned_cost: 3175, planned_margin: null, actual_cost: null, actual_margin: null,
        variance: null, no_rate: true,
        warnings: [{ code: 'no_rate', message: 'Costing lines without a rate' }] },
      { ...rowsFixture[0], change_id: 16, change_number: 'CR-16', currency: 'USD',
        revenue_currency: 'EUR', currency_mismatch: true, offer_revenue: 1000,
        planned_cost: 400, planned_margin: null, margin: null, actual_cost: null,
        actual_margin: null, variance: null },
    ] })
    renderPage()
    const row15 = (await screen.findByText('CR-15')).closest('tr')!
    expect(row15.textContent).toContain('3,175.00 USD')
    expect(row15.textContent).not.toContain('EUR')
    expect(screen.getByTestId('pnl-no-rate-15')).toBeDefined()
    const row16 = screen.getByText('CR-16').closest('tr')!
    expect(row16.textContent).toContain('1,000.00 EUR')
    expect(row16.textContent).toContain('400.00 USD')
    expect(screen.getByTestId('pnl-currency-mismatch-16').textContent).toBe('EUR vs USD: no margin')
  })

  it('groups the summary by currency: one block of tiles per currency', async () => {
    summaryMock.mockResolvedValueOnce({
      ...summaryFixture, currency: 'EUR', currencies: ['EUR', 'USD'],
      by_currency: {
        EUR: summaryFixture,
        USD: { ...summaryFixture, count: 1,
          totals: { ...summaryFixture.totals, planned_cost: 3175, no_rate_count: 1 } },
      },
    })
    renderPage()
    const usd = await screen.findByTestId('pnl-summary-USD')
    expect(usd.textContent).toContain('3,175.00 USD')
    expect(usd.textContent).not.toContain('EUR')
    expect(screen.getByTestId('pnl-summary-EUR').textContent).toContain('100,000.00 EUR')
    expect(screen.getByTestId('pnl-summary-notes-USD').textContent)
      .toContain('without a rate in the cost sheet')
  })

  it('labels the actual margin a forecast only while the change is running', async () => {
    changesMock.mockResolvedValueOnce({ rows: [
      { ...rowsFixture[0], change_id: 31, change_number: 'CR-31', status: 'closed', realized: true,
        actual_margin: 5000, forecast_margin: 5000 },
      { ...rowsFixture[0], change_id: 32, change_number: 'CR-32', status: 'in_implementation', realized: true,
        actual_margin: 9000, forecast_margin: 7000 },
    ] })
    renderPage()
    await screen.findByText('CR-31')
    expect(screen.queryByTestId('pnl-margin-forecast-31')).toBeNull()
    expect(screen.getByTestId('pnl-actual-margin-31').textContent).not.toMatch(/forecast/)
    expect(screen.getByTestId('pnl-margin-forecast-32').textContent).toMatch(/forecast, to date 9[.,]000/)
    // A running change in scope: the tile says forecast.
    expect(screen.getByText('Actual margin (forecast)')).toBeDefined()
  })

  it('a closed-only portfolio shows the booked actual margin, not a forecast', async () => {
    changesMock.mockResolvedValueOnce({ rows: [
      { ...rowsFixture[0], change_id: 33, change_number: 'CR-33', status: 'closed', realized: true },
    ] })
    renderPage()
    await screen.findByText('CR-33')
    expect(screen.queryByText('Actual margin (forecast)')).toBeNull()
    expect(screen.queryByText(/^forecast, to date/)).toBeNull()
  })

  it('shows an engineering review as unpriced by design, not "price pending"', async () => {
    changesMock.mockResolvedValueOnce({ rows: [
      { ...rowsFixture[1], change_id: 34, change_number: 'CR-34', origin: 'engineering_review' },
    ] })
    renderPage()
    const row = (await screen.findByText('CR-34')).closest('tr')!
    expect(row.textContent).toContain('engineering review')
    expect(row.textContent).not.toMatch(/price pending/i)
  })
})
