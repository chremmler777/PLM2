/**
 * Paint catalog and part paint setup API functions
 */
import client from './client';
import type {
  Paint,
  PaintCreateRequest,
  PaintUpdateRequest,
  PaintUsedIn,
  PartPaintSetup,
  PartPaintSetupInput,
  PaintOverviewPart,
} from '../types/paint';

export const listPaints = async (params?: {
  activeOnly?: boolean;
  q?: string;
}): Promise<Paint[]> => {
  const response = await client.get('/v1/paints', {
    params: {
      active_only: params?.activeOnly,
      q: params?.q,
    },
  });
  return response.data;
};

export const createPaint = async (data: PaintCreateRequest): Promise<Paint> => {
  const response = await client.post('/v1/paints', data);
  return response.data;
};

export const updatePaint = async (id: number, data: PaintUpdateRequest): Promise<Paint> => {
  const response = await client.put(`/v1/paints/${id}`, data);
  return response.data;
};

export const paintUsedIn = async (id: number): Promise<PaintUsedIn[]> => {
  const response = await client.get(`/v1/paints/${id}/used-in`);
  return response.data;
};

export const getPartPaint = async (partId: number): Promise<PartPaintSetup> => {
  const response = await client.get(`/v1/parts/${partId}/paint`);
  return response.data;
};

export const putPartPaint = async (
  partId: number,
  setup: PartPaintSetupInput
): Promise<PartPaintSetup> => {
  const response = await client.put(`/v1/parts/${partId}/paint`, setup);
  return response.data;
};

export const projectPaintOverview = async (projectId: number): Promise<PaintOverviewPart[]> => {
  const response = await client.get(`/v1/parts/project/${projectId}/paint-overview`);
  return response.data;
};
