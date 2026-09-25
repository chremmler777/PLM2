import client, { API_BASE_URL } from './client';
import type {
  CostSheetDiff, CostSheetOverview, CostSheetRow, CostSheetSection, CostSheetVersionDetail,
  MachineClass, PlantCurrency,
} from '../types/costSheet';

const base = '/v1/cost-sheet';

export const costSheetApi = {
  overview: (): Promise<CostSheetOverview> => client.get(base).then((r) => r.data),

  /** My Tasks "Review the cost sheet": due for Finance when the sheet is stale. */
  reviewTask: (): Promise<{
    due: boolean; is_finance: boolean
    stale: { stale: boolean; review_months: number; latest_version: number | null;
      reviewed_on: string | null; due_on: string | null; reason: string | null } | null
  }> => client.get(`${base}/review-task`).then((r) => r.data),

  version: (id: number): Promise<CostSheetVersionDetail> =>
    client.get(`${base}/versions/${id}`).then((r) => r.data),

  diff: (id: number, against?: number): Promise<CostSheetDiff> =>
    client.get(`${base}/versions/${id}/diff`, { params: against ? { against } : {} })
      .then((r) => r.data),

  createDraft: (basedOn?: number): Promise<CostSheetVersionDetail> =>
    client.post(`${base}/drafts`, { based_on_version_id: basedOn ?? null }).then((r) => r.data),

  updateDraft: (id: number, body: { valid_from?: string | null; note?: string | null }):
    Promise<CostSheetVersionDetail> =>
    client.patch(`${base}/versions/${id}`, body).then((r) => r.data),

  deleteDraft: (id: number): Promise<void> =>
    client.delete(`${base}/versions/${id}`).then(() => undefined),

  publish: (id: number, body: { valid_from: string; note?: string | null; confirm_backdated?: boolean }):
    Promise<CostSheetVersionDetail> =>
    client.post(`${base}/versions/${id}/publish`, body).then((r) => r.data),

  addRow: (id: number, section: CostSheetSection, row: CostSheetRow):
    Promise<CostSheetVersionDetail> =>
    client.post(`${base}/versions/${id}/${section}`, row).then((r) => r.data),

  updateRow: (id: number, section: CostSheetSection, rowId: number, changes: CostSheetRow):
    Promise<CostSheetVersionDetail> =>
    client.patch(`${base}/versions/${id}/${section}/${rowId}`, changes).then((r) => r.data),

  deleteRow: (id: number, section: CostSheetSection, rowId: number):
    Promise<CostSheetVersionDetail> =>
    client.delete(`${base}/versions/${id}/${section}/${rowId}`).then((r) => r.data),

  addMachineClass: (body: Partial<MachineClass>): Promise<MachineClass> =>
    client.post(`${base}/machine-classes`, body).then((r) => r.data),

  updateMachineClass: (id: number, body: Partial<MachineClass>): Promise<MachineClass> =>
    client.patch(`${base}/machine-classes/${id}`, body).then((r) => r.data),

  setPlantCurrency: (plantId: number, currency: string): Promise<PlantCurrency[]> =>
    client.put(`${base}/plants/${plantId}/currency`, { currency }).then((r) => r.data),

  setReviewMonths: (months: number): Promise<{ review_months: number }> =>
    client.put(`${base}/settings`, { review_months: months }).then((r) => r.data),

  /** A plain link: the download rides the SSO cookie like any other GET. */
  exportUrl: (id: number, format: 'csv' | 'xlsx', section = 'Positions'): string =>
    `${API_BASE_URL}${base}/versions/${id}/export?format=${format}&section=${section}`,
};
