/**
 * Everything waiting on the signed-in caller, in one number: the rows of the
 * one task list on My Tasks (workflow tasks for "my departments" plus the
 * change tasks), folded the same way the page folds them, so an R and an A
 * on the same step count once and the badge always equals the rows shown.
 *
 * Both queries share My Tasks' cache keys, so opening the page costs no extra
 * fetch, and both ride the shared api client: acting-as is honoured for free.
 */
import { useQuery } from '@tanstack/react-query';
import { changesApi } from '../../api/changes';
import { getMyTasks } from '../../api/workflows';
import { foldChangeTasks, foldWorkflowTasks } from '../../lib/myTasks';

const REFETCH_MS = 60_000;

export function useOpenTaskCount(): number {
  const { data: workflow } = useQuery({
    queryKey: ['workflow', 'my-tasks', 0],
    queryFn: () => getMyTasks(0),
    refetchInterval: REFETCH_MS,
    staleTime: 30_000,
  });
  const { data: changeTasks } = useQuery({
    queryKey: ['change-my-tasks'],
    queryFn: () => changesApi.myTasks(),
    refetchInterval: REFETCH_MS,
    staleTime: 30_000,
  });
  return foldWorkflowTasks(workflow).length + foldChangeTasks(changeTasks).length;
}
