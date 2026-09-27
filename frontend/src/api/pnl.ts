import client from './client';
import type { OfferVsActual, PnlRow, PnlSummary, PnlFilters } from '../types/pnl';

export const pnlApi = {
  changes: (filters: PnlFilters = {}): Promise<{ rows: PnlRow[] }> =>
    client.get('/v1/pnl/changes', { params: filters }).then((r) => r.data),

  summary: (filters: PnlFilters = {}): Promise<PnlSummary> =>
    client.get('/v1/pnl/summary', { params: filters }).then((r) => r.data),

  offerVsActual: (changeId: number): Promise<OfferVsActual> =>
    client.get(`/v1/pnl/changes/${changeId}/offer-vs-actual`).then((r) => r.data),
};
