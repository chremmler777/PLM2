import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, cleanup, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import PnlCard from './PnlCard'
import type { ChangeDetail, Summation } from '../../types/change'
import { changesApi } from '../../api/changes'

vi.mock('../../api/changes', () => ({
  changesApi: { getSummation: vi.fn() },
}))

const ovaMock = vi.fn().mockResolvedValue(null)
const costListMock = vi.fn().mockResolvedValue(null)
const costAddMock = vi.fn()
vi.mock('../../api/pnl', () => ({
  pnlApi: { offerVsActual: (...a: unknown[]) => ovaMock(...a) },
}))
vi.mock('../../api/actualCosts', () => ({
  actualCostsApi: {
    list: (...a: unknown[]) => costListMock(...a),
    add: (...a: unknown[]) => costAddMock(...a),
    remove: vi.fn(),
  },
}))

const ova = {
  change_id: 7, currency: 'EUR', basis: 'accepted_offer', phase: 'actual',
  offer_version: 2, frozen_at: '2026-06-01T10:00:00',
  lines: [
    { key: 'revenue', label: 'Revenue (offer)', kind: 'revenue', planned: 3000, actual: 3000, variance: 0, in_margin: true },
    { key: 'internal', label: 'Internal effort (hours x rate)', kind: 'cost', planned: 1000, actual: 1050, variance: 50, in_margin: true },
    { key: 'external', label: 'External (supplier)', kind: 'cost', planned: 500, actual: 700, variance: 200, in_margin: true },
    { key: 'issues_supplier', label: 'Validation issues, recoverable from supplier', kind: 'info', planned: 0, actual: 40, variance: 40, in_margin: false },
  ],
  planned_revenue: 3000, actual_revenue: 3000, planned_cost: 1500, actual_cost: 1750,
  planned_margin: 1500, actual_margin: 1250, planned_margin_pct: 50, actual_margin_pct: 41.7,
  variance: -250, booked_hours: 10.5, issue_count: 1,
  timing: { baseline_finish: '2026-07-07', forecast_finish: '2026-07-10', actual_finish: null,
            slip_days: 3, unit: 'working days', baseline_source: 'detailed_baseline' },
  piece_price: { delta_per_piece: 0.12, annual_volume: 10000, annual_effect: 1200 },
  warnings: ['No supplier invoice entered yet'],
}

const change = (over: Partial<ChangeDetail> = {}): ChangeDetail => ({
  id: 7, change_number: 'CR-2026-0007', project_id: 1, title: 'Housing fix',
  change_type: 'tooling', priority: 'medium', status: 'costing',
  raised_by: 1, customer_response: 'pending',
  created_at: '2026-07-01T00:00:00', updated_at: '2026-07-01T00:00:00',
  impacted_items: [], assessments: [], attachments: [], ...over,
} as ChangeDetail)

const summation = (over: Partial<Summation['totals']> = {}): Summation => ({
  by_plant: [],
  by_department: [],
  totals: {
    one_time_internal: 1000,
    one_time_external: 500,
    lifecycle_internal: 200,
    lifecycle_external: 300,
    grand_total: 2000,
    ...over,
  },
  effort_by_department: [],
  total_effort_hours: 0,
})

const wrap = (ui: React.ReactElement) => (
  <QueryClientProvider client={new QueryClient()}>{ui}</QueryClientProvider>
)

