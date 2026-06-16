import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { changesApi } from '../../api/changes';

const LETTER_LABEL: Record<string, string> = {
  R: 'Responsible', A: 'Accountable', S: 'Support', C: 'Consulted', I: 'Informed',
};
const TIER_BADGE: Record<string, string> = {
  blocking: 'bg-rose-900/50 text-rose-200 border-rose-700',
  optional: 'bg-amber-900/40 text-amber-200 border-amber-700',
  info: 'bg-slate-700/50 text-slate-300 border-slate-600',
};

export default function AssessmentRouting({ changeId }: { changeId: number }) {
  const qc = useQueryClient();
  const { data: routing, isLoading } = useQuery({
    queryKey: ['change-routing', changeId],
    queryFn: () => changesApi.getRouting(changeId),
  });
  const approve = useMutation({
    mutationFn: () => changesApi.approveDeviation(changeId),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['change-routing', changeId] }),
  });

  if (isLoading) return <div className="text-slate-400 text-sm p-4">Loading routing…</div>;
  if (!routing || routing.stages.length === 0)
    return <div className="text-slate-400 text-sm p-4">No routing yet — enter assessment to generate it.</div>;

  const activeOrder = routing.stages.find(
    s => s.departments.some(d => d.status === 'active'))?.stage_order;

  return (
    <div className="space-y-3">
      {routing.deviation_status === 'pending_approval' && (
        <div className="flex items-center justify-between rounded border border-amber-700 bg-amber-900/30 px-3 py-2">
          <span className="text-amber-200 text-sm">Routing deviation pending approval.</span>
          <button onClick={() => approve.mutate()} disabled={approve.isPending}
            className="px-2.5 py-1 text-xs rounded bg-amber-600 hover:bg-amber-500 text-white">
            Approve deviation
          </button>
        </div>
      )}
      {routing.stages.map(stage => {
        const isActive = stage.stage_order === activeOrder;
        const done = stage.departments.filter(d => d.tier === 'blocking')
          .every(d => d.status === 'submitted');
        return (
          <div key={stage.stage_order}
            className={`rounded border p-3 ${isActive ? 'border-sky-600 bg-slate-800' : 'border-slate-700 bg-slate-800/40'}`}>
            <div className="flex items-center gap-2 mb-2">
              <span className="text-slate-100 text-sm font-semibold">Stage {stage.stage_order}</span>
              {isActive && <span className="text-xs text-sky-300">active</span>}
              {!isActive && done && <span className="text-xs text-emerald-400">complete</span>}
            </div>
            <ul className="space-y-1">
              {stage.departments.map(d => (
                <li key={`${d.department_id}-${d.rasic_letter}`}
                  className="flex items-center justify-between text-sm">
                  <span className="flex items-center gap-2">
                    <span className={`px-1.5 py-0.5 rounded border text-xs ${TIER_BADGE[d.tier]}`}
                      title={LETTER_LABEL[d.rasic_letter]}>{d.rasic_letter}</span>
                    <span className="text-slate-200">Dept {d.department_id}</span>
                  </span>
                  <span className="text-slate-400 text-xs">
                    {d.tier === 'info' ? 'notified' : (d.verdict && d.verdict !== 'pending' ? d.verdict : d.status)}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        );
      })}
    </div>
  );
}
