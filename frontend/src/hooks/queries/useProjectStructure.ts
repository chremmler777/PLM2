import { useQuery } from '@tanstack/react-query';
import client from '../../api/client';

export interface StructureRevision { id: number; revision_name: string; customer_index: string | null; status: string; phase: 'review' | 'official'; parent_revision_id: number | null; is_active: boolean;
  /** Spec §17: a customer major still waiting for triage (or its change). */
  intake_pending?: boolean; intake_id?: number | null }
export interface StructureRelated { relation_type: string; direction: 'outgoing' | 'incoming'; label: string; part_id: number; part_number: string; name: string; item_category: string }
export interface StructureBrief { part_id: number; part_number: string; customer_part_number: string | null; name: string; thumbnail_url?: string | null }
export interface StructureArticle extends StructureBrief {
  lifecycle_phase: string; active_revision_id: number | null;
  revisions: StructureRevision[]; related: StructureRelated[];
  /** Spec §17: some new index of this article is still pending. */
  intake_pending?: boolean;
  mirror_of: StructureBrief | null; mirrored_by: StructureBrief[];
}
export interface ProjectStructure { articles: StructureArticle[] }

export function useProjectStructure(projectId: number) {
  return useQuery<ProjectStructure>({
    queryKey: ['project-structure', projectId],
    queryFn: async () => (await client.get(`/v1/parts/project/${projectId}/structure`)).data,
    enabled: !!projectId,
  });
}

export function articleOf(structure: ProjectStructure | undefined, partId: number | null): StructureArticle | undefined {
  if (!structure || partId === null || !structure.articles) return undefined;
  return structure.articles.find((a) => a.part_id === partId);
}
