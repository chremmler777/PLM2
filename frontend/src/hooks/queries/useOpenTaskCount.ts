/**
 * Everything waiting on the signed-in caller, in one number: workflow tasks plus
 * the change-side rows (assessments and the stage-responsibility kinds) — the
 * same two sources My Tasks lists, so the badge and the page always agree.
 *
 * Both queries share My Tasks' cache keys, so opening the page costs no extra
 * fetch, and both ride the shared api client — acting-as is honoured for free.
 */
import { useQuery } from '@tanstack/react-query';
import client from '../../api/client';
import { changesApi } from '../../api/changes';

const REFETCH_MS = 60_000;

export function useOpenTaskCount(): number {
  const { data: workflow } = useQuery<{ count: number }>({
    queryKey: ['open-task-count'],
    queryFn: async () => (await client.get('/v1/workflow-instances/open-task-count')).data,
    refetchInterval: REFETCH_MS,
  });
  const { data: changeTasks } = useQuery({
    queryKey: ['change-my-tasks'],
    queryFn: () => changesApi.myTasks(),
    refetchInterval: REFETCH_MS,
    staleTime: 30_000,
  });
  return (workflow?.count ?? 0) + (changeTasks?.length ?? 0);
}
