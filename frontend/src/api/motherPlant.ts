/**
 * Mother-plant changes (spec 2026-09-25 §14): the Mother plant tab's API.
 * Every write answers the tab state again.
 */
import client from './client';

export interface InfoReceipt {
  id: number;
  department_id: number;
  department_name: string | null;
  sent_by: number;
  sent_by_name: string | null;
  sent_at: string;
  acknowledged_by: number | null;
  acknowledged_by_name: string | null;
  acknowledged_at: string | null;
  note: string | null;
}

export interface MotherPlantState {
  change_id: number;
  mother_plant_name: string | null;
  mother_plant_ref: string | null;
  mother_plant_sop: string | null;
  mother_plants: string[];
  default_department_ids: number[];
  receipts: InfoReceipt[];
  open_count: number;
  timing_attachment: { id: number; filename: string; created_at: string } | null;
  documents: { id: number; filename: string; created_at: string; uploaded_by_name: string | null }[];
  /** The "Inform mother plant" stamp (validated timing told to them). */
  informed_at: string | null;
  informed_by_name: string | null;
  can_send: boolean;
  can_inform: boolean;
  my_open_receipt_ids: number[];
}

export const motherPlantKey = (changeId: number) => ['change', changeId, 'mother-plant'] as const;

export const motherPlantApi = {
  get: (changeId: number) =>
    client.get<MotherPlantState>(`/v1/changes/${changeId}/mother-plant`).then((r) => r.data),
  sendInfo: (changeId: number, body: { department_ids: number[]; message?: string }) =>
    client.post<MotherPlantState>(`/v1/changes/${changeId}/mother-plant/info`, body).then((r) => r.data),
  acknowledge: (changeId: number, receiptId: number, note?: string) =>
    client.post<MotherPlantState>(
      `/v1/changes/${changeId}/mother-plant/info/${receiptId}/ack`, { note: note || null },
    ).then((r) => r.data),
  inform: (changeId: number) =>
    client.post<MotherPlantState>(`/v1/changes/${changeId}/mother-plant/inform`).then((r) => r.data),
};

/** The configured plants when the permissions call is not there yet. */
export const FALLBACK_MOTHER_PLANTS = ['KTX Weissenburg (WUG)', 'KTX Solingen'];

export const isMotherPlant = (c?: { origin?: string | null } | null): boolean =>
  c?.origin === 'mother_plant';
