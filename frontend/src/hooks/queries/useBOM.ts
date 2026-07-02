/**
 * React Query hooks for BOM and catalog parts
 */
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import * as bomApi from '../../api/bom';
import type {
  CatalogPartCreateRequest,
  CatalogPartUpdateRequest,
} from '../../types/bom';

const QUERY_KEYS = {
  catalogParts: ['catalog-parts'] as const,
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
