/**
 * Project worksheet rows and the xlsx export. Mirrors
 * backend/app/api/v1/items/worksheet.py.
 */
import client from './client';
import type { DfmParty } from './dfm';
import type { FieldFlag } from './fieldNotes';
import type { PartMaterial } from './materials';

export interface WorksheetTool {
  part_id: number;
  part_number: string;
  name: string;
  cavities: number | null;
  toolmaker_id: number | null;
  toolmaker_name: string | null;
  cycle_time_s: number | null;
  tonnage_class: number | null;
}

export type DfmSheetStatus = 'no_topic' | 'waiting' | 'all_answered' | 'open' | 'finished';

export interface WorksheetDfm {
  status: DfmSheetStatus;
  waiting_on: DfmParty[];
  open_topics: number;
}

export interface WorksheetPaint {
  painted: boolean;
  colour: string | null;
  colour_hex: string | null;
  paint_system: string | null;
}

export type WorksheetRowKind = 'article' | 'purchased' | 'tool_only';

export interface WorksheetRow {
  part_id: number;
  row_kind: WorksheetRowKind;
  part_number: string;
  customer_part_number: string | null;
  tier1_part_number: string | null;
  name: string;
  part_type: string;
  item_category: string;
  thumbnail_url: string | null;
  lifecycle_phase: string;
  /** MIC colour of an unpainted article, e.g. NM0 (a painted article's colour is in paint). */
  colour_code: string | null;
  /** e.g. KF8 */
  grain: string | null;
  mirror_of: { part_id: number; part_number: string; customer_part_number: string | null } | null;
  revision: { revision_name: string; customer_index: string | null; phase: string } | null;
  material: PartMaterial;
  paint: WorksheetPaint;
  tool: WorksheetTool | null;
  other_tools: string[];
  dfm: WorksheetDfm | null;
}

export interface Worksheet {
  project_id: number;
  rows: WorksheetRow[];
}

export interface WorksheetExportColumn {
  key: string;
  label: string;
  type: 'text' | 'number' | 'date';
}

export interface WorksheetExportCell {
  value: string | number | null;
  flag: FieldFlag | null;
  comments: number;
}

export interface WorksheetExportPayload {
  columns: WorksheetExportColumn[];
  rows: { cells: WorksheetExportCell[] }[];
  frozen_columns: number;
}

export const getWorksheet = async (projectId: number): Promise<Worksheet> =>
  (await client.get(`/v1/projects/${projectId}/worksheet`)).data;

function filenameFrom(disposition: string | undefined, fallback: string): string {
  const m = /filename="?([^";]+)"?/i.exec(disposition ?? '');
  return m ? m[1] : fallback;
}

/** With responseType blob an error body is a Blob too: read it back as JSON so apiErrorMessage finds the detail. */
async function withJsonErrorBody(e: unknown): Promise<unknown> {
  const response = (e as { response?: { data?: unknown } })?.response;
  if (!(response?.data instanceof Blob)) return e;
  try {
    response.data = JSON.parse(await response.data.text());
  } catch {
    // not JSON: keep the Blob, the caller shows its fallback text
  }
  return e;
}

const REVOKE_DELAY_MS = 10_000;

export async function downloadWorksheetXlsx(projectId: number, payload: WorksheetExportPayload): Promise<void> {
  let res;
  try {
    res = await client.post(`/v1/projects/${projectId}/worksheet/export`, payload, { responseType: 'blob' });
  } catch (e) {
    throw await withJsonErrorBody(e);
  }
  const url = URL.createObjectURL(res.data as Blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filenameFrom(res.headers?.['content-disposition'] as string | undefined, `worksheet-${projectId}.xlsx`);
  a.click();
  // Revoking right after click() can cancel the download in some browsers.
  setTimeout(() => URL.revokeObjectURL(url), REVOKE_DELAY_MS);
}
