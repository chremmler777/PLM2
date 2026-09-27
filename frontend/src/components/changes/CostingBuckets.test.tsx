import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import CostingBuckets from './CostingBuckets'
import { changesApi } from '../../api/changes'
import { t } from '../../i18n/cmLabels'

vi.mock('../../api/changes', () => ({
  changesApi: {
    getSummation: vi.fn(),
    setCostLeadTime: vi.fn().mockResolvedValue({}),
    getCostLines: vi.fn().mockResolvedValue([]),
    putCostLines: vi.fn().mockResolvedValue([]),
    referenceRates: vi.fn().mockResolvedValue([
      { department_id: 2, plant_id: 1, hourly_rate: 90, min_factor: 1 },
      { department_id: 4, plant_id: 1, hourly_rate: 80, min_factor: 1 },
    ]),
    referenceActivities: vi.fn().mockResolvedValue([]),
    listCostPositions: vi.fn().mockResolvedValue([]),
    costingTags: vi.fn().mockResolvedValue({ items: [] }),
  },
}))

const DEPTS = [
  { id: 2, name: 'Development', is_active: true },
  { id: 4, name: 'Tool Engineer', is_active: true },
]
const PLANTS = [{ id: 1, name: 'Plant A', is_active: true }]

const assessment = (over: Record<string, unknown> = {}) => ({
  id: 1, department_id: 2, verdict: 'feasible', stage_order: 1, rasic_letter: 'R',
  status: 'submitted', owner_id: null, owner_name: null, accepted_at: null,
  due_date: null, overdue: false, lead_time_impact_days: null, ...over,
})

const change = (over: Record<string, unknown> = {}) => ({
  id: 7, status: 'costing',
  assessments: [assessment(), assessment({ id: 2, department_id: 4 })],
  ...over,
}) as never

const summation = {
  by_plant: [], by_department: [
    { department_id: 2, one_time_internal: 900, one_time_external: 100,
      lifecycle_internal: 0, lifecycle_external: 0 },
    { department_id: 4, one_time_internal: 0, one_time_external: 0,
      lifecycle_internal: 0, lifecycle_external: 0 },
  ],
  totals: { one_time_internal: 900, one_time_external: 100,
    lifecycle_internal: 0, lifecycle_external: 0, grand_total: 1000 },
  effort_by_department: [], total_effort_hours: 0,
  lead_time_by_department: [{ department_id: 2, lead_time_days: 15 }],
  max_lead_time_days: 15,
}

const wrap = (ui: React.ReactElement) =>
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    {ui}
  </QueryClientProvider>)

const buckets = (props: Record<string, unknown> = {}) =>
  wrap(<CostingBuckets change={change()} departments={DEPTS} plants={PLANTS}
    myDepartmentIds={[]} canSeeAll={false} editable {...props} />)

