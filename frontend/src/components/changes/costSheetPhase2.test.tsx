/**
 * Cost sheet phase 2 (spec §15): the costing strip (stale banner, source,
 * machine class, summation warnings), the offer Price section's currency and
 * version warnings, the P&L currency chip and the Finance review task.
 */
import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, cleanup, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import CostingSheetBar from './CostingSheetBar'
import OfferPriceSection from './offer/OfferPriceSection'
import OfferVsActualTable from './pnl/OfferVsActualTable'
import CostSheetReviewTask from '../costSheet/CostSheetReviewTask'
import { changesApi } from '../../api/changes'
import { costSheetApi } from '../../api/costSheet'
import type { CostingContext, Summation } from '../../types/change'
import type { OfferData } from '../../types/changeOffer'
import type { OfferVsActual } from '../../types/pnl'

vi.mock('../../api/changes', () => ({
  changesApi: { costingContext: vi.fn(), setMachineClass: vi.fn() },
}))
vi.mock('../../api/costSheet', () => ({
  costSheetApi: { reviewTask: vi.fn() },
}))

const ctx: CostingContext = {
  plant_id: 1, plant_name: 'Toccoa', currency: 'USD', rate_source: 'cost_sheet',
  current_version: { id: 9, version: 2, valid_from: '2026-07-01' }, latest_version: 2,
  stale: { stale: true, review_months: 12, latest_version: 2, reviewed_on: '2025-07-01',
    due_on: '2026-07-01', reason: 'review_due' },
  machine_classes: [{ id: 3, name: '200-450 t', tonnage_min: 200, tonnage_max: 450 },
    { id: 4, name: '>450 t', tonnage_min: 450, tonnage_max: null }],
  machine_class_id: null, default_machine_class_id: 3, effective_machine_class_id: 3,
  tonnage: 350, positions_by_department: {}, can_set_machine_class: true,
}

const wrap = (ui: React.ReactElement) =>
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <MemoryRouter>{ui}</MemoryRouter>
  </QueryClientProvider>)

describe('CostingSheetBar', () => {
  afterEach(cleanup)

  it('shows the stale banner, the source and the tonnage default class', async () => {
    vi.mocked(changesApi.costingContext).mockResolvedValue(ctx as never)
    wrap(<CostingSheetBar changeId={7} editable />)
    const banner = await screen.findByTestId('costing-stale-banner')
    expect(banner.textContent).toContain('Cost sheet v2 is older than 12 months')
    expect(banner.textContent).toContain('01.07.2026')
    expect(screen.getByTestId('costing-sheet-source').textContent)
      .toBe('Priced from cost sheet v2 (Toccoa, USD)')
    const pick = screen.getByTestId('costing-machine-class') as HTMLSelectElement
    expect(pick.options[0].textContent).toBe('Automatic: 200-450 t (from tool 350 t)')
    vi.mocked(changesApi.setMachineClass).mockResolvedValue({ ...ctx, machine_class_id: 4 } as never)
    fireEvent.change(pick, { target: { value: '4' } })
    await waitFor(() => expect(changesApi.setMachineClass).toHaveBeenCalledWith(7, 4))
  })

  it('lists the summation warnings and the totals per currency', async () => {
    vi.mocked(changesApi.costingContext).mockResolvedValue(
      { ...ctx, stale: { ...ctx.stale!, stale: false } } as never)
    const summation = {
      currency: 'USD', mixed_currency: true,
      totals_by_currency: {
        EUR: { one_time_internal: 120, one_time_external: 0, lifecycle_internal: 0, lifecycle_external: 0, grand_total: 120 },
        USD: { one_time_internal: 100, one_time_external: 0, lifecycle_internal: 0, lifecycle_external: 0, grand_total: 100 },
      },
      warnings: [
        { code: 'mixed_currency', message: 'Costing has amounts in EUR: they are not in the USD totals' },
        { code: 'no_rate', message: '1 costing line has no rate in the cost sheet and is not counted' },
      ],
    } as unknown as Summation
    wrap(<CostingSheetBar changeId={7} editable summation={summation} />)
    const list = await screen.findByTestId('costing-summation-warnings')
    expect(list.querySelectorAll('li')).toHaveLength(2)
    expect(screen.queryByTestId('costing-stale-banner')).toBeNull()
    expect(screen.getByTestId('costing-totals-by-currency').textContent)
      .toContain('120,00 EUR · 100,00 USD')
  })

  it('says so when no version is valid today', async () => {
    vi.mocked(changesApi.costingContext).mockResolvedValue(
      { ...ctx, current_version: null, stale: null } as never)
    wrap(<CostingSheetBar changeId={7} editable={false} />)
    expect((await screen.findByTestId('costing-sheet-source')).textContent)
      .toBe('No cost sheet version is valid today: nothing can be priced')
    expect((screen.getByTestId('costing-machine-class') as HTMLSelectElement).disabled).toBe(true)
  })
})

