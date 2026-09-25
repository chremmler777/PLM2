import { useEffect, useRef, useState } from 'react';
import { toastError } from '../../lib/apiError';
import { btnSm } from '../common/buttonStyles';
import { transitionLabel } from '../../lib/changeStatus';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { changesApi } from '../../api/changes';
import ReasonDialog from './ReasonDialog';

interface Props {
  changeId: number;
  blockedTo: string;
  /** The change's current status: resuming, reopening and going back read
   * by where the change comes from (transitionLabel). */
  from?: string | null;
  blockedReason: string;
  /** Bumped by the caller on every block report, even an identical one, so
   * the scroll-into-view effect below re-fires when the same transition is
   * blocked twice in a row. */
  seq: number;
  onRetry: () => void;
  onClose: () => void;
}

/** A soft guard's refusal ends in this sentence (ChangeService.transition);
 * a hard rule never does, and no deviation lifts it. */
const isDeviable = (reason: string): boolean => /approved deviation is required/i.test(reason);

const STATUS_STYLE: Record<string, string> = {
  pending: 'bg-amber-900 text-amber-200',
  approved: 'bg-emerald-900 text-emerald-200',
  rejected: 'bg-red-900 text-red-200',
  consumed: 'bg-slate-700 text-slate-400',
};

export default function DeviationBanner({ changeId, blockedTo, from, blockedReason, seq, onRetry, onClose }: Props) {
  const qc = useQueryClient();
  const [dialogOpen, setDialogOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);

  // The banner sits above the tabs while the button that raised the block
  // (e.g. Release at the bottom of the Release tab) can be far below: bring
  // it into view and move focus to it whenever a new block is reported.
  useEffect(() => {
    const el = rootRef.current;
    if (!el) return;
    el.scrollIntoView?.({ behavior: 'smooth', block: 'start' });
    el.focus({ preventScroll: true });
  }, [blockedTo, blockedReason, seq]);

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
    onError: (e: unknown) => toastError(e, 'Could not record the decision'),
  });

  const relevant = deviations.filter((d) => d.to_status === blockedTo);
  const hasApproved = relevant.some((d) => d.status === 'approved');
  const hasPending = relevant.some((d) => d.status === 'pending');
  // Only a soft guard can be deviated from: a hard rule gets no request button.
  const deviable = isDeviable(blockedReason);

  return (
    <div ref={rootRef} tabIndex={-1} role="alert" aria-label="Transition blocked"
         className="border border-amber-700 bg-amber-900/30 rounded-xl p-4 my-3 text-sm scroll-mt-4 focus:outline-none focus-visible:ring-2 focus-visible:ring-amber-500"
         data-testid="deviation-banner">
      <div className="flex items-start justify-between gap-4">
        <div>
          <p className="font-medium text-amber-200">Transition blocked</p>
          <p className="text-amber-200 mt-0.5">{blockedReason}</p>
        </div>
        <button type="button" className={btnSm.ghost} onClick={onClose}>Dismiss</button>
      </div>

      {relevant.length > 0 && (
        <ul className="mt-3 space-y-1">
          {relevant.map((d) => (
            <li key={d.id} className="flex items-center gap-2">
              <span className={`px-2 py-0.5 rounded-full text-xs ${STATUS_STYLE[d.status]}`}>{d.status}</span>
              <span className="text-slate-400">{d.reason}</span>
              {d.status === 'pending' && (
                <span className="ml-auto flex gap-1">
                  <button type="button" className={btnSm.secondary}
                          onClick={() => decide.mutate({ devId: d.id, decision: 'approved' })}>Approve</button>
                  <button type="button" className={`${btnSm.secondary} text-red-200`}
                          onClick={() => decide.mutate({ devId: d.id, decision: 'rejected' })}>Reject</button>
                </span>
              )}
            </li>
          ))}
        </ul>
      )}

      <div className="flex gap-2 mt-3">
        {deviable && !hasPending && !hasApproved && (
          <button type="button" className={btnSm.primary}
                  onClick={() => setDialogOpen(true)}>Request deviation</button>
        )}
        {deviable && hasApproved && (
          <button type="button" className={btnSm.primary}
                  onClick={onRetry}>Retry transition</button>
        )}
      </div>

      <ReasonDialog
        open={dialogOpen}
        title={`Deviation: ${transitionLabel(blockedTo, from)}`}
        label="Reason (recorded in the audit trail, requires 4-eyes approval)"
        submitLabel="Submit"
        onSubmit={(reason) => { propose.mutate(reason); setDialogOpen(false); }}
        onClose={() => setDialogOpen(false)}
      />
    </div>
  );
}
