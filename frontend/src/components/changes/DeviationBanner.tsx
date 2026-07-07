import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import { changesApi } from '../../api/changes';
import ReasonDialog from './ReasonDialog';

interface Props {
  changeId: number;
  blockedTo: string;
  blockedReason: string;
  onRetry: () => void;
  onClose: () => void;
}

const STATUS_STYLE: Record<string, string> = {
  pending: 'bg-amber-900 text-amber-200',
  approved: 'bg-emerald-900 text-emerald-200',
  rejected: 'bg-red-900 text-red-200',
  consumed: 'bg-slate-700 text-slate-400',
};

export default function DeviationBanner({ changeId, blockedTo, blockedReason, onRetry, onClose }: Props) {
  const qc = useQueryClient();
  const [dialogOpen, setDialogOpen] = useState(false);

  const { data: deviations = [] } = useQuery({
    queryKey: ['change', changeId, 'deviations'],
    queryFn: () => changesApi.listDeviations(changeId),
  });
  const propose = useMutation({
    mutationFn: (reason: string) =>
      changesApi.proposeDeviation(changeId, { to_status: blockedTo, reason }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['change', changeId, 'deviations'] }),
  });
  const decide = useMutation({
    mutationFn: (vars: { devId: number; decision: 'approved' | 'rejected' }) =>
      changesApi.decideDeviation(changeId, vars.devId, { decision: vars.decision }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['change', changeId, 'deviations'] }),
    onError: (e: Error & { response?: { data?: { detail?: string } } }) =>
      toast.error(e.response?.data?.detail ?? 'Decision failed'),
  });

  const relevant = deviations.filter((d) => d.to_status === blockedTo);
  const hasApproved = relevant.some((d) => d.status === 'approved');
  const hasPending = relevant.some((d) => d.status === 'pending');

  return (
    <div className="border border-amber-700 bg-amber-900/30 rounded-xl p-4 my-3 text-sm" data-testid="deviation-banner">
      <div className="flex items-start justify-between gap-4">
        <div>
          <p className="font-medium text-amber-200">Transition blocked</p>
          <p className="text-amber-200 mt-0.5">{blockedReason}</p>
        </div>
        <button className="text-amber-200 text-xs" onClick={onClose}>Dismiss</button>
      </div>

      {relevant.length > 0 && (
        <ul className="mt-3 space-y-1">
          {relevant.map((d) => (
            <li key={d.id} className="flex items-center gap-2">
              <span className={`px-2 py-0.5 rounded-full text-xs ${STATUS_STYLE[d.status]}`}>{d.status}</span>
              <span className="text-slate-400">{d.reason}</span>
              {d.status === 'pending' && (
                <span className="ml-auto flex gap-1">
                  <button className="px-2 py-0.5 text-xs border border-emerald-700 text-emerald-200 rounded-lg hover:bg-emerald-900/30"
                          onClick={() => decide.mutate({ devId: d.id, decision: 'approved' })}>Approve</button>
                  <button className="px-2 py-0.5 text-xs border border-red-700 text-red-200 rounded-lg hover:bg-red-900/30"
                          onClick={() => decide.mutate({ devId: d.id, decision: 'rejected' })}>Reject</button>
                </span>
              )}
            </li>
          ))}
        </ul>
      )}

      <div className="flex gap-2 mt-3">
        {!hasPending && !hasApproved && (
          <button className="px-3 py-1.5 rounded-lg bg-amber-600 hover:bg-amber-500 text-white text-xs"
                  onClick={() => setDialogOpen(true)}>Request deviation</button>
        )}
        {hasApproved && (
          <button className="px-3 py-1.5 rounded-lg bg-sky-600 hover:bg-sky-500 text-white text-xs"
                  onClick={onRetry}>Retry transition</button>
        )}
      </div>

      <ReasonDialog
        open={dialogOpen}
        title={`Deviation for transition to "${blockedTo}"`}
        label="Reason (recorded in the audit trail, requires 4-eyes approval)"
        submitLabel="Submit"
        onSubmit={(reason) => { propose.mutate(reason); setDialogOpen(false); }}
        onClose={() => setDialogOpen(false)}
      />
    </div>
  );
}
