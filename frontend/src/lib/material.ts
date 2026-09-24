/** Material display rules shared by the article page and the worksheet. */
import type { PartMaterial } from '../api/materials';

export const NEW_MATERIAL_BADGE = 'NEW, not in MaterialDB';

export function materialOf(part: Partial<PartMaterial>): PartMaterial {
  return {
    material_source: part.material_source ?? null,
    materialdb_id: part.materialdb_id ?? null,
    material_ktx_number: part.material_ktx_number ?? null,
    material_label: part.material_label ?? null,
    material_new_text: part.material_new_text ?? null,
    material_synced_at: part.material_synced_at ?? null,
  };
}

/** Plain text for filtering, sorting and the export. */
export function materialText(m: PartMaterial): string | null {
  if (m.material_source === 'materialdb') return m.material_label ?? `MaterialDB #${m.materialdb_id}`;
  if (m.material_source === 'new') return `${m.material_new_text ?? ''} (${NEW_MATERIAL_BADGE})`;
  return null;
}