describe('CostingBuckets', () => {
  beforeEach(() => {
    vi.mocked(changesApi.getSummation).mockClear()
      .mockResolvedValue(summation as never)
    vi.mocked(changesApi.setCostLeadTime).mockClear()
  })
  afterEach(cleanup)

  it('says once that Mexico (Silao) is not in use yet when it is one of the change\'s plants', () => {
    buckets({ canSeeAll: true, plants: [...PLANTS, { id: 3, name: 'Silao Mexico', code: 'SIL', is_active: true }] })
    expect(screen.getAllByTestId('plant-not-in-use')).toHaveLength(1)
    expect(screen.getByTestId('costing-bucket-2')).toBeTruthy()
  })

  it('has no Mexico note for the US plant alone', () => {
    buckets({ canSeeAll: true })
    expect(screen.queryByTestId('plant-not-in-use')).toBeNull()
  })

  it('gives every participating department a bucket', () => {
    buckets({ canSeeAll: true })
    expect(screen.getByTestId('costing-bucket-2')).toBeTruthy()
    expect(screen.getByTestId('costing-bucket-4')).toBeTruthy()
  })

  it('opens the member’s own bucket into their grid and lead time', async () => {
    buckets({ myDepartmentIds: [2] })
    fireEvent.click(screen.getByTestId('costing-toggle-2'))
    await waitFor(() => expect(changesApi.getCostLines).toHaveBeenCalledWith(7, 1))
    expect(screen.getByTestId('lead-time-2')).toBeTruthy()
    // The workbook matrix, not a line editor.
    expect(screen.getByTestId('cost-add-row')).toBeTruthy()
    expect(screen.getByTestId('plant-col-1').textContent).toBe('Plant A')
  })

  it('saves the lead time for that department', async () => {
    buckets({ myDepartmentIds: [2] })
    fireEvent.click(screen.getByTestId('costing-toggle-2'))
    fireEvent.change(await screen.findByTestId('lead-time-2'), { target: { value: '20' } })
    fireEvent.click(screen.getByTestId('lead-time-save-2'))
    await waitFor(() => expect(changesApi.setCostLeadTime).toHaveBeenCalledWith(7, 2, 20))
  })

  it('shows a department member their own bucket and nobody else’s', async () => {
    buckets({ myDepartmentIds: [2],
      change: change({ costing_pending_department_ids: [2, 4] }) })
    // No summation is even requested without the privilege.
    expect(changesApi.getSummation).not.toHaveBeenCalled()
    expect(screen.getByTestId('costing-bucket-2')).toBeTruthy()
    // Another department's block is gone entirely — not even a collapsed row.
    expect(screen.queryByTestId('costing-bucket-4')).toBeNull()
    expect(screen.queryByTestId('costing-state-4')).toBeNull()
    // Just a line saying the change does not sit on them alone.
    expect(screen.getByTestId('costing-others').textContent)
      .toBe(t('costing.others').replace('{n}', '1').replace('{s}', ''))
  })

  it('counts the others from the backend pending list, the same as the cockpit', () => {
    // Four departments routed, two of them already done: only the one still
    // owing (not the viewer's) is "still costing".
    buckets({ myDepartmentIds: [2], change: change({
      assessments: [assessment(), assessment({ id: 2, department_id: 4 }),
        assessment({ id: 3, department_id: 6 }), assessment({ id: 4, department_id: 8 })],
      costing_pending_department_ids: [2, 6],
    }) })
    expect(screen.getByTestId('costing-others').textContent)
      .toBe(t('costing.others').replace('{n}', '1').replace('{s}', ''))
  })

  it('says nothing about others once nobody else is costing', () => {
    buckets({ myDepartmentIds: [2], change: change({ costing_pending_department_ids: [2] }) })
    expect(screen.queryByTestId('costing-others')).toBeNull()
  })

  it('opens the member’s bucket onto their cost positions', async () => {
    buckets({ myDepartmentIds: [2] })
    fireEvent.click(screen.getByTestId('costing-toggle-2'))
    expect(await screen.findByTestId('costpos-section-2')).toBeTruthy()
    // Their own department during costing: the add form is there.
    expect(await screen.findByTestId('costpos-new-2')).toBeTruthy()
  })

  it('lets PM see the figures and which buckets are still empty', async () => {
    buckets({ canSeeAll: true })
    await waitFor(() => expect(screen.getByTestId('costing-total-2').textContent).toBe('1,000.00'))
    expect(screen.getByTestId('costing-state-2').textContent).toBe(t('costing.filled'))
    expect(screen.getByTestId('costing-state-4').textContent).toBe(t('costing.empty'))
    expect(screen.getByTestId('costing-lead-2').textContent).toContain('15')
    fireEvent.click(screen.getByTestId('costing-toggle-4'))
    expect(screen.getByTestId('costing-readonly-4')).toBeTruthy()
    // Sales and the lead read another department's positions, never write them.
    expect(await screen.findByTestId('costpos-readonly-4')).toBeTruthy()
    expect(screen.queryByTestId('costpos-new-4')).toBeNull()
  })

  it('gives a department routed on two stages one bucket, not two', () => {
    buckets({ canSeeAll: true, change: change({ assessments: [
      { id: 1, department_id: 2, stage_order: 1, rasic_letter: 'R', status: 'active', verdict: 'feasible' },
      { id: 9, department_id: 2, stage_order: 2, rasic_letter: 'R', status: 'pending', verdict: 'pending' },
    ] }) })
    expect(screen.getAllByTestId('costing-bucket-2')).toHaveLength(1)
  })

  it('says so plainly when nobody is costing yet', () => {
    buckets({ change: change({ assessments: [] }) })
    expect(screen.getByText(t('costing.none'))).toBeTruthy()
  })

  it('names the departments that have not costed yet (costing-side signal for the step button)', async () => {
    buckets({ canSeeAll: true })
    const note = await screen.findByTestId('costing-readiness')
    expect(note.textContent).toContain('1 of 2 departments has not costed yet: Tool Engineer')
  })

  it('says loudly when nothing is costed at all', async () => {
    vi.mocked(changesApi.getSummation).mockResolvedValue({
      ...summation, currency: 'USD',
      by_department: summation.by_department.map((d) => ({ ...d, one_time_internal: 0, one_time_external: 0 })),
      totals: { ...summation.totals, one_time_internal: 0, one_time_external: 0, grand_total: 0 },
    } as never)
    buckets({ canSeeAll: true })
    const note = await screen.findByTestId('costing-readiness')
    expect(note.textContent).toContain('Nothing is costed yet: the total is 0.00 USD')
  })

  it('counts money booked only in another currency as costed', async () => {
    vi.mocked(changesApi.getSummation).mockResolvedValue({
      ...summation, currency: 'EUR',
      by_department: summation.by_department.map((d) => ({ ...d, one_time_internal: 0, one_time_external: 0 })),
      totals: { ...summation.totals, one_time_internal: 0, one_time_external: 0, grand_total: 0 },
      totals_by_currency: { USD: { one_time_internal: 0, one_time_external: 700,
        lifecycle_internal: 0, lifecycle_external: 0, grand_total: 700 } },
      mixed_currency: true,
      by_department_plant: [{ department_id: 2, plant_id: 1, currency: 'USD', one_time_internal: 0,
        one_time_external: 500, lifecycle_internal: 0, lifecycle_external: 0 }],
      positions_by_department: [{ department_id: 4, position_cost: 0, hours: 0, hours_cost: 0, machine_hours: 0,
        trials: 0, position_count: 1, unrated_hours: false, unpriced_count: 0,
        positions: [{ position_id: 1, label: 'Tool', kind: 'external', cost: 200, currency: 'USD',
          line_value: null, rate: null }] }],
    } as never)
    buckets({ canSeeAll: true })
    await waitFor(() => expect(screen.getByTestId('costing-state-2').textContent).toBe(t('costing.filled')))
    expect(screen.getByTestId('costing-state-4').textContent).toBe(t('costing.filled'))
    expect(screen.queryByTestId('costing-readiness')).toBeNull()
  })

  it('stays quiet once every department has costed, and outside costing', async () => {
    vi.mocked(changesApi.getSummation).mockResolvedValue({
      ...summation,
      by_department: summation.by_department.map((d) => ({ ...d, one_time_internal: 50 })),
    } as never)
    buckets({ canSeeAll: true })
    await waitFor(() => expect(changesApi.getSummation).toHaveBeenCalled())
    await new Promise((r) => setTimeout(r, 10))
    expect(screen.queryByTestId('costing-readiness')).toBeNull()
  })
})
