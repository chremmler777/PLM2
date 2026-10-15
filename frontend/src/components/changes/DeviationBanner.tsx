import { useEffect, useRef, useState } from 'react';
import { toastError } from '../../lib/apiError';
import { btnSm } from '../common/buttonStyles';
import { transitionLabel } from '../../lib/changeStatus';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { changesApi } from '../../api/changes';
import OverrideDialog from './OverrideDialog';
import { t } from '../../i18n/cmLabels';
import { ruleText } from '../../lib/overrideRules';
import type { ChangeStatus } from '../../types/change';

interface Props {
  changeId: number;
  blockedTo: string;
  /** The change's current status: resuming, reopening and going back read
   * by where the change comes from (transitionLabel). */
  from?: string | null;
  blockedReason: string;
  /** C6: the soft rule that refused the move (X-Deviation-Rule); the
   * override asked here is bound to it. */
  rule?: string | null;
  customerRelevant?: boolean;
  leadName?: string | null;
  /** Bumped by the caller on every block report, even an identical one, so
   * the scroll-into-view effect below re-fires when the same transition is
   * blocked twice in a row. */
  seq: number;
  onRetry: () => void;
  onClose: () => void;
}

/** A soft rule's refusal says an approved override would lift it
 * (ChangeService.transition; older servers said "deviation"); a hard rule
 * never does, and no override lifts it. */
const isDeviable = (reason: string): boolean => /approved (override|deviation)\b[^.]*\bis required/i.test(reason);

const STATUS_STYLE: Record<string, string> = {
  pending: 'bg-amber-900 text-amber-200',
  approved: 'bg-emerald-900 text-emerald-200',
  rejected: 'bg-red-900 text-red-200',
  consumed: 'bg-slate-700 text-slate-400',
};

export default function DeviationBanner({ changeId, blockedTo, from, blockedReason, rule, customerRelevant = true, leadName, seq, onRetry, onClose }: Props) {
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
  // R4: a reject says why (the asker is told)
  const [rejecting, setRejecting] = useState<number | null>(null);
  const [rejectNote, setRejectNote] = useState('');
  const decide = useMutation({
    mutationFn: (vars: { devId: number; decision: 'approved' | 'rejected'; note?: string }) =>
      changesApi.decideDeviation(changeId, vars.devId, {
        decision: vars.decision, ...(vars.note ? { note: vars.note } : {}) }),
    onSuccess: () => {
      setRejecting(null); setRejectNote('');
      qc.invalidateQueries({ queryKey: ['change', changeId, 'deviations'] });
    },
    onError: (e: unknown) => toastError(e, 'Could not record the decision'),
  });

  // C6: an override covers its own rule only; rows asked before the
  // binding (no rule) still count for their target.
  const relevant = deviations.filter((d) => d.to_status === blockedTo
    && (!rule || !d.guard_key || d.guard_key === rule));
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
          <p className="font-medium text-amber-200">Transition blocked: {transitionLabel(blockedTo, from)}</p>
          <p className="text-amber-200 mt-0.5">{blockedReason}</p>
        </div>
        <button type="button" className={btnSm.ghost} onClick={onClose}>Dismiss</button>
      </div>

      {relevant.length > 0 && (
        <ul className="mt-3 space-y-1">
          {relevant.map((d) => (
            <li key={d.id} className="flex items-center gap-2">
              <span className={`px-2 py-0.5 rounded-full text-xs ${STATUS_STYLE[d.status]}`}>{d.status}</span>
              <span className="text-slate-400">
                {d.guard_key ? `${t('override.waives').replace('{rule}', ruleText(d.guard_key))}: ` : ''}{d.reason}
              </span>
              {/* lead or admin, never the proposer: the backend's verdict per row */}
              {d.status === 'pending' && d.can_decide && rejecting !== d.id && (
                <span className="ml-auto flex gap-1">
                  <button type="button" className={btnSm.secondary}
                          onClick={() => decide.mutate({ devId: d.id, decision: 'approved' })}>{t('override.approve')}</button>
                  <button type="button" className={`${btnSm.secondary} text-red-200`} data-testid={`banner-reject-${d.id}`}
                          onClick={() => setRejecting(d.id)}>{t('override.reject')}</button>
                </span>
              )}
              {d.status === 'pending' && d.can_decide && rejecting === d.id && (
                <span className="ml-auto flex min-w-0 gap-1">
                  <input aria-label={`Note on override #${d.id}`} placeholder={t('override.decideNote')}
                    data-testid={`banner-reject-note-${d.id}`} value={rejectNote}
                    onChange={(e) => setRejectNote(e.target.value)}
                    className="min-w-0 flex-1 rounded-lg border border-slate-600 bg-slate-900 px-2 py-1 text-xs text-slate-100 placeholder-slate-500" />
                  <button type="button" className={`${btnSm.secondary} text-red-200`} data-testid={`banner-reject-confirm-${d.id}`}
                          disabled={!rejectNote.trim() || decide.isPending}
                          onClick={() => decide.mutate({ devId: d.id, decision: 'rejected', note: rejectNote.trim() })}>{t('override.reject')}</button>
                </span>
              )}
            </li>
          ))}
        </ul>
      )}

      <div className="flex gap-2 mt-3">
        {deviable && !hasPending && !hasApproved && (
          <button type="button" className={btnSm.primary}
                  data-testid="deviation-banner-override"
                  onClick={() => setDialogOpen(true)}>{t('why.override')}</button>
        )}
        {deviable && hasApproved && (
          <button type="button" className={btnSm.primary}
                  onClick={onRetry}>Retry transition</button>
        )}
      </div>

      {dialogOpen && (
        <OverrideDialog changeId={changeId} to={blockedTo as ChangeStatus} rule={rule}
          customerRelevant={customerRelevant} leadName={leadName}
          onDone={() => qc.invalidateQueries({ queryKey: ['change', changeId, 'deviations'] })}
          onClose={() => setDialogOpen(false)} />
      )}
    </div>
  );
}
