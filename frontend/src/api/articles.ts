/**
 * Article and revision API functions
 */
import client from './client';
import type {
  ArticleResponse,
  ArticleDetailResponse,
  RevisionResponse,
  RevisionTreeResponse,
  ArticleCreateRequest,
  ArticleUpdateRequest,
  RevisionStatusEnum,
} from '../types/article';

/**
 * Create a new article
 */
export const createArticle = async (data: ArticleCreateRequest): Promise<ArticleResponse> => {
  const response = await client.post('/v1/articles', data);
  return response.data;
};

/**
 * List articles for current organization
 */
export const listArticles = async (projectId?: number): Promise<ArticleResponse[]> => {
  const params = projectId ? { project_id: projectId } : {};
  const response = await client.get('/v1/articles', { params });
  return response.data;
};

/**
 * Get article details with revisions
 */
export const getArticle = async (articleId: number): Promise<ArticleDetailResponse> => {
  const response = await client.get(`/v1/articles/${articleId}`);
  return response.data;
};

/**
 * Update article metadata
 */
export const updateArticle = async (
  articleId: number,
  data: ArticleUpdateRequest
): Promise<ArticleResponse> => {
  const response = await client.put(`/v1/articles/${articleId}`, data);
  return response.data;
};

/**
 * Create a new engineering revision
 */
export const createEngineeringRevision = async (articleId: number): Promise<RevisionResponse> => {
  const response = await client.post(`/v1/articles/${articleId}/revisions/engineering`, {});
  return response.data;
};

/**
 * Release an engineering revision to a released index
 */
export const releaseRevision = async (
  articleId: number,
  revisionId: number,
  notes?: string
): Promise<RevisionResponse> => {
  const response = await client.post(
    `/v1/articles/${articleId}/revisions/${revisionId}/release`,
    { notes }
  );
  return response.data;
};

/**
 * Create a change proposal for a released index
 */
export const createChangeProposal = async (
  articleId: number,
  releasedIndexId: number,
  changeSummary?: string
): Promise<RevisionResponse> => {
  const response = await client.post(
    `/v1/articles/${articleId}/revisions/${releasedIndexId}/change-proposal`,
    { change_summary: changeSummary }
  );
  return response.data;
};

/**
 * Transition a revision to a new status
 */
export const transitionRevisionStatus = async (
  articleId: number,
  revisionId: number,
  newStatus: RevisionStatusEnum,
  notes?: string
): Promise<RevisionResponse> => {
  const response = await client.put(
    `/v1/articles/${articleId}/revisions/${revisionId}/status`,
    { new_status: newStatus, notes }
  );
  return response.data;
};

/**
 * Get revision tree for an article
 */
export const getRevisionTree = async (articleId: number): Promise<RevisionTreeResponse> => {
  const response = await client.get(`/v1/articles/${articleId}/revision-tree`);
  return response.data;
};
