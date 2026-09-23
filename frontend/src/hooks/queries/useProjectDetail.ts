/**
 * Queries behind the project page and the pop-out detail window.
 * Moved out of ProjectDetailPage without change; query keys are shared with
 * the invalidations spread across the page, so do not rename them.
 */
import { useQuery } from '@tanstack/react-query';
import client from '../../api/client';
import type {
  AssemblyFileEntry, CatalogPart, ChangelogEntry, Part, PartRevision, Project, RevisionFile,
} from '../../components/project/projectTypes';

export function useProject(projectId: number) {
  return useQuery<Project>({
    queryKey: ['project', projectId],
    queryFn: async () => {
      const res = await client.get(`/v1/plants/projects`);
      return res.data.find((p: Project) => p.id === projectId);
    },
    enabled: !!projectId,
  });
}

export function useProjectParts(projectId: number) {
  return useQuery<Part[]>({
    queryKey: ['parts', projectId],
    queryFn: async () => {
      const res = await client.get(`/v1/parts/project/${projectId}`);
      return res.data;
    },
    enabled: !!projectId,
  });
}

export function usePartRevisions(partId: number) {
  return useQuery<PartRevision[]>({
    queryKey: ['part-revisions', partId],
    queryFn: async () => {
      const res = await client.get(`/v1/parts/${partId}/revisions`);
      return res.data;
    },
    enabled: !!partId,
  });
}

export function useRevisionFiles(revisionId: number) {
  return useQuery<RevisionFile[]>({
    queryKey: ['revision-files', revisionId],
    queryFn: async () => {
      const res = await client.get(`/v1/parts/revisions/${revisionId}/files`);
      return res.data;
    },
    enabled: !!revisionId,
  });
}

export function useAssemblyFiles(partId: number) {
  return useQuery<AssemblyFileEntry[]>({
    queryKey: ['assembly-files', partId],
    queryFn: async () => {
      const res = await client.get(`/v1/parts/${partId}/assembly-files`);
      return res.data;
    },
    enabled: !!partId,
  });
}

export function useChangelog(partId: number) {
  return useQuery<ChangelogEntry[]>({
    queryKey: ['part-changelog', partId],
    queryFn: async () => {
      const res = await client.get(`/v1/parts/${partId}/changelog`);
      return res.data;
    },
    enabled: !!partId,
  });
}

export function useCatalogParts() {
  return useQuery<CatalogPart[]>({
    queryKey: ['catalog-parts'],
    queryFn: async () => {
      const res = await client.get('/v1/catalog-parts?is_active=true');
      return res.data;
    },
  });
}
