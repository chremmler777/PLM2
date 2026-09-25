/**
 * Everything waiting on the signed-in caller, in one number: the rows of the
 * one task list on My Tasks (workflow tasks for "my departments" plus the
 * change tasks), folded the same way the page folds them, so an R and an A
 * on the same step count once; plus the new-index triage and engineering
 * review rows and the Finance cost sheet review. Rows where the caller is
 * only backup (spec §18) are listed, not counted. The sidebar badge, the My
 * Tasks header and GET /workflow-instances/open-task-count all count this.
 *
 * Every query shares My Tasks' cache keys, so opening the page costs no extra
 * fetch, and all ride the shared api client: acting-as is honoured for free.
 */
import { useQuery } from '@tanstack/react-query';
import { changesApi } from '../../api/changes';
import { costSheetApi } from '../../api/costSheet';
import { intakeKeys, intakesApi } from '../../api/intakes';
import { getMyTasks } from '../../api/workflows';
import { foldChangeTasks, foldWorkflowTasks, isBackup } from '../../lib/myTasks';

const REFETCH_MS = 60_000;

export interface MyTaskCounts {
  /** Main rows of the task list (workflow + change tasks, folded). */
  list: number;
  /** Main rows of "New indexes" (triage and engineering review). */
  intakes: number;
  /** 1 when the Finance cost sheet review is due for the caller. */
  finance: number;
  total: number;
}

export function useMyTaskCounts(): MyTaskCounts {
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
  const { data: intakes } = useQuery({
    queryKey: intakeKeys.my,
    queryFn: intakesApi.my,
    refetchInterval: REFETCH_MS,
    staleTime: 30_000,
  });
  const { data: review } = useQuery({
    queryKey: ['cost-sheet-review-task'],
    queryFn: () => costSheetApi.reviewTask(),
    retry: false,
    staleTime: 5 * 60 * 1000,
  });
  // Project team (spec §18): backup rows are listed on My Tasks but do not
  // count; where no responsible is set every row is main (today's behaviour).
  const main = (rows: { role?: string | null }[]) => rows.filter((r) => !isBackup(r)).length;
  const list = main(foldWorkflowTasks(workflow)) + main(foldChangeTasks(changeTasks));
  const intakeRows = main([...(intakes?.triage ?? []), ...(intakes?.review ?? [])]);
  const finance = review?.due ? 1 : 0;
  return { list, intakes: intakeRows, finance, total: list + intakeRows + finance };
}

export function useOpenTaskCount(): number {
  return useMyTaskCounts().total;
}
