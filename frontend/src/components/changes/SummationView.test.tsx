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
    // And the wrap-up counts what Sales bought: 9000, shipping included.
    expect(screen.getByTestId('summation-positions-total').textContent).toBe('9000.00');
  });

  it('leaves the divergence chip off when Sales followed the recommendation', async () => {
    const { changesApi } = await import('../../api/changes');
    vi.mocked(changesApi.listCostPositions).mockResolvedValue([position([
      { ...OFFER_A, chosen: true, chosen_by_name: 'Sara Sales' }, OFFER_B,
    ])] as never);
    quoting();
    await screen.findByTestId('vendor-chosen-3');
    expect(screen.queryByTestId('vendor-divergence-3')).toBeNull();
    // 5000 + 200 freight, the favourite's own figure.
    expect(screen.getByTestId('summation-positions-total').textContent).toBe('5200.00');
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
