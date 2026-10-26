/**
 * My Tasks' "Late in my departments" (migration 149, Christoph 2026-10-26):
 * for a department manager, every escalated item of the departments they
 * manage across all changes (the overdue digest's own late items), one row
 * each. View only: managing grants no write rights, the row links to the
 * change. Renders nothing for anyone who manages no department.
 */
import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { AlarmClock } from 'lucide-react';
import { getMyDepartmentEscalations } from '../api/workflows';
import { formatCalendarDate } from '../lib/format';
import { t } from '../i18n/cmLabels';

export default function LateInMyDepartments() {
  const { data } = useQuery({
    queryKey: ['my-department-escalations'],
    queryFn: getMyDepartmentEscalations,
    refetchInterval: 60_000,
  });
  if (!data?.departments?.length || !Array.isArray(data.items)) return null;
  const names = data.departments.map((d) => d.name).join(', ');
  const th = 'text-left px-4 py-3 text-slate-400 font-medium';
  return (
    <section data-testid="late-in-my-departments">
      <h2 className="mb-1 flex items-center gap-2 text-sm font-semibold uppercase tracking-wide text-red-300">
        <AlarmClock aria-hidden="true" size={14} />
        {t('tasks.lateInMyDepts')} ({data.items.length})
      </h2>
      <p className="mb-2 text-xs text-slate-400">{t('tasks.lateInMyDeptsHint').replace('{x}', names)}</p>
      {data.items.length === 0 ? (
        <p data-testid="late-in-my-departments-empty"
          className="rounded-lg border border-slate-700 bg-slate-800 px-4 py-3 text-sm text-slate-400">
          {t('tasks.lateInMyDeptsEmpty')}
        </p>
      ) : (
        <div className="bg-slate-800 border border-red-900/60 rounded-lg overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-700 bg-slate-900">
                <th className={th}>{t('tasks.what')}</th>
                <th className={th}>{t('tasks.department')}</th>
                <th className={th}>{t('tasks.task')}</th>
                <th className={th}>{t('tasks.owner')}</th>
                <th className={th}>{t('tasks.due')}</th>
              </tr>
            </thead>
            <tbody>
              {data.items.map((r, i) => (
                <tr key={`${r.kind}-${r.change_id}-${r.department_id}-${i}`} data-testid="late-dept-row"
                  className="border-b border-slate-700 last:border-0 hover:bg-slate-700/30">
                  <td className="px-4 py-3 align-top">
                    <Link to={`/changes/${r.change_id}`} className="font-mono text-sky-400 hover:text-sky-300 whitespace-nowrap">
                      {r.change_number}
                    </Link>
                    <span className="block text-slate-200">{r.change_title}</span>
                  </td>
                  <td className="px-4 py-3 align-top text-slate-300">{r.department_name}</td>
                  <td className="px-4 py-3 align-top text-slate-200">{r.label}</td>
                  <td className="px-4 py-3 align-top text-slate-300">{r.owner_name ?? '-'}</td>
                  <td className="px-4 py-3 align-top text-xs whitespace-nowrap">
                    <span className="block text-slate-300">{r.due_date ? formatCalendarDate(r.due_date) : '-'}</span>
                    <span className="block font-semibold text-red-400">
                      {t('tasks.daysLate').replace('{n}', String(r.days_overdue))}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
