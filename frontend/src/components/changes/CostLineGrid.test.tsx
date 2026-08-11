import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, cleanup, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { internalCost } from './CostLineGrid';
import CostLineGrid from './CostLineGrid';
import { changesApi } from '../../api/changes';

// ── pure calc helper ─────────────────────────────────────────────────────────

describe('internalCost', () => {
  it('multiplies hours by the matching rate', () => {
    const rates = [{ department_id: 1, plant_id: 10, hourly_rate: 65, min_factor: 0.6 }];
    expect(internalCost(rates, 1, 10, 5)).toBe(325);
  });

  it('returns 0 when no rate matches', () => {
    expect(internalCost([], 1, 10, 5)).toBe(0);
  });

  it('returns 0 when department does not match', () => {
    const rates = [{ department_id: 2, plant_id: 10, hourly_rate: 65, min_factor: 0.6 }];
    expect(internalCost(rates, 1, 10, 5)).toBe(0);
  });

  it('returns 0 when plant does not match', () => {
    const rates = [{ department_id: 1, plant_id: 99, hourly_rate: 65, min_factor: 0.6 }];
    expect(internalCost(rates, 1, 10, 5)).toBe(0);
  });
});

// ── component tests ──────────────────────────────────────────────────────────

vi.mock('../../api/changes', () => ({
  changesApi: {
    referenceRates: vi.fn().mockResolvedValue([
      { department_id: 1, plant_id: 10, hourly_rate: 100, min_factor: 0.5 },
    ]),
    referenceActivities: vi.fn().mockResolvedValue([
      { id: 1, department_id: 1, label: 'Design', sort_order: 1 },
    ]),
    getCostLines: vi.fn().mockResolvedValue([]),
    putCostLines: vi.fn().mockResolvedValue([]),
  },
}));

const ACTIVITIES = [{ id: 1, department_id: 1, label: 'Design', sort_order: 1 }];



