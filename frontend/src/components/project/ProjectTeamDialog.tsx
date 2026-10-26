/**
 * The project team dialog (Christoph 2026-10-26), opened from the header's
 * Team button and the ⋯ menu.
 *
 * Left: the people of each department (name + email). Right: per department
 * a Responsible and a Backup slot. Drag a person onto a slot to set it; only
 * a member of that department may go there (an invalid drop says why). A
 * select per slot is the keyboard / click fallback. Same rules as before
 * (ProjectTeamCard): two different people per department, picking the
 * backup as responsible swaps the two; PM members and admins edit, everyone
 * else reads.
 *
 * Every edit changes a DRAFT: nothing is stored until Save (PUT
 * /projects/{id}/team/batch, all or nothing; the backend tells every newly
 * named person once, by notice and mail). Discard drops the draft; closing
 * with unsaved changes asks first.
 *
 * Red: an empty Responsible slot of a department that has members (the
 * project team is not defined there). An empty Backup is not red: the
 * members cover. The Project Manager row's responsible is the project's
 * overall responsible, the lead PM, shown on top.
 */
import { useEffect, useMemo, useState, type DragEvent } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import { X } from 'lucide-react';
import client from '../../api/client';
import Dialog from '../common/Dialog';
import ConfirmDialog from '../common/ConfirmDialog';
import Button from '../common/Button';
import PersonDetail from '../common/PersonDetail';
import { toastError } from '../../lib/apiError';
import { t } from '../../i18n/cmLabels';
import { useChangePermissions } from '../../hooks/queries/useCanStartChange';

export interface TeamMember { id: number; name: string; email?: string | null; role?: string; named_backup?: boolean }
export interface TeamRow {
  department_id: number;
  department_name: string;
  responsible: { id: number; name: string } | null;
  backup?: { id: number; name: string } | null;
  /** A slot pointing to someone inactive or no longer a member (reads empty). */
  responsible_missing?: { id: number; name: string } | null;
  backup_missing?: { id: number; name: string } | null;
  members: TeamMember[];
}
type Slot = 'responsible' | 'backup';
type Pair = { responsible: number | null; backup: number | null };
type Draft = Record<number, Pair>;

const PM_DEPARTMENT = 'Project Manager';
const DRAG_TYPE = 'application/x-plm-person';

export const teamQueryKey = (projectId: number) => ['project-team', projectId];

export function useProjectTeam(projectId: number) {
  return useQuery<TeamRow[]>({
    queryKey: teamQueryKey(projectId),
    queryFn: async () => (await client.get(`/v1/projects/${projectId}/team`)).data,
  });
}

/** Open Responsible slots: departments with members and nobody responsible. */
export function openSlots(team: TeamRow[] | undefined): number {
  return (team ?? []).filter((r) => r.members.length > 0 && !r.responsible).length;
}

const fromServer = (team: TeamRow[]): Draft =>
  Object.fromEntries(team.map((r) => [r.department_id,
    { responsible: r.responsible?.id ?? null, backup: r.backup?.id ?? null }]));

export default function ProjectTeamDialog({ projectId, projectLabel, open, onClose }: {
  projectId: number; projectLabel?: string; open: boolean; onClose(): void;
}) {
  if (!open) return null;
  return <TeamDialogBody projectId={projectId} projectLabel={projectLabel} onClose={onClose} />;
}

