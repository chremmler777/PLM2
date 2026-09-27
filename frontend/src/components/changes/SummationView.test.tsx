/**
 * Sales' vendor decision in the wrap-up.
 *
 * The department's favourite is a recommendation, and it stays named as one.
 * Sales decides — and deciding against the recommendation costs a written
 * reason, recorded before anything is sent. Wish and decision stay side by side.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import SummationView from './SummationView';
import { t } from '../../i18n/cmLabels';

vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

vi.mock('../../api/changes', () => ({
  changesApi: {
    getSummation: vi.fn(),
    listCostPositions: vi.fn(),
    chooseCostingOffer: vi.fn().mockResolvedValue({}),
  },
}));

const TOTALS = {
  by_plant: [], by_department: [],
  totals: {
    one_time_internal: 0, one_time_external: 0,
    lifecycle_internal: 0, lifecycle_external: 0, grand_total: 0,
  },
};

const OFFER_A = {
  id: 91, vendor_name: 'Vendor A', cost: 5000, shipping_cost: 200,
  shipping_included: false, favorite: true, chosen: false,
};
const OFFER_B = {
  id: 92, vendor_name: 'Vendor B', cost: 9000,
  shipping_included: true, favorite: false, chosen: false,
};

const position = (offers: unknown[]) => ({
  id: 3, department_id: 5, label: 'Anlagenumbau', tag: 'equipment_change',
  kind: 'external', pricing: 'quote', effective_cost: null, offers,
});

const wrap = (ui: React.ReactElement) =>
  render(<QueryClientProvider
    client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    {ui}
  </QueryClientProvider>);

const quoting = (props: Record<string, unknown> = {}) =>
  wrap(<SummationView changeId={1} status="quoting" canQuote {...props} />);

describe('SummationView vendor decision', () => {
  beforeEach(async () => {
    vi.clearAllMocks();
    const { changesApi } = await import('../../api/changes');
    vi.mocked(changesApi.getSummation).mockResolvedValue(TOTALS as never);
    vi.mocked(changesApi.listCostPositions)
      .mockResolvedValue([position([OFFER_A, OFFER_B])] as never);
    vi.mocked(changesApi.chooseCostingOffer).mockResolvedValue({} as never);
  });
  afterEach(cleanup);

  it('names the department’s recommendation as a recommendation', async () => {
    quoting();
    const rec = await screen.findByTestId('vendor-recommended-3');
    expect(rec.textContent).toContain(t('vendor.recommended'));
    expect(rec.textContent).toContain('Vendor A');
  });

  it('records the favourite without asking for a reason', async () => {
    const { changesApi } = await import('../../api/changes');
    quoting();
    fireEvent.click(await screen.findByTestId('vendor-choose-91'));
    await waitFor(() => expect(changesApi.chooseCostingOffer)
      .toHaveBeenCalledWith(1, 91, undefined));
    expect(screen.queryByTestId('vendor-reason-3')).toBeNull();
  });

  it('holds the request until a reason for going against the recommendation exists', async () => {
    const { changesApi } = await import('../../api/changes');
    quoting();
    fireEvent.click(await screen.findByTestId('vendor-choose-92'));
    // Nothing is sent on the click alone — the reason comes first.
    expect(changesApi.chooseCostingOffer).not.toHaveBeenCalled();
    const box = await screen.findByTestId('vendor-reason-3');
    expect(box.textContent).toContain(t('vendor.reasonLabel'));
    const confirm = screen.getByTestId('vendor-reason-confirm-3') as HTMLButtonElement;
    expect(confirm.disabled).toBe(true);
    fireEvent.change(screen.getByTestId('vendor-reason-input-3'),
      { target: { value: 'Liefertermin' } });
    fireEvent.click(screen.getByTestId('vendor-reason-confirm-3'));
    await waitFor(() => expect(changesApi.chooseCostingOffer)
      .toHaveBeenCalledWith(1, 92, 'Liefertermin'));
  });

  it('drops the pending pick when the reason is abandoned', async () => {
    const { changesApi } = await import('../../api/changes');
    quoting();
    fireEvent.click(await screen.findByTestId('vendor-choose-92'));
    fireEvent.click(screen.getByTestId('vendor-reason-cancel-3'));
    expect(screen.queryByTestId('vendor-reason-3')).toBeNull();
    expect(changesApi.chooseCostingOffer).not.toHaveBeenCalled();
  });

  it('marks a decision that went against the recommendation, with who and why', async () => {
    const { changesApi } = await import('../../api/changes');
    vi.mocked(changesApi.listCostPositions).mockResolvedValue([position([
      OFFER_A,
      { ...OFFER_B, chosen: true, chosen_reason: 'Liefertermin',
        chosen_by_name: 'Sara Sales', chosen_at: '2026-08-01T10:00:00Z' },
    ])] as never);
    quoting();
    const chosen = await screen.findByTestId('vendor-chosen-3');
    expect(chosen.textContent).toContain('Vendor B');
    expect(chosen.textContent).toContain('Sara Sales');
    expect(screen.getByTestId('vendor-divergence-3').textContent)
      .toContain(t('vendor.againstRecommendation'));
    expect(screen.getByTestId('vendor-chosen-reason-3').textContent).toBe('Liefertermin');
    // The recommendation does not disappear once it has been overruled.
    expect(screen.getByTestId('vendor-recommended-3').textContent).toContain('Vendor A');
  });

  it('leaves the divergence chip off when Sales followed the recommendation', async () => {
    const { changesApi } = await import('../../api/changes');
    vi.mocked(changesApi.listCostPositions).mockResolvedValue([position([
      { ...OFFER_A, chosen: true, chosen_by_name: 'Sara Sales' }, OFFER_B,
    ])] as never);
    quoting();
    await screen.findByTestId('vendor-chosen-3');
    expect(screen.queryByTestId('vendor-divergence-3')).toBeNull();
  });

  it('keeps the decision away from readers who do not answer for the price', async () => {
    wrap(<SummationView changeId={1} status="quoting" canQuote={false} />);
    await screen.findByTestId('summation-position-3');
    expect(screen.queryByTestId('vendor-decision-3')).toBeNull();
  });

  it('keeps the decision out of the stages before quoting', async () => {
    quoting({ status: 'costing' });
    await screen.findByTestId('summation-position-3');
    expect(screen.queryByTestId('vendor-decision-3')).toBeNull();
  });

  it('offers no decision on a position with no offers to decide between', async () => {
    const { changesApi } = await import('../../api/changes');
    vi.mocked(changesApi.listCostPositions).mockResolvedValue([
      { ...position([]), kind: 'support_effort', pricing: null,
        effective_cost: 800, hours: 8 },
    ] as never);
    quoting();
    await screen.findByTestId('summation-position-3');
    expect(screen.queryByTestId('vendor-decision-3')).toBeNull();
  });
});

/**
 * CR-3's shape: the backend's totals already hold the positions (the
 * internal hours of the own-time lines and the external tool money), so the
 * wrap-up splits the total, it never adds the positions on top of it.
 */
