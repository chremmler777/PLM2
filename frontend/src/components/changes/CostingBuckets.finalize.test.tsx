/** Christoph 2026-11-08: Finalize is the department's dominant last step:
 *  at the end of its lines, disabled with what is missing, pinned on top once
 *  nothing is, confirmed inline, and saying what happens next. */
import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import CostingBuckets from './CostingBuckets'
import { changesApi } from '../../api/changes'

vi.mock('../../api/changes', () => ({
  changesApi: {
    getSummation: vi.fn().mockResolvedValue(undefined),
    getCostLines: vi.fn().mockResolvedValue([]),
    putCostLines: vi.fn().mockResolvedValue([]),
    referenceRates: vi.fn().mockResolvedValue([]),
    referenceActivities: vi.fn().mockResolvedValue([]),
    listCostPositions: vi.fn().mockResolvedValue([]),
    costingTags: vi.fn().mockResolvedValue({ items: [] }),
    finalizeCheck: vi.fn(),
    finalizeDepartmentCosting: vi.fn().mockResolvedValue({}),
    reopenDepartmentCosting: vi.fn().mockResolvedValue({}),
  },
}))

const DEPTS = [
  { id: 2, name: 'Tool Engineer', is_active: true },
  { id: 9, name: 'Project Manager', is_active: true },
]
const assessment = (over: Record<string, unknown> = {}) => ({
  id: 1, department_id: 2, verdict: 'feasible', stage_order: 1, rasic_letter: 'R',
  status: 'submitted', owner_id: null, owner_name: null, accepted_at: null,
  due_date: null, overdue: false, lead_time_impact_days: null, ...over,
})
const change = (over: Record<string, unknown> = {}) => ({
  id: 7, status: 'costing',
  assessments: [assessment(), assessment({ id: 2, department_id: 9, owner_name: 'Steven' })],
  costing_owed_department_ids: [2], costing_pending_department_ids: [2],
  costing_finalized_department_ids: [],
  ...over,
}) as never

const show = (over: Record<string, unknown> = {}) => render(
  <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <CostingBuckets change={change(over)} departments={DEPTS} plants={[]}
      myDepartmentIds={[2]} canSeeAll={false} editable />
  </QueryClientProvider>)

afterEach(() => { cleanup(); vi.clearAllMocks() })

describe('FinalizeBar', () => {
  it('while something is missing: disabled at the end with the list, nothing pinned on top', async () => {
    vi.mocked(changesApi.finalizeCheck).mockResolvedValue({
      reasons: ['Insert: enter the hours'], position_ids: [],
      items: [{ tag: 'support_hours', text: 'Implementation support: enter the hours (0 allowed)' }] })
    show()
    expect((await screen.findByTestId('costing-why-not-2')).textContent).toMatch(/Implementation support/)
    expect((screen.getByTestId('costing-finalize-2') as HTMLButtonElement).disabled).toBe(true)
    expect(screen.queryByTestId('costing-finalize-top-2')).toBeNull()
  })

  it('nothing missing: pinned on top as well; confirm inline, Keep working changes nothing', async () => {
    vi.mocked(changesApi.finalizeCheck).mockResolvedValue({ reasons: [], position_ids: [], items: [] })
    show()
    expect(await screen.findByTestId('costing-finalize-top-2')).toBeTruthy()
    const btn = screen.getByTestId('costing-finalize-2') as HTMLButtonElement
    await waitFor(() => expect(btn.disabled).toBe(false))
    fireEvent.click(btn)
    expect(screen.getByTestId('costing-finalize-confirm-2').textContent)
      .toMatch(/Finalize costing for Tool Engineer\? You can't change your lines afterwards; the PM takes over/)
    fireEvent.click(screen.getByTestId('costing-keep-working-2'))
    expect(screen.queryByTestId('costing-finalize-confirm-2')).toBeNull()
    expect(screen.getByTestId('costing-kept-working-2').textContent)
      .toMatch(/Not finalized: the PM sees your department as open/)
    expect(changesApi.finalizeDepartmentCosting).not.toHaveBeenCalled()
  })

  it('Finalize now finalizes', async () => {
    vi.mocked(changesApi.finalizeCheck).mockResolvedValue({ reasons: [], position_ids: [], items: [] })
    show()
    fireEvent.click(await screen.findByTestId('costing-finalize-top-btn-2'))
    fireEvent.click(screen.getByTestId('costing-finalize-now-2'))
    await waitFor(() => expect(changesApi.finalizeDepartmentCosting).toHaveBeenCalledWith(7, 2))
  })

  it('finalized: who and when, what happens next (the PM by name), who may reopen', async () => {
    show({ costing_finalized_department_ids: [2], costing_pending_department_ids: [],
      costing_finalized_info: { 2: { at: '2026-11-07T10:00:00', by: 3, by_name: 'Dale Smith' } } })
    expect((await screen.findByTestId('costing-finalized-by-2')).textContent).toMatch(/Finalized by Dale Smith, /)
    expect(screen.getByTestId('costing-next-2').textContent).toMatch(/the PM \(Steven\).*prepares the\s+offer/)
    expect(screen.getByText(/Project Management or an admin can/)).toBeTruthy()
    expect(screen.getByTestId('costing-reopen-2')).toBeTruthy()
    expect(screen.queryByTestId('costing-finalize-2')).toBeNull()
  })
})
