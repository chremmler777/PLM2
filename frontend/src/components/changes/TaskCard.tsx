/**
 * The task card (spec §0 "Task links"): a My Tasks link opens the change with
 * the viewer's part on top: "Your part: Assess, due Thu (quote deadline Mon).
 * Next: <button>". The button goes where the work is done. A first-use help
 * line explains it once and is dismissed for good (per browser).
 */
import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { X } from 'lucide-react';
import { changesApi } from '../../api/changes';
import { t } from '../../i18n/cmLabels';
import { formatCalendarDateShort } from '../../lib/format';
import { taskKindLabel } from '../../lib/humanLabels';
import { dueNote } from '../../lib/myTasks';
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
  /** The viewer's cockpit actions: the next step's label and tab. */
  actions: { kind: string; label: string; target_tab?: string | null; department_id?: number | null }[];
  onGo: (tab: string) => void;
  onClose: () => void;
}

export default function TaskCard({ changeId, kind, departmentId, actions, onGo, onClose }: Props) {
  const [help, setHelp] = useState(() => !helpDismissed());
  const { data: tasks, isLoading } = useQuery({
    queryKey: ['change-my-tasks'],
    queryFn: () => changesApi.myTasks(),
    staleTime: 30_000,
  });
  const task = (tasks ?? []).find((x: ChangeTask) => x.change_id === changeId && x.kind === kind
    && (departmentId == null || x.department_id == null || x.department_id === departmentId));
  const action = actions.find((a) => (a.kind === kind || (kind === 'create_quote' && a.kind === 'offer_build'))
    && (departmentId == null || a.department_id == null || a.department_id === departmentId));
  if (isLoading) return null;

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
                  {', '}{t('taskcard.due').replace('{d}', formatCalendarDateShort(task.due_date))}
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
              <button type="button" data-testid="task-card-next" className={btnSm.primary}
                onClick={() => onGo(action?.target_tab ?? task.target_tab ?? 'overview')}>
                {action?.label ?? taskKindLabel(task.kind, task.kind_label ?? task.label)}
              </button>
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
