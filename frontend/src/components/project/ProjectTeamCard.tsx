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
import PersonDetail from '../common/PersonDetail';

interface TeamMember {
  id: number;
  name: string;
  email?: string | null;
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

/**
 * detailed (2026-10-26, the Team dialog): per department a block with the
 * responsible and the backup (same pickers and rules) and every member with
 * name, email and a lead / backup / member badge. Without it: the compact
 * card (kept for its tests and any narrow place).
 */
export function ProjectTeamCard({ projectId, detailed = false }: { projectId: number; detailed?: boolean }) {
  const qc = useQueryClient();
  const perms = useChangePermissions();
  const canManage = perms?.can_manage_team === true;
  const [editing, setEditing] = useState<{ dept: number; slot: Slot } | null>(null);
  const { data: team = [], isLoading } = useQuery<TeamRow[]>({
    queryKey: ['project-team', projectId],
    queryFn: async () => (await client.get(`/v1/projects/${projectId}/team`)).data,
  });
  const set = useMutation({
    mutationFn: async ({ department_id, user_id, slot }: { department_id: number; user_id: number | null; slot: Slot; swapNote?: string }) =>
      (await client.put(`/v1/projects/${projectId}/team`, { department_id, user_id, slot })).data,
    onSuccess: (_data, vars) => {
      // a swap says so: nobody loses the responsible without a word
      toast.success(vars.swapNote ?? t('team.saved'));
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
          const picked = v ? Number(v) : null;
          const swap = slot === 'responsible' && picked !== null && picked === row.backup?.id
            && row.responsible && row.responsible.id !== picked;
          set.mutate({
            department_id: row.department_id, user_id: picked, slot,
            swapNote: swap
              ? t('team.swapped').replace('{x}', row.backup!.name).replace('{y}', row.responsible!.name)
              : undefined,
          });
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

  if (detailed) {
    const badge = (row: TeamRow, m: TeamMember) => {
      const kind = m.id === row.responsible?.id ? 'lead' : m.id === row.backup?.id ? 'backup' : 'member';
      const cls = kind === 'lead' ? 'bg-sky-900/60 text-sky-200 ring-sky-700'
        : kind === 'backup' ? 'bg-amber-900/40 text-amber-200 ring-amber-700/60'
          : 'bg-slate-800 text-slate-400 ring-slate-600';
      return (
        <span data-testid={`team-badge-${row.department_id}-${m.id}`} data-kind={kind}
          className={`rounded px-1.5 py-px text-[10px] font-semibold uppercase tracking-wide ring-1 ${cls}`}>
          {t(`team.badge.${kind}`)}
        </span>
      );
    };
    const slotLine = (row: TeamRow, slot: Slot) => {
      const isEditing = editing?.dept === row.department_id && editing.slot === slot;
      const who = slot === 'backup' ? row.backup : row.responsible;
      return (
        <div className="flex items-center gap-2"
          data-testid={slot === 'backup' ? `team-backup-${row.department_id}` : `team-responsible-${row.department_id}`}>
          <span className="w-28 flex-shrink-0 text-xs uppercase tracking-wide text-slate-500">
            {t(slot === 'backup' ? 'team.backup' : 'team.responsible')}
          </span>
          {isEditing ? picker(row, slot) : (
            <>
              <span className="min-w-0 flex-1 truncate text-slate-100">
                {who ? who.name : <span className="text-slate-500">{t('team.unassigned')}</span>}
              </span>
              {changeButton(row, slot)}
            </>
          )}
        </div>
      );
    };
    // the people's order: lead, backup, then the rest by name
    const order = (row: TeamRow) => [...row.members].sort((a, b) => {
      const rank = (m: TeamMember) => (m.id === row.responsible?.id ? 0 : m.id === row.backup?.id ? 1 : 2);
      return rank(a) - rank(b) || a.name.localeCompare(b.name);
    });
    return (
      <div data-testid="project-team-detailed" className="space-y-3">
        {team.map((row) => (
          <section key={row.department_id} data-testid={`team-row-${row.department_id}`}
            className="rounded-lg border border-slate-700 bg-slate-900/40 p-3 space-y-2">
            <h3 className="text-sm font-semibold text-slate-100">{row.department_name}</h3>
            {slotLine(row, 'responsible')}
            {slotLine(row, 'backup')}
            {row.department_name === PM_DEPARTMENT && (
              <p className="text-xs text-slate-500" data-testid="team-lead-pm-hint">{t('team.leadPmHint')}</p>
            )}
            {row.members.length === 0 ? (
              <p className="text-xs text-slate-500">{t('team.noMembers')}</p>
            ) : (
              <ul aria-label={`${t('team.membersOf')}: ${row.department_name}`} className="flex flex-wrap gap-2 pt-1">
                {order(row).map((m) => (
                  <li key={m.id} className="max-w-full">
                    <PersonDetail data-testid={`team-member-${row.department_id}-${m.id}`}
                      name={m.name} email={m.email} badge={badge(row, m)} />
                  </li>
                ))}
              </ul>
            )}
          </section>
        ))}
        <p className="text-xs text-slate-500" data-testid="team-routing-hint">{t('team.routingHint')}</p>
      </div>
    );
  }

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
