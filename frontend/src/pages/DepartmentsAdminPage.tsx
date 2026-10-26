/**
 * Departments page (Christoph 2026-10-26). Read by everyone; only a real
 * admin sees edit controls (the API refuses others with 403).
 *
 * Membership comes from AdminPanel (migration 150: the department's hub
 * role on a person's token), so members are listed read-only with name and
 * email. The admin sets the one optional manager (migration 149, for the
 * escalation overview: the overdue digest and My Tasks' "Late in my
 * departments") from the department's own members, and activates or
 * retires a department. Warnings for everyone: no manager, manager inactive
 * or no longer a member, an inactive member, no members, no hub role.
 */
import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import { AlertTriangle, Building2 } from 'lucide-react';
import { useAuth } from '../contexts/AuthContext';
import { departmentsAdminApi } from '../api/workflows';
import type { DepartmentAdmin } from '../types/workflow';
import { toastError } from '../lib/apiError';
import { btnSm } from '../components/common/buttonStyles';
import { LoadingSkeleton } from '../components/common/LoadingSkeleton';
import ConfirmDialog from '../components/common/ConfirmDialog';
import PersonDetail from '../components/common/PersonDetail';
import { t } from '../i18n/cmLabels';

const KEY = ['departments', 'overview'];

export default function DepartmentsAdminPage() {
  const { role } = useAuth();
  const isAdmin = role === 'admin';
  const qc = useQueryClient();
  const { data: depts, isLoading } = useQuery({ queryKey: KEY, queryFn: departmentsAdminApi.list });
  const [showRetired, setShowRetired] = useState(false);
  const [retire, setRetire] = useState<DepartmentAdmin | null>(null);

  const onSaved = (row: DepartmentAdmin) => {
    qc.setQueryData<DepartmentAdmin[]>(KEY, (old) => old?.map((d) => (d.id === row.id ? row : d)));
    // pickers and My Tasks read the departments list (manager, is_active)
    qc.invalidateQueries({ queryKey: ['workflow', 'departments'] });
  };
  const onError = (e: unknown) => toastError(e, t('deptAdmin.saveFailed'));
  const manager = useMutation({
    mutationFn: ({ id, userId }: { id: number; userId: number | null }) =>
      departmentsAdminApi.setManager(id, userId),
    onSuccess: (row) => { onSaved(row); toast.success(t('deptAdmin.saved')); },
    onError,
  });
  const active = useMutation({
    mutationFn: ({ id, on }: { id: number; on: boolean }) =>
      (on ? departmentsAdminApi.activate(id) : departmentsAdminApi.deactivate(id)),
    onSuccess: (row) => {
      onSaved(row);
      toast.success(t(row.is_active ? 'deptAdmin.activated' : 'deptAdmin.deactivated').replace('{x}', row.name));
    },
    onError,
  });

  const live = (depts ?? []).filter((d) => d.is_active);
  const retired = (depts ?? []).filter((d) => !d.is_active);

  return (
    <div className="p-6 space-y-6 max-w-5xl">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-slate-100">{t('deptAdmin.title')}</h1>
        <p className="text-slate-400 text-sm mt-1">{t('deptAdmin.subtitle')}</p>
      </div>
      {isLoading ? <LoadingSkeleton count={4} /> : (
        <div className="grid gap-4 md:grid-cols-2">
          {live.map((d) => (
            <DepartmentCard key={d.id} dept={d} isAdmin={isAdmin} busy={manager.isPending || active.isPending}
              onManager={(userId) => manager.mutate({ id: d.id, userId })}
              onRetire={() => setRetire(d)} />
          ))}
        </div>
      )}
      {retired.length > 0 && (
        <section data-testid="retired-departments">
          <button type="button" aria-expanded={showRetired} onClick={() => setShowRetired((v) => !v)}
            className="text-sm font-semibold uppercase tracking-wide text-slate-400 hover:text-slate-200">
            {showRetired ? '▾' : '▸'} {t('deptAdmin.retired').replace('{n}', String(retired.length))}
          </button>
          {showRetired && (
            <ul className="mt-2 divide-y divide-slate-700 rounded-lg border border-slate-700 bg-slate-800">
              {retired.map((d) => (
                <li key={d.id} data-testid={`retired-${d.id}`} className="flex items-center justify-between gap-3 px-4 py-2">
                  <span className="text-slate-300">{d.name}</span>
                  {isAdmin && (
                    <button type="button" className={btnSm.secondary} disabled={active.isPending}
                      onClick={() => active.mutate({ id: d.id, on: true })}>
                      {t('deptAdmin.activate')}
                    </button>
                  )}
                </li>
              ))}
            </ul>
          )}
        </section>
      )}
      <ConfirmDialog open={retire !== null} danger data-testid="dept-retire-confirm"
        title={t('deptAdmin.retireTitle').replace('{x}', retire?.name ?? '')}
        body={t('deptAdmin.retireBody')}
        confirmLabel={t('deptAdmin.retire')} cancelLabel={t('deptAdmin.cancel')}
        onConfirm={() => { if (retire) active.mutate({ id: retire.id, on: false }); setRetire(null); }}
        onClose={() => setRetire(null)} />
    </div>
  );
}

