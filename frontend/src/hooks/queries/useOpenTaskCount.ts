/**
 * Everything waiting on the signed-in caller, in one number: the rows of the
 * one task list on My Tasks (workflow tasks for "my departments" plus the
 * change tasks), folded the same way the page folds them, so an R and an A
 * on the same step count once; plus the new-index triage and engineering
 * review rows, the Finance cost sheet review and the caller's open project
 * LOP lines (GET /v1/lop/mine; a failure there counts 0). LOP escalations are
 * counted apart (`escalated`). Rows where the caller is
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
import { lopApi, lopOverviewKeys } from '../../api/lop';
import { getMyTasks } from '../../api/workflows';
import { LIVE_REFETCH_MS } from '../../lib/invalidateCosting';
import { foldChangeTasks, foldWorkflowTasks, isBackup } from '../../lib/myTasks';

const REFETCH_MS = 60_000;

export interface MyTaskCounts {
  /** Main rows of the task list (workflow + change tasks, folded). */
  list: number;
  /** Main rows of "New indexes" (triage and engineering review). */
  intakes: number;
  /** 1 when the Finance cost sheet review is due for the caller. */
  finance: number;
  /** The caller's open lines in the project LOPs (always their own, never backup). */
  lop: number;
  total: number;
  /** Project LOP escalations the caller has to act on (GET /v1/lop/escalations/mine):
   *  their own escalated lines and, for the PM, those of the project. Shown as a
   *  third, red counter; not added to total (an own line is in `lop` already). */
  escalated: number;
  /** Rows where the caller is only the named backup (listed, not in total);
   *  the sidebar shows them as a second, grey counter (Christoph 2026-10-28). */
  backup: number;
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
    // change tasks move with other departments' input: same pace as the
    // change page (Christoph 2026-11-09 night)
    refetchInterval: LIVE_REFETCH_MS,
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
  const { data: lopLines } = useQuery({
    queryKey: lopOverviewKeys.mine,
    queryFn: lopApi.mine,
    refetchInterval: REFETCH_MS,
    staleTime: 30_000,
  });
  const { data: lopEscalations } = useQuery({
    queryKey: lopOverviewKeys.myEscalations,
    queryFn: lopApi.myEscalations,
    refetchInterval: REFETCH_MS,
    staleTime: 30_000,
  });
  // Project team (spec §18): backup rows are listed on My Tasks but do not
  // count; where no responsible is set every row is main (today's behaviour).
  const main = (rows: { role?: string | null }[]) => rows.filter((r) => !isBackup(r)).length;
  const backups = (rows: { role?: string | null }[]) => rows.filter(isBackup).length;
  const wf = foldWorkflowTasks(workflow);
  const ch = foldChangeTasks(changeTasks);
  const intakeAll = [...(intakes?.triage ?? []), ...(intakes?.review ?? [])];
  const list = main(wf) + main(ch);
  const intakeRows = main(intakeAll);
  const finance = review?.due ? 1 : 0;
  const lop = Array.isArray(lopLines) ? lopLines.length : 0;
  const escalated = Array.isArray(lopEscalations) ? lopEscalations.length : 0;
  return { list, intakes: intakeRows, finance, lop, escalated, total: list + intakeRows + finance + lop,
           backup: backups(wf) + backups(ch) + backups(intakeAll) };
}

export function useOpenTaskCount(): number {
  return useMyTaskCounts().total;
}
