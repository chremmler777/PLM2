import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, cleanup, fireEvent, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import EcrKpiBoardPage from './EcrKpiBoardPage'
import { reportsApi } from '../api/reports'


vi.mock('../api/reports', () => ({
  reportsApi: {
    ecrKpis: vi.fn().mockResolvedValue({
      window_months: 12,
      rfq: { on_time: 3, late: 1, rate: 0.75, avg_days_late: 3, open_overdue: 1, open_due_7d: 2, open_total: 5 },
      implementation: { on_time: 0, late: 0, rate: null, avg_days_late: null, open_overdue: 0, open_due_7d: 0, open_total: 1 },
      trend: [{ month: '2026-09', rfq_on_time: 3, rfq_late: 1, impl_on_time: 0, impl_late: 0 }],
      by_project: [{ project_id: 1, project_number: '1994', project_name: 'Brose', rfq_on_time: 3, rfq_late: 1, impl_on_time: 0, impl_late: 0 }],
      late: [
        { id: 7, change_number: 'GB-CM-0007', title: 'Open quote', project_number: '1994', lead_name: 'Ann',
          status: 'costing', kind: 'rfq', due: '2026-09-20', done: null, days_late: 11 },
        { id: 8, change_number: 'GB-CM-0008', title: 'Late release', project_number: '1994', lead_name: null,
          status: 'released', kind: 'implementation', due: '2026-09-01', done: '2026-09-05', days_late: 4 },
      ],
    }),
  },
}))

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter><EcrKpiBoardPage /></MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('EcrKpiBoardPage', () => {
  afterEach(() => cleanup())

  it('shows both on-time rates, with a dash when nothing completed', async () => {
    renderPage()
    expect((await screen.findByTestId('rfq-rate')).textContent).toBe('75%')
    expect(screen.getByText('3 of 4 on time')).toBeDefined()
    expect(screen.getByTestId('implementation-rate').textContent).toBe('-')
    expect(screen.getByText('nothing completed in this period')).toBeDefined()
  })

  it('lists misses with links and filters them by deadline', async () => {
    renderPage()
    const table = await screen.findByRole('region', { name: 'Late and overdue' })
    expect(within(table).getByText('GB-CM-0007').closest('a')?.getAttribute('href')).toBe('/changes/7')
    expect(within(table).getByText('open')).toBeDefined()
    fireEvent.click(within(table).getByRole('button', { name: 'Implementation' }))
    expect(within(table).queryByText('GB-CM-0007')).toBeNull()
    expect(within(table).getByText('GB-CM-0008')).toBeDefined()
  })

  it('refetches for the chosen period, 0 meaning all time', async () => {
    renderPage()
    await screen.findByTestId('rfq-rate')
    fireEvent.click(screen.getByRole('button', { name: 'All time' }))
    expect(reportsApi.ecrKpis).toHaveBeenLastCalledWith(0)
  })
})
