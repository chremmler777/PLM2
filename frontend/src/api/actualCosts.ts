import client from './client';
import type { ActualCost, ActualCostIn, ActualCostList } from '../types/pnl';

/** Actual costs of a change that are not booked hours (supplier invoices,
 *  scrap, other): /api/v1/changes/{id}/actual-costs. */
export const actualCostsApi = {
  list: (changeId: number): Promise<ActualCostList> =>
    client.get(`/v1/changes/${changeId}/actual-costs`).then((r) => r.data),

  add: (changeId: number, body: ActualCostIn): Promise<ActualCost> =>
    client.post(`/v1/changes/${changeId}/actual-costs`, body).then((r) => r.data),

  remove: (changeId: number, costId: number): Promise<void> =>
    client.delete(`/v1/changes/${changeId}/actual-costs/${costId}`).then(() => undefined),
};
