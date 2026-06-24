import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, cleanup, waitFor, act } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { internalCost } from './CostLineGrid';
import CostLineGrid from './CostLineGrid';

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

const RATES = [{ department_id: 1, plant_id: 10, hourly_rate: 100, min_factor: 0.5 }];
const ACTIVITIES = [{ id: 1, department_id: 1, label: 'Design', sort_order: 1 }];

/** Creates a wrapper that pre-seeds the query cache so rates are available synchronously */
function makeWrapper() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  // Pre-populate the cache so the component sees rates immediately (no async fetch needed)
  qc.setQueryData(['cm-rates'], RATES);
  qc.setQueryData(['cm-activities', 1], ACTIVITIES);
  qc.setQueryData(['cost-lines', 1, 2], []);
  return function wrapper({ children }: { children: React.ReactNode }) {
    return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
  };
}

// Simple wrapper without pre-seeded cache (for render-only tests)
function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

const PLANTS = [{ id: 10, name: 'Plant A' }, { id: 20, name: 'Plant B' }];
// RATES only covers plant 10 (not plant 20) for department 1
// This mirrors the real scenario: Weissenburg rated, some other plant not rated

describe('CostLineGrid component', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  afterEach(() => {
    cleanup();
  });

  it('renders Save button and Add row button', () => {
    render(
      <CostLineGrid changeId={1} assessmentId={2} departmentId={1} plants={PLANTS} />,
      { wrapper }
    );
    expect(screen.getByRole('button', { name: /save/i })).toBeDefined();
    expect(screen.getByRole('button', { name: /\+\s*row/i })).toBeDefined();
  });

  it('adds a row when "+ row" is clicked', () => {
    render(
      <CostLineGrid changeId={1} assessmentId={2} departmentId={1} plants={PLANTS} />,
      { wrapper }
    );
    const addBtn = screen.getByRole('button', { name: /\+\s*row/i });
    fireEvent.click(addBtn);
    // A hours input should now be present
    const hoursInputs = screen.getAllByRole('spinbutton');
    expect(hoursInputs.length).toBeGreaterThanOrEqual(1);
  });

  it('auto-computes internal cost when hours are entered', async () => {
    // Pre-seed the cache so rates are available before the component mounts
    render(
      <CostLineGrid changeId={1} assessmentId={2} departmentId={1} plants={PLANTS} />,
      { wrapper: makeWrapper() }
    );

    // Add a row — rates are synchronously available from cache
    fireEvent.click(screen.getByRole('button', { name: /\+\s*row/i }));

    // Change hours — internal cost = 5 × 100 = 500
    const spinbuttons = screen.getAllByRole('spinbutton');
    fireEvent.change(spinbuttons[0], { target: { value: '5' } });

    // 500.00 may appear in both the row cell and the per-plant footer
    expect(screen.getAllByText('500.00').length).toBeGreaterThanOrEqual(1);
  });

  it('total updates when hours change', async () => {
    render(
      <CostLineGrid changeId={1} assessmentId={2} departmentId={1} plants={PLANTS} />,
      { wrapper: makeWrapper() }
    );

    fireEvent.click(screen.getByRole('button', { name: /\+\s*row/i }));

    const spinbuttons = screen.getAllByRole('spinbutton');
    fireEvent.change(spinbuttons[0], { target: { value: '3' } }); // 3h × 100 = 300

    // Total = 300 (internal) + 0 (external). Grand total span shows "Total: 300.00"
    expect(screen.getAllByText(/300\.00/).length).toBeGreaterThanOrEqual(1);
  });

  it('only offers rated plants in the row dropdown (plant 20 has no rate)', async () => {
    // RATES = [{dept:1, plant:10}] — plant 20 has no rate for dept 1
    // So only Plant A (id=10) should appear in the select, not Plant B (id=20)
    render(
      <CostLineGrid changeId={1} assessmentId={2} departmentId={1} plants={PLANTS} />,
      { wrapper: makeWrapper() }
    );
    fireEvent.click(screen.getByRole('button', { name: /\+\s*row/i }));
    const selects = screen.getAllByRole('combobox');
    // The plant select is the second combobox (after activity datalist)
    // Find the one containing plant options
    const plantSelect = selects.find((s) =>
      Array.from(s.querySelectorAll('option')).some((o) => o.textContent === 'Plant A')
    );
    expect(plantSelect).toBeDefined();
    const options = Array.from(plantSelect!.querySelectorAll('option')).map((o) => o.textContent);
    expect(options).toContain('Plant A');
    expect(options).not.toContain('Plant B');
  });

  it('shows no-rate message and no table when no rates exist for the department', async () => {
    // Use a wrapper with rates for a DIFFERENT department (dept 99), not dept 1
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    qc.setQueryData(['cm-rates'], [{ department_id: 99, plant_id: 10, hourly_rate: 100, min_factor: 0.5 }]);
    qc.setQueryData(['cm-activities', 1], ACTIVITIES);
    qc.setQueryData(['cost-lines', 1, 2], []);
    const noRateWrapper = ({ children }: { children: React.ReactNode }) => (
      <QueryClientProvider client={qc}>{children}</QueryClientProvider>
    );

    render(
      <CostLineGrid changeId={1} assessmentId={2} departmentId={1} plants={PLANTS} />,
      { wrapper: noRateWrapper }
    );
    // Should show the no-rate message instead of the grid
    expect(screen.getByText(/no cost rates configured/i)).toBeDefined();
    // Save button should not be present
    expect(screen.queryByRole('button', { name: /save/i })).toBeNull();
  });

  it('calls putCostLines with correct payload on Save', async () => {
    const { changesApi } = await import('../../api/changes');
    render(
      <CostLineGrid changeId={1} assessmentId={2} departmentId={1} plants={PLANTS} />,
      { wrapper: makeWrapper() }
    );

    fireEvent.click(screen.getByRole('button', { name: /\+\s*row/i }));

    const spinbuttons = screen.getAllByRole('spinbutton');
    fireEvent.change(spinbuttons[0], { target: { value: '2' } });

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /save/i }));
    });

    await waitFor(() => {
      expect(changesApi.putCostLines).toHaveBeenCalledWith(
        1,
        2,
        expect.arrayContaining([
          expect.objectContaining({ demand_hours: 2, plant_id: PLANTS[0].id }),
        ])
      );
    });
    // Payload must NOT include _internal (private field)
    const [, , lines] = (changesApi.putCostLines as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(lines[0]).not.toHaveProperty('_internal');
  });
});
