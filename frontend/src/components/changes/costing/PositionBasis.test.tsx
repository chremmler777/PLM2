import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, cleanup, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { PositionBasis, basisWords } from './PositionBasis'
import { changesApi } from '../../../api/changes'
import type { CostPosition } from '../../../types/change'

vi.mock('../../../api/changes', () => ({
  changesApi: {
    updateCostPosition: vi.fn().mockResolvedValue({}),
    updateCostingOffer: vi.fn().mockResolvedValue({}),
    checkEstimate: vi.fn().mockResolvedValue({}),
  },
}))

const wrap = (ui: React.ReactElement) => (
  <QueryClientProvider client={new QueryClient()}>{ui}</QueryClientProvider>
)
const pos = (over: Partial<CostPosition> = {}): CostPosition => ({
  id: 9, department_id: 3, label: 'Insert re-cut', kind: 'external', pricing: 'estimate',
  est_cost: 900, basis: 'estimate', estimated: true, offers: [], ...over,
} as CostPosition)

afterEach(() => { cleanup(); vi.clearAllMocks() })

describe('PositionBasis (spec §4, C25)', () => {
  it('an estimate is marked and saves only a reference that names something', async () => {
    render(wrap(<PositionBasis changeId={7} position={pos()} editable onChanged={() => {}} />))
    expect(screen.getByTestId('basis-estimated-9')).toBeTruthy()
    const save = screen.getByTestId('basis-save-9') as HTMLButtonElement
    fireEvent.change(screen.getByTestId('basis-ref-9'), { target: { value: 'ok' } })
    expect(save.disabled).toBe(true)
    fireEvent.change(screen.getByTestId('basis-ref-9'), { target: { value: 'Hasco 12 Oct 2026' } })
    fireEvent.click(save)
    await waitFor(() => expect(changesApi.updateCostPosition).toHaveBeenCalledWith(
      7, 9, { basis: 'estimate', basis_ref: 'Hasco 12 Oct 2026' }))
  })

  it('asks quote vs estimate with nothing preselected; above needs the amount', async () => {
    // quoted status: the costing window is closed (editable false), the
    // served flag opens the form (R24)
    render(wrap(<PositionBasis changeId={7} editable={false} onChanged={() => {}}
      position={pos({ estimate_check: 'pending', can_check_estimate: true })} />))
    const save = screen.getByTestId('estcheck-save-9') as HTMLButtonElement
    expect(save.disabled).toBe(true)
    fireEvent.click(screen.getByTestId('estcheck-9-above'))
    expect(save.disabled).toBe(true)
    fireEvent.change(screen.getByTestId('estcheck-over-9'), { target: { value: '300' } })
    fireEvent.click(save)
    await waitFor(() => expect(changesApi.checkEstimate).toHaveBeenCalledWith(
      7, 9, { verdict: 'above', over: 300 }))
  })

  it('records the quote that came in with the comparison, in one step', async () => {
    render(wrap(<PositionBasis changeId={7} editable={false} onChanged={() => {}}
      position={pos({ estimate_check: null, can_check_estimate: true })} />))
    const save = screen.getByTestId('estcheck-save-9') as HTMLButtonElement
    fireEvent.click(screen.getByTestId('estcheck-9-within'))
    expect(save.disabled).toBe(true)                 // no supplier, number, amount
    fireEvent.change(screen.getByTestId('estcheck-vendor-9'), { target: { value: 'FZ' } })
    fireEvent.change(screen.getByTestId('estcheck-ref-9'), { target: { value: 'ok' } })
    fireEvent.change(screen.getByTestId('estcheck-amount-9'), { target: { value: '920' } })
    expect(save.disabled).toBe(true)                 // a number that says nothing
    fireEvent.change(screen.getByTestId('estcheck-ref-9'), { target: { value: 'FZ-Q-2240' } })
    fireEvent.click(save)
    await waitFor(() => expect(changesApi.checkEstimate).toHaveBeenCalledWith(
      7, 9, { verdict: 'within', vendor_name: 'FZ', quote_ref: 'FZ-Q-2240', cost: 920 }))
  })

  it('no form without the served flag; a settled one reads settled', () => {
    render(wrap(<PositionBasis changeId={7} editable onChanged={() => {}}
      position={pos({ estimate_check: 'pending', can_check_estimate: false })} />))
    expect(screen.queryByTestId('estcheck-9')).toBeNull()
    cleanup()
    render(wrap(<PositionBasis changeId={7} editable={false} onChanged={() => {}}
      position={pos({ estimate_check: 'settled', estimate_over: 300 })} />))
    expect(screen.getByTestId('basis-9').textContent).toContain('settled')
  })

  it('reads the basis in words, read-only for others', () => {
    expect(basisWords(pos({ basis: 'same_as', basis_part_number: 'T-3454',
      basis_differs: '2 cavities' }))).toBe('same as T-3454, differs: 2 cavities')
    render(wrap(<PositionBasis changeId={7} position={pos({ basis_ref: 'Hasco 12 Oct' })}
      editable={false} onChanged={() => {}} />))
    expect(screen.queryByTestId('basis-save-9')).toBeNull()
    expect(screen.getByTestId('basis-9').textContent).toContain('estimate: Hasco 12 Oct')
  })
})
