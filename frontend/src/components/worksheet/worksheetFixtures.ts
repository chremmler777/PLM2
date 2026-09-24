/** Worksheet test data: one 1994 style article row made by tool 199401. Imported only by tests. */
import type { WorksheetRow } from '../../api/worksheet';
import { materialOf } from '../../lib/material';

const tool = {
  part_id: 90, part_number: '199401', name: 'TOOL Handle', cavities: 2, toolmaker_id: 3,
  toolmaker_name: 'Formenbau Nord', cycle_time_s: 55, tonnage_class: null,
};

export const row = (over: Partial<WorksheetRow> = {}): WorksheetRow => ({
  part_id: 1, row_kind: 'article', part_number: '20-1994-001-0', customer_part_number: '206.882.251',
  tier1_part_number: 'S00H4X-110', name: 'Handle LH', part_type: 'internal_mfg', item_category: 'article',
  thumbnail_url: null, lifecycle_phase: 'rfq', colour_code: null, grain: 'KF8', mirror_of: null,
  revision: { revision_name: 'E1', customer_index: '001', phase: 'review' },
  material: { ...materialOf({}), material_source: 'new', material_new_text: 'PA6-GF15' },
  paint: { painted: true, colour: 'VM0 Skyscraper', colour_hex: null, paint_system: 'Base / Clear' },
  tool, other_tools: ['199409'], dfm: { status: 'waiting', waiting_on: ['ktx', 'tier1'], open_topics: 1 }, ...over,
});
