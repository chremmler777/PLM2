/**
 * The task card (spec §0 "Task links"): a My Tasks link opens the change with
 * the viewer's part on top: "Your part: Assess, due Thu (quote deadline Mon).
 * Next: <button>". The button goes where the work is done; "Ready: move it
 * on" makes the move itself, named like the Next step button ("Close
 * assessment"). On the tab where the work already is, the card names the
 * step instead of repeating that tab's own button. A first-use help line
 * explains it once and is dismissed for good (per browser).
 */
import { useEffect, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { X } from 'lucide-react';
import { changesApi } from '../../api/changes';
import { t } from '../../i18n/cmLabels';
import { formatDueDay } from '../../lib/format';
import { taskKindLabel } from '../../lib/humanLabels';
import { dueNote } from '../../lib/myTasks';
import { transitionLabel } from '../../lib/changeStatus';
import { btnSm } from '../common/buttonStyles';
import type { ChangeTask } from '../../types/change';

const HELP_KEY = 'plm2.taskCard.helpDismissed';

function helpDismissed(): boolean {
  try { return window.localStorage.getItem(HELP_KEY) === '1'; } catch { return false; }
}


interface Props {
  changeId: number;
  kind: string;
  departmentId?: number | null;
  /** Which override or sign-off side, when a change has two of the kind. */
  deviationId?: number | null;
  side?: 'pm' | 'quality' | null;
  /** The viewer's cockpit actions: the next step's label and tab. */
  actions: { kind: string; label: string; target_tab?: string | null; department_id?: number | null;
    deviation_id?: number | null; side?: string | null }[];
  onGo: (tab: string) => void;
  onClose: () => void;
  /** The tab on screen: there the card does not repeat the tab's button. */
  currentTab?: string;
  /** Runs an onward hop the way the Next step button does (confirm included). */
  onAdvance?: (to: string) => void;
}

export default function TaskCard({ changeId, kind, departmentId, deviationId, side, actions, onGo, onClose, currentTab, onAdvance }: Props) {
  const [help, setHelp] = useState(() => !helpDismissed());
  const { data: tasks, isLoading } = useQuery({
    queryKey: ['change-my-tasks'],
    queryFn: () => changesApi.myTasks(),
    staleTime: 30_000,
  });
  // The card must not outlive its task: whatever the viewer does on this change
  // (submit, finalize, close...) refreshes the change's queries; the list of my
  // tasks follows, so "Your part" turns into "done" at once, not after a reload.
  const qc = useQueryClient();
  useEffect(() => qc.getQueryCache().subscribe((ev) => {
    const key = ev.query.queryKey
    if (ev.type === 'updated' && ev.action.type === 'success'
      && key[0] === 'change' && key[1] === changeId) {
      void qc.invalidateQueries({ queryKey: ['change-my-tasks'] })
    }
  }), [qc, changeId]);
  // optional narrowing: a link names the department, the override or the side
  const fits = (x: { department_id?: number | null; deviation_id?: number | null; side?: string | null }) =>
    (departmentId == null || x.department_id == null || x.department_id === departmentId)
    && (deviationId == null || x.deviation_id == null || x.deviation_id === deviationId)
    && (side == null || x.side == null || x.side === side);
  const task = (tasks ?? []).find((x: ChangeTask) => x.change_id === changeId && x.kind === kind && fits(x));
  const action = actions.find((a) => (a.kind === kind || (kind === 'create_quote' && a.kind === 'offer_build'))
    && fits(a));
  if (isLoading) return null;
  const advanceTo = task?.kind === 'advance' && onAdvance ? task.to_status ?? null : null;
  const target = action?.target_tab ?? task?.target_tab ?? 'overview';
  const nextLabel = !task ? ''
    : advanceTo ? transitionLabel(advanceTo, task.status)
      : action?.label ?? taskKindLabel(task.kind, task.kind_label ?? task.label);

  const dismissHelp = () => {
    setHelp(false);
    try { window.localStorage.setItem(HELP_KEY, '1'); } catch { /* private window: show again next time */ }
  };

  return (
    <section data-testid="task-card" aria-label={t('taskcard.yourPart').replace('{x}', '')}
      className="rounded-lg border border-sky-700/60 bg-sky-950/40 px-4 py-3 text-sm">
      <div className="flex items-start gap-3">
        <div className="min-w-0 flex-1">
          {task ? (
            <p className="text-slate-100">
              <span className="font-semibold">
                {t('taskcard.yourPart').replace('{x}', taskKindLabel(task.kind, task.kind_label ?? task.label))}
              </span>
              {task.due_date && (
                <span data-testid="task-card-due" className={task.overdue ? 'text-red-300' : 'text-slate-300'}>
                  {', '}{t('taskcard.due').replace('{d}', formatDueDay(task.due_date))}
                  {dueNote(task) && ` ${dueNote(task)}`}
                </span>
              )}
              {task.late && <span className="ml-2 rounded bg-red-900/60 px-1.5 text-[11px] font-semibold text-red-200">{t('tasks.late')}</span>}
            </p>
          ) : (
            <p data-testid="task-card-done" className="text-slate-300">{t('taskcard.done')}</p>
          )}
          {task && (
            <div className="mt-2 flex flex-wrap items-center gap-2">
              <span className="text-slate-400">{t('taskcard.next')}</span>
              {!advanceTo && currentTab === target ? (
                <span data-testid="task-card-here" className="text-slate-200">
                  {t('taskcard.below').replace('{x}', nextLabel)}
                </span>
              ) : (
                <button type="button" data-testid="task-card-next" className={btnSm.primary}
                  onClick={() => (advanceTo ? onAdvance?.(advanceTo) : onGo(target))}>
                  {nextLabel}
                </button>
              )}
            </div>
          )}
          {help && (
            <p data-testid="task-card-help" className="mt-2 text-xs text-slate-400">
              {t('taskcard.help')}{' '}
              <button type="button" onClick={dismissHelp}
                className="text-sky-300 underline underline-offset-2 hover:text-sky-200">
                {t('taskcard.gotIt')}
              </button>
            </p>
          )}
        </div>
        <button type="button" onClick={onClose} aria-label={t('taskcard.close')}
          className="text-slate-400 hover:text-slate-200">
          <X size={16} aria-hidden="true" />
        </button>
      </div>
    </section>
  );
}
