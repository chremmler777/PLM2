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

export interface BOMItemCreateRequest {
  catalog_part_id: number;
  quantity: number;
  notes?: string | null;
  position?: number | null;
}

export interface BOMItemUpdateRequest {
  quantity?: number;
  notes?: string | null;
  position?: number;
}

export interface BOMItemResponse {
  id: number;
  bom_id: number;
  catalog_part_id: number | null;
  part_number: string | null;
  name: string;
  part_type: string | null;
  quantity: number;
  unit: string;
  supplier: string | null;
  notes: string | null;
  position: number;
}

export interface BOMResponse {
  id: number;
  article_id: number;
  revision_id: number | null;
  status: string;
  items: BOMItemResponse[];
}

export interface ProjectBOMSourceResponse {
  article_id: number;
  article_number: string;
  article_name: string;
  revision_id: number;
  revision: string;
  quantity: number;
}

export interface ProjectBOMLineResponse {
  catalog_part_id: number;
  part_number: string;
  name: string;
  part_type: string;
  unit: string;
  supplier: string | null;
  total_quantity: number;
  sources: ProjectBOMSourceResponse[];
}

export interface ProjectBOMResponse {
  project_id: number;
  lines: ProjectBOMLineResponse[];
}
