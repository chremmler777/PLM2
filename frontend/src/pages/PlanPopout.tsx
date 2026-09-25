/**
 * PlanPopout - one change plan (quote or detailed) alone in its own browser
 * window (/changes/:changeId/plan/:plan). No app sidebar: a small header and
 * the Gantt at full window size. It shares the react-query keys of the main
 * window, refetches on focus, and hears saves from other windows through the
 * planner's BroadcastChannel, so both windows stay current.
 */
import { useEffect } from 'react';
import { useParams, useSearchParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { changesApi } from '../api/changes';
import { planApi } from '../api/changePlan';
import { CHANGE_STATUS_ORDER, type ChangeStatus } from '../types/change';
import GanttPlanner from '../components/changes/plan/GanttPlanner';

const phase = (s: string) => CHANGE_STATUS_ORDER.indexOf(s as ChangeStatus);
const statusOf = (e: unknown) => (e as { response?: { status?: number } })?.response?.status;
/** A plan that does not exist or is not ours to see stays so: no retries. */
const retry = (count: number, e: unknown) => ![401, 403, 404].includes(statusOf(e) ?? 0) && count < 2;

export default function PlanPopout() {
  const params = useParams<{ changeId: string; plan: string }>();
  const id = params.changeId ? parseInt(params.changeId, 10) : 0;
  const plan = params.plan === 'quote' || params.plan === 'detailed' ? params.plan : null;
  const valid = id > 0 && plan !== null;
  const [search] = useSearchParams();
  const taskParam = Number(search.get('task'));
  const focusTaskId = Number.isInteger(taskParam) && taskParam > 0 ? taskParam : undefined;

  const { data: change, error: changeError } = useQuery({
    queryKey: ['change', id], queryFn: () => changesApi.get(id), enabled: valid, retry,
  });
  const detailed = valid && plan === 'detailed';
  const { data: planOut } = useQuery({
    queryKey: ['change', id, 'plan', 'detailed'], queryFn: () => planApi.get(id, 'detailed'), enabled: detailed, retry,
  });
  const { data: feedback } = useQuery({
    queryKey: ['change', id, 'plan-feedback'], queryFn: () => planApi.feedback(id), enabled: detailed, retry,
  });

  const label = plan === 'quote' ? 'Quote plan' : 'Detailed plan';
  const number = change?.change_number ?? `Change ${id}`;
  useEffect(() => { if (valid) document.title = `${number} - ${label}`; }, [valid, number, label]);

  const denied = [403, 404].includes(statusOf(changeError) ?? 0);
  if (!valid || denied) {
    return (
      <div className="h-screen bg-slate-900 p-6 text-sm text-slate-300" data-testid="plan-popout-invalid" role="alert">
        This plan was not found or you can't open it.
      </div>
    );
  }
  const status = change?.status;
  const track = plan === 'detailed'
    && (!!planOut?.baseline_set || !!feedback?.validated_at || (!!status && phase(status) >= phase('in_implementation')));

  return (
    <div className="h-screen flex flex-col bg-slate-900 text-slate-100">
      <header data-testid="plan-popout-header"
        className="flex flex-wrap items-baseline gap-x-3 gap-y-1 px-4 py-2 border-b border-slate-700 bg-slate-800">
        <span className="text-xs text-slate-400">{label}</span>
        <span className="font-semibold tabular-nums">{number}</span>
        <span className="text-slate-300">{change?.title}</span>
      </header>
      <main className="flex-1 min-h-0 overflow-auto p-3">
        <GanttPlanner changeId={id} plan={plan} changeNumber={change?.change_number}
          mode={track ? 'track' : 'plan'} status={plan === 'detailed' ? status : undefined}
          hideSeed={plan === 'detailed'} height="calc(100vh - 11rem)" inWindow focusTaskId={focusTaskId} />
      </main>
    </div>
  );
}