describe('Offer Price section warnings', () => {
  afterEach(cleanup)

  it('shows currency and cost sheet warnings, not the others', () => {
    const data = { cost_lines: [], factors: [], risks: [], changeover: { mode: 'running_change' },
      piece_price: { enabled: false, rows: [] }, free_fields: [] } as unknown as OfferData
    render(<OfferPriceSection data={data} update={() => {}} editable={false} currency="EUR"
      warnings={[
        { code: 'currency_mismatch', message: 'The costing is in USD, this offer is in EUR: amounts are not converted' },
        { code: 'cost_sheet_outdated', message: 'Costing used cost sheet v1, current is v2' },
        { code: 'recipient_missing', message: 'The recipient company is empty' },
      ]} />)
    const box = screen.getByTestId('offer-price-warnings')
    expect(box.textContent).toContain('The costing is in USD, this offer is in EUR')
    expect(box.textContent).toContain('Costing used cost sheet v1, current is v2')
    expect(box.textContent).not.toContain('recipient')
  })
})

describe('P&L offer vs actual', () => {
  afterEach(cleanup)

  it('flags a costing currency that differs from the offer', () => {
    const data = {
      change_id: 7, currency: 'EUR', costing_currency: 'USD', basis: 'accepted_offer',
      phase: 'plan', offer_version: 1, frozen_at: null, lines: [],
      planned_revenue: null, actual_revenue: null, planned_cost: null, actual_cost: null,
      planned_margin: null, actual_margin: null, planned_margin_pct: null,
      actual_margin_pct: null, variance: null, booked_hours: 0, issue_count: 0,
      timing: { baseline_finish: null, forecast_finish: null, actual_finish: null,
        slip_days: null, unit: 'calendar days', baseline_source: null },
      piece_price: null,
      warnings: ['Costing used cost sheet v1, current is v2'],
    } as unknown as OfferVsActual
    render(<OfferVsActualTable data={data} />)
    expect(screen.getByTestId('ova-currency-mismatch').textContent)
      .toBe('Offer EUR, costing USD: not converted')
    expect(screen.getByTestId('ova-sheet-outdated').textContent)
      .toBe('Costing used cost sheet v1, current is v2')
  })
})

describe('My Tasks: Review the cost sheet', () => {
  afterEach(cleanup)

  it('appears for Finance when the sheet is stale', async () => {
    vi.mocked(costSheetApi.reviewTask).mockResolvedValue({
      due: true, is_finance: true,
      stale: { stale: true, review_months: 12, latest_version: 3, reviewed_on: '2025-06-01',
        due_on: '2026-06-01', reason: 'review_due' },
    })
    wrap(<CostSheetReviewTask />)
    const item = await screen.findByTestId('cost-sheet-review-task')
    expect(item.textContent).toContain('Review the cost sheet')
    expect(item.textContent).toContain('Cost sheet v3')
  })

  it('stays away when nothing is due', async () => {
    vi.mocked(costSheetApi.reviewTask).mockResolvedValue({ due: false, is_finance: false, stale: null })
    wrap(<CostSheetReviewTask />)
    await waitFor(() => expect(costSheetApi.reviewTask).toHaveBeenCalled())
    expect(screen.queryByTestId('cost-sheet-review-task')).toBeNull()
  })
})