function DepartmentCard({ dept, isAdmin, busy, onManager, onRetire }: {
  dept: DepartmentAdmin;
  isAdmin: boolean;
  busy: boolean;
  onManager(userId: number | null): void;
  onRetire(): void;
}) {
  const selectId = `dept-manager-${dept.id}`;
  const candidates = dept.members.filter((m) => m.is_active);
  const red = dept.warnings.some((w) => w.level === 'red');
  return (
    <section data-testid={`dept-card-${dept.id}`}
      className={`rounded-lg border bg-slate-800 p-4 space-y-4 ${red ? 'border-red-800' : 'border-slate-700'}`}>
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <h2 className="flex items-center gap-2 text-base font-semibold text-slate-100">
            <Building2 aria-hidden="true" size={16} className="text-slate-400" />{dept.name}
          </h2>
          <p className="text-xs text-slate-500">{dept.hub_role ?? t('deptAdmin.noHubRole')}</p>
        </div>
        {isAdmin && (
          <button type="button" className={btnSm.ghost} disabled={busy} onClick={onRetire}
            data-testid={`dept-retire-${dept.id}`}>
            {t('deptAdmin.retire')}
          </button>
        )}
      </div>

      {dept.warnings.length > 0 && (
        <ul data-testid={`dept-warnings-${dept.id}`} className="space-y-1">
          {dept.warnings.map((w) => (
            <li key={w.code + w.text} data-code={w.code}
              className={`flex items-start gap-1.5 text-xs ${w.level === 'red' ? 'text-red-300' : 'text-amber-300'}`}>
              <AlertTriangle aria-hidden="true" size={13} className="mt-px flex-shrink-0" />{w.text}
            </li>
          ))}
        </ul>
      )}

      <div>
        {isAdmin ? (
          <>
            <label htmlFor={selectId} className="block text-[11px] uppercase tracking-wide text-slate-400 mb-1">
              {t('deptAdmin.manager')}
            </label>
            <div className="flex items-center gap-2">
              <select id={selectId} data-testid={selectId} disabled={busy}
                value={dept.manager_id ?? ''}
                onChange={(e) => onManager(e.target.value ? Number(e.target.value) : null)}
                className="h-8 min-w-0 flex-1 rounded-md border border-slate-600 bg-slate-900 px-2 text-sm text-slate-100 focus:border-sky-500 focus:outline-none">
                <option value="">{t('deptAdmin.noManager')}</option>
                {/* a manager who left stays visible (and warned) until replaced */}
                {dept.manager_id != null && !candidates.some((m) => m.id === dept.manager_id) && (
                  <option value={dept.manager_id}>{dept.manager_name} ({t('deptAdmin.notMemberAny')})</option>
                )}
                {candidates.map((m) => <option key={m.id} value={m.id}>{m.name}</option>)}
              </select>
              {dept.manager_id != null && (
                <button type="button" data-testid={`dept-manager-clear-${dept.id}`} disabled={busy}
                  onClick={() => onManager(null)} className={btnSm.ghost}>
                  {t('deptAdmin.clear')}
                </button>
              )}
            </div>
          </>
        ) : (
          <p data-testid={`dept-manager-ro-${dept.id}`} className="text-sm">
            <span className="block text-[11px] uppercase tracking-wide text-slate-400">{t('deptAdmin.manager')}</span>
            <span className="text-slate-100">{dept.manager_name ?? <span className="text-slate-500">{t('deptAdmin.noManager')}</span>}</span>
          </p>
        )}
      </div>

      <div>
        <p className="text-[11px] uppercase tracking-wide text-slate-400 mb-1">
          {t('deptAdmin.members')} ({dept.members.length})
          <span className="ml-2 normal-case tracking-normal text-slate-500">{t('deptAdmin.fromHub')}</span>
        </p>
        {dept.members.length === 0 ? (
          <p className="text-sm text-slate-500">{t('deptAdmin.noMembers')}</p>
        ) : (
          <ul className="flex flex-wrap gap-2">
            {dept.members.map((m) => (
              <li key={m.id} className="max-w-full">
                <PersonDetail data-testid={`dept-member-${dept.id}-${m.id}`} name={m.name} email={m.email}
                  inactive={!m.is_active}
                  badge={m.id === dept.manager_id ? (
                    <span className="rounded px-1.5 py-px text-[10px] font-semibold uppercase tracking-wide ring-1 bg-sky-900/60 text-sky-200 ring-sky-700">
                      {t('deptAdmin.manager')}
                    </span>
                  ) : undefined} />
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}