function TeamDialogBody({ projectId, projectLabel, onClose }: { projectId: number; projectLabel?: string; onClose(): void }) {
  const qc = useQueryClient();
  const perms = useChangePermissions();
  const canManage = perms?.can_manage_team === true;
  const { data: team } = useProjectTeam(projectId);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [dragging, setDragging] = useState<number | null>(null);
  // where a drag started when it came out of a slot (dropping back on the people list clears that slot)
  const [dragFrom, setDragFrom] = useState<{ dept: number; slot: Slot } | null>(null);
  const [askDiscard, setAskDiscard] = useState(false);

  useEffect(() => { if (team && draft === null) setDraft(fromServer(team)); }, [team, draft]);

  const server = useMemo(() => (team ? fromServer(team) : {}), [team]);
  const changed = (team ?? []).filter((r) => {
    const d = draft?.[r.department_id];
    const s = server[r.department_id];
    return d && s && (d.responsible !== s.responsible || d.backup !== s.backup);
  });
  const dirty = changed.length > 0;

  const save = useMutation({
    mutationFn: async () => (await client.put(`/v1/projects/${projectId}/team/batch`, {
      slots: changed.map((r) => ({ department_id: r.department_id,
        responsible_id: draft![r.department_id].responsible, backup_id: draft![r.department_id].backup })),
    })).data as TeamRow[],
    onSuccess: (rows) => {
      qc.setQueryData(teamQueryKey(projectId), rows);
      qc.invalidateQueries({ queryKey: ['project-team-gaps'] });
      setDraft(fromServer(rows));
      setErrors({});
      toast.success(t('team.saved'));
    },
    onError: (e: unknown) => { toastError(e, t('team.saveFailed')); },
  });

  const nameOf = (id: number | null) => {
    if (id == null) return null;
    for (const r of team ?? []) {
      const m = r.members.find((x) => x.id === id);
      if (m) return m.name;
    }
    return null;
  };

  /** Put a person into a slot of the draft; refused (with the reason) for a non-member. */
  const assign = (row: TeamRow, slot: Slot, userId: number | null) => {
    const key = `${row.department_id}-${slot}`;
    if (userId !== null && !row.members.some((m) => m.id === userId)) {
      setErrors((e) => ({ ...e, [key]: t('team.notMember')
        .replace('{x}', nameOf(userId) ?? '?').replace('{d}', row.department_name) }));
      return;
    }
    setErrors((e) => { const n = { ...e }; delete n[key]; return n; });
    setDraft((d) => {
      if (!d) return d;
      const cur = d[row.department_id] ?? { responsible: null, backup: null };
      let next: Pair;
      if (slot === 'responsible') {
        // the backup made responsible swaps the two (as the card does)
        next = { responsible: userId, backup: userId !== null && cur.backup === userId ? cur.responsible : cur.backup };
      } else {
        next = { backup: userId, responsible: userId !== null && cur.responsible === userId ? cur.backup : cur.responsible };
      }
      return { ...d, [row.department_id]: next };
    });
  };

  const requestClose = () => { if (dirty) setAskDiscard(true); else onClose(); };

  const pmRow = (team ?? []).find((r) => r.department_name === PM_DEPARTMENT);
  const pmId = pmRow ? draft?.[pmRow.department_id]?.responsible ?? null : null;

  const onDragStart = (e: DragEvent, userId: number, from: { dept: number; slot: Slot } | null = null) => {
    e.dataTransfer.setData(DRAG_TYPE, String(userId));
    e.dataTransfer.setData('text/plain', String(userId));
    e.dataTransfer.effectAllowed = 'move';
    setDragging(userId);
    setDragFrom(from);
  };
  const endDrag = () => { setDragging(null); setDragFrom(null); };
  const dropped = (e: DragEvent): number | null => {
    const raw = e.dataTransfer.getData(DRAG_TYPE) || e.dataTransfer.getData('text/plain');
    const n = Number(raw);
    return raw && Number.isFinite(n) ? n : null;
  };

  const slotBox = (row: TeamRow, slot: Slot) => {
    const value = draft?.[row.department_id]?.[slot] ?? null;
    const key = `${row.department_id}-${slot}`;
    const missing = slot === 'responsible' && value === null && row.members.length > 0;
    const orig = server[row.department_id]?.[slot] ?? null;
    const edited = value !== orig;
    const canDrop = dragging !== null && row.members.some((m) => m.id === dragging);
    const tone = dragging !== null
      ? (canDrop ? 'border-sky-500 bg-sky-950/40' : 'border-slate-700 opacity-60')
      : missing ? 'border-red-600 bg-red-950/30' : edited ? 'border-amber-600/70' : 'border-slate-700';
    const label = t(slot === 'responsible' ? 'team.responsible' : 'team.backup');
    return (
      <div
        data-testid={`team-slot-${slot}-${row.department_id}`}
        data-missing={missing ? 'true' : undefined}
        aria-label={`${label}: ${row.department_name}`}
        onDragOver={canManage ? (e) => { e.preventDefault(); e.dataTransfer.dropEffect = canDrop ? 'move' : 'none'; } : undefined}
        onDrop={canManage ? (e) => {
          e.preventDefault(); const id = dropped(e); endDrag();
          // from the row's other slot this moves the person (assign swaps the two)
          if (id !== null) assign(row, slot, id);
        } : undefined}
        className={`min-w-0 flex-1 rounded-lg border-2 border-dashed px-3 py-2 transition-colors ${tone}`}
      >
        <p className={`text-[11px] uppercase tracking-wide ${missing ? 'text-red-300' : 'text-slate-500'}`}>{label}</p>
        <div className="mt-0.5 flex items-center gap-2">
          <span className="min-w-0 flex-1 truncate text-sm font-medium text-slate-100"
            data-testid={value !== null ? `team-slot-person-${slot}-${row.department_id}` : undefined}
            draggable={canManage && value !== null}
            onDragStart={canManage && value !== null ? (e) => onDragStart(e, value, { dept: row.department_id, slot }) : undefined}
            onDragEnd={endDrag}
            style={canManage && value !== null ? { cursor: 'grab' } : undefined}>
            {value !== null ? nameOf(value) : (
              <span className={missing ? 'text-red-300' : 'text-slate-500'}>
                {missing ? t('team.notDefined') : t('team.unassigned')}
              </span>
            )}
          </span>
          {canManage && value !== null && (
            <button type="button" aria-label={`${t('team.clearSlot')}: ${label}, ${row.department_name}`}
              data-testid={`team-clear-${slot}-${row.department_id}`}
              onClick={() => assign(row, slot, null)}
              className="rounded p-0.5 text-slate-500 hover:bg-slate-700 hover:text-slate-200">
              <X aria-hidden="true" size={14} />
            </button>
          )}
        </div>
        {canManage && (
          // keyboard / click fallback for the drag and drop
          <select
            aria-label={`${t(slot === 'backup' ? 'team.pickBackup' : 'team.pick')}: ${row.department_name}`}
            data-testid={`team-pick-${slot}-${row.department_id}`}
            value={value ?? ''}
            onChange={(e) => assign(row, slot, e.target.value ? Number(e.target.value) : null)}
            className="mt-1 h-7 w-full rounded-md border border-slate-600 bg-slate-900 px-2 text-xs text-slate-100 focus:border-sky-500 focus:outline-none"
          >
            <option value="">{t('team.unassigned')}</option>
            {row.members.map((m) => <option key={m.id} value={m.id}>{m.name}</option>)}
          </select>
        )}
        {value === null && row[`${slot}_missing`] && (
          <p data-testid={`team-missing-${slot}-${row.department_id}`} className="mt-1 text-xs text-amber-300">
            {t('team.missingUser').replace('{x}', row[`${slot}_missing`]!.name)}
          </p>
        )}
        {errors[key] && (
          <p role="alert" data-testid={`team-drop-error-${slot}-${row.department_id}`}
            className="mt-1 text-xs text-red-300">{errors[key]}</p>
        )}
      </div>
    );
  };

  const badge = (row: TeamRow, m: TeamMember) => {
    const d = draft?.[row.department_id];
    const kind = m.id === d?.responsible ? 'lead' : m.id === d?.backup ? 'backup' : 'member';
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

  return (
    <>
      <Dialog open onClose={requestClose} size="xl" data-testid="project-team-dialog" busy={save.isPending}
        closeOnBackdrop={!dirty}
        title={projectLabel ? `${t('team.title')}: ${projectLabel}` : t('team.title')} description={t(canManage ? 'team.dialogHint' : 'team.dialogHintRead')}
        footer={canManage ? (
          <>
            {dirty && <span data-testid="team-unsaved" className="mr-auto text-xs text-amber-300">
              {t('team.unsaved').replace('{n}', String(changed.length))}</span>}
            <Button data-testid="team-discard" disabled={!dirty || save.isPending}
              onClick={() => { setDraft(team ? fromServer(team) : null); setErrors({}); }}>
              {t('team.discard')}
            </Button>
            <Button variant="primary" data-testid="team-save" disabled={!dirty} loading={save.isPending}
              onClick={() => save.mutate()}>
              {t('save')}
            </Button>
          </>
        ) : undefined}>
        {!team || !draft ? <p className="py-6 text-slate-400">{t('team.loading')}</p> : (
          <div className="space-y-4">
            {pmRow && (
              <div data-testid="team-project-responsible"
                className={`rounded-lg border px-3 py-2 ${pmId === null && pmRow.members.length > 0 ? 'border-red-600 bg-red-950/30' : 'border-slate-700 bg-slate-900/40'}`}>
                <p className="text-[11px] uppercase tracking-wide text-slate-400">{t('team.projectResponsible')}</p>
                <p className="text-base font-semibold text-slate-100">
                  {pmId !== null ? nameOf(pmId) : <span className="text-red-300">{t('team.notDefined')}</span>}
                </p>
                <p className="text-xs text-slate-500">{t('team.leadPmHint')}</p>
              </div>
            )}
            {team.map((row) => (
              <section key={row.department_id} data-testid={`team-row-${row.department_id}`}
                className="grid gap-3 rounded-lg border border-slate-700 bg-slate-900/40 p-3 md:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
                <div className="min-w-0">
                  <h3 className="mb-2 text-sm font-semibold text-slate-100">{row.department_name}</h3>
                  {row.members.length === 0 ? (
                    <p className="text-xs text-slate-500">{t('team.noMembers')}</p>
                  ) : (
                    <ul aria-label={`${t('team.membersOf')}: ${row.department_name}`}
                      data-testid={`team-people-${row.department_id}`}
                      // drop a person dragged out of this row's slot back here: the slot is cleared
                      onDragOver={canManage && dragFrom?.dept === row.department_id ? (e) => { e.preventDefault(); e.dataTransfer.dropEffect = 'move'; } : undefined}
                      onDrop={canManage ? (e) => {
                        e.preventDefault(); const from = dragFrom; endDrag();
                        if (from && from.dept === row.department_id) assign(row, from.slot, null);
                      } : undefined}
                      className={`flex flex-wrap gap-2 rounded-md p-1 transition-colors ${dragFrom?.dept === row.department_id ? 'bg-slate-800/80 ring-1 ring-dashed ring-slate-500' : ''}`}>
                      {row.members.map((m) => {
                        const d = draft[row.department_id];
                        const placed = m.id === d?.responsible || m.id === d?.backup;
                        return (
                        <li key={m.id} className={`max-w-full ${placed ? 'opacity-40' : ''}`}
                          data-placed={placed ? 'true' : undefined}
                          draggable={canManage && !placed}
                          onDragStart={canManage && !placed ? (e) => onDragStart(e, m.id) : undefined}
                          onDragEnd={endDrag}
                          style={canManage && !placed ? { cursor: 'grab' } : undefined}>
                          <PersonDetail data-testid={`team-member-${row.department_id}-${m.id}`}
                            name={m.name} email={m.email} badge={badge(row, m)} />
                        </li>
                        );
                      })}
                    </ul>
                  )}
                </div>
                <div className="flex min-w-0 flex-col gap-2 sm:flex-row">
                  {slotBox(row, 'responsible')}
                  {slotBox(row, 'backup')}
                </div>
              </section>
            ))}
            <p className="text-xs text-slate-500" data-testid="team-routing-hint">{t('team.routingHint')}</p>
          </div>
        )}
      </Dialog>
      <ConfirmDialog open={askDiscard} title={t('team.discardTitle')} body={t('team.discardBody')}
        confirmLabel={t('team.discard')} cancelLabel={t('team.keepEditing')} danger
        data-testid="team-discard-confirm"
        onConfirm={() => { setAskDiscard(false); onClose(); }} onClose={() => setAskDiscard(false)} />
    </>
  );
}
