import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest'
import { render, screen, cleanup, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import QuoteBasis from './QuoteBasis'
import { changesApi } from '../../api/changes'
import { t } from '../../i18n/cmLabels'

vi.mock('../../api/changes', () => ({ changesApi: { getSummation: vi.fn() } }))

const DEPTS = [{ id: 2, name: 'Development' }, { id: 4, name: 'Tool Engineer' }]

const concern = (over: Record<string, unknown> = {}) => ({
  id: 1, change_id: 7, kind: 'risk', note: 'thin wall will not fill',
  raised_by: 9, raised_at: '2026-08-08T09:00:00', is_open: true,
  department_id: 4, risk_type: 'fill_issue', severity: 3, ...over,
}) as never

const wrap = (concerns: unknown[] = []) => render(
  <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <QuoteBasis changeId={7} plants={[{ id: 1, name: 'Plant A' }]}
      concerns={concerns as never} departments={DEPTS} />
  </QueryClientProvider>)

const SUMMATION = {
  by_plant: [], by_department: [],
  totals: { one_time_internal: 0, one_time_external: 0,
    lifecycle_internal: 0, lifecycle_external: 0, grand_total: 500 },
  effort_by_department: [], total_effort_hours: 0,
}

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
    vi.mocked(changesApi.getSummation).mockResolvedValue(SUMMATION as never)
    wrap()
    await waitFor(() => expect(screen.getByTestId('quote-basis-total')).toBeTruthy())
    expect(screen.queryByTestId('quote-basis-minutes')).toBeNull()
  })
})

describe('QuoteBasis technical risks', () => {
  afterEach(cleanup)
  beforeEach(() => {
    vi.mocked(changesApi.getSummation).mockResolvedValue(SUMMATION as never)
  })

  it('carries an open severity-3 risk onto the offer, named and attributed', async () => {
    wrap([concern()])
    await waitFor(() => expect(screen.getByTestId('quote-risks')).toBeTruthy())
    expect(screen.getByText(t('quote.risks'))).toBeTruthy()
    const row = screen.getByTestId('quote-risk-1')
    expect(row.textContent).toContain('Tool Engineer')
    expect(row.textContent).toContain(t('risktype.fill_issue'))
    expect(row.textContent).toContain('thin wall will not fill')
    // The rating is on the row, in the colour that says "worst".
    expect(row.textContent).toContain('3')
  })

  it('keeps the lesser and the settled risks off the offer', async () => {
    // A 2 is internal housekeeping; a closed 3 was dealt with. Neither is a
    // judgement Sales owes the customer.
    wrap([
      concern({ id: 2, severity: 2, note: 'minor witness line' }),
      concern({ id: 3, severity: 3, is_open: false, withdrawn_at: '2026-08-09T00:00:00',
        note: 'gate moved, closed' }),
    ])
    await waitFor(() => expect(screen.getByTestId('quote-basis-total')).toBeTruthy())
    expect(screen.queryByTestId('quote-risks')).toBeNull()
    expect(screen.queryByText('minor witness line')).toBeNull()
    expect(screen.queryByText('gate moved, closed')).toBeNull()
  })

  it('says nothing at all when there is no such risk', async () => {
    wrap([])
    await waitFor(() => expect(screen.getByTestId('quote-basis-total')).toBeTruthy())
    expect(screen.queryByTestId('quote-risks')).toBeNull()
    expect(screen.queryByText(t('quote.risks'))).toBeNull()
  })

  it('ignores a legacy flag that never was a risk', async () => {
    // Old reject_proposal / needs_info rows carry no severity — they must not
    // leak onto the offer through a loose filter.
    wrap([concern({ id: 4, kind: 'reject_proposal', severity: null, risk_type: null,
      note: 'would reject' })])
    await waitFor(() => expect(screen.getByTestId('quote-basis-total')).toBeTruthy())
    expect(screen.queryByTestId('quote-risks')).toBeNull()
  })
})
