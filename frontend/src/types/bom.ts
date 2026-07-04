/**
 * BOM and catalog part types
 */

export type PartTypeEnum = 'purchased' | 'manufactured';

export interface CatalogPartCreateRequest {
  part_number: string;
  name: string;
  description?: string | null;
  part_type: PartTypeEnum;
  supplier?: string | null;
  unit: string;
}

export interface CatalogPartUpdateRequest {
  name?: string;
  description?: string | null;
  part_type?: PartTypeEnum;
  supplier?: string | null;
  unit?: string;
}

export interface CatalogPartResponse {
  id: number;
  organization_id: number;
  part_number: string;
  name: string;
  description: string | null;
  part_type: PartTypeEnum;
  supplier: string | null;
  unit: string;
  is_active: boolean;
  created_at: string;
  created_by: number;
  updated_at: string;
}

export interface DuplicateCheckResponse {
  exact_match: boolean;
  similar_parts: CatalogPartResponse[];
}
