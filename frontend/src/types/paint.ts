/**
 * Paint catalog and part paint setup types
 */

export type PaintType = 'primer' | 'basecoat' | 'clearcoat' | 'one_coat' | 'other';

export const PAINT_TYPE_LABEL: Record<PaintType, string> = {
  primer: 'Primer',
  basecoat: 'Basecoat',
  clearcoat: 'Clearcoat',
  one_coat: 'One coat',
  other: 'Other',
};

export interface Paint {
  id: number;
  organization_id: number;
  name: string;
  paint_type: PaintType;
  colour_code: string | null;
  colour_name: string | null;
  colour_hex: string | null;
  supplier_id: number | null;
  supplier_text: string | null;
  spec_reference: string | null;
  notes: string | null;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface PaintCreateRequest {
  name: string;
  paint_type: PaintType;
  colour_code?: string | null;
  colour_name?: string | null;
  colour_hex?: string | null;
  supplier_id?: number | null;
  supplier_text?: string | null;
  spec_reference?: string | null;
  notes?: string | null;
  is_active?: boolean | null;
}

export interface PaintUpdateRequest {
  name?: string;
  paint_type?: PaintType;
  colour_code?: string | null;
  colour_name?: string | null;
  colour_hex?: string | null;
  supplier_id?: number | null;
  supplier_text?: string | null;
  spec_reference?: string | null;
  notes?: string | null;
  is_active?: boolean;
}

export interface PaintUsedIn {
  part_id: number;
  part_number: string;
  name: string;
  project_id: number;
  project_code: string;
  layer_order: number;
}

export interface PartPaintLayer {
  layer_order: number;
  area: string | null;
  notes: string | null;
  paint: Paint;
}

export interface PartPaintLayerInput {
  paint_id: number;
  area?: string | null;
  notes?: string | null;
}

export interface PartPaintSetup {
  paint_required: boolean;
  process: string | null;
  notes: string | null;
  layers: PartPaintLayer[];
}

export interface PartPaintSetupInput {
  paint_required: boolean;
  process?: string | null;
  notes?: string | null;
  layers: PartPaintLayerInput[];
}

export interface PaintOverviewPart {
  part_id: number;
  part_number: string;
  name: string;
  process: string | null;
  layers: PartPaintLayer[];
}
