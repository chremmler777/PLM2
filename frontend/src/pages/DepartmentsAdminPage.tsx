/**
 * Departments admin page (Christoph 2026-10-26): per department its one
 * optional manager (migration 149, for the escalation overview: the overdue
 * digest and My Tasks' "Late in my departments") and its members (PLM had
 * no screen for memberships before). Admin only: no nav link for anyone
 * else, a no-access note here, and the API answers 403.
 *
 * The manager need not be a member and may manage several departments;
 * managing grants no write rights. Retired departments sit collapsed at the
 * bottom with Activate.
 */
import { useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import { Building2 } from 'lucide-react';
import { useAuth } from '../contexts/AuthContext';
import { departmentsAdminApi } from '../api/workflows';
import type { DepartmentAdmin } from '../types/workflow';
import { toastError } from '../lib/apiError';
import { btnSm } from '../components/common/buttonStyles';
import EmptyState from '../components/common/EmptyState';
import { LoadingSkeleton } from '../components/common/LoadingSkeleton';
import PersonDetail from '../components/common/PersonDetail';
import { t } from '../i18n/cmLabels';

const KEY = ['departments', 'admin'];

type Account = Awaited<ReturnType<typeof departmentsAdminApi.users>>[number];

const display = (u: Account) => u.full_name || u.username;

export default function DepartmentsAdminPage() {
  const { role } = useAuth();
  if (role !== 'admin') {
    return (
      <div className="p-6">
        <EmptyState data-testid="departments-no-access" title={t('deptAdmin.noAccess')}
          hint={t('deptAdmin.noAccessHint')} />
      </div>
    );
  }
  return <DepartmentsAdmin />;
}

function DepartmentsAdmin() {
  const qc = useQueryClient();
  const { data: depts, isLoading } = useQuery({ queryKey: KEY, queryFn: departmentsAdminApi.list });
  const { data: users = [] } = useQuery({ queryKey: ['users', 'all'], queryFn: departmentsAdminApi.users });
  const [showRetired, setShowRetired] = useState(false);
  const active = useMemo(() => users.filter((u) => u.is_active)
    .sort((a, b) => display(a).localeCompare(display(b))), [users]);

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
  const members = useMutation({
    mutationFn: ({ id, ids }: { id: number; ids: number[] }) => departmentsAdminApi.setMembers(id, ids),
    onSuccess: (row) => { onSaved(row); toast.success(t('deptAdmin.saved')); },
    onError,
  });
  const activate = useMutation({
    mutationFn: (id: number) => departmentsAdminApi.activate(id),
    onSuccess: (row) => { onSaved(row); toast.success(t('deptAdmin.activated').replace('{x}', row.name)); },
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
            <DepartmentCard key={d.id} dept={d} users={active}
              busy={manager.isPending || members.isPending}
              onManager={(userId) => manager.mutate({ id: d.id, userId })}
              onMembers={(ids) => members.mutate({ id: d.id, ids })} />
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
                  <button type="button" className={btnSm.secondary} disabled={activate.isPending}
                    onClick={() => activate.mutate(d.id)}>
                    {t('deptAdmin.activate')}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </section>
      )}
    </div>
  );
}

function DepartmentCard({ dept, users, busy, onManager, onMembers }: {
  dept: DepartmentAdmin;
  users: Account[];
  busy: boolean;
  onManager(userId: number | null): void;
  onMembers(ids: number[]): void;
}) {
  const [query, setQuery] = useState('');
  const memberIds = dept.members.map((m) => m.id);
  const q = query.trim().toLowerCase();
  const matches = q === '' ? [] : users.filter((u) => !memberIds.includes(u.id)
    && (display(u).toLowerCase().includes(q) || u.email.toLowerCase().includes(q)
      || u.username.toLowerCase().includes(q))).slice(0, 8);
  const selectId = `dept-manager-${dept.id}`;

  return (
    <section data-testid={`dept-card-${dept.id}`}
      className="rounded-lg border border-slate-700 bg-slate-800 p-4 space-y-4">
      <h2 className="flex items-center gap-2 text-base font-semibold text-slate-100">
        <Building2 aria-hidden="true" size={16} className="text-slate-400" />{dept.name}
      </h2>

      <div>
        <label htmlFor={selectId} className="block text-[11px] uppercase tracking-wide text-slate-400 mb-1">
          {t('deptAdmin.manager')}
        </label>
        <div className="flex items-center gap-2">
          <select id={selectId} data-testid={selectId} disabled={busy}
            value={dept.manager_id ?? ''}
            onChange={(e) => onManager(e.target.value ? Number(e.target.value) : null)}
            className="h-8 min-w-0 flex-1 rounded-md border border-slate-600 bg-slate-900 px-2 text-sm text-slate-100 focus:border-sky-500 focus:outline-none">
            <option value="">{t('deptAdmin.noManager')}</option>
            {/* a manager who left stays visible until replaced */}
            {dept.manager_id != null && !users.some((u) => u.id === dept.manager_id) && (
              <option value={dept.manager_id}>{dept.manager_name} ({t('deptAdmin.inactive')})</option>
            )}
            {users.map((u) => <option key={u.id} value={u.id}>{display(u)}</option>)}
          </select>
          {dept.manager_id != null && (
            <button type="button" data-testid={`dept-manager-clear-${dept.id}`} disabled={busy}
              onClick={() => onManager(null)} className={btnSm.ghost}>
              {t('deptAdmin.clear')}
            </button>
          )}
        </div>
      </div>

      <div>
        <p className="text-[11px] uppercase tracking-wide text-slate-400 mb-1">
          {t('deptAdmin.members')} ({dept.members.length})
        </p>
        {dept.members.length === 0 ? (
          <p className="text-sm text-slate-500">{t('deptAdmin.noMembers')}</p>
        ) : (
          <ul className="flex flex-wrap gap-2">
            {dept.members.map((m) => (
              <li key={m.id} className="max-w-full">
                <PersonDetail data-testid={`dept-member-${dept.id}-${m.id}`} name={m.name} email={m.email}
                  inactive={!m.is_active}
                  removeLabel={t('deptAdmin.remove').replace('{x}', m.name).replace('{d}', dept.name)}
                  onRemove={busy ? undefined : () => onMembers(memberIds.filter((i) => i !== m.id))} />
              </li>
            ))}
          </ul>
        )}
        <div className="relative mt-2">
          <input type="search" value={query} onChange={(e) => setQuery(e.target.value)}
            aria-label={`${t('deptAdmin.addPerson')}: ${dept.name}`}
            data-testid={`dept-add-${dept.id}`}
            placeholder={t('deptAdmin.addPerson')}
            className="h-8 w-full rounded-md border border-slate-600 bg-slate-900 px-2 text-sm text-slate-100 placeholder:text-slate-500 focus:border-sky-500 focus:outline-none" />
          {matches.length > 0 && (
            <ul role="listbox" className="absolute z-20 mt-1 w-full overflow-hidden rounded-md border border-slate-600 bg-slate-900 shadow-lg">
              {matches.map((u) => (
                <li key={u.id}>
                  <button type="button" role="option" aria-selected={false} disabled={busy}
                    data-testid={`dept-add-option-${dept.id}-${u.id}`}
                    onClick={() => { onMembers([...memberIds, u.id]); setQuery(''); }}
                    className="w-full px-3 py-1.5 text-left hover:bg-slate-700">
                    <span className="block text-sm text-slate-100">{display(u)}</span>
                    <span className="block text-xs text-slate-400">{u.email}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </section>
  );
}
