/**
 * React Query hooks for articles
 */
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import * as articleApi from '../../api/articles';
import type {
  ArticleResponse,
  ArticleDetailResponse,
  ArticleCreateRequest,
  ArticleUpdateRequest,
  RevisionStatusEnum,
} from '../../types/article';

const QUERY_KEYS = {
  articles: ['articles'],
  articlesForProject: (projectId: number) => ['articles', 'project', projectId],
  article: (articleId: number) => ['articles', articleId],
  revisionTree: (articleId: number) => ['articles', articleId, 'revisions', 'tree'],
};

/**
 * Hook to list articles
 */
export const useArticles = (projectId?: number) => {
  return useQuery({
    queryKey: projectId ? QUERY_KEYS.articlesForProject(projectId) : QUERY_KEYS.articles,
    queryFn: () => articleApi.listArticles(projectId),
  });
};

/**
 * Hook to get article details
 */
export const useArticle = (articleId: number) => {
  return useQuery({
    queryKey: QUERY_KEYS.article(articleId),
    queryFn: () => articleApi.getArticle(articleId),
  });
};

/**
 * Hook to get revision tree
 */
export const useRevisionTree = (articleId: number) => {
  return useQuery({
    queryKey: QUERY_KEYS.revisionTree(articleId),
    queryFn: () => articleApi.getRevisionTree(articleId),
  });
};

/**
 * Hook to create an article
 */
export const useCreateArticle = () => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (data: ArticleCreateRequest) => articleApi.createArticle(data),
    onSuccess: (newArticle) => {
      // Invalidate articles list
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.articles });
      // Optionally add to cache
      queryClient.setQueryData(QUERY_KEYS.article(newArticle.id), {
        article: newArticle,
        revisions: [],
        revision_tree: { engineering: [], released_indexes: [] },
      });
    },
  });
};

/**
 * Hook to update an article
 */
export const useUpdateArticle = (articleId: number) => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (data: ArticleUpdateRequest) => articleApi.updateArticle(articleId, data),
    onSuccess: (updatedArticle) => {
      // Update cache
      queryClient.setQueryData(QUERY_KEYS.article(articleId), (prev: ArticleDetailResponse | undefined) => {
        if (prev) {
          return { ...prev, article: updatedArticle };
        }
        return undefined;
      });
      // Invalidate lists
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.articles });
    },
  });
};

/**
 * Hook to create engineering revision
 */
export const useCreateEngineeringRevision = (articleId: number) => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: () => articleApi.createEngineeringRevision(articleId),
    onSuccess: () => {
      // Invalidate article and revision tree
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.article(articleId) });
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.revisionTree(articleId) });
    },
  });
};

/**
 * Hook to release revision
 */
export const useReleaseRevision = (articleId: number) => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (params: { revisionId: number; notes?: string }) =>
      articleApi.releaseRevision(articleId, params.revisionId, params.notes),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.article(articleId) });
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.revisionTree(articleId) });
    },
  });
};

/**
 * Hook to create change proposal
 */
export const useCreateChangeProposal = (articleId: number) => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (params: { releasedIndexId: number; changeSummary?: string }) =>
      articleApi.createChangeProposal(articleId, params.releasedIndexId, params.changeSummary),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.article(articleId) });
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.revisionTree(articleId) });
    },
  });
};

/**
 * Hook to transition revision status
 */
export const useTransitionRevisionStatus = (articleId: number) => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (params: { revisionId: number; newStatus: RevisionStatusEnum; notes?: string }) =>
      articleApi.transitionRevisionStatus(articleId, params.revisionId, params.newStatus, params.notes),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.article(articleId) });
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.revisionTree(articleId) });
    },
  });
};
