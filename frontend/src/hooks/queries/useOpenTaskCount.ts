/**
 * Everything waiting on the signed-in caller, in one number: the rows of the
 * one task list on My Tasks (workflow tasks for "my departments" plus the
 * change tasks), folded the same way the page folds them, so an R and an A
 * on the same step count once and the badge always equals the page's count.
 * Rows where the caller is only backup (spec §18) are listed, not counted.
 *
 * Both queries share My Tasks' cache keys, so opening the page costs no extra
 * fetch, and both ride the shared api client: acting-as is honoured for free.
 */
import { useQuery } from '@tanstack/react-query';
import { changesApi } from '../../api/changes';
import { getMyTasks } from '../../api/workflows';
import { foldChangeTasks, foldWorkflowTasks, isBackup } from '../../lib/myTasks';

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
  // Project team (spec §18): backup rows are listed on My Tasks but do not
  // count; where no responsible is set every row is main (today's behaviour).
  const main = (rows: { role?: string | null }[]) => rows.filter((r) => !isBackup(r)).length;
  return main(foldWorkflowTasks(workflow)) + main(foldChangeTasks(changeTasks));
}
