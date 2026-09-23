/**
 * Data behind the Changes and Lessons buttons of the project status nav bar.
 * Uses the same query keys as the changes and lessons sections so the panel
 * opens on a warm cache. The SEP gate strip reads its own SEP query.
 */
import { useQuery } from '@tanstack/react-query';
import client from '../../api/client';
import { changesApi } from '../../api/changes';

export type ChipTone = 'neutral' | 'green' | 'amber';
export interface StatusChip { label: string; tone: ChipTone; title: string }

const CLOSED_CHANGE_STATUSES = ['closed', 'rejected', 'cancelled'];

export function changesChip(changes: { status: string }[] | undefined): StatusChip {
  if (!changes) return { label: 'Changes', tone: 'neutral', title: 'Change requests' };
  const open = changes.filter((c) => !CLOSED_CHANGE_STATUSES.includes(c.status)).length;
  return {
    label: `Changes (${open})`,
    tone: 'neutral',
    title: `${open} open of ${changes.length} change requests`,
  };
}

export function lessonsChip(references: unknown[] | undefined): StatusChip {
  if (!references) return { label: 'Lessons', tone: 'neutral', title: 'Lessons learned' };
  if (references.length === 0) {
    return { label: 'Lessons · no review', tone: 'amber', title: 'Gate prep: no lessons review recorded yet' };
  }
  return { label: `Lessons (${references.length})`, tone: 'green', title: 'Lessons reviewed for reuse' };
}

export function useProjectStatus(projectId: number) {
  const changes = useQuery({
    queryKey: ['changes', 'project', projectId],
    queryFn: () => changesApi.list({ project_id: projectId }),
    enabled: !!projectId,
  });
  const references = useQuery({
    queryKey: ['lesson-references', projectId],
    queryFn: async () => (await client.get(`/v1/lessons/projects/${projectId}/references`)).data as unknown[],
    enabled: !!projectId,
  });
  return {
    changes: changesChip(Array.isArray(changes.data) ? changes.data : undefined),
    lessons: lessonsChip(Array.isArray(references.data) ? references.data : undefined),
  };
}
