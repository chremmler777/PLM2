/**
 * Departments page (Christoph 2026-10-26). Read by everyone; only a real
 * admin sees edit controls (the API refuses others with 403).
 *
 * One card per active department, top to bottom: the name with its member
 * count, warnings as chips, the HEAD banner (migration 151: the senior
 * member who leads the department day to day, "give heads like Russ or
 * Holmes a banner or a headline"), the manager line (migration 149: where
 * escalations go, the overdue digest and My Tasks' "Late in my
 * departments"), then the members with head / manager badges.
 *
 * Membership comes from AdminPanel (migration 150: the department's hub
 * role on a person's token), so members are read-only. The admin names the
 * head and the manager from the department's own active members and
 * activates or retires a department; those controls sit in the card's
 * footer so admins and everyone else read the same card. Warnings for
 * everyone: head or manager inactive / no longer a member (red), no
 * manager (amber), an inactive member (amber), no members, no hub role (red).
 * No head is no warning.
 */
import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import { AlertTriangle, ChevronDown, ChevronRight } from 'lucide-react';
import { useAuth } from '../contexts/AuthContext';
import { departmentsAdminApi } from '../api/workflows';
import type { DepartmentAdmin, DepartmentPerson } from '../types/workflow';
import { toastError } from '../lib/apiError';
import { btnSm } from '../components/common/buttonStyles';
import ConfirmDialog from '../components/common/ConfirmDialog';
import { t } from '../i18n/cmLabels';
import { mailAddress } from '../lib/mailAddress';

const KEY = ['departments', 'overview'];

