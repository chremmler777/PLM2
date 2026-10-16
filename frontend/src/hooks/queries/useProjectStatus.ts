/**
 * Data behind the Changes, Lessons and Tooling DFM buttons of the project
 * status nav bar. Uses the same query keys as the changes and lessons
 * sections and the project DFM archive so the panel opens on a warm cache. The SEP gate strip reads its own SEP query.
 */
import { useQuery } from '@tanstack/react-query';
import client from '../../api/client';
import { changesApi } from '../../api/changes';
import { dfmKey, listTopics, projectScope, type DfmTopicSummary } from '../../api/dfm';
import { getProjectMoldflow, moldflowKey, type MfStatus, type ProjectMoldflow } from '../../api/moldflow';

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

/** "Tooling DFM 2" with the open topic count; amber while any open topic waits on KTX. */
export function dfmChip(topics: DfmTopicSummary[] | undefined): StatusChip {
  const base = { label: 'Tooling DFM', tone: 'neutral' as ChipTone, title: 'General tooling DFM for all tools of this project' };
  if (!topics) return base;
  const open = topics.filter((t) => t.status === 'open');
  const onKtx = open.filter((t) => (t.waiting_on ?? []).some((w) => w.party === 'ktx' && w.count > 0)).length;
  return {
    label: open.length > 0 ? `Tooling DFM ${open.length}` : 'Tooling DFM',
    tone: onKtx > 0 ? 'amber' : 'neutral',
    title: `General tooling DFM: ${open.length} open of ${topics.length} topics${onKtx > 0 ? `, ${onKtx} waiting on KTX` : ''}`,
  };
}

const MF_BUCKETS: { label: string; statuses: MfStatus[] }[] = [
  { label: 'feedback', statuses: ['customer_feedback', 'rework'] },
  { label: 'at customer', statuses: ['sent_to_customer'] },
  { label: 'in review', statuses: ['received', 'in_review'] },
  { label: 'running', statuses: ['running'] },
  { label: 'ready', statuses: ['ready_for_mf'] },
  { label: 'inputs open', statuses: ['inputs_open', 'not_started'] },
  { label: 'final', statuses: ['final'] },
];

/** "Moldflow · 3 at customer · 2 ready" from each tool's latest row (the two most advanced buckets with tools);
 *  amber while customer feedback or rework waits on KTX. */
export function moldflowChip(data: ProjectMoldflow | undefined): StatusChip {
  const base = { label: 'Moldflow', tone: 'neutral' as ChipTone, title: 'Moldflow timing per tool' };
  const tools = Array.isArray(data?.tools) ? data!.tools : undefined;
  if (!tools) return base;
  const latest = tools.map((t) => t.rows.find((r) => r.id === t.latest_id)).filter((r) => r !== undefined);
  if (latest.length === 0) return { ...base, title: `Moldflow timing: no Moldflow recorded for ${tools.length} tools` };
  const counts = MF_BUCKETS.map((b) => ({ label: b.label, n: latest.filter((r) => b.statuses.includes(r.status)).length }))
    .filter((c) => c.n > 0);
  const text = counts.map((c) => `${c.n} ${c.label}`);
  const none = tools.length - latest.length;
  return {
    label: `Moldflow · ${text.slice(0, 2).join(' · ')}`,
    tone: counts.some((c) => c.label === 'feedback') ? 'amber' : 'neutral',
    title: `Moldflow timing (latest version per tool): ${text.join(', ')}${none > 0 ? `; ${none} tools without Moldflow` : ''}`,
  };
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
  const dfmScope = projectScope(projectId);
  const dfm = useQuery({
    queryKey: dfmKey('dfm-topics', dfmScope),
    queryFn: () => listTopics(dfmScope),
    enabled: !!projectId,
  });
  const moldflow = useQuery({
    queryKey: moldflowKey(projectId),
    queryFn: () => getProjectMoldflow(projectId),
    enabled: !!projectId,
  });
  return {
    moldflow: moldflowChip(moldflow.data && !Array.isArray(moldflow.data) ? moldflow.data : undefined),
    dfm: dfmChip(Array.isArray(dfm.data) ? dfm.data : undefined),
    changes: changesChip(Array.isArray(changes.data) ? changes.data : undefined),
    lessons: lessonsChip(Array.isArray(references.data) ? references.data : undefined),
  };
}
