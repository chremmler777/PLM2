/**
 * My Tasks' "LOP in my departments" (Christoph 2026-11-18: "he needs to see
 * all the tasks of his team as a manager"): for a department manager, every
 * open project LOP line of the departments they manage, whoever owns it,
 * late first. View only: managing grants no write rights, a row opens the
 * project's LOP. Renders nothing for anyone who manages no department.
 */
import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { Users } from 'lucide-react';
import { lopApi, lopOverviewKeys } from '../../api/lop';
import { dueLabel, STATUS_LABEL } from '../../lib/lop';
import { lopByUrgency } from '../../lib/myTasks';

export default function LopInMyDepartments() {
  const { data } = useQuery({
    queryKey: lopOverviewKeys.myDepartments,
    queryFn: lopApi.myDepartments,
    refetchInterval: 60_000,
  });
  if (!data?.departments?.length || !Array.isArray(data.lines)) return null;
  const names = data.departments.map((d) => d.name).join(', ');
  const lines = [...data.lines].sort(lopByUrgency);
  const late = lines.filter((l) => l.late).length;
  const th = 'text-left px-4 py-3 text-slate-400 font-medium';
  return (
    <section data-testid="lop-in-my-departments" aria-labelledby="lop-in-my-departments-heading">
      <h2 id="lop-in-my-departments-heading"
        className="mb-1 flex items-center gap-2 text-sm font-semibold uppercase tracking-wide text-slate-300">
        <Users aria-hidden="true" size={14} className="text-slate-400" />
        LOP in my departments ({lines.length})
        {late > 0 && <span data-testid="lop-dept-late-count" className="text-red-300 normal-case">{late} late</span>}
      </h2>
      <p className="mb-2 text-xs text-slate-400">
        As manager of {names}: every open LOP task of your team, whoever owns it. View only, a row opens the project LOP.
      </p>
      {lines.length === 0 ? (
        <p data-testid="lop-in-my-departments-empty"
          className="rounded-lg border border-slate-700 bg-slate-800 px-4 py-3 text-sm text-slate-400">
          No open LOP task in your departments.
        </p>
      ) : (
        <div className="bg-slate-800 border border-slate-700 rounded-lg overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-700 bg-slate-900">
                <th className={th}>Project</th>
                <th className={th}>Task</th>
                <th className={th}>Department</th>
                <th className={th}>Owner</th>
                <th className={th}>Due</th>
                <th className={th}>Status</th>
              </tr>
            </thead>
            <tbody>
              {lines.map((l) => (
                <tr key={l.id ?? `${l.project_code}-${l.ref_key}`} data-testid="lop-dept-row"
                  className="border-b border-slate-700 last:border-0 hover:bg-slate-700/30">
                  <td className="px-4 py-3 align-top whitespace-nowrap">
                    <Link to={`/projects/${l.project_id}/lop`}
                      className="text-sky-400 hover:text-sky-300 underline underline-offset-2 tabular-nums">
                      {l.project_code}
                    </Link>
                    {l.project_name && <span className="text-xs text-slate-500 ml-2">{l.project_name}</span>}
                  </td>
                  <td className="px-4 py-3 align-top text-slate-100">{l.text ?? l.title}</td>
                  <td className="px-4 py-3 align-top text-slate-300">{l.department_name ?? '-'}</td>
                  <td className="px-4 py-3 align-top text-slate-300">
                    {l.responsible_name ?? <span className="text-amber-300">nobody</span>}
                    {(l.additional_owners ?? []).length > 0 && (
                      <span className="block text-xs text-slate-500">
                        + {(l.additional_owners ?? []).map((o) => o.name).join(', ')}
                      </span>
                    )}
                  </td>
                  <td className={`px-4 py-3 align-top text-xs tabular-nums whitespace-nowrap ${l.late ? 'text-red-300 font-medium' : 'text-slate-400'}`}>
                    {dueLabel(l)}
                  </td>
                  <td className="px-4 py-3 align-top text-xs text-slate-300">{STATUS_LABEL[l.status] ?? l.status}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
