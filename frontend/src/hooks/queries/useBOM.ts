/**
 * React Query hooks for BOM and catalog parts
 */
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import * as bomApi from '../../api/bom';
import type {
  CatalogPartCreateRequest,
  CatalogPartUpdateRequest,
  BOMItemCreateRequest,
  BOMItemUpdateRequest,
} from '../../types/bom';

const QUERY_KEYS = {
  catalogParts: ['catalog-parts'] as const,
  bom: (articleId: number, revisionId: number) => ['bom', articleId, revisionId] as const,
  projectBOM: (projectId: number) => ['bom', 'project', projectId] as const,
};

export const useCatalogParts = (params?: {
  search?: string;
  part_type?: string;
  is_active?: boolean;
}) => {
  return useQuery({
    queryKey: [...QUERY_KEYS.catalogParts, params],
    queryFn: () => bomApi.listCatalogParts(params),
  });
};

export const useCreateCatalogPart = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (data: CatalogPartCreateRequest) => bomApi.createCatalogPart(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.catalogParts });
    },
  });
};

export const useUpdateCatalogPart = (partId: number) => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (data: CatalogPartUpdateRequest) => bomApi.updateCatalogPart(partId, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.catalogParts });
    },
  });
};

export const useDeactivateCatalogPart = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (partId: number) => bomApi.deactivateCatalogPart(partId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.catalogParts });
    },
  });
};

export const useBOM = (articleId: number, revisionId: number) => {
  return useQuery({
    queryKey: QUERY_KEYS.bom(articleId, revisionId),
    queryFn: () => bomApi.getBOM(articleId, revisionId),
    enabled: !!articleId && !!revisionId,
  });
};

export const useAddBOMItem = (articleId: number, revisionId: number) => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (data: BOMItemCreateRequest) => bomApi.addBOMItem(articleId, revisionId, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.bom(articleId, revisionId) });
    },
  });
};

export const useUpdateBOMItem = (articleId: number, revisionId: number) => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ itemId, data }: { itemId: number; data: BOMItemUpdateRequest }) =>
      bomApi.updateBOMItem(articleId, revisionId, itemId, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.bom(articleId, revisionId) });
    },
  });
};

export const useDeleteBOMItem = (articleId: number, revisionId: number) => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (itemId: number) => bomApi.deleteBOMItem(articleId, revisionId, itemId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.bom(articleId, revisionId) });
    },
  });
};

export const useProjectBOM = (projectId: number) => {
  return useQuery({
    queryKey: QUERY_KEYS.projectBOM(projectId),
    queryFn: () => bomApi.getProjectBOM(projectId),
    enabled: !!projectId,
  });
};
