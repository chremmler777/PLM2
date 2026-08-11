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
    vi.mocked(changesApi.getSummation).mockResolvedValue(summation as never)
    vi.mocked(changesApi.setCostLeadTime).mockClear()
  })
  afterEach(cleanup)

  it('gives every participating department a bucket', () => {
    buckets()
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

  it('shows a department member nothing of another department’s figures', async () => {
    buckets({ myDepartmentIds: [2] })
    // No summation is even requested without the privilege.
    expect(changesApi.getSummation).not.toHaveBeenCalled()
    expect(screen.getByTestId('costing-state-4').textContent).toBe(t('costing.hidden'))
    expect(screen.queryByTestId('costing-total-4')).toBeNull()
    fireEvent.click(screen.getByTestId('costing-toggle-4'))
    expect(screen.getByTestId('costing-hidden-4').textContent).toBe(t('costing.hiddenHint'))
    expect(screen.queryByTestId('costing-readonly-4')).toBeNull()
  })

  it('lets PM see the figures and which buckets are still empty', async () => {
    buckets({ canSeeAll: true })
    await waitFor(() => expect(screen.getByTestId('costing-total-2').textContent).toBe('1000.00'))
    expect(screen.getByTestId('costing-state-2').textContent).toBe(t('costing.filled'))
    expect(screen.getByTestId('costing-state-4').textContent).toBe(t('costing.empty'))
    expect(screen.getByTestId('costing-lead-2').textContent).toContain('15')
    fireEvent.click(screen.getByTestId('costing-toggle-4'))
    expect(screen.getByTestId('costing-readonly-4')).toBeTruthy()
  })

  it('says so plainly when nobody is costing yet', () => {
    buckets({ change: change({ assessments: [] }) })
    expect(screen.getByText(t('costing.none'))).toBeTruthy()
  })
})
