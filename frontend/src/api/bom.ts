/**
 * BOM and catalog parts API functions
 */
import client from './client';
import type {
  CatalogPartCreateRequest,
  CatalogPartUpdateRequest,
  CatalogPartResponse,
  DuplicateCheckResponse,
  BOMItemCreateRequest,
  BOMItemUpdateRequest,
  BOMItemResponse,
  BOMResponse,
  ProjectBOMResponse,
} from '../types/bom';

export const listCatalogParts = async (params?: {
  search?: string;
  part_type?: string;
  is_active?: boolean;
}): Promise<CatalogPartResponse[]> => {
  const response = await client.get('/v1/catalog-parts', { params });
  return response.data;
};

export const createCatalogPart = async (data: CatalogPartCreateRequest): Promise<CatalogPartResponse> => {
  const response = await client.post('/v1/catalog-parts', data);
  return response.data;
};

export const checkDuplicate = async (params: {
  part_number?: string;
  name?: string;
}): Promise<DuplicateCheckResponse> => {
  const response = await client.get('/v1/catalog-parts/check-duplicate', { params });
  return response.data;
};

export const getCatalogPart = async (partId: number): Promise<CatalogPartResponse> => {
  const response = await client.get(`/v1/catalog-parts/${partId}`);
  return response.data;
};

export const updateCatalogPart = async (
  partId: number,
  data: CatalogPartUpdateRequest
): Promise<CatalogPartResponse> => {
  const response = await client.put(`/v1/catalog-parts/${partId}`, data);
  return response.data;
};

export const deactivateCatalogPart = async (partId: number): Promise<void> => {
  await client.delete(`/v1/catalog-parts/${partId}`);
};

export const getBOM = async (articleId: number, revisionId: number): Promise<BOMResponse> => {
  const response = await client.get(`/v1/articles/${articleId}/revisions/${revisionId}/bom`);
  return response.data;
};

export const addBOMItem = async (
  articleId: number,
  revisionId: number,
  data: BOMItemCreateRequest
): Promise<BOMItemResponse> => {
  const response = await client.post(
    `/v1/articles/${articleId}/revisions/${revisionId}/bom/items`,
    data
  );
  return response.data;
};

export const updateBOMItem = async (
  articleId: number,
  revisionId: number,
  itemId: number,
  data: BOMItemUpdateRequest
): Promise<BOMItemResponse> => {
  const response = await client.put(
    `/v1/articles/${articleId}/revisions/${revisionId}/bom/items/${itemId}`,
    data
  );
  return response.data;
};

export const deleteBOMItem = async (
  articleId: number,
  revisionId: number,
  itemId: number
): Promise<void> => {
  await client.delete(
    `/v1/articles/${articleId}/revisions/${revisionId}/bom/items/${itemId}`
  );
};

export const getProjectBOM = async (projectId: number): Promise<ProjectBOMResponse> => {
  const response = await client.get(`/v1/projects/${projectId}/bom-aggregation`);
  return response.data;
};