describe('PnlCard', () => {
  afterEach(() => {
    cleanup()
    vi.clearAllMocks()
  })

  it('shows Revenue and margin for a customer-relevant change', async () => {
    vi.mocked(changesApi.getSummation).mockResolvedValue(summation({ grand_total: 2000 }))
    render(wrap(<PnlCard change={change({ customer_relevant: true, quoted_price: 5000 })} />))
    expect(await screen.findByText('Revenue')).toBeDefined()
    expect(screen.getByText('Margin')).toBeDefined()
    expect(screen.getByText('5.000,00 EUR')).toBeDefined()
    expect(await screen.findByText('3.000,00 EUR')).toBeDefined()
  })

  it('prices the cost in the costing currency and shows the costing warnings', async () => {
    vi.mocked(changesApi.getSummation).mockResolvedValue({
      ...summation({ grand_total: 2000 }), currency: 'USD',
      warnings: [{ code: 'no_rate', message: '1 costing line has no rate in the cost sheet and is not counted: the total is too low' }],
    })
    render(wrap(<PnlCard change={change({ customer_relevant: true, quoted_price: 5000 })} />))
    expect(await screen.findByText('2.000,00 USD')).toBeDefined()
    expect((await screen.findByTestId('pnl-costing-warnings')).textContent)
      .toContain('no rate in the cost sheet')
  })

  it('EUR revenue against a USD costing: revenue in EUR, costs in USD, no margin', async () => {
    vi.mocked(changesApi.getSummation).mockResolvedValue({
      ...summation({ grand_total: 2000 }), currency: 'USD', revenue_currency: 'EUR',
    })
    render(wrap(<PnlCard change={change({ customer_relevant: true, quoted_price: 5000 })} />))
    expect(await screen.findByText('2.000,00 USD')).toBeDefined()
    expect(screen.getByText('5.000,00 EUR')).toBeDefined()
    expect(screen.getByTestId('pnl-margin').textContent).toBe('-')
    expect(screen.getByTestId('pnl-currency-mismatch').textContent)
      .toBe('No margin: EUR revenue vs USD costs')
  })

  it('offer vs actual across currencies: each line in its own currency, no margin row values', async () => {
    vi.mocked(changesApi.getSummation).mockResolvedValue({
      ...summation(), currency: 'USD', revenue_currency: 'EUR',
    })
    ovaMock.mockResolvedValueOnce({
      ...ova, currency: 'EUR', revenue_currency: 'EUR', costing_currency: 'USD',
      currency_mismatch: true, phase: 'actual', in_progress: false,
      lines: ova.lines.map((l) => ({ ...l, currency: l.kind === 'revenue' ? 'EUR' : 'USD' })),
      margin_row: { planned: null, actual: null, forecast: null, planned_pct: null,
        actual_pct: null, forecast_pct: null, variance: null },
      planned_margin: null, actual_margin: null, planned_margin_pct: null,
      actual_margin_pct: null, variance: null,
    })
    render(wrap(<PnlCard change={change({ status: 'released', customer_relevant: true, quoted_price: 3000 })} />))
    const rev = await screen.findByTestId('ova-line-revenue')
    expect(rev.textContent).toContain('3.000,00 EUR')
    expect(screen.getByTestId('ova-line-internal').textContent).toContain('1.000,00 USD')
    expect(screen.getByTestId('ova-line-internal').textContent).not.toContain('EUR')
    expect(screen.getByTestId('ova-line-external').textContent).toContain('700,00 USD')
    expect(screen.getByTestId('ova-planned-margin').textContent).toBe('-')
    expect(screen.getByTestId('ova-actual-margin').textContent).toBe('-')
    expect(screen.queryByTestId('ova-margin-variance')).toBeNull()
    expect(screen.getByTestId('ova-currency-mismatch').textContent)
      .toBe('No margin: EUR revenue vs USD costs')
  })

  it('shows Approved budget and "vs. approved budget" label for an internal change', async () => {
    vi.mocked(changesApi.getSummation).mockResolvedValue(summation({ grand_total: 2000 }))
    render(wrap(<PnlCard change={change({ customer_relevant: false, internal_approved_amount: 3000 })} />))
    expect(await screen.findByText('Approved budget')).toBeDefined()
    expect(screen.getByText('vs. approved budget')).toBeDefined()
    expect(screen.getByText('3.000,00 EUR')).toBeDefined()
    expect(await screen.findByText('1.000,00 EUR')).toBeDefined()
  })

  it('is hidden before costing (in_assessment)', () => {
    render(wrap(<PnlCard change={change({ status: 'in_assessment', customer_relevant: true, quoted_price: 5000 })} />))
    expect(screen.queryByText('Revenue')).toBeNull()
    expect(changesApi.getSummation).not.toHaveBeenCalled()
  })

  it('is hidden for scoping and captured statuses', () => {
    render(wrap(<PnlCard change={change({ status: 'scoping' })} />))
    expect(screen.queryByText('Revenue')).toBeNull()
    cleanup()
    render(wrap(<PnlCard change={change({ status: 'captured' })} />))
    expect(screen.queryByText('Revenue')).toBeNull()
  })

  it('no longer shows the old Actuals block (actual total and delta), even when the payload carries one', async () => {
    vi.mocked(changesApi.getSummation).mockResolvedValue({
      ...summation(),
      actuals: { by_department: [{ department_id: 1, hours: 10, internal_cost: 900 }], total_cost: 900, delta: -100 },
    } as Summation)
    ovaMock.mockResolvedValue(ova)
    costListMock.mockResolvedValue({ items: [], total: 0, can_write: false, writable_department_ids: null, cost_role: true })
    render(wrap(<PnlCard change={change({ status: 'in_validation', customer_relevant: true, quoted_price: 3000 })} />))
    await screen.findByTestId('pnl-offer-vs-actual')
    expect(screen.queryByTestId('pnl-actuals')).toBeNull()
    expect(screen.queryByTestId('pnl-actuals-total')).toBeNull()
    expect(screen.queryByTestId('pnl-actuals-delta')).toBeNull()
  })

  it('while running: actual margin to date and the forecast margin sit in separate, labelled columns', async () => {
    vi.mocked(changesApi.getSummation).mockResolvedValue(summation())
    ovaMock.mockResolvedValue({ ...ova, in_progress: true, actual_margin: 19592, actual_margin_pct: 72.85,
      forecast_margin: -1800, forecast_margin_pct: -6.69, variance: -1800,
      lines: ova.lines.map((l) => ({ ...l, forecast: l.key === 'internal' ? 1000 : l.actual })) })
    costListMock.mockResolvedValue({ items: [], total: 0, can_write: false, writable_department_ids: null, cost_role: true })
    render(wrap(<PnlCard change={change({ status: 'in_validation', customer_relevant: true, quoted_price: 3000 })} />))
    await screen.findByTestId('pnl-offer-vs-actual')
    expect(screen.getByText('Actual to date')).toBeDefined()
    expect(screen.getByTestId('ova-forecast-head').textContent).toBe('Forecast')
    expect(screen.getByTestId('ova-actual-margin').textContent).toContain('19.592,00 EUR')
    expect(screen.getByTestId('ova-forecast-margin').textContent).toContain('-1.800,00 EUR')
    expect(screen.queryByText('Margin (forecast)')).toBeNull()
    // the internal line: 1.050 booked, 1.000 forecast
    const internal = screen.getByTestId('ova-line-internal').textContent ?? ''
    expect(internal).toContain('1.050,00 EUR')
    expect(internal).toContain('1.000,00 EUR')
  })

  it('the margin row reads from margin_row when the server sends it', async () => {
    vi.mocked(changesApi.getSummation).mockResolvedValue(summation())
    ovaMock.mockResolvedValue({ ...ova, in_progress: true,
      // flat fields deliberately stale: margin_row wins
      margin_row: { planned: 0, actual: 19592, forecast: -1800, planned_pct: 0, actual_pct: 72.85,
        forecast_pct: -6.69, variance: -1800 } })
    costListMock.mockResolvedValue({ items: [], total: 0, can_write: false, writable_department_ids: null, cost_role: true })
    render(wrap(<PnlCard change={change({ status: 'in_validation', customer_relevant: true, quoted_price: 3000 })} />))
    await screen.findByTestId('pnl-offer-vs-actual')
    expect(screen.getByTestId('ova-planned-margin').textContent).toContain('0,00 EUR')
    expect(screen.getByTestId('ova-actual-margin').textContent).toContain('19.592,00 EUR')
    expect(screen.getByTestId('ova-actual-margin').textContent).toContain('72.8')
    expect(screen.getByTestId('ova-forecast-margin').textContent).toContain('-1.800,00 EUR')
    expect(screen.getByTestId('ova-margin-variance').textContent).toContain('-1.800,00 EUR')
    expect(screen.getByTestId('ova-margin-variance').getAttribute('data-tone')).toBe('rose')
  })

  it('once released there is no forecast column: the actual is the end', async () => {
    vi.mocked(changesApi.getSummation).mockResolvedValue(summation())
    ovaMock.mockResolvedValue({ ...ova, in_progress: false })
    costListMock.mockResolvedValue({ items: [], total: 0, can_write: false, writable_department_ids: null, cost_role: true })
    render(wrap(<PnlCard change={change({ status: 'released', customer_relevant: true, quoted_price: 3000 })} />))
    await screen.findByTestId('pnl-offer-vs-actual')
    expect(screen.queryByTestId('ova-forecast-head')).toBeNull()
    expect(screen.queryByTestId('ova-forecast-margin')).toBeNull()
    expect(screen.getByTestId('ova-actual-margin').textContent).toContain('1.250,00 EUR')
  })

  it('a department member (no cost role) gets only their own actual costs, and no P&L request', async () => {
    costListMock.mockResolvedValue({ items: [
      { id: 5, change_id: 7, department_id: 28, department_name: 'Development', category: 'scrap',
        vendor_name: null, amount: 120, cost_date: '2026-09-20', note: 'Scrapped samples', attachment_id: null,
        created_by: 9, created_by_name: 'Dev', created_at: '2026-09-20T08:00:00', can_delete: true },
    ], total: 120, can_write: true, writable_department_ids: [28], cost_role: false })
    render(wrap(<PnlCard canSeeCosts={false}
      change={change({ status: 'in_validation', customer_relevant: true, quoted_price: 3000 })}
      departments={[{ id: 28, name: 'Development' }, { id: 27, name: 'Tool Engineer' }]} />))
    expect((await screen.findByTestId('actual-cost-5')).textContent).toContain('Scrapped samples')
    expect(screen.getByText('Actual costs of your department')).toBeDefined()
    expect(screen.queryByText('Revenue')).toBeNull()
    expect(screen.queryByTestId('pnl-offer-vs-actual')).toBeNull()
    expect(changesApi.getSummation).not.toHaveBeenCalled()
    expect(ovaMock).not.toHaveBeenCalled()
    fireEvent.click(screen.getByTestId('actual-cost-open'))
    const dept = screen.getByLabelText('Department') as HTMLSelectElement
    expect([...dept.options].map((o) => o.textContent)).toEqual(['Choose', 'Development'])
  })

  it('a department member sees nothing before implementation', () => {
    render(wrap(<PnlCard canSeeCosts={false} change={change({ status: 'costing' })} />))
    expect(screen.queryByTestId('pnl-department-costs')).toBeNull()
    expect(costListMock).not.toHaveBeenCalled()
  })

  it('shows no offer-vs-actual block before implementation', async () => {
    vi.mocked(changesApi.getSummation).mockResolvedValue(summation())
    render(wrap(<PnlCard change={change({ status: 'quoted', customer_relevant: true, quoted_price: 3000 })} />))
    await screen.findByText('Revenue')
    expect(screen.queryByTestId('pnl-offer-vs-actual')).toBeNull()
    expect(ovaMock).not.toHaveBeenCalled()
  })

  it('shows offer vs actual with variance chips, margins, slip, piece price and warnings', async () => {
    vi.mocked(changesApi.getSummation).mockResolvedValue(summation())
    ovaMock.mockResolvedValue(ova)
    costListMock.mockResolvedValue({ items: [], total: 0, can_write: true,
      writable_department_ids: null, cost_role: true })
    render(wrap(<PnlCard change={change({ status: 'in_implementation', customer_relevant: true, quoted_price: 3000 })} />))
    await screen.findByTestId('pnl-offer-vs-actual')
    expect(screen.getByTestId('ova-chip-internal').getAttribute('data-tone')).toBe('amber')   // +5 %
    expect(screen.getByTestId('ova-chip-external').getAttribute('data-tone')).toBe('rose')    // +40 %
    expect(screen.getByTestId('ova-chip-revenue').getAttribute('data-tone')).toBe('green')
    expect(screen.queryByTestId('ova-chip-issues_supplier')).toBeNull()
    expect(screen.getByTestId('ova-actual-margin').textContent).toContain('1.250,00 EUR')
    expect(screen.getByTestId('ova-margin-variance').getAttribute('data-tone')).toBe('rose')
    expect(screen.getByTestId('ova-timing').textContent).toContain('3 working days late')
    expect(screen.getByTestId('ova-piece-price').textContent).toContain('1.200,00 EUR per year')
    expect(screen.getByTestId('ova-warnings').textContent).toContain('No supplier invoice')
    expect(document.body.textContent).not.toContain('\u2014')
  })

  it('adds an actual cost through the form', async () => {
    vi.mocked(changesApi.getSummation).mockResolvedValue(summation())
    ovaMock.mockResolvedValue(ova)
    costListMock.mockResolvedValue({ items: [
      { id: 3, change_id: 7, department_id: 1, department_name: 'Tooling', category: 'external',
        vendor_name: 'Hasco', amount: 700, cost_date: '2026-06-02', note: null, attachment_id: null,
        created_by: 1, created_by_name: 'Anna', created_at: '2026-06-02T08:00:00', can_delete: true },
    ], total: 700, can_write: true, writable_department_ids: [1], cost_role: false })
    costAddMock.mockResolvedValue({})
    render(wrap(<PnlCard change={change({ status: 'in_validation', customer_relevant: true })}
      departments={[{ id: 1, name: 'Tooling' }, { id: 2, name: 'Quality' }]} />))
    expect((await screen.findByTestId('actual-cost-3')).textContent).toContain('Hasco')
    expect(screen.getByTestId('actual-cost-delete-3')).toBeDefined()
    fireEvent.click(screen.getByTestId('actual-cost-open'))
    const dept = screen.getByLabelText('Department') as HTMLSelectElement
    // a department member only sees their own department
    expect([...dept.options].map((o) => o.textContent)).toEqual(['Choose', 'Tooling'])
    fireEvent.change(screen.getByLabelText('Amount'), { target: { value: '250,50' } })
    expect((screen.getByTestId('actual-cost-save') as HTMLButtonElement).disabled).toBe(true)
    fireEvent.change(dept, { target: { value: '1' } })
    fireEvent.change(screen.getByLabelText('Vendor'), { target: { value: 'Meusburger' } })
    fireEvent.click(screen.getByTestId('actual-cost-save'))
    await waitFor(() => expect(costAddMock).toHaveBeenCalledWith(7, expect.objectContaining({
      category: 'external', amount: 250.5, department_id: 1, vendor_name: 'Meusburger' })))
  })
})
