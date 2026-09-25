/**
 * The project team (spec 2026-09-25): one responsible (main owner) per
 * department. Everyone else active in the department is a backup -- still
 * able to act, just not "theirs" for counting. The picker for a role is
 * limited to that department's own members; PM members and admins may set
 * or clear it (server-enforced: a refusal surfaces as a toast here, the
 * same graceful pattern as the lead picker).
 */
import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import client from '../../api/client';
import { apiErrorMessage } from '../../lib/apiError';
import { t } from '../../i18n/cmLabels';

interface TeamMember {
  id: number;
  name: string;
  role: 'main' | 'backup';
}

interface TeamRow {
  department_id: number;
  department_name: string;
  responsible: { id: number; name: string } | null;
  members: TeamMember[];
}

export function ProjectTeamCard({ projectId }: { projectId: number }) {
  const qc = useQueryClient();
  const [editing, setEditing] = useState<number | null>(null);
  const { data: team = [], isLoading } = useQuery<TeamRow[]>({
    queryKey: ['project-team', projectId],
    queryFn: async () => (await client.get(`/v1/projects/${projectId}/team`)).data,
  });
  const set = useMutation({
    mutationFn: async ({ department_id, user_id }: { department_id: number; user_id: number | null }) =>
      (await client.put(`/v1/projects/${projectId}/team`, { department_id, user_id })).data,
    onSuccess: () => {
      toast.success(t('team.saved'));
      setEditing(null);
      qc.invalidateQueries({ queryKey: ['project-team', projectId] });
    },
    onError: (e: unknown) => toast.error(apiErrorMessage(e, t('team.saveFailed'))),
  });

  if (isLoading) return null;

  return (
    <div data-testid="project-team-card">
      <p className="text-[11px] uppercase tracking-wide text-slate-500 mb-1">{t('team.title')}</p>
      <ul className="space-y-1">
        {team.map((row) => (
          <li key={row.department_id} className="flex items-center gap-2 text-sm" data-testid={`team-row-${row.department_id}`}>
            <span className="w-36 flex-shrink-0 text-slate-400 truncate">{row.department_name}</span>
            {editing === row.department_id ? (
              <select
                autoFocus
                aria-label={`${t('team.pick')}: ${row.department_name}`}
                data-testid={`team-select-${row.department_id}`}
                disabled={set.isPending}
                defaultValue={row.responsible?.id ?? ''}
                onBlur={() => { if (!set.isPending) setEditing(null); }}
                onChange={(e) => {
                  const v = e.target.value;
                  set.mutate({ department_id: row.department_id, user_id: v ? Number(v) : null });
                }}
                className="flex-1 rounded border border-slate-600 bg-slate-900 px-2 py-0.5 text-xs text-slate-100"
              >
                <option value="">{t('team.unassigned')}</option>
                {row.members.map((m) => (
                  <option key={m.id} value={m.id}>{m.name}</option>
                ))}
              </select>
            ) : (
              <>
                <span className="flex-1 truncate text-slate-200">
                  {row.responsible ? row.responsible.name : (
                    <span className="text-slate-500">{t('team.unassigned')}</span>
                  )}
                </span>
                <button type="button" data-testid={`team-edit-${row.department_id}`}
                  onClick={() => setEditing(row.department_id)}
                  className="flex-shrink-0 text-xs text-sky-300 hover:text-sky-200 underline decoration-dotted underline-offset-2">
                  {t('team.change')}
                </button>
              </>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}

export default ProjectTeamCard;
