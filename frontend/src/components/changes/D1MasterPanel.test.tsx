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

const CHANGE = {
  id: 1, change_number: 'CHG-001', project_id: 1, title: 'Test', change_type: 'physical_part',
  priority: 'medium', status: 'in_assessment', lead_id: null, raised_by: 1,
  customer_response: 'pending', created_at: '2026-01-01', updated_at: '2026-01-01',
  issuer: 'Alice', car_line: 'VW426', is_series: true, cm_internal: false, cm_external: true,
  implementation_mode: 'integrated', customer_relevant: false,
  affected_plant_ids: [1],
  impacted_items: [{ id: 10, part_id: 99, is_lead: true, impact_note: null }],
  assessments: [], attachments: [],
};

const PLANTS = [
  { id: 1, name: 'Plant A', code: 'PA' },
  { id: 2, name: 'Plant B', code: 'PB' },
];

vi.mock('../../api/changes', () => ({
  changesApi: {
    get: vi.fn(),
    getGates: vi.fn(),
    putGate: vi.fn(),
    update: vi.fn(),
    getSummation: vi.fn(),
  },
}));

vi.mock('../../api/plants', () => ({
  plantsApi: {
    list: vi.fn(),
  },
}));

function makeWrapper(preloadGates?: boolean, preloadSummation?: boolean, preloadChange?: boolean, preloadPlants?: boolean) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  if (preloadGates) qc.setQueryData(['change-gates', 1], GATES);
  if (preloadSummation) qc.setQueryData(['change-summation', 1], SUMMATION);
  if (preloadChange) qc.setQueryData(['change', 1], CHANGE);
  if (preloadPlants) qc.setQueryData(['plants'], PLANTS);
  return function wrapper({ children }: { children: React.ReactNode }) {
    return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
  };
}