describe('CostLineGrid matrix', () => {
  beforeEach(() => { vi.clearAllMocks() })
  afterEach(cleanup)

  const TWO_PLANTS = [{ id: 10, name: 'Weissenburg' }, { id: 20, name: 'USA' }]

  /** Rates for both plants, and a line already seeded from the assessment. */
  const seeded = (lines: unknown[] = [], plants = TWO_PLANTS) => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    qc.setQueryData(['cm-rates'], plants.map((p) => (
      { department_id: 1, plant_id: p.id, hourly_rate: 100, min_factor: 0.5 })))
    qc.setQueryData(['cm-activities', 1], ACTIVITIES)
    qc.setQueryData(['cost-lines', 1, 2], lines)
    return ({ children }: { children: React.ReactNode }) => (
      <QueryClientProvider client={qc}>{children}</QueryClientProvider>)
  }

  const line = (over: Record<string, unknown> = {}) => ({
    id: 1, plant_id: 10, activity_id: 1, activity_label: 'Design',
    cost_kind: 'one_time', demand_hours: 0, rate_snapshot: 100,
    internal_cost: 0, external_cost: 0, minutes_per_part: 0, note: null, ...over,
  })

  const grid = (lines: unknown[] = [], plants = TWO_PLANTS) => render(
    <CostLineGrid changeId={1} assessmentId={2} departmentId={1} plants={plants} />,
    { wrapper: seeded(lines, plants) })

  it('puts the affected plants across the top and the activities down the side', () => {
    grid([line({ activity_id: 1, activity_label: 'Design' }),
      line({ id: 2, activity_id: 2, activity_label: 'Tool rework', plant_id: 20 })])
    expect(screen.getByTestId('plant-col-10').textContent).toBe('Weissenburg')
    expect(screen.getByTestId('plant-col-20').textContent).toBe('USA')
    // Rows come pre-seeded from what the assessment ticked.
    expect(screen.getByTestId('cost-row-a1').textContent).toContain('Design')
    expect(screen.getByTestId('cost-row-a2').textContent).toContain('Tool rework')
  })

  it('gives a single-plant change one tight column group', () => {
    grid([line()], [{ id: 10, name: 'Weissenburg' }])
    expect(screen.getByTestId('plant-col-10')).toBeTruthy()
    expect(screen.queryByTestId('plant-col-20')).toBeNull()
    expect(screen.getByTestId('hours-a1-10')).toBeTruthy()
    expect(screen.queryByTestId('hours-a1-20')).toBeNull()
  })

  it('prices hours per plant and sums the column', () => {
    grid([line()])
    fireEvent.change(screen.getByTestId('hours-a1-10'), { target: { value: '5' } })
    expect(screen.getByTestId('internal-a1-10').textContent).toBe('500.00')
    fireEvent.change(screen.getByTestId('external-a1-10'), { target: { value: '250' } })
    expect(screen.getByTestId('plant-sum-10').textContent).toContain('750.00')
    // The other plant stays untouched — a column is its own world.
    expect(screen.getByTestId('plant-sum-20').textContent).toContain('0.00')
    expect(screen.getByTestId('cost-grand-total').textContent).toContain('750.00')
  })

  it('keeps ongoing production time in its own block, one input per plant', () => {
    grid([line()])
    fireEvent.change(screen.getByTestId('minutes-a1-20'), { target: { value: '-1.5' } })
    expect(screen.getByTestId('lifecycle-row-a1')).toBeTruthy()
    expect(screen.getByTestId('plant-sum-20').textContent).toContain('-1.5')
  })

  it('saves the matrix as one line per activity, plant and kind', async () => {
    grid([line()])
    fireEvent.change(screen.getByTestId('hours-a1-10'), { target: { value: '4' } })
    fireEvent.change(screen.getByTestId('external-a1-20'), { target: { value: '99' } })
    fireEvent.change(screen.getByTestId('minutes-a1-10'), { target: { value: '2' } })
    fireEvent.click(screen.getByRole('button', { name: /save/i }))
    await waitFor(() => expect(changesApi.putCostLines).toHaveBeenCalled())
    const [, , lines] = vi.mocked(changesApi.putCostLines).mock.calls[0]
    expect(lines).toEqual([
      expect.objectContaining({ plant_id: 10, cost_kind: 'one_time', demand_hours: 4,
        external_cost: 0, activity_id: 1 }),
      expect.objectContaining({ plant_id: 10, cost_kind: 'lifecycle', minutes_per_part: 2,
        demand_hours: 0 }),
      expect.objectContaining({ plant_id: 20, cost_kind: 'one_time', demand_hours: 0,
        external_cost: 99 }),
    ])
  })

  it('adds an activity the assessment did not seed', async () => {
    grid([])
    expect(screen.getByText(/No activities yet/)).toBeTruthy()
    fireEvent.click(screen.getByTestId('cost-add-row'))
    fireEvent.blur(screen.getByTestId('cost-add-input'), { target: { value: 'Operator training' } })
    expect(screen.getByTestId('cost-row-f:Operator training').textContent)
      .toContain('Operator training')
    fireEvent.change(screen.getByTestId('hours-f:Operator training-10'), { target: { value: '2' } })
    fireEvent.click(screen.getByRole('button', { name: /save/i }))
    await waitFor(() => expect(changesApi.putCostLines).toHaveBeenCalledWith(1, 2, [
      expect.objectContaining({ activity_id: null, activity_label: 'Operator training',
        plant_id: 10, demand_hours: 2 }),
    ]))
  })

  it('says so when the department has no rate for any affected plant', () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    qc.setQueryData(['cm-rates'], [{ department_id: 99, plant_id: 10, hourly_rate: 100, min_factor: 0.5 }])
    qc.setQueryData(['cost-lines', 1, 2], [])
    render(<CostLineGrid changeId={1} assessmentId={2} departmentId={1} plants={TWO_PLANTS} />,
      { wrapper: ({ children }) => <QueryClientProvider client={qc}>{children}</QueryClientProvider> })
    expect(screen.getByText(/no cost rates configured/i)).toBeTruthy()
    expect(screen.queryByRole('button', { name: /save/i })).toBeNull()
  })
})
