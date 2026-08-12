import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, cleanup } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import PnlCard from './PnlCard'
import type { ChangeDetail, Summation } from '../../types/change'
import { changesApi } from '../../api/changes'
import { t } from '../../i18n/cmLabels'

vi.mock('../../api/changes', () => ({
  changesApi: { getSummation: vi.fn() },
}))

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
    expect(screen.getByText('5.000')).toBeDefined()
    expect(await screen.findByText('3.000')).toBeDefined()
  })

  it('shows Approved budget and "vs. approved budget" label for an internal change', async () => {
    vi.mocked(changesApi.getSummation).mockResolvedValue(summation({ grand_total: 2000 }))
    render(wrap(<PnlCard change={change({ customer_relevant: false, internal_approved_amount: 3000 })} />))
    expect(await screen.findByText('Approved budget')).toBeDefined()
    expect(screen.getByText('vs. approved budget')).toBeDefined()
    expect(screen.getByText('3.000')).toBeDefined()
    expect(await screen.findByText('1.000')).toBeDefined()
  })

  it('is hidden before costing (in_assessment)', () => {
    render(wrap(<PnlCard change={change({ status: 'in_assessment', customer_relevant: true, quoted_price: 5000 })} />))
    expect(screen.queryByText('Revenue')).toBeNull()
    expect(changesApi.getSummation).not.toHaveBeenCalled()
  })

  it('adds an Actuals section when the payload carries one', async () => {
    vi.mocked(changesApi.getSummation).mockResolvedValue({
      ...summation({ grand_total: 2000 }),
      actuals: {
        by_department: [
          { department_id: 2, hours: 12, rate: 100, internal_cost: 1200,
            plan_internal_cost: 1000 },
          { department_id: 4, hours: 5, rate: null, internal_cost: 0, unrated: true },
        ],
        internal_cost: 1200,
        plan_internal_cost: 1500,
        extras: [
          { key: 'scrap_quote', amount: 800 },
          { key: 'weight_delta', amount: 250 },
        ],
        extra_cost: 1050,
        total_cost: 2250,
        delta: 250,
      },
    } as never)
    render(wrap(<PnlCard change={change({ status: 'in_validation', customer_relevant: true, quoted_price: 5000 })}
      departments={[{ id: 2, name: 'Development' }, { id: 4, name: 'Tool Engineer' }]} />))

    expect(await screen.findByTestId('pnl-actuals')).toBeDefined()
    // Per department: booked hours, what they cost, and what was planned.
    const dev = screen.getByTestId('pnl-actual-dept-2')
    expect(dev.textContent).toContain('Development')
    expect(dev.textContent).toContain('12 h')
    expect(dev.textContent).toContain('1.200')
    expect(dev.textContent).toContain('1.000')
    // Unpriced hours are called out rather than counted as zero in silence.
    expect(screen.getByTestId('pnl-actual-unrated-4')).toBeDefined()
    expect(screen.getByText(t('actuals.unratedHint'))).toBeDefined()
    // The extras the plan did not carry, named.
    expect(screen.getByTestId('pnl-actual-extra-scrap_quote').textContent)
      .toContain(t('actuals.extra.scrap_quote'))
    expect(screen.getByTestId('pnl-actual-extra-weight_delta').textContent).toContain('250')
    expect(screen.getByTestId('pnl-actuals-total').textContent).toBe('2.250')
    expect(screen.getByTestId('pnl-actuals-delta').textContent).toContain('+250')
  })

  it('renders exactly as before when the payload carries no actuals', async () => {
    vi.mocked(changesApi.getSummation).mockResolvedValue(summation({ grand_total: 2000 }))
    render(wrap(<PnlCard change={change({ customer_relevant: true, quoted_price: 5000 })} />))
    expect(await screen.findByText('Revenue')).toBeDefined()
    expect(screen.queryByTestId('pnl-actuals')).toBeNull()
  })

  it('is hidden for scoping and captured statuses', () => {
    render(wrap(<PnlCard change={change({ status: 'scoping' })} />))
    expect(screen.queryByText('Revenue')).toBeNull()
    cleanup()
    render(wrap(<PnlCard change={change({ status: 'captured' })} />))
    expect(screen.queryByText('Revenue')).toBeNull()
  })
})
