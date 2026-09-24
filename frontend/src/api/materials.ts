/**
 * Material on the article: MaterialDB search (proxied by the PLM backend, the
 * service token never reaches the browser), link, new material, refresh.
 * Mirrors backend/app/api/v1/items/materials.py.
 */
import client from './client';

export type MaterialSource = 'materialdb' | 'new';

export interface MaterialHit {
  id: number;
  ktx_number: string | null;
  trade_name: string;
  grade: string | null;
  manufacturer: string | null;
  family: string | null;
  classification: string | null;
  label: string;
}

export interface PartMaterial {
  material_source: MaterialSource | null;
  materialdb_id: number | null;
  material_ktx_number: string | null;
  material_label: string | null;
  material_new_text: string | null;
  material_synced_at: string | null;
}

export type MaterialInput =
  | { source: 'materialdb'; materialdb_id: number }
  | { source: 'new'; new_text: string }
  | { source: null };

export const MATERIALDB_UI_BASE = '/materialdb/materials';

export function materialDbUrl(id: number): string {
  return `${MATERIALDB_UI_BASE}/${id}`;
}

export const searchMaterials = async (q: string): Promise<MaterialHit[]> =>
  (await client.get('/v1/materials/search', { params: { q } })).data;

export const setPartMaterial = async (partId: number, input: MaterialInput): Promise<PartMaterial> =>
  (await client.put(`/v1/parts/${partId}/material`, input)).data;

export const refreshPartMaterial = async (partId: number): Promise<PartMaterial> =>
  (await client.post(`/v1/parts/${partId}/material/refresh`)).data;
