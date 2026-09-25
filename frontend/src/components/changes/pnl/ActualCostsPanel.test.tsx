/** Actual cost entry: a typed currency mark goes to the backend as typed, and
 *  its refusal (400, the mark contradicts the currency) is shown inline. */
import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { changesApi } from '../../../api/changes'
import { actualCostsApi } from '../../../api/actualCosts'
import ActualCostsPanel from './ActualCostsPanel'

vi.mock('../../../api/changes', () => ({ changesApi: { costingContext: vi.fn() } }))
vi.mock('../../../api/actualCosts', () => ({
  actualCostsApi: { list: vi.fn(), add: vi.fn(), remove: vi.fn() },
}))

const wrap = (ui: React.ReactElement) =>
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    {ui}
  </QueryClientProvider>)

afterEach(() => { cleanup(); vi.clearAllMocks() })

const list = { items: [], total: 0, currency: 'EUR', can_write: true, writable_department_ids: null, cost_role: true }

async function openForm() {
  vi.mocked(actualCostsApi.list).mockResolvedValue(list as never)
  vi.mocked(changesApi.costingContext).mockResolvedValue({ currency: 'EUR' } as never)
  wrap(<ActualCostsPanel changeId={21} />)
  fireEvent.click(await screen.findByTestId('actual-cost-open'))
}

describe('ActualCostsPanel currency marks', () => {
  it('sends a plain amount as a number', async () => {
    vi.mocked(actualCostsApi.add).mockResolvedValue({} as never)
    await openForm()
    fireEvent.change(screen.getByLabelText('Amount'), { target: { value: '1,250.50' } })
    fireEvent.click(screen.getByTestId('actual-cost-save'))
    await waitFor(() => expect(actualCostsApi.add).toHaveBeenCalled())
    expect(vi.mocked(actualCostsApi.add).mock.calls[0][1].amount).toBe(1250.5)
  })

  it('sends a marked amount as typed and shows the backend refusal inline', async () => {
    vi.mocked(actualCostsApi.add).mockRejectedValue({
      response: { status: 400, data: { detail: 'The amount is in $ but this change is costed in EUR: choose the currency (USD, CAD, MXN)' } },
    })
    await openForm()
    fireEvent.change(screen.getByLabelText('Amount'), { target: { value: '$1,250' } })
    expect(screen.queryByTestId('actual-cost-amount-hint')).toBeNull()
    fireEvent.click(screen.getByTestId('actual-cost-save'))
    await waitFor(() => expect(actualCostsApi.add).toHaveBeenCalled())
    expect(vi.mocked(actualCostsApi.add).mock.calls[0][1].amount).toBe('$1,250')
    expect((await screen.findByRole('alert')).textContent)
      .toContain('The amount is in $ but this change is costed in EUR')
    // editing the amount clears the refusal
    fireEvent.change(screen.getByLabelText('Amount'), { target: { value: '1,250' } })
    expect(screen.queryByRole('alert')).toBeNull()
  })

  it('still refuses an ambiguous number behind a mark', async () => {
    await openForm()
    fireEvent.change(screen.getByLabelText('Amount'), { target: { value: '12,5 EUR' } })
    expect(screen.getByTestId('actual-cost-amount-hint')).toBeTruthy()
    expect((screen.getByTestId('actual-cost-save') as HTMLButtonElement).disabled).toBe(true)
  })
})
