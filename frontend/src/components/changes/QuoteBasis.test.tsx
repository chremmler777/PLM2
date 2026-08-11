import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, cleanup, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import QuoteBasis from './QuoteBasis'
import { changesApi } from '../../api/changes'
import { t } from '../../i18n/cmLabels'

vi.mock('../../api/changes', () => ({ changesApi: { getSummation: vi.fn() } }))

const wrap = () => render(
  <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <QuoteBasis changeId={7} plants={[{ id: 1, name: 'Plant A' }]} />
  </QueryClientProvider>)

describe('QuoteBasis', () => {
  afterEach(cleanup)

  it('states cost and production-time basis without suggesting a price', async () => {
    vi.mocked(changesApi.getSummation).mockResolvedValue({
      by_plant: [], by_department: [],
      totals: { one_time_internal: 900, one_time_external: 100,
        lifecycle_internal: 0, lifecycle_external: 0, grand_total: 1000 },
      effort_by_department: [], total_effort_hours: 0,
      lifecycle_minutes_by_plant: [{ plant_id: 1, minutes_per_part: -1.5 }],
      total_minutes_per_part: -1.5, max_lead_time_days: 15,
    } as never)
    wrap()
    await waitFor(() => expect(screen.getByTestId('quote-basis-total').textContent).toBe('1000.00'))
    const minutes = screen.getByTestId('quote-basis-minutes')
    // A time saving reads as a saving, with its plant named.
    expect(minutes.textContent).toContain('Plant A')
    expect(minutes.textContent).toContain('-1.5')
    expect(screen.getByText(t('quote.basisHint'))).toBeTruthy()
  })

  it('leaves out the time block when the change costs no production time', async () => {
    vi.mocked(changesApi.getSummation).mockResolvedValue({
      by_plant: [], by_department: [],
      totals: { one_time_internal: 0, one_time_external: 0,
        lifecycle_internal: 0, lifecycle_external: 0, grand_total: 500 },
      effort_by_department: [], total_effort_hours: 0,
    } as never)
    wrap()
    await waitFor(() => expect(screen.getByTestId('quote-basis-total')).toBeTruthy())
    expect(screen.queryByTestId('quote-basis-minutes')).toBeNull()
  })
})
