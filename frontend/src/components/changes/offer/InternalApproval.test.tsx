import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, cleanup, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import InternalApproval, { paybackMonths } from './InternalApproval'
import { changesApi } from '../../../api/changes'
import type { ChangeDetail } from '../../../types/change'

let total = 4800
vi.mock('../../../api/changes', () => ({
  changesApi: {
    approveInternalCosts: vi.fn().mockResolvedValue({}),
    getSummation: vi.fn(() => Promise.resolve({ totals: { grand_total: total }, currency: 'EUR' })),
    listCostPositions: vi.fn(() => Promise.resolve([
      { id: 1, label: 'Insert re-cut', kind: 'external', estimated: true }])),
  },
}))
vi.mock('../../gantt/DateInput', () => ({
  default: ({ onChange, id }: { onChange: (v: string) => void; id: string }) => (
    <input data-testid="due" id={id} onChange={(e) => onChange(e.target.value)} />),
}))

const wrap = (ui: React.ReactElement) => (
  <QueryClientProvider client={new QueryClient()}>{ui}</QueryClientProvider>
)
const change = { id: 7, status: 'costing', assessment_v2: true } as unknown as ChangeDetail

afterEach(() => { cleanup(); vi.clearAllMocks(); total = 4800 })

describe('InternalApproval card (spec §5)', () => {
  it('approved and owed again: the record stays, the card asks to re-approve (A3-05)', () => {
    const approved = { ...change, internal_approved_at: '2026-10-14T10:00:00Z',
      internal_approved_amount: 5000 } as unknown as ChangeDetail
    render(wrap(<InternalApproval change={approved} canApprove />))
    expect(screen.getByTestId('internal-approved')).toBeTruthy()
    expect(screen.getByTestId('internal-reapprove')).toBeTruthy()
    expect(screen.getByRole('button', { name: /approve internal costs/i })).toBeTruthy()
  })

  it('approved and nothing owed: no button (A3-05 negative)', () => {
    const approved = { ...change, internal_approved_at: '2026-10-14T10:00:00Z' } as unknown as ChangeDetail
    render(wrap(<InternalApproval change={approved} canApprove={false} />))
    expect(screen.getByTestId('internal-approved')).toBeTruthy()
    expect(screen.queryByRole('button', { name: /approve internal costs/i })).toBeNull()
  })

  it('held by C5: says why and offers the override, no approve button (A3-09)', () => {
    const onOverride = vi.fn()
    render(wrap(<InternalApproval change={change} canApprove={false}
      hold="Costing not finalized: Toolshop. Approve once they are finalized" onOverride={onOverride} />))
    expect(screen.getByTestId('internal-hold').textContent).toContain('Costing not finalized: Toolshop')
    expect(screen.queryByRole('button', { name: /approve internal costs/i })).toBeNull()
    fireEvent.click(screen.getByTestId('internal-hold-override'))
    expect(onOverride).toHaveBeenCalled()
  })

  it('held without the right to ask: no override button (A3-09 negative)', () => {
    render(wrap(<InternalApproval change={change} canApprove={false} hold="Costing not finalized: Toolshop" />))
    expect(screen.queryByTestId('internal-hold-override')).toBeNull()
  })

  it('payback in months', () => {
    expect(paybackMonths(4800, 2400)).toBe(24)
    expect(paybackMonths(4800, 0)).toBeNull()
  })

  it('with money: banner, and nothing approves without the case', async () => {
    render(wrap(<InternalApproval change={change} canApprove />))
    fireEvent.click(screen.getByRole('button', { name: /approve internal costs/i }))
    expect(await screen.findByTestId('internal-estimate-banner')).toBeTruthy()
    fireEvent.change(screen.getByTestId('due'), { target: { value: '2027-02-01' } })
    const go = screen.getByTestId('internal-approve-confirm') as HTMLButtonElement
    expect(go.disabled).toBe(true)
    fireEvent.change(screen.getByTestId('internal-rationale'), { target: { value: 'saving' } })
    expect(go.disabled).toBe(true)                        // volume, saving, basis owed
    fireEvent.change(screen.getByTestId('internal-volume'), { target: { value: '120000' } })
    fireEvent.change(screen.getByTestId('internal-saving'), { target: { value: '2400' } })
    fireEvent.click(screen.getByTestId('internal-basis-calculated'))
    expect(screen.getByTestId('internal-payback').textContent).toContain('24 months')
    expect(go.disabled).toBe(false)
    fireEvent.click(go)
    await waitFor(() => expect(changesApi.approveInternalCosts).toHaveBeenCalledWith(7,
      expect.objectContaining({ rationale: 'saving', volume: 120000, saving: 2400,
        saving_basis: 'calculated' })))
  })

  it('an approver without price view still gets the money fields (served flag)', async () => {
    vi.mocked(changesApi.getSummation).mockRejectedValueOnce(new Error('403'))
    render(wrap(<InternalApproval change={change} canApprove needsMoney />))
    fireEvent.click(screen.getByRole('button', { name: /approve internal costs/i }))
    expect(await screen.findByTestId('internal-volume')).toBeTruthy()
    expect(screen.queryByTestId('internal-cost')).toBeNull()       // no amount shown
    fireEvent.change(screen.getByTestId('due'), { target: { value: '2027-02-01' } })
    fireEvent.change(screen.getByTestId('internal-rationale'), { target: { value: 'saving' } })
    fireEvent.change(screen.getByTestId('internal-volume'), { target: { value: '1000' } })
    fireEvent.change(screen.getByTestId('internal-saving'), { target: { value: '500' } })
    fireEvent.click(screen.getByTestId('internal-basis-estimate'))
    fireEvent.click(screen.getByTestId('internal-approve-confirm'))
    await waitFor(() => expect(changesApi.approveInternalCosts).toHaveBeenCalledWith(7,
      expect.objectContaining({ volume: 1000, saving: 500, saving_basis: 'estimate' })))
  })

  it('at no cost: one click and the rationale', async () => {
    total = 0
    render(wrap(<InternalApproval change={change} canApprove />))
    fireEvent.click(screen.getByRole('button', { name: /approve internal costs/i }))
    await screen.findByTestId('internal-cost')
    expect(screen.queryByTestId('internal-volume')).toBeNull()
    fireEvent.change(screen.getByTestId('due'), { target: { value: '2027-02-01' } })
    fireEvent.change(screen.getByTestId('internal-rationale'), { target: { value: 'quality' } })
    expect((screen.getByTestId('internal-approve-confirm') as HTMLButtonElement).disabled).toBe(false)
  })
})
