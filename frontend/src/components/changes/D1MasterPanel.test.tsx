import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, cleanup, waitFor, act } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import D1MasterPanel from './D1MasterPanel';
import SummationView from './SummationView';

const GATES = [
  { gate_key: 'feasibility', decision: 'yes', decided_by: null, decided_at: null, remark: null },
  { gate_key: 'budget', decision: 'no', decided_by: null, decided_at: null, remark: null },
  { gate_key: 'release', decision: 'na', decided_by: null, decided_at: null, remark: null },
];

const SUMMATION = {
  by_plant: [],
  by_department: [],
  totals: {
    one_time_internal: 100,
    one_time_external: 50,
    lifecycle_internal: 200,
    lifecycle_external: 75,
    grand_total: 425,
  },
};

vi.mock('../../api/changes', () => ({
  changesApi: {
    getGates: vi.fn().mockResolvedValue([
      { gate_key: 'feasibility', decision: 'yes', decided_by: null, decided_at: null, remark: null },
      { gate_key: 'budget', decision: 'no', decided_by: null, decided_at: null, remark: null },
      { gate_key: 'release', decision: 'na', decided_by: null, decided_at: null, remark: null },
    ]),
    putGate: vi.fn().mockResolvedValue({ gate_key: 'feasibility', decision: 'no' }),
    getSummation: vi.fn().mockResolvedValue({
      by_plant: [],
      by_department: [],
      totals: {
        one_time_internal: 100,
        one_time_external: 50,
        lifecycle_internal: 200,
        lifecycle_external: 75,
        grand_total: 425,
      },
    }),
  },
}));

function makeWrapper(preloadGates?: boolean, preloadSummation?: boolean) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  if (preloadGates) qc.setQueryData(['change-gates', 1], GATES);
  if (preloadSummation) qc.setQueryData(['change-summation', 1], SUMMATION);
  return function wrapper({ children }: { children: React.ReactNode }) {
    return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
  };
}

describe('D1MasterPanel', () => {
  beforeEach(() => { vi.clearAllMocks(); });
  afterEach(() => { cleanup(); });

  it('renders all three gate labels', () => {
    render(<D1MasterPanel changeId={1} />, { wrapper: makeWrapper(true) });
    expect(screen.getByText(/Feasible\?/i)).toBeDefined();
    expect(screen.getByText(/Budget checked\?/i)).toBeDefined();
    expect(screen.getByText(/Technical release\?/i)).toBeDefined();
  });

  it('renders yes/no/na buttons for each gate', () => {
    render(<D1MasterPanel changeId={1} />, { wrapper: makeWrapper(true) });
    const yesBtns = screen.getAllByRole('button', { name: 'yes' });
    expect(yesBtns.length).toBe(3);
  });

  it('calls putGate when a decision button is clicked', async () => {
    const { changesApi } = await import('../../api/changes');
    render(<D1MasterPanel changeId={1} />, { wrapper: makeWrapper(true) });
    const noBtns = screen.getAllByRole('button', { name: 'no' });
    await act(async () => { fireEvent.click(noBtns[0]); });
    await waitFor(() => {
      expect(changesApi.putGate).toHaveBeenCalledWith(1, 'feasibility', { decision: 'no' });
    });
  });
});

describe('SummationView', () => {
  beforeEach(() => { vi.clearAllMocks(); });
  afterEach(() => { cleanup(); });

  it('renders grand total from summation data', () => {
    render(<SummationView changeId={1} />, { wrapper: makeWrapper(false, true) });
    expect(screen.getByText('425.00')).toBeDefined();
  });

  it('renders all four cost breakdown rows', () => {
    render(<SummationView changeId={1} />, { wrapper: makeWrapper(false, true) });
    expect(screen.getByText('100.00')).toBeDefined();
    expect(screen.getByText('50.00')).toBeDefined();
    expect(screen.getByText('200.00')).toBeDefined();
    expect(screen.getByText('75.00')).toBeDefined();
  });
});
