/**
 * Data behind the three status chips in the project header. Uses the same
 * query keys as the SEP, changes and lessons sections so the slide-over
 * opens on a warm cache.
 */
import { useQuery } from '@tanstack/react-query';
import client from '../../api/client';
import { changesApi } from '../../api/changes';
import type { SepState } from '../../types/sep';

export type ChipTone = 'neutral' | 'green' | 'yellow' | 'red' | 'amber';
export interface StatusChip { label: string; tone: ChipTone; title: string }

const CLOSED_CHANGE_STATUSES = ['closed', 'rejected', 'cancelled'];

export function sepChip(sep: SepState | undefined): StatusChip {
  if (!sep) return { label: 'SEP', tone: 'neutral', title: 'SEP Q-gates' };
  if (!sep.active) return { label: 'SEP off', tone: 'neutral', title: 'SEP not active for this project' };
  const gates = Array.isArray(sep.gates) ? sep.gates : [];
  const current = gates.find((g) => g.status === 'in_progress');
  if (!current) {
    const done = gates.length > 0 && gates.every((g) => g.status === 'closed');
    return { label: done ? 'SEP done' : 'SEP', tone: done ? 'green' : 'neutral', title: 'SEP Q-gates' };
  }
  const applicable = current.progress.total - current.progress.not_applicable;
  return {
    label: `${current.code} ${current.progress.pct}%`,
    tone: current.color,
    title: `${current.phase_en}: ${current.progress.done} of ${applicable} done`,
  };
}

export function changesChip(changes: { status: string }[] | undefined): StatusChip {
  if (!changes) return { label: 'Changes', tone: 'neutral', title: 'Change requests' };
  const open = changes.filter((c) => !CLOSED_CHANGE_STATUSES.includes(c.status)).length;
  return {
    label: `${open} change${open === 1 ? '' : 's'}`,
    tone: 'neutral',
    title: `${open} open of ${changes.length} change requests`,
  };
}

export function lessonsChip(references: unknown[] | undefined): StatusChip {
  if (!references) return { label: 'Lessons', tone: 'neutral', title: 'Lessons learned' };
  if (references.length === 0) {
    return { label: 'No lessons review', tone: 'amber', title: 'Gate prep: no lessons review recorded yet' };
  }
  const n = references.length;
  return { label: `${n} lesson${n === 1 ? '' : 's'} reviewed`, tone: 'green', title: 'Lessons reviewed for reuse' };
}

export function useProjectStatus(projectId: number) {
  const sep = useQuery({
    queryKey: ['sep', projectId],
    queryFn: async () => (await client.get(`/v1/sep/projects/${projectId}`)).data as SepState,
    enabled: !!projectId,
  });
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
    sep: sepChip(sep.data),
    changes: changesChip(Array.isArray(changes.data) ? changes.data : undefined),
    lessons: lessonsChip(Array.isArray(references.data) ? references.data : undefined),
  };
}
