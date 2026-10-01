import { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link, useSearchParams } from 'react-router-dom';
import { changesApi } from '../api/changes';
import { STATUS_LABELS, STATUS_PILL, stepPosition } from '../lib/changeStatus';
import { projectLabel } from '../lib/project';
import { changeTypeLabel, priorityLabel } from '../lib/humanLabels';
import { endLabel, endStateOf, hasEnded } from '../lib/transitionRights';
import { daysUntil, formatCalendarDate } from '../lib/format';
import StartChangeModal from '../components/changes/StartChangeModal';
import StartChangeButton from '../components/changes/StartChangeButton';
import { DeadlineChip } from '../components/changes/DeadlineChip';
import { StageResponsibleBadge, stageResponsibleKey } from '../components/changes/StageResponsibleBadge';
import ColumnHeader from '../components/common/ColumnHeader';
import TableFilterBar from '../components/common/TableFilterBar';
import {
  activeFilterCount, applyTableState, ariaSort, nextSort, readTableState, withFilter, writeTableState,
  type ColumnFilter, type FilterColumnDef, type TableState,
} from '../components/common/tableFilters';
import { useAuth } from '../contexts/AuthContext';
import { t } from '../i18n/cmLabels';
import EmptyState from '../components/common/EmptyState';
import type { ChangeRequest } from '../types/change';

type Sort = 'action' | 'recent' | 'overdue';
const SORTS: Sort[] = ['action', 'recent', 'overdue'];

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

/** Priority reads as a chip only when it is not the usual Medium. */
const PRIORITY_CHIP: Record<string, string> = {
  low: 'bg-slate-700 text-slate-200',
  high: 'bg-amber-900/70 text-amber-200',
  critical: 'bg-red-900 text-red-200',
};

/** "Needs action first": the viewer's own overdue changes, then the viewer's
 *  own open ones, then anyone's overdue, then open, then ended; the API's
 *  newest-first order inside each group. */
const actionRank = (c: ChangeRequest, mine: boolean): number => {
  if (hasEnded(c)) return 4;
  const overdue = isOverdue(c);
  if (mine) return overdue ? 0 : 1;
  return overdue ? 2 : 3;
};

/** Workflow order of the statuses, for sorting the Status column. */
const STATUS_ORDER = Object.keys(STATUS_LABELS);

const statusText = (c: ChangeRequest): string => endLabel(c) ?? STATUS_LABELS[c.status] ?? c.status;

/** Who holds the change now: the server's word, else the stage's role. */
const ownerText = (c: ChangeRequest): string => {
  if (endStateOf(c)) return '';
  if (c.stage_owner) return c.stage_owner;
  const key = stageResponsibleKey(c.status, c.origin);
  return key ? t(key) : '';
};

/** Excel-like sort and filter per column (spec: the change list). The keys
 *  are the URL names: f.<key> for a value filter, csort=<key>:asc|desc. */
const COLUMNS: FilterColumnDef<ChangeRequest>[] = [
  { key: 'project', label: 'Project', kind: 'values',
    value: (c) => projectLabel(c.project_number, c.project_name) },
  { key: 'number', label: 'Number', kind: 'values', value: (c) => c.change_number, filterable: false },
  { key: 'title', label: 'Title', kind: 'values', value: (c) => c.title, filterable: false },
  { key: 'type', label: 'Type', kind: 'values', value: (c) => c.change_type,
    display: (c) => changeTypeLabel(c.change_type) },
  { key: 'status', label: 'Status', kind: 'values', value: (c) => c.status, display: statusText,
    // workflow order, ended changes after the running ones
    sortValue: (c) => (endStateOf(c) ? 100 : 0) + Math.max(0, STATUS_ORDER.indexOf(c.status)) },
  { key: 'owner', label: t('changes.owner'), kind: 'values', value: ownerText },
  { key: 'priority', label: 'Priority', kind: 'values', value: (c) => c.priority,
    display: (c) => priorityLabel(c.priority), sortValue: (c) => PRIORITY_RANK[c.priority] ?? 9 },
  { key: 'deadline', label: 'Deadline', kind: 'values', value: (c) => activeDue(c),
    display: (c) => { const d = activeDue(c); return d ? formatCalendarDate(d) : ''; } },
  { key: 'progress', label: 'Progress', kind: 'number', filterable: false,
    value: (c) => { const p = stepPosition(c.status, c.customer_relevant, c.origin); return p ? p.index + 1 : null; },
    sortValue: (c) => { const p = stepPosition(c.status, c.customer_relevant, c.origin); return p ? (p.index + 1) / p.total : null; } },
];
const COL = Object.fromEntries(COLUMNS.map((c) => [c.key, c])) as Record<string, FilterColumnDef<ChangeRequest>>;