export default function DepartmentsAdminPage() {
  const { role } = useAuth();
  const isAdmin = role === 'admin';
  const qc = useQueryClient();
  const { data: depts, isLoading, isError, refetch, isFetching } = useQuery({
    queryKey: KEY, queryFn: departmentsAdminApi.list,
  });
  const [showRetired, setShowRetired] = useState(false);
  const [retire, setRetire] = useState<DepartmentAdmin | null>(null);

  const onSaved = (row: DepartmentAdmin) => {
    qc.setQueryData<DepartmentAdmin[]>(KEY, (old) => old?.map((d) => (d.id === row.id ? row : d)));
    // pickers and My Tasks read the departments list (manager, is_active)
    qc.invalidateQueries({ queryKey: ['workflow', 'departments'] });
  };
  const onError = (e: unknown) => toastError(e, t('deptAdmin.saveFailed'));
  const person = useMutation({
    mutationFn: ({ id, field, userId }: { id: number; field: 'head' | 'manager'; userId: number | null }) =>
      (field === 'head' ? departmentsAdminApi.setHead(id, userId) : departmentsAdminApi.setManager(id, userId)),
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
  const busy = person.isPending || active.isPending;

  const live = (depts ?? []).filter((d) => d.is_active);
  const retired = (depts ?? []).filter((d) => !d.is_active);
  const summary = t('deptAdmin.summary')
    .replace('{n}', String(live.length))
    .replace('{h}', String(live.filter((d) => d.head_id != null).length))
    .replace('{w}', String(live.filter((d) => d.warnings.length > 0).length));

  return (
    <div className="mx-auto max-w-screen-2xl space-y-8 px-4 py-6 sm:px-6">
      <header className="max-w-3xl">
        <h1 className="text-2xl font-semibold tracking-tight text-slate-100">{t('deptAdmin.title')}</h1>
        <p className="mt-2 text-sm leading-relaxed text-slate-400">{t('deptAdmin.subtitle')}</p>
        {depts && live.length > 0 && (
          <p data-testid="dept-summary" className="mt-3 text-sm text-slate-300 tabular-nums">{summary}</p>
        )}
      </header>

      {isLoading ? (
        <div data-testid="dept-loading" aria-busy="true" className="grid gap-5 lg:grid-cols-2 2xl:grid-cols-3">
          {[0, 1, 2, 3].map((i) => (
            <div key={i} className="h-72 motion-safe:animate-pulse rounded-xl border border-slate-700/60 bg-slate-800/60" />
          ))}
        </div>
      ) : isError ? (
        <div role="alert" data-testid="dept-error"
          className="flex flex-wrap items-center gap-3 rounded-xl border border-red-800/70 bg-red-950/30 px-4 py-3 text-sm text-red-200">
          <AlertTriangle aria-hidden="true" size={16} className="flex-shrink-0" />
          <span className="mr-auto">{t('deptAdmin.loadFailed')}</span>
          <button type="button" className={btnSm.secondary} disabled={isFetching} onClick={() => refetch()}>
            {t('deptAdmin.retry')}
          </button>
        </div>
      ) : live.length === 0 ? (
        <p data-testid="dept-empty" className="rounded-xl border border-dashed border-slate-700 px-4 py-8 text-center text-sm text-slate-400">
          {t('deptAdmin.empty')}
        </p>
      ) : (
        <div className="grid items-start gap-5 lg:grid-cols-2 2xl:grid-cols-3">
          {live.map((d) => (
            <DepartmentCard key={d.id} dept={d} isAdmin={isAdmin} busy={busy}
              onPerson={(field, userId) => person.mutate({ id: d.id, field, userId })}
              onRetire={() => setRetire(d)} />
          ))}
        </div>
      )}

      {retired.length > 0 && (
        <section data-testid="retired-departments" className="border-t border-slate-800 pt-6">
          <button type="button" aria-expanded={showRetired} aria-controls="retired-list"
            onClick={() => setShowRetired((v) => !v)}
            className="inline-flex items-center gap-1.5 rounded-md text-sm font-medium text-slate-400 hover:text-slate-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400">
            {showRetired
              ? <ChevronDown aria-hidden="true" size={16} />
              : <ChevronRight aria-hidden="true" size={16} />}
            {t('deptAdmin.retired').replace('{n}', String(retired.length))}
          </button>
          {showRetired && (
            <ul id="retired-list" className="mt-3 max-w-3xl divide-y divide-slate-700/70 rounded-xl border border-slate-700 bg-slate-800/60">
              {retired.map((d) => (
                <li key={d.id} data-testid={`retired-${d.id}`} className="flex items-center justify-between gap-3 px-4 py-2.5">
                  <span className="text-sm text-slate-300">{d.name}</span>
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

function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return '?';
  return ((parts[0][0] ?? '') + (parts.length > 1 ? parts[parts.length - 1][0] : '')).toUpperCase();
}

function MailLink({ email: raw, className = '' }: { email: string | null | undefined; className?: string }) {
  const email = mailAddress(raw);
  if (!email) return null;
  return (
    <a href={`mailto:${email}`} translate="no"
      className={`block truncate text-sky-400 underline-offset-2 hover:text-sky-300 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400 rounded-sm ${className}`}>
      {email}
    </a>
  );
}

function RoleBadge({ kind }: { kind: 'head' | 'manager' }) {
  const look = kind === 'head'
    ? 'bg-indigo-500/15 text-indigo-200 ring-indigo-400/30'
    : 'bg-yellow-400/15 text-yellow-100 ring-yellow-400/40';
  return (
    <span className={`rounded-md px-1.5 py-0.5 text-xs font-medium ring-1 ${look}`}>
      {t(kind === 'head' ? 'deptAdmin.head' : 'deptAdmin.manager')}
    </span>
  );
}

function DepartmentCard({ dept, isAdmin, busy, onPerson, onRetire }: {
  dept: DepartmentAdmin;
  isAdmin: boolean;
  busy: boolean;
  onPerson(field: 'head' | 'manager', userId: number | null): void;
  onRetire(): void;
}) {
  const red = dept.warnings.some((w) => w.level === 'red');
  const memberIds = new Set(dept.members.map((m) => m.id));
  const headGone = dept.head_id != null && (dept.head_active === false || !memberIds.has(dept.head_id));
  const n = dept.members.length;
  const titleId = `dept-title-${dept.id}`;
  return (
    <section data-testid={`dept-card-${dept.id}`} aria-labelledby={titleId}
      className={`flex flex-col gap-5 rounded-xl border bg-slate-800 p-5 ${red ? 'border-red-800/80' : 'border-slate-700'}`}>
      <div>
        <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
          <h2 id={titleId} className="text-lg font-semibold tracking-tight text-slate-100 [text-wrap:balance]">{dept.name}</h2>
          <span data-testid={`dept-count-${dept.id}`} className="text-sm text-slate-400 tabular-nums">
            {n === 1 ? t('deptAdmin.memberCountOne') : t('deptAdmin.memberCount').replace('{n}', String(n))}
          </span>
        </div>
        {dept.hub_role == null && (
          <p className="mt-0.5 text-xs text-slate-500">{t('deptAdmin.noHubRole')}</p>
        )}
        {dept.warnings.length > 0 && (
          <ul data-testid={`dept-warnings-${dept.id}`} className="mt-3 flex flex-wrap gap-1.5">
            {dept.warnings.map((w) => (
              <li key={w.code + w.text} data-code={w.code} data-level={w.level}
                className={`inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-xs ring-1 ${w.level === 'red'
                  ? 'bg-red-500/10 text-red-200 ring-red-500/40'
                  : 'bg-amber-500/10 text-amber-200 ring-amber-500/30'}`}>
                <AlertTriangle aria-hidden="true" size={13} className="flex-shrink-0" />{w.text}
              </li>
            ))}
          </ul>
        )}
      </div>

      {/* The manager: where escalations go - the card's headline, in yellow. */}
      {dept.manager_id != null ? (
        <div data-testid={`dept-manager-ro-${dept.id}`}
          className={`flex items-center gap-4 rounded-lg bg-yellow-400/10 px-4 py-3.5 ring-1 ${dept.manager_active === false ? 'ring-red-500/40' : 'ring-yellow-400/40'}`}>
          <span aria-hidden="true"
            className="flex h-11 w-11 flex-shrink-0 items-center justify-center rounded-full bg-yellow-400/25 text-sm font-semibold text-yellow-100">
            {initials(dept.manager_name ?? '')}
          </span>
          <div className="min-w-0 flex-1">
            <p className="flex flex-wrap items-center gap-x-2 gap-y-1">
              <span className="truncate text-lg font-semibold text-yellow-50">{dept.manager_name}</span>
              <span className="rounded-md bg-yellow-400/25 px-1.5 py-0.5 text-xs font-medium text-yellow-100">
                {t('deptAdmin.managerLine')}
              </span>
            </p>
            <MailLink email={dept.manager_email} className="mt-0.5 text-sm" />
          </div>
        </div>
      ) : (
        <p data-testid={`dept-manager-ro-${dept.id}`}
          className="rounded-lg border border-dashed border-yellow-700/50 px-4 py-2.5 text-sm text-slate-500">
          {t('deptAdmin.noManager')}
        </p>
      )}

      {/* The head: second line, who leads the department day to day. */}
      {dept.head_id != null ? (
        <div data-testid={`dept-head-banner-${dept.id}`}
          className={`-mt-2 flex items-center gap-3 rounded-lg bg-indigo-500/10 px-4 py-2.5 ring-1 ${headGone ? 'ring-red-500/40' : 'ring-indigo-400/25'}`}>
          <span aria-hidden="true"
            className="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-full bg-indigo-500/25 text-xs font-semibold text-indigo-100">
            {initials(dept.head_name ?? '')}
          </span>
          <div className="min-w-0 flex-1">
            <p className="flex flex-wrap items-center gap-x-2 gap-y-0.5">
              <span className="truncate font-medium text-slate-100">{dept.head_name}</span>
              <span className="rounded-md bg-indigo-400/20 px-1.5 py-0.5 text-xs font-medium text-indigo-100">
                {t('deptAdmin.head')}
              </span>
              {headGone && (
                <span className="text-xs text-red-300">
                  {dept.head_active === false ? t('deptAdmin.inactive') : t('deptAdmin.headNotMember')}
                </span>
              )}
              <MailLink email={dept.head_email} className="text-xs" />
            </p>
          </div>
        </div>
      ) : (
        <p data-testid={`dept-head-none-${dept.id}`}
          className="-mt-2 px-4 text-sm text-slate-500">
          {t('deptAdmin.noHead')}
        </p>
      )}

      <div>
        <p className="mb-2 flex items-baseline gap-2 text-sm font-medium text-slate-300">
          {t('deptAdmin.members')}
          <span className="text-xs font-normal text-slate-500">{t('deptAdmin.fromHub')}</span>
        </p>
        {n === 0 ? (
          <p className="text-sm text-slate-500">{t('deptAdmin.noMembers')}</p>
        ) : (
          <ul className="divide-y divide-slate-700/60 rounded-lg border border-slate-700/70 bg-slate-900/40">
            {dept.members.map((m) => (
              <MemberRow key={m.id} deptId={dept.id} m={m}
                head={m.id === dept.head_id} manager={m.id === dept.manager_id} />
            ))}
          </ul>
        )}
      </div>

      {isAdmin && (
        <div data-testid={`dept-admin-${dept.id}`}
          className="mt-auto space-y-2.5 border-t border-slate-700/70 pt-4">
          <PersonSelect deptId={dept.id} field="head" busy={busy}
            label={t('deptAdmin.head')} none={t('deptAdmin.noHead')}
            value={dept.head_id} valueName={dept.head_name} members={dept.members}
            onChange={(id) => onPerson('head', id)} />
          <PersonSelect deptId={dept.id} field="manager" busy={busy}
            label={t('deptAdmin.manager')} none={t('deptAdmin.noManager')}
            value={dept.manager_id} valueName={dept.manager_name} members={dept.members}
            onChange={(id) => onPerson('manager', id)} />
          <div className="flex justify-end pt-1">
            <button type="button" className={btnSm.ghost} disabled={busy} onClick={onRetire}
              data-testid={`dept-retire-${dept.id}`}>
              {t('deptAdmin.retire')}
            </button>
          </div>
        </div>
      )}
    </section>
  );
}

function MemberRow({ deptId, m, head, manager }: {
  deptId: number; m: DepartmentPerson; head: boolean; manager: boolean;
}) {
  return (
    <li data-testid={`dept-member-${deptId}-${m.id}`}
      className={`flex items-center gap-3 px-3 py-2 ${m.is_active ? '' : 'opacity-60'}`}>
      <div className="min-w-0 flex-1">
        <span className="block truncate text-sm font-medium text-slate-100">{m.name}</span>
        <MailLink email={m.email} className="text-xs" />
      </div>
      <span className="flex flex-shrink-0 items-center gap-1.5">
        {!m.is_active && <span className="text-xs text-slate-400">{t('deptAdmin.inactive')}</span>}
        {head && <RoleBadge kind="head" />}
        {manager && <RoleBadge kind="manager" />}
      </span>
    </li>
  );
}

function PersonSelect({ deptId, field, label, none, value, valueName, members, busy, onChange }: {
  deptId: number;
  field: 'head' | 'manager';
  label: string;
  none: string;
  value: number | null;
  valueName: string | null;
  members: DepartmentPerson[];
  busy: boolean;
  onChange(userId: number | null): void;
}) {
  const id = `dept-${field}-${deptId}`;
  const candidates = members.filter((m) => m.is_active);
  return (
    <div className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1">
      <label htmlFor={id} className="w-20 flex-shrink-0 text-sm text-slate-400">{label}</label>
      <div className="flex min-w-[12rem] flex-1 items-center gap-1.5">
        <select id={id} name={id} data-testid={id} disabled={busy}
          value={value ?? ''}
          onChange={(e) => onChange(e.target.value ? Number(e.target.value) : null)}
          className="h-9 min-w-0 flex-1 rounded-md border border-slate-600 bg-slate-900 px-2 text-sm text-slate-100 focus:border-sky-500 focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-400/60 disabled:opacity-60">
          <option value="">{none}</option>
          {/* a person who left stays visible (and warned) until replaced */}
          {value != null && !candidates.some((m) => m.id === value) && (
            <option value={value}>{valueName} ({t('deptAdmin.notMemberAny')})</option>
          )}
          {candidates.map((m) => <option key={m.id} value={m.id}>{m.name}</option>)}
        </select>
        {value != null && (
          <button type="button" data-testid={`dept-${field}-clear-${deptId}`} disabled={busy}
            aria-label={`${t('deptAdmin.clear')} ${label}`}
            onClick={() => onChange(null)} className={btnSm.ghost}>
            {t('deptAdmin.clear')}
          </button>
        )}
      </div>
    </div>
  );
}