describe('D1MasterPanel', () => {
  beforeEach(async () => {
    vi.clearAllMocks();
    const { changesApi } = await import('../../api/changes');
    const { plantsApi } = await import('../../api/plants');
    (changesApi.get as ReturnType<typeof vi.fn>).mockResolvedValue(CHANGE);
    (changesApi.getGates as ReturnType<typeof vi.fn>).mockResolvedValue([
      { gate_key: 'feasibility', decision: 'yes', decided_by: null, decided_at: null, remark: null },
      { gate_key: 'budget', decision: 'no', decided_by: null, decided_at: null, remark: null },
      { gate_key: 'release', decision: 'na', decided_by: null, decided_at: null, remark: null },
    ]);
    (changesApi.putGate as ReturnType<typeof vi.fn>).mockResolvedValue({ gate_key: 'feasibility', decision: 'no' });
    (changesApi.update as ReturnType<typeof vi.fn>).mockResolvedValue(CHANGE);
    (changesApi.getSummation as ReturnType<typeof vi.fn>).mockResolvedValue({
      by_plant: [], by_department: [],
      totals: { one_time_internal: 100, one_time_external: 50, lifecycle_internal: 200, lifecycle_external: 75, grand_total: 425 },
    });
    (plantsApi.list as ReturnType<typeof vi.fn>).mockResolvedValue(PLANTS);
  });
  afterEach(() => { cleanup(); });

  it('renders all three gate labels', () => {
    render(<D1MasterPanel changeId={1} />, { wrapper: makeWrapper(true, false, true) });
    expect(screen.getByText(/Feasible\?/i)).toBeDefined();
    expect(screen.getByText(/Budget checked\?/i)).toBeDefined();
    expect(screen.getByText(/Technical release\?/i)).toBeDefined();
  });

  it('renders yes/no/na buttons for each gate', () => {
    render(<D1MasterPanel changeId={1} />, { wrapper: makeWrapper(true, false, true) });
    const yesBtns = screen.getAllByRole('button', { name: 'yes' });
    expect(yesBtns.length).toBe(3);
  });

  it('calls putGate when a decision button is clicked', async () => {
    const { changesApi } = await import('../../api/changes');
    render(<D1MasterPanel changeId={1} />, { wrapper: makeWrapper(true, false, true) });
    const noBtns = screen.getAllByRole('button', { name: 'no' });
    await act(async () => { fireEvent.click(noBtns[0]); });
    await waitFor(() => {
      expect(changesApi.putGate).toHaveBeenCalledWith(1, 'feasibility', { decision: 'no' });
    });
  });

  it('renders D1 header fields pre-filled', async () => {
    render(<D1MasterPanel changeId={1} />, { wrapper: makeWrapper(true, false, true, true) });
    await waitFor(() => {
      const issuerInput = screen.getByDisplayValue('Alice');
      expect(issuerInput).toBeDefined();
    });
    expect(screen.getByDisplayValue('VW426')).toBeDefined();
  });

  it('calls changesApi.update with edited field', async () => {
    const { changesApi } = await import('../../api/changes');
    render(<D1MasterPanel changeId={1} />, { wrapper: makeWrapper(true, false, true, true) });
    await waitFor(() => screen.getByDisplayValue('Alice'));
    const issuerInput = screen.getByDisplayValue('Alice');
    await act(async () => {
      fireEvent.change(issuerInput, { target: { value: 'Bob' } });
    });
    const saveBtn = screen.getByRole('button', { name: /save/i });
    await act(async () => { fireEvent.click(saveBtn); });
    await waitFor(() => {
      expect(changesApi.update).toHaveBeenCalledWith(1, expect.objectContaining({ issuer: 'Bob' }));
    });
  });

  it('calls changesApi.update with affected_plant_ids on plant toggle', async () => {
    const { changesApi } = await import('../../api/changes');
    render(<D1MasterPanel changeId={1} />, { wrapper: makeWrapper(true, false, true, true) });
    await waitFor(() => screen.getByLabelText(/Plant B/i));
    const plantBCheckbox = screen.getByLabelText(/Plant B/i);
    await act(async () => { fireEvent.click(plantBCheckbox); });
    const saveBtn = screen.getByRole('button', { name: /save/i });
    await act(async () => { fireEvent.click(saveBtn); });
    await waitFor(() => {
      expect(changesApi.update).toHaveBeenCalledWith(1, expect.objectContaining({
        affected_plant_ids: expect.arrayContaining([2]),
      }));
    });
  });

  it('renders decided_at and decided_by for a gate', async () => {
    const gatesWithMeta = [
      { gate_key: 'feasibility', decision: 'yes', decided_by: 42, decided_at: '2026-03-15T10:00:00Z', remark: null },
      { gate_key: 'budget', decision: 'no', decided_by: null, decided_at: null, remark: null },
      { gate_key: 'release', decision: 'na', decided_by: null, decided_at: null, remark: null },
    ];
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    qc.setQueryData(['change-gates', 1], gatesWithMeta);
    qc.setQueryData(['change', 1], CHANGE);
    qc.setQueryData(['plants'], PLANTS);
    const wrapper = ({ children }: { children: React.ReactNode }) => (
      <QueryClientProvider client={qc}>{children}</QueryClientProvider>
    );
    render(<D1MasterPanel changeId={1} />, { wrapper });
    await waitFor(() => {
      expect(screen.getByText(/#42/)).toBeDefined();
    });
  });

  it('renders lead part indicator', async () => {
    render(<D1MasterPanel changeId={1} />, { wrapper: makeWrapper(true, false, true, true) });
    await waitFor(() => {
      expect(screen.getByText('Lead part')).toBeDefined();
    });
  });
});

describe('SummationView', () => {
  beforeEach(async () => {
    vi.clearAllMocks();
    const { changesApi } = await import('../../api/changes');
    (changesApi.getSummation as ReturnType<typeof vi.fn>).mockResolvedValue({
      by_plant: [], by_department: [],
      totals: { one_time_internal: 100, one_time_external: 50, lifecycle_internal: 200, lifecycle_external: 75, grand_total: 425 },
    });
  });
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

  it('renders by_department row', async () => {
    const summationWithDept = {
      by_plant: [],
      by_department: [{ department_id: 5, one_time_internal: 10, one_time_external: 5, lifecycle_internal: 20, lifecycle_external: 8 }],
      totals: { one_time_internal: 10, one_time_external: 5, lifecycle_internal: 20, lifecycle_external: 8, grand_total: 43 },
    };
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    qc.setQueryData(['change-summation', 1], summationWithDept);
    const wrapper = ({ children }: { children: React.ReactNode }) => (
      <QueryClientProvider client={qc}>{children}</QueryClientProvider>
    );
    render(<SummationView changeId={1} />, { wrapper });
    await waitFor(() => {
      // No department list loaded in this test -> name falls back to '#<id>'.
      expect(screen.getByText('#5')).toBeDefined();
    });
  });

  it('renders by_plant row', async () => {
    const summationWithPlant = {
      by_plant: [{ plant_id: 3, one_time_internal: 15, one_time_external: 7, lifecycle_internal: 30, lifecycle_external: 12 }],
      by_department: [],
      totals: { one_time_internal: 15, one_time_external: 7, lifecycle_internal: 30, lifecycle_external: 12, grand_total: 64 },
    };
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    qc.setQueryData(['change-summation', 1], summationWithPlant);
    const wrapper = ({ children }: { children: React.ReactNode }) => (
      <QueryClientProvider client={qc}>{children}</QueryClientProvider>
    );
    render(<SummationView changeId={1} />, { wrapper });
    await waitFor(() => {
      expect(screen.getByText('Plant #3')).toBeDefined();
    });
  });
});
