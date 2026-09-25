import { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link, useSearchParams } from 'react-router-dom';
import { changesApi } from '../api/changes';
import { STATUS_LABELS, STATUS_PILL, stepPosition } from '../lib/changeStatus';
import { projectLabel } from '../lib/project';
import { changeTypeLabel, priorityLabel } from '../lib/humanLabels';
import { endLabel, endStateOf, hasEnded } from '../lib/transitionRights';
import { daysUntil } from '../lib/format';
import StartChangeModal from '../components/changes/StartChangeModal';
import StartChangeButton from '../components/changes/StartChangeButton';
import { DeadlineChip } from '../components/changes/DeadlineChip';
import { StageResponsibleBadge } from '../components/changes/StageResponsibleBadge';
import { useAuth } from '../contexts/AuthContext';
import { t } from '../i18n/cmLabels';
import type { ChangeRequest } from '../types/change';

type Sort = 'recent' | 'overdue';

/** The date the running phase is measured against; none once the change ended. */
const activeDue = (c: ChangeRequest): string | null =>
  hasEnded(c) ? null
    : c.active_deadline === 'release' ? c.release_due_date
      : c.active_deadline === 'quote' ? c.required_by_date : null;

/** Overdue: the backend says so, or the running deadline has passed. */
const isOverdue = (c: ChangeRequest): boolean => {
  if (hasEnded(c)) return false;
  if (c.deadline_state === 'overdue') return true;
  const due = activeDue(c);
  return !!due && daysUntil(due) < 0;
};

const PRIORITY_RANK: Record<string, number> = { critical: 0, high: 1, medium: 2, low: 3 };

