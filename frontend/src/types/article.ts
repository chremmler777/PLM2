/**
 * Article and revision types
 */

export enum ArticleTypeEnum {
  INJECTION_TOOL = 'injection_tool',
  ASSEMBLY_EQUIPMENT = 'assembly_equipment',
  PURCHASED_PART = 'purchased_part',
}

export enum SourcingTypeEnum {
  INTERNAL = 'internal',
  EXTERNAL = 'external',
}

export enum RevisionTypeEnum {
  ENGINEERING = 'engineering',
  RELEASED = 'released',
  CHANGE = 'change',
}

export enum RevisionStatusEnum {
  DRAFT = 'draft',
  RFQ = 'rfq',
  IN_REVIEW = 'in_review',
  APPROVED = 'approved',
  IN_IMPLEMENTATION = 'in_implementation',
  RELEASED = 'released',
  REJECTED = 'rejected',
  CANCELED = 'canceled',
  SUPERSEDED = 'superseded',
}

export interface ArticleCreateRequest {
  article_number: string;
  name: string;
  description?: string;
  article_type: ArticleTypeEnum;
  sourcing_type?: SourcingTypeEnum;
}

export interface ArticleUpdateRequest {
  name?: string;
  description?: string | null;
  sourcing_type?: SourcingTypeEnum;
}

export interface ArticleResponse {
  id: number;
  article_number: string;
  name: string;
  description: string | null;
  article_type: ArticleTypeEnum;
  sourcing_type: SourcingTypeEnum;
  data_classification: string;
  active_revision_id: number | null;
  project_id: number | null;
  created_at: string;
  created_by: number;
}

export interface RevisionResponse {
  id: number;
  article_id: number;
  revision: string;
  version: number;
  status: RevisionStatusEnum;
  revision_type: RevisionTypeEnum;
  rfq_number: string | null;
  is_official: boolean;
  change_summary: string | null;
  comments: string | null;
  created_at: string;
  created_by: number;
  released_at: string | null;
  released_by: number | null;
  parent_revision_id: number | null;
  supersedes_id: number | null;
  parent_index_id: number | null;
}

export interface RevisionTreeNodeResponse {
  id: number;
  revision: string;
  status: RevisionStatusEnum;
  revision_type: RevisionTypeEnum;
}

export interface RevisionChangeResponse {
  id: number;
  revision: string;
  status: RevisionStatusEnum;
}

export interface RevisionIndexResponse {
  id: number;
  revision: string;
  status: RevisionStatusEnum;
  changes: RevisionChangeResponse[];
}

export interface RevisionTreeResponse {
  engineering: RevisionTreeNodeResponse[];
  released_indexes: RevisionIndexResponse[];
}

export interface ArticleDetailResponse {
  article: ArticleResponse;
  revisions: RevisionResponse[];
  revision_tree: RevisionTreeResponse;
}
