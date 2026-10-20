/**
 * The project team (spec 2026-09-25): one responsible (main owner) per
 * department, and (D2b, Christoph 2026-10-19) a named backup. The
 * department's tasks go to the responsible; to the backup when the
 * responsible is inactive or not set, and to the backup too once a task is
 * overdue; to the whole department only when neither is named. The Project
 * Manager responsible is the project's lead PM: they lead every change on
 * the project by default (D2). The picker for a role is limited to that
 * department's own members; PM members and admins set or clear it
 * (server-enforced; R24: nobody else sees the change buttons).
 */
import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import client from '../../api/client';
import { toastError } from '../../lib/apiError';
import { btnSm } from '../common/buttonStyles';
import { t } from '../../i18n/cmLabels';
import { useChangePermissions } from '../../hooks/queries/useCanStartChange';

interface TeamMember {
  id: number;
  name: string;
  role: 'main' | 'backup';
  named_backup?: boolean;
}

interface TeamRow {
  department_id: number;
  department_name: string;
  responsible: { id: number; name: string } | null;
  backup?: { id: number; name: string } | null;
  members: TeamMember[];
}

type Slot = 'responsible' | 'backup';

const PM_DEPARTMENT = 'Project Manager';

const selectCls = 'h-7 min-w-0 flex-1 rounded-md border border-slate-600 bg-slate-900 px-2 text-xs text-slate-100 focus:border-sky-500 focus:outline-none';

export function ProjectTeamCard({ projectId }: { projectId: number }) {
  const qc = useQueryClient();
  const perms = useChangePermissions();
  const canManage = perms?.can_manage_team === true;
  const [editing, setEditing] = useState<{ dept: number; slot: Slot } | null>(null);
  const { data: team = [], isLoading } = useQuery<TeamRow[]>({
    queryKey: ['project-team', projectId],
    queryFn: async () => (await client.get(`/v1/projects/${projectId}/team`)).data,
  });
  const set = useMutation({
    mutationFn: async ({ department_id, user_id, slot }: { department_id: number; user_id: number | null; slot: Slot }) =>
      (await client.put(`/v1/projects/${projectId}/team`, { department_id, user_id, slot })).data,
    onSuccess: () => {
      toast.success(t('team.saved'));
      setEditing(null);
      qc.invalidateQueries({ queryKey: ['project-team', projectId] });
    },
    onError: (e: unknown) => { toastError(e, t('team.saveFailed')); },
  });

  if (isLoading) return null;

  const picker = (row: TeamRow, slot: Slot) => {
    const current = slot === 'backup' ? row.backup : row.responsible;
    // the responsible is never their own backup; the backup picked as
    // responsible swaps the two in one step (the backend does the swap)
    const other = slot === 'backup' ? row.responsible?.id : undefined;
    const testid = slot === 'backup' ? `team-backup-select-${row.department_id}` : `team-select-${row.department_id}`;
    return (
      <select
        autoFocus
        aria-label={`${t(slot === 'backup' ? 'team.pickBackup' : 'team.pick')}: ${row.department_name}`}
        data-testid={testid}
        disabled={set.isPending}
        defaultValue={current?.id ?? ''}
        onBlur={() => { if (!set.isPending) setEditing(null); }}
        onChange={(e) => {
          const v = e.target.value;
          set.mutate({ department_id: row.department_id, user_id: v ? Number(v) : null, slot });
        }}
        className={selectCls}
      >
        <option value="">{t('team.unassigned')}</option>
        {row.members.filter((m) => m.id !== other).map((m) => (
          <option key={m.id} value={m.id}>
            {slot === 'responsible' && m.id === row.backup?.id
              ? `${m.name} (${t('team.swapWithBackup')})` : m.name}
          </option>
        ))}
      </select>
    );
  };

  const changeButton = (row: TeamRow, slot: Slot) => canManage && (
    <button type="button"
      data-testid={slot === 'backup' ? `team-backup-edit-${row.department_id}` : `team-edit-${row.department_id}`}
      onClick={() => setEditing({ dept: row.department_id, slot })}
      aria-label={`${t(slot === 'backup' ? 'team.changeBackup' : 'team.change')}: ${row.department_name}`}
      className={`${btnSm.ghost} flex-shrink-0 text-sky-300 hover:text-sky-200`}>
      {t('team.change')}
    </button>
  );

  return (
    <div data-testid="project-team-card">
      <h3 className="text-[11px] uppercase tracking-wide text-slate-400 mb-1">{t('team.title')}</h3>
      <ul className="space-y-1.5">
        {team.map((row) => {
          const isEditing = (slot: Slot) => editing?.dept === row.department_id && editing.slot === slot;
          return (
            <li key={row.department_id} className="text-sm" data-testid={`team-row-${row.department_id}`}>
              <div className="flex items-center gap-2">
                <span className="w-36 flex-shrink-0 text-slate-400 truncate">{row.department_name}</span>
                {isEditing('responsible') ? picker(row, 'responsible') : (
                  <>
                    <span className="min-w-0 flex-1 truncate text-slate-200">
                      {row.responsible ? row.responsible.name : (
                        <span className="text-slate-500">{t('team.unassigned')}</span>
                      )}
                    </span>
                    {changeButton(row, 'responsible')}
                  </>
                )}
              </div>
              <div className="flex items-center gap-2 pl-36 text-xs" data-testid={`team-backup-${row.department_id}`}>
                <span className="flex-shrink-0 text-slate-500">{t('team.backup')}:</span>
                {isEditing('backup') ? picker(row, 'backup') : (
                  <>
                    <span className="min-w-0 flex-1 truncate text-slate-300">
                      {row.backup ? row.backup.name : (
                        <span className="text-slate-500">{t('team.unassigned')}</span>
                      )}
                    </span>
                    {changeButton(row, 'backup')}
                  </>
                )}
              </div>
              {row.department_name === PM_DEPARTMENT && (
                <p className="pl-36 text-[11px] text-slate-500" data-testid="team-lead-pm-hint">{t('team.leadPmHint')}</p>
              )}
            </li>
          );
        })}
      </ul>
      <p className="mt-2 text-[11px] text-slate-500" data-testid="team-routing-hint">{t('team.routingHint')}</p>
    </div>
  );
}

export default ProjectTeamCard;