export default function ChangesPage() {
  const [showCreate, setShowCreate] = useState(false);
  const [searchParams, setSearchParams] = useSearchParams();
  const [statusFilter, setStatusFilter] = useState<string>(searchParams.get('status') ?? '');
  const [query, setQuery] = useState('');
  const [mineOnly, setMineOnly] = useState(false);
  // Spec §17: the changes a new customer index started (or joined).
  const [intakeOnly, setIntakeOnly] = useState(false);
  const [sort, setSort] = useState<Sort>('recent');
  const { userId } = useAuth();

  const onStatusChange = (value: string) => {
    setStatusFilter(value);
    setSearchParams(value ? { status: value } : {}, { replace: true });
  };

  const { data, isLoading } = useQuery({
    queryKey: ['changes', statusFilter],
    queryFn: () => changesApi.list(statusFilter ? { status: statusFilter } : {}),
  });

  const shown = useMemo(() => {
    const all = Array.isArray(data) ? data : [];
    const q = query.trim().toLowerCase();
    const mine = (c: ChangeRequest) =>
      c.is_mine ?? (userId != null && c.lead_id === userId);
    const rows = all.filter((c) => (!mineOnly || mine(c)) && (!intakeOnly || !!c.from_intake) && (!q || [
      c.change_number, c.title, c.project_number, c.project_name,
    ].some((f) => (f ?? '').toLowerCase().includes(q))));
    if (sort === 'overdue') {
      // Overdue first; then the nearest running deadline; then by priority.
      const due = (c: ChangeRequest) => activeDue(c) ?? '9999-12-31';
      return [...rows].sort((a, b) =>
        Number(isOverdue(b)) - Number(isOverdue(a))
        || due(a).localeCompare(due(b))
        || (PRIORITY_RANK[a.priority] ?? 9) - (PRIORITY_RANK[b.priority] ?? 9));
    }
    return rows;
  }, [data, query, mineOnly, intakeOnly, sort, userId]);

  const filtered = query.trim() !== '' || mineOnly || intakeOnly;

  return (
    <div className="max-w-7xl mx-auto p-6">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-semibold">Change Management</h1>
        <div className="flex items-center gap-4">
          {/* The whole flow, one click from the list it governs. */}
          <Link to="/process-map" data-testid="process-map-link"
            className="text-sm text-sky-400 hover:underline">
            {t('procmap.link')}
          </Link>
          <StartChangeButton label="New Change Request" onClick={() => setShowCreate(true)} />
        </div>
      </div>

      <div className="mb-4 flex flex-wrap items-center gap-3">
        <input
          type="search"
          data-testid="changes-search"
          aria-label={t('changes.search')}
          placeholder={t('changes.search')}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          className="w-72 border border-slate-700 bg-slate-900 rounded-lg px-3 py-2 text-sm text-slate-100 placeholder-slate-500"
        />
        <select
          aria-label={t('changes.statusFilter')}
          className="border border-slate-700 rounded-lg px-3 py-2 text-sm"
          value={statusFilter}
          onChange={(e) => onStatusChange(e.target.value)}
        >
          <option value="">All statuses</option>
          {Object.entries(STATUS_LABELS).map(([k, v]) => (
            <option key={k} value={k}>{v}</option>
          ))}
        </select>
        <label className="flex items-center gap-2 text-sm text-slate-300 cursor-pointer">
          <input type="checkbox" data-testid="changes-mine" checked={mineOnly}
            onChange={(e) => setMineOnly(e.target.checked)} />
          {t('changes.mine')}
        </label>
        <label className="flex items-center gap-2 text-sm text-slate-300 cursor-pointer"
          title="Changes started by a new customer index (or that took one)">
          <input type="checkbox" data-testid="changes-from-intake" checked={intakeOnly}
            onChange={(e) => setIntakeOnly(e.target.checked)} />
          From intake
        </label>
        <select
          data-testid="changes-sort"
          aria-label={t('changes.sort')}
          className="border border-slate-700 rounded-lg px-3 py-2 text-sm"
          value={sort}
          onChange={(e) => setSort(e.target.value as Sort)}
        >
          <option value="recent">{t('changes.sortRecent')}</option>
          <option value="overdue">{t('changes.sortOverdue')}</option>
        </select>
      </div>

      {isLoading ? (
        <p className="text-slate-400">Loading…</p>
      ) : (
        <div className="border border-slate-700 rounded-xl overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-slate-700 text-left text-slate-400">
              <tr className="whitespace-nowrap">
                <th className="px-4 py-3">Project</th>
                <th className="px-4 py-3">Number</th>
                <th className="px-4 py-3">Title</th>
                <th className="px-4 py-3">Type</th>
                <th className="px-4 py-3">Status</th>
                <th className="px-4 py-3">{t('changes.owner')}</th>
                <th className="px-4 py-3">Priority</th>
                <th className="px-4 py-3">Deadline</th>
                <th className="px-4 py-3">Progress</th>
              </tr>
            </thead>
            <tbody>
              {shown.map((c) => {
                const pos = stepPosition(c.status, c.customer_relevant, c.origin);
                const ended = endStateOf(c);
                const pill = ended === 'rejected' ? STATUS_PILL.rejected
                  : ended === 'cancelled' ? STATUS_PILL.cancelled : STATUS_PILL[c.status];
                const due = activeDue(c);
                return (
                <tr key={c.id} data-testid={`change-row-${c.id}`}
                  className="border-t border-slate-700 hover:bg-slate-800/60">
                  <td className="px-4 py-3 max-w-[12rem]">
                    {projectLabel(c.project_number, c.project_name) ? (
                      <span className="block truncate text-slate-300"
                        title={projectLabel(c.project_number, c.project_name) ?? undefined}>
                        {projectLabel(c.project_number, c.project_name)}
                      </span>
                    ) : <span className="text-slate-600">-</span>}
                  </td>
                  <td className="px-4 py-3 font-mono whitespace-nowrap">
                    <Link className="text-sky-400 hover:underline" to={`/changes/${c.id}`}>
                      {c.change_number}
                    </Link>
                  </td>
                  <td className="px-4 py-3 min-w-[16rem]">
                    <span className="line-clamp-2" title={c.title}>{c.title}</span>
                    {c.origin === 'engineering_review' ? (
                      <span data-testid={`change-review-${c.id}`}
                        className="mt-0.5 inline-block rounded-full bg-teal-900/60 px-2 py-0.5 text-[11px] text-teal-200">
                        Engineering review
                      </span>
                    ) : c.from_intake ? (
                      <span className="mt-0.5 inline-block rounded-full bg-amber-900/50 px-2 py-0.5 text-[11px] text-amber-200">
                        From intake
                      </span>
                    ) : null}
                  </td>
                  <td className="px-4 py-3 whitespace-nowrap">{changeTypeLabel(c.change_type)}</td>
                  <td className="px-4 py-3 whitespace-nowrap">
                    <span data-testid={`change-status-${c.id}`}
                      className={`inline-block whitespace-nowrap px-2.5 py-1 rounded-full text-xs font-semibold ${pill}`}>
                      {endLabel(c) ?? STATUS_LABELS[c.status] ?? c.status}
                    </span>
                  </td>
                  <td className="px-4 py-3 whitespace-nowrap" data-testid={`change-owner-${c.id}`}>
                    {ended ? <span className="text-slate-600">-</span>
                      : c.stage_owner ? <span className="text-slate-300">{c.stage_owner}</span>
                        : <StageResponsibleBadge status={c.status} origin={c.origin} />}
                  </td>
                  <td className="px-4 py-3 whitespace-nowrap">{priorityLabel(c.priority)}</td>
                  <td className="px-4 py-3 whitespace-nowrap">
                    {/* Whichever phase is running owns the visible date; an
                        ended change has no live deadline. */}
                    {due && (
                      <DeadlineChip date={due}
                        state={isOverdue(c) ? 'overdue' : c.deadline_state} />
                    )}
                  </td>
                  <td className="px-4 py-3 whitespace-nowrap">
                    {pos && (
                      <span className="text-xs text-slate-400" title={`Step ${pos.index + 1} of ${pos.total}`}>
                        {pos.index + 1}/{pos.total}
                      </span>
                    )}
                  </td>
                </tr>
              );})}
              {shown.length === 0 && (
                <tr><td colSpan={9} className="px-4 py-8 text-center text-slate-400">
                  {filtered ? t('changes.noMatch') : 'No changes yet.'}
                </td></tr>
              )}
            </tbody>
          </table>
        </div>
      )}

      {showCreate && (
        <StartChangeModal open onClose={() => setShowCreate(false)} />
      )}
    </div>
  );
}
