import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, cleanup } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import PnlCard from './PnlCard'
import type { ChangeDetail, Summation } from '../../types/change'
import { changesApi } from '../../api/changes'

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

  it('is hidden for scoping and captured statuses', () => {
    render(wrap(<PnlCard change={change({ status: 'scoping' })} />))
    expect(screen.queryByText('Revenue')).toBeNull()
    cleanup()
    render(wrap(<PnlCard change={change({ status: 'captured' })} />))
    expect(screen.queryByText('Revenue')).toBeNull()
  })
})