describe('SummationView totals come from the backend, counted once', () => {
  const CR3 = {
    currency: 'USD',
    by_plant: [],
    by_department: [
      { department_id: 5, one_time_internal: 279.5, one_time_external: 850,
        lifecycle_internal: 0, lifecycle_external: 0 },
      { department_id: 6, one_time_internal: 0, one_time_external: 12500,
        lifecycle_internal: 0, lifecycle_external: 0 },
    ],
    totals: { one_time_internal: 279.5, one_time_external: 13350,
      lifecycle_internal: 0, lifecycle_external: 0, grand_total: 13629.5 },
    effort_by_department: [], total_effort_hours: 0,
    positions_by_department: [
      { department_id: 5, position_cost: 850, hours: 13, hours_cost: 279.5, machine_hours: 0,
        trials: 0, position_count: 2, unrated_hours: false, unpriced_count: 0,
        positions: [
          { position_id: 11, label: 'Implementation support', kind: 'support_effort',
            cost: 0, currency: 'USD', line_value: 172, rate: 21.5 },
          { position_id: 12, label: 'cvxc', kind: 'external', cost: 850, currency: 'USD',
            line_value: 107.5, rate: 21.5 },
        ] },
      { department_id: 6, position_cost: 12500, hours: 0, hours_cost: 0, machine_hours: 0,
        trials: 0, position_count: 1, unrated_hours: false, unpriced_count: 0,
        positions: [
          { position_id: 13, label: 'Tool modification insert LH', kind: 'external',
            cost: 12500, currency: 'USD', line_value: 0, rate: null },
        ] },
    ],
    total_position_cost: 13350,
    total_position_hours_cost: 279.5,
  };
  const POSITIONS = [
    { id: 11, department_id: 5, label: 'Implementation support', kind: 'support_effort',
      pricing: null, hours: 8, effective_cost: 999, line_value: 172, rate_currency: 'USD', offers: [] },
    { id: 12, department_id: 5, label: 'cvxc', kind: 'external', pricing: 'estimate',
      hours: 5, est_cost: 850, effective_cost: 850, line_value: 107.5, rate_currency: 'USD', offers: [] },
    { id: 13, department_id: 6, label: 'Tool modification insert LH', kind: 'external',
      pricing: 'estimate', est_cost: 12500, effective_cost: 12500, offers: [] },
  ];

  beforeEach(async () => {
    vi.clearAllMocks();
    const { changesApi } = await import('../../api/changes');
    vi.mocked(changesApi.getSummation).mockResolvedValue(CR3 as never);
    vi.mocked(changesApi.listCostPositions).mockResolvedValue(POSITIONS as never);
  });
  afterEach(cleanup);

  it('shows 13,629.50 USD including the positions, and the positions as a part of it', async () => {
    wrap(<SummationView changeId={3} status="closed" />);
    expect((await screen.findByTestId('summation-grand-with-positions')).textContent)
      .toBe('13,629.50 USD');
    // the cost lines alone: nothing beyond the positions
    expect(screen.getByTestId('summation-total').textContent).toBe('0.00 USD');
    expect(screen.getByTestId('summation-positions-total').textContent).toBe('13,629.50 USD');
  });

  it('keeps the department total the backend row total; positions are a part of it', async () => {
    wrap(<SummationView changeId={3} status="closed" />);
    expect((await screen.findByTestId('summation-dept-total-5')).textContent).toBe('1,129.50 USD');
    expect(screen.getByTestId('summation-dept-positions-5').textContent).toBe('1,129.50 USD');
    expect(screen.getByTestId('summation-dept-total-6').textContent).toBe('12,500.00 USD');
    expect(screen.getByTestId('summation-positions-dept-total-6').textContent).toBe('12,500.00 USD');
  });

  it('shows each position at its backend amount: money plus priced hours', async () => {
    wrap(<SummationView changeId={3} status="closed" />);
    // an effort line shows its value, not the frontend's effective cost
    expect((await screen.findByTestId('summation-position-amount-11')).textContent)
      .toBe('172.00 USD');
    expect(screen.getByTestId('summation-position-amount-12').textContent).toBe('957.50 USD');
  });
});