export default function ChangesPage() {
  const [showCreate, setShowCreate] = useState(false);
  // Every filter lives in the URL, so Back and a shared link keep them.
  const [searchParams, setSearchParams] = useSearchParams();
  // An unknown ?status (typo, old link) is ignored rather than sent on.
  const rawStatus = searchParams.get('status') ?? '';
  const statusFilter = Object.prototype.hasOwnProperty.call(STATUS_LABELS, rawStatus) ? rawStatus : '';
  const query = searchParams.get('q') ?? '';
  const mineOnly = searchParams.get('mine') === '1';
  // Spec §17: the changes a new customer index started (or joined).
  const intakeOnly = searchParams.get('intake') === '1';
  const rawSort = searchParams.get('sort') as Sort | null;
  const sort: Sort = rawSort && SORTS.includes(rawSort) ? rawSort : 'action';
  const { userId } = useAuth();

  /** One URL parameter; the default value drops out of the URL. */
  const setParam = (key: string, value: string | null) => {
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev);
      if (value) next.set(key, value); else next.delete(key);
      return next;
    }, { replace: true });
  };

  // Column sort and filters, in the URL next to the list's own parameters.
  const table: TableState = useMemo(() => readTableState(searchParams, COLUMNS), [searchParams]);
  const setTable = (next: TableState) =>
    setSearchParams((prev) => writeTableState(prev, next), { replace: true });
  const toggleSort = (key: string) => setTable({ ...table, sort: nextSort(table.sort, key) });
  const setFilter = (key: string, f: ColumnFilter | null) => setTable(withFilter(table, key, f));
  const filterCount = activeFilterCount(table);
  const sortCol = table.sort ? COL[table.sort.key] : undefined;

  const { data, isLoading } = useQuery({
    queryKey: ['changes', statusFilter],
    queryFn: () => changesApi.list(statusFilter ? { status: statusFilter } : {}),
  });

  const listed = useMemo(() => {
    const all = Array.isArray(data) ? data : [];
    const q = query.trim().toLowerCase();
    const mine = (c: ChangeRequest) =>
      c.is_mine ?? (userId != null && c.lead_id === userId);
    const rows = all.filter((c) => (!mineOnly || mine(c)) && (!intakeOnly || !!c.from_intake) && (!q || [
      c.change_number, c.title, c.project_number, c.project_name,
    ].some((f) => (f ?? '').toLowerCase().includes(q))));
    if (sort === 'action') {
      return [...rows].sort((a, b) => actionRank(a, mine(a)) - actionRank(b, mine(b)));
    }
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
  // A column sort reorders the list's order stably: ties keep "needs action first".
  const shown = useMemo(() => applyTableState(listed, COLUMNS, table), [listed, table]);

  const filtered = statusFilter !== '' || query.trim() !== '' || mineOnly || intakeOnly || filterCount > 0;
  const head = (key: string, extra = '', title?: string) => (
    <th className={`px-4 py-3 ${extra}`} aria-sort={ariaSort(table, key)}>
      <ColumnHeader col={COL[key]} rows={listed} cols={COLUMNS} state={table} title={title}
        onToggleSort={toggleSort} onFilter={setFilter} />
    </th>
  );
  // Type only earns a column when the list actually mixes types.
  // Counted before the column filters, so filtering by type keeps its column.
  const showType = new Set(listed.map((c) => c.change_type)).size > 1
    || !!table.filters.type || table.sort?.key === 'type';
  const cols = showType ? 9 : 8;

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
          <Link to="/changes/kpis" data-testid="ecr-kpi-link"
            className="text-sm text-sky-400 hover:underline">
            KPI board
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
          onChange={(e) => setParam('q', e.target.value)}
          className="w-72 border border-slate-700 bg-slate-900 rounded-lg px-3 py-2 text-sm text-slate-100 placeholder-slate-500"
        />
        <select
          aria-label={t('changes.statusFilter')}
          className="border border-slate-700 rounded-lg px-3 py-2 text-sm"
          value={statusFilter}
          onChange={(e) => setParam('status', e.target.value)}
        >
          <option value="">All statuses</option>
          {Object.entries(STATUS_LABELS).map(([k, v]) => (
            <option key={k} value={k}>{v}</option>
          ))}
        </select>
        <label className="flex items-center gap-2 text-sm text-slate-300 cursor-pointer">
          <input type="checkbox" data-testid="changes-mine" checked={mineOnly}
            onChange={(e) => setParam('mine', e.target.checked ? '1' : null)} />
          {t('changes.mine')}
        </label>
        <label className="flex items-center gap-2 text-sm text-slate-300 cursor-pointer"
          title="Changes started by a new customer index (or that took one)">
          <input type="checkbox" data-testid="changes-from-intake" checked={intakeOnly}
            onChange={(e) => setParam('intake', e.target.checked ? '1' : null)} />
          From intake
        </label>
        <select
          data-testid="changes-sort"
          aria-label={t('changes.sort')}
          className="border border-slate-700 rounded-lg px-3 py-2 text-sm"
          value={sortCol ? 'column' : sort}
          onChange={(e) => {
            // Picking a list order drops the column sort, which otherwise wins.
            const value = e.target.value;
            if (value === 'column') return;
            setSearchParams((prev) => {
              const next = writeTableState(prev, { ...table, sort: null });
              if (value === 'action') next.delete('sort'); else next.set('sort', value);
              return next;
            }, { replace: true });
          }}
        >
          {sortCol && table.sort && (
            <option value="column">
              By {sortCol.label}, {table.sort.dir === 'asc' ? 'ascending' : 'descending'}
            </option>
          )}
          <option value="action">{t('changes.sortAction')}</option>
          <option value="recent">{t('changes.sortRecent')}</option>
          <option value="overdue">{t('changes.sortOverdue')}</option>
        </select>
      </div>

      <TableFilterBar className="mb-3" count={filterCount} shown={shown.length} total={listed.length}
        onClear={() => setTable({ ...table, filters: {} })} />

      {isLoading ? (
        <p className="text-slate-400">Loading…</p>
      ) : (
        <div className="border border-slate-700 rounded-xl overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-slate-800 text-left text-slate-400">
              <tr className="whitespace-nowrap">
                {head('project')}
                {head('number')}
                {head('title', 'w-full')}
                {showType && head('type')}
                {head('status')}
                {head('owner')}
                {head('priority', '', t('changes.priorityMediumHint'))}
                {head('deadline')}
                {head('progress')}
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
                  className={`border-t border-slate-700 hover:bg-slate-800/60${hasEnded(c) ? ' text-slate-400' : ''}`}>
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
                  <td className="px-4 py-3 min-w-[20rem]">
                    <span className="line-clamp-2 text-slate-100" title={c.title}>{c.title}</span>
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
                  {showType && <td className="px-4 py-3 whitespace-nowrap">{changeTypeLabel(c.change_type)}</td>}
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
                  <td className="px-4 py-3 whitespace-nowrap" data-testid={`change-priority-${c.id}`}>
                    {c.priority !== 'medium' && (
                      <span className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${PRIORITY_CHIP[c.priority] ?? PRIORITY_CHIP.low}`}>
                        {priorityLabel(c.priority)}
                      </span>
                    )}
                  </td>
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
                      <span className="text-xs tabular-nums text-slate-400" title={`Step ${pos.index + 1} of ${pos.total}`}>
                        {pos.index + 1}/{pos.total}
                      </span>
                    )}
                  </td>
                </tr>
              );})}
              {shown.length === 0 && (
                <tr><td colSpan={cols} className="p-4">
                  <EmptyState size="sm" bordered={false}
                    title={filtered ? t('changes.noMatch') : 'No changes yet'}
                    hint={filtered ? undefined : 'A change request starts from a part, a tool or the button above.'} />
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
