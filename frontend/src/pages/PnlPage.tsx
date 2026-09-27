/**
 * PnlPage - P&L (Profit & Loss) dashboard over the change portfolio.
 * Mirrors ReportsPage tile/card patterns. Live-computed backend aggregates
 * (Task 1/2); this page is a thin read view + filter bar + row table.
 *
 * IMPORTANT semantics: for internal-branch changes, "revenue" is the PM-approved
 * budget snapshot, not a sale price - so "margin" there means "vs. approved
 * budget", never "profit". This is called out in the table header/tooltip.
 */
import { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import client from '../api/client';
import { pnlApi } from '../api/pnl';
import { STATUS_LABELS, STATUS_PILL } from '../lib/changeStatus';
import type { ChangeStatus } from '../types/change';
import { formatDays, formatMoney, formatMoneyDelta, formatPercent } from '../lib/format';
import { ArrowDown, ArrowUp, CircleAlert } from 'lucide-react';
import DateInput from '../components/gantt/DateInput';
import { LoadingSkeleton } from '../components/common/LoadingSkeleton';
import EmptyState from '../components/common/EmptyState';
import { TONE_CLASS, varianceTone } from '../components/changes/pnl/variance';
import type {
  PnlAggregate, PnlBranch, PnlStatusGroup, PnlFilters, PnlRow, PnlSummary, PnlSummaryBlock,
} from '../types/pnl';

/** Money always with its currency: amounts in different currencies are never added. */
const fmtMoney = (v: number | null | undefined, currency?: string | null) =>
  v === null || v === undefined || !Number.isFinite(v) ? '-' : formatMoney(v, currency);

const fmtPct = (v: number | null | undefined) =>
  formatPercent(v);

/**
 * While a change is implemented or validated its actual margin is a forecast
 * (open cost lines count at plan); from release on it is the booked result.
 * Mirrors pnl_service.IN_PROGRESS_STATUSES.
 */
const IN_PROGRESS: ChangeStatus[] = ['in_implementation', 'in_validation'];
const runningRow = (r: PnlRow) => r.phase === 'actual' && IN_PROGRESS.includes(r.status);

/** Engineering reviews carry no price by design (spec §17): the row's origin
 *  (pnl_service UNPRICED_BY_DESIGN). */
/** Actual costs in another currency than the row's: left out, not converted. */
const otherCurrencyActual = (r: PnlRow) => r.warnings?.find((w) => w.code === 'other_currency_actual');
const isReview = (r: PnlRow) => r.origin === 'engineering_review';

type SortKey = 'change_number' | 'title' | 'status' | 'offer_revenue' | 'planned_cost'
  | 'actual_cost' | 'planned_margin' | 'actual_margin' | 'variance' | 'slip_days';

const COLUMNS: { key: SortKey; label: string; numeric?: boolean; title?: string }[] = [
  { key: 'change_number', label: 'Change #' },
  { key: 'title', label: 'Title' },
  { key: 'status', label: 'Status' },
  { key: 'offer_revenue', label: 'Offer revenue', numeric: true,
    title: 'Accepted offer total; for internal changes the approved budget' },
  { key: 'planned_cost', label: 'Planned cost', numeric: true,
    title: 'Costing frozen at customer acceptance' },
  { key: 'actual_cost', label: 'Actual cost', numeric: true,
    title: 'Booked hours x rate, supplier invoices, scrap, validation issues. From implementation on.' },
  { key: 'planned_margin', label: 'Planned margin', numeric: true,
    title: 'For internal changes: vs. approved budget, not profit' },
  { key: 'actual_margin', label: 'Actual margin', numeric: true,
    title: 'While running: open cost lines at plan (forecast); after release: actual' },
  { key: 'variance', label: 'Variance', numeric: true, title: 'Actual margin minus planned margin' },
  { key: 'slip_days', label: 'Slip', numeric: true, title: 'Finish against the baseline, in plan units' },
];

/** A second figure worth a line under the first: present and not the same. */
const differs = (v: number | null | undefined, base: number | null | undefined): v is number =>
  v !== null && v !== undefined && Number.isFinite(v) && Math.abs(v - (base ?? 0)) > 0.005;

/** Offer revenue tile: how many changes carry a price and how many still wait for one. */
function pricedLine(t: PnlAggregate, count: number): string {
  if (t.priced_count === undefined) return `${count} changes, incl. internal budgets`;
  const pending = t.unpriced_count ?? 0;
  return `${t.priced_count} priced${pending ? `, ${pending} price pending` : ''}, incl. internal budgets`;
}

/** Actual cost tile: the expected end cost next to what is booked. */
function actualCostLine(t: PnlAggregate, currency?: string): string {
  const c = t.actual_count ?? 0;
  const n = `${c} change${c === 1 ? '' : 's'} with hours, invoices or issue costs`;
  return t.forecast_cost !== undefined && differs(t.forecast_cost, t.actual_cost)
    ? `forecast ${fmtMoney(t.forecast_cost, currency)}; ${n}` : n;
}

function sortRows(rows: PnlRow[], key: SortKey, dir: 1 | -1): PnlRow[] {
  return [...rows].sort((a, b) => {
    const va = a[key] as unknown;
    const vb = b[key] as unknown;
    // missing values always last, whatever the direction
    if (va === null || va === undefined) return vb === null || vb === undefined ? 0 : 1;
    if (vb === null || vb === undefined) return -1;
    if (typeof va === 'number' && typeof vb === 'number') return (va - vb) * dir;
    return String(va).localeCompare(String(vb)) * dir;
  });
}

function marginAccent(v: number | null | undefined): string {
  if (v === null || v === undefined) return 'text-slate-400';
  return v >= 0 ? 'text-emerald-400' : 'text-red-400';
}

function marginBadgeClasses(v: number | null | undefined): string {
  if (v === null || v === undefined) return 'bg-slate-700 text-slate-300';
  return v >= 0 ? 'bg-emerald-900 text-emerald-200' : 'bg-red-900 text-red-200';
}

function Tile({ title, value, sub, subClassName, accent = 'text-slate-100' }: {
  title: string;
  value: string | number;
  sub?: string;
  subClassName?: string;
  accent?: string;
}) {
  return (
    <div className="bg-slate-800 border border-slate-700 rounded-lg p-4">
      <div className="text-xs text-slate-400 uppercase tracking-wide">{title}</div>
      <div className={`text-3xl font-bold mt-1 ${accent}`}>{value}</div>
      {sub && <div className={subClassName ?? 'text-xs text-slate-500 mt-1'}>{sub}</div>}
    </div>
  );
}

/**
 * Pipeline / Realized: the same offer-versus-doing figures as the tiles, for
 * the changes in that group. The plan (offer revenue, planned cost and
 * margin) always; the actuals once any change in the group has some.
 */
function SplitCard({ title, agg, currency, running }: {
  title: string; agg: PnlAggregate; currency?: string
  /** Some change in this group is still running: its margin is a forecast. */
  running: boolean
}) {
  const revenue = agg.offer_revenue ?? agg.revenue;
  const planned = agg.planned_cost ?? agg.total_cost;
  const plannedMargin = agg.planned_margin ?? agg.margin;
  const pct = (m: number | undefined, r: number | undefined): number | null =>
    m === undefined || !r ? null : (m / r) * 100;
  const plannedPct = agg.planned_margin !== undefined ? pct(plannedMargin, revenue) : agg.margin_pct;
  const hasActual = (agg.actual_count ?? 0) > 0;
  const actualMargin = agg.forecast_margin ?? agg.actual_margin;
  const line = (label: string, value: React.ReactNode, cls = 'text-slate-100') => (
    <div className="flex items-center justify-between text-sm">
      <span className="text-slate-400">{label}</span>
      <span className={`font-semibold ${cls}`}>{value}</span>
    </div>
  );
  return (
    <div className="bg-slate-800 border border-slate-700 rounded-lg p-4" data-testid={`split-${title.toLowerCase()}`}>
      <div className="text-xs text-slate-400 uppercase tracking-wide mb-2">{title}</div>
      {line('Offer revenue', fmtMoney(revenue, currency))}
      {line('Planned cost', fmtMoney(planned, currency))}
      {line('Planned margin',
        `${fmtMoney(plannedMargin, currency)}${plannedPct === null || plannedPct === undefined ? '' : ` (${fmtPct(plannedPct)})`}`,
        marginAccent(plannedMargin))}
      {hasActual && (
        <div className="mt-2 pt-2 border-t border-slate-700/70 space-y-0.5">
          {line('Actual cost', fmtMoney(agg.actual_cost, currency))}
          {line(running ? 'Actual margin (forecast)' : 'Actual margin', fmtMoney(actualMargin, currency),
            marginAccent(actualMargin))}
        </div>
      )}
      {!hasActual && agg.actual_count !== undefined && (
        <p className="mt-2 text-[11px] text-slate-500">No actuals booked yet</p>
      )}
    </div>
  );
}

/**
 * The summary tiles for one costing currency. A portfolio in several
 * currencies gets one block per currency: amounts are never added across
 * currencies (no FX), and changes whose revenue is in another currency than
 * their costing carry no margin and are only counted.
 */
function SummaryBlock({ block, currency, heading, rows }: {
  block: PnlSummaryBlock; currency?: string; heading?: boolean
  /** The listed rows of this currency: which of them are still running. */
  rows: PnlRow[]
}) {
  const t = block.totals;
  // Only the rows the tiles sum (backend _agg: priced, same currency) can
  // make the figures provisional.
  const summed = rows.filter((r) => r.offer_revenue != null && !r.currency_mismatch);
  const running = summed.some(runningRow);
  const realizedRunning = summed.some((r) => r.realized && runningRow(r));
  const notes = [
    (t.mismatch_count ?? 0) > 0
      && `${t.mismatch_count} change${t.mismatch_count === 1 ? '' : 's'} with the revenue in another currency: no margin, not in the sums`,
    (t.no_rate_count ?? 0) > 0
      && `${t.no_rate_count} change${t.no_rate_count === 1 ? '' : 's'} with costing lines without a rate in the cost sheet: the cost is too low`,
  ].filter(Boolean) as string[];
  return (
    <div data-testid={`pnl-summary-${currency ?? 'all'}`} className="mb-6">
      {heading && (
        <h2 className="text-sm font-semibold text-slate-300 mb-2">
          {currency} <span className="font-normal text-slate-500">({block.count} change{block.count === 1 ? '' : 's'})</span>
        </h2>
      )}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-3">
        <Tile
          title="Offer revenue"
          value={fmtMoney(t.offer_revenue ?? t.revenue, currency)}
          sub={pricedLine(t, block.count)}
          subClassName="text-[11px] text-slate-500 mt-1"
        />
        <Tile
          title="Planned cost"
          value={fmtMoney(t.planned_cost ?? t.total_cost, currency)}
          sub="internal hours x rate, external, scrap"
        />
        <Tile
          title="Planned margin"
          value={fmtMoney(t.planned_margin ?? t.margin, currency)}
          accent={marginAccent(t.planned_margin ?? t.margin)}
          sub={`on the plan frozen at acceptance`}
        />
        <Tile
          title="Late"
          value={t.late_count ?? 0}
          sub={t.max_slip_days ? `worst slip ${t.max_slip_days} day${t.max_slip_days === 1 ? '' : 's'}` : 'no slip'}
          accent={(t.late_count ?? 0) > 0 ? 'text-rose-300' : 'text-slate-100'}
        />
      </div>
      <div className="grid grid-cols-1 md:grid-cols-3 gap-3 mb-3">
        <Tile
          title="Actual cost"
          value={fmtMoney(t.actual_cost, currency)}
          sub={actualCostLine(t, currency)}
        />
        <Tile
          title={running ? 'Actual margin (forecast)' : 'Actual margin'}
          value={fmtMoney(t.forecast_margin ?? t.actual_margin, currency)}
          accent={marginAccent(t.forecast_margin ?? t.actual_margin)}
          sub={running
            // Running changes count their open cost lines at plan: say so,
            // with what is booked so far next to it.
            ? `open lines at plan until release; booked to date ${fmtMoney(t.actual_margin, currency)}${
              t.actual_revenue !== undefined ? ` on ${fmtMoney(t.actual_revenue, currency)} revenue` : ''}`
            : `booked${t.actual_revenue !== undefined ? `, on ${fmtMoney(t.actual_revenue, currency)} revenue` : ''}`}
        />
        <Tile
          title="Variance"
          value={fmtMoney(t.variance, currency)}
          sub="actual minus planned margin, changes with actuals"
          accent={t.variance === undefined ? 'text-slate-100'
            : t.variance < -0.005 ? 'text-rose-300' : 'text-emerald-400'}
        />
      </div>
      {notes.length > 0 && (
        <ul data-testid={`pnl-summary-notes-${currency ?? 'all'}`}
          className="mb-3 space-y-0.5 text-xs text-amber-300">
          {notes.map((n) => <li key={n}>{n}</li>)}
        </ul>
      )}
      {/* Pipeline vs. Realized */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        <SplitCard title="Pipeline" agg={block.pipeline} currency={currency} running={false} />
        <SplitCard title="Realized" agg={block.realized} currency={currency} running={realizedRunning} />
      </div>
    </div>
  );
}

/** One block per currency, the main currency first; a single block otherwise. */
function summaryBlocks(summary: PnlSummary): { currency?: string; block: PnlSummaryBlock }[] {
  const byCur = summary.by_currency ?? {};
  const order = summary.currencies ?? Object.keys(byCur);
  if (order.length <= 1) return [{ currency: summary.currency ?? order[0], block: summary }];
  return order.filter((c) => byCur[c]).map((c) => ({ currency: c, block: byCur[c] }));
}

function useProjects() {
  return useQuery({
    queryKey: ['projects'],
    queryFn: async () => (await client.get('/v1/plants/projects')).data as { id: number; name: string }[],
  });
}

function usePlants() {
  return useQuery({
    queryKey: ['plants'],
    queryFn: async () => (await client.get('/v1/plants')).data as { id: number; name: string }[],
  });
}

const BRANCH_OPTIONS: { value: PnlBranch | ''; label: string }[] = [
  { value: '', label: 'All' },
  { value: 'customer', label: 'Customer' },
  { value: 'internal', label: 'Internal' },
];

const STATUS_GROUP_OPTIONS: { value: PnlStatusGroup | ''; label: string }[] = [
  { value: '', label: 'All' },
  { value: 'pipeline', label: 'Pipeline' },
  { value: 'realized', label: 'Realized' },
];

export default function PnlPage() {
  const [projectId, setProjectId] = useState<number | ''>('');
  const [plantId, setPlantId] = useState<number | ''>('');
  const [branch, setBranch] = useState<PnlBranch | ''>('');
  const [statusGroup, setStatusGroup] = useState<PnlStatusGroup | ''>('');
  const [dateFrom, setDateFrom] = useState('');
  const [dateTo, setDateTo] = useState('');

  const { data: projects } = useProjects();
  const { data: plants } = usePlants();

  const filters: PnlFilters = {
    ...(projectId !== '' ? { project_id: projectId } : {}),
    ...(plantId !== '' ? { plant_id: plantId } : {}),
    ...(branch !== '' ? { branch } : {}),
    ...(statusGroup !== '' ? { status_group: statusGroup } : {}),
    ...(dateFrom !== '' ? { date_from: dateFrom } : {}),
    ...(dateTo !== '' ? { date_to: dateTo } : {}),
  };
  const filterKey = [projectId, plantId, branch, statusGroup, dateFrom, dateTo];

  const { data: summary, isLoading: summaryLoading } = useQuery({
    queryKey: ['pnl', 'summary', ...filterKey],
    queryFn: () => pnlApi.summary(filters),
  });

  const { data: changesData, isLoading: rowsLoading } = useQuery({
    queryKey: ['pnl', 'changes', ...filterKey],
    queryFn: () => pnlApi.changes(filters),
  });
  const rows = useMemo(() => changesData?.rows ?? [], [changesData]);
  const [sortKey, setSortKey] = useState<SortKey>('change_number');
  const [sortDir, setSortDir] = useState<1 | -1>(-1);
  const sorted = useMemo(() => sortRows(rows, sortKey, sortDir), [rows, sortKey, sortDir]);
  const toggleSort = (k: SortKey) => {
    if (k === sortKey) setSortDir((d) => (d === 1 ? -1 : 1));
    else { setSortKey(k); setSortDir(k === 'change_number' || k === 'title' || k === 'status' ? 1 : -1); }
  };

  const segBtn = (active: boolean) => `px-3 py-1.5 text-sm font-medium focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-sky-400 ${
    active ? 'bg-sky-500/20 text-sky-200' : 'bg-slate-800 text-slate-400 hover:text-slate-200'}`;
  const selectCls = 'bg-slate-800 border border-slate-700 rounded-lg px-3 py-1.5 text-sm text-slate-200';
  const dateCls = 'w-40 bg-slate-900 border border-slate-700 rounded-md px-2 py-1 text-sm text-slate-200';

  return (
    <div className="max-w-7xl mx-auto p-6">
      <h1 className="text-2xl font-semibold mb-6">P&amp;L</h1>

      {/* Filter bar: what (project, plant), which changes (scope, stage), and
          when (one date range), each group kept together when the bar wraps. */}
      <div className="flex flex-wrap items-center gap-x-4 gap-y-3 mb-6" data-testid="pnl-filters">
        <div className="flex items-center gap-2">
          <select aria-label="Project" className={selectCls} value={projectId}
            onChange={(e) => setProjectId(e.target.value ? Number(e.target.value) : '')}>
            <option value="">All projects</option>
            {projects?.map((p) => (
              <option key={p.id} value={p.id}>{p.name}</option>
            ))}
          </select>
          <select aria-label="Plant" className={selectCls} value={plantId}
            onChange={(e) => setPlantId(e.target.value ? Number(e.target.value) : '')}>
            <option value="">All plants</option>
            {plants?.map((p) => (
              <option key={p.id} value={p.id}>{p.name}</option>
            ))}
          </select>
        </div>

        <div className="flex items-center gap-2">
          <div role="group" aria-label="Scope" className="flex rounded-lg border border-slate-700 overflow-hidden">
            {BRANCH_OPTIONS.map((opt) => (
              <button key={opt.label} type="button" onClick={() => setBranch(opt.value)}
                aria-pressed={branch === opt.value} className={segBtn(branch === opt.value)}>
                {opt.label}
              </button>
            ))}
          </div>
          <div role="group" aria-label="Stage" className="flex rounded-lg border border-slate-700 overflow-hidden">
            {STATUS_GROUP_OPTIONS.map((opt) => (
              <button key={opt.label} type="button" onClick={() => setStatusGroup(opt.value)}
                aria-pressed={statusGroup === opt.value} className={segBtn(statusGroup === opt.value)}>
                {opt.label}
              </button>
            ))}
          </div>
        </div>

        <fieldset className="m-0 flex items-center gap-2 rounded-lg border border-slate-700 bg-slate-800 px-2 py-1">
          <legend className="sr-only">Raised between</legend>
          <span aria-hidden="true" className="text-xs text-slate-400">Raised</span>
          <DateInput aria-label="From" className={dateCls} value={dateFrom}
            max={dateTo || undefined} onChange={setDateFrom} commitOnChange />
          <span aria-hidden="true" className="text-xs text-slate-500">to</span>
          <DateInput aria-label="To" className={dateCls} value={dateTo}
            min={dateFrom || undefined} onChange={setDateTo} commitOnChange />
        </fieldset>
      </div>

      {/* Summary tiles: offer versus doing across the rows in scope */}
      {summaryLoading || !summary ? (
        <div className="mb-6 -mx-6"><LoadingSkeleton count={2} /></div>
      ) : (
        <>
          {summaryBlocks(summary).map(({ currency, block }, _i, all) => (
            <SummaryBlock key={currency ?? 'all'} block={block} currency={currency}
              heading={all.length > 1}
              rows={all.length > 1 ? rows.filter((r) => r.currency === currency) : rows} />
          ))}
        </>
      )}

      {/* Row table: scrolls inside its card, the change number stays in view. */}
      {rowsLoading ? (
        <div className="-mx-6"><LoadingSkeleton count={3} /></div>
      ) : rows.length === 0 ? (
        <EmptyState title="No changes in scope" hint="Widen the filters above, or clear the date range." />
      ) : (
        <div className="border border-slate-700 rounded-xl overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-slate-700 text-left text-slate-300">
              <tr>
                {COLUMNS.map((c, i) => (
                  <th key={c.key} title={c.title}
                    aria-sort={sortKey === c.key ? (sortDir === 1 ? 'ascending' : 'descending') : 'none'}
                    className={`px-2 py-2.5 whitespace-nowrap ${c.numeric ? 'text-right' : ''} ${
                      i === 0 ? 'sticky left-0 z-10 bg-slate-700' : ''}`}>
                    <button type="button" className="inline-flex items-center gap-1 hover:text-slate-100"
                      onClick={() => toggleSort(c.key)}>
                      {c.label}
                      {sortKey === c.key && (sortDir === 1
                        ? <ArrowUp aria-hidden="true" size={12} />
                        : <ArrowDown aria-hidden="true" size={12} />)}
                    </button>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {sorted.map((r) => {
                const tone = varianceTone(r.variance, r.planned_margin, 1);
                // costs and margins in the costing currency, the revenue in its own
                const cur = r.currency;
                const rcur = r.revenue_currency ?? r.currency;
                const running = runningRow(r);
                const shownMargin = r.forecast_margin ?? r.actual_margin;
                const otherCur = otherCurrencyActual(r);
                return (
                <tr key={r.change_id} className="group border-t border-slate-700 hover:bg-slate-800/60">
                  <td className="sticky left-0 z-[1] bg-slate-900 group-hover:bg-slate-800 px-2 py-2.5 font-mono whitespace-nowrap">
                    <Link className="text-sky-300 hover:underline" to={`/changes/${r.change_id}?tab=costing`}>
                      {r.change_number}
                    </Link>
                    <span
                      className={`ml-2 px-1.5 py-0.5 rounded-full text-[11px] font-semibold font-sans ${
                        r.branch === 'internal' ? 'bg-violet-900 text-violet-200' : 'bg-blue-900 text-blue-200'
                      }`}
                      title={r.branch === 'internal' ? 'Internal: margin vs. approved budget' : undefined}
                    >
                      {r.branch === 'internal' ? 'Internal' : 'Customer'}
                    </span>
                  </td>
                  <td className="px-2 py-2.5 text-slate-200 truncate max-w-[180px]" title={r.title}>{r.title}</td>
                  <td className="px-2 py-2.5">
                    <span className={`px-2.5 py-1 rounded-full text-xs font-semibold whitespace-nowrap ${STATUS_PILL[r.status as ChangeStatus]}`}>
                      {STATUS_LABELS[r.status as ChangeStatus] ?? r.status}
                    </span>
                  </td>
                  <td className="px-2 py-2.5 text-right whitespace-nowrap">
                    {isReview(r) && (r.offer_revenue === null || r.offer_revenue === undefined) ? (
                      <span data-testid={`pnl-review-${r.change_id}`} className="inline-flex items-center gap-1"
                        title="An engineering review is not priced">
                        <span className="text-slate-400">-</span>
                        <span className="px-2 py-0.5 rounded-full text-xs bg-slate-700 text-slate-300">
                          engineering review
                        </span>
                      </span>
                    ) : r.pending_price && (r.offer_revenue === null || r.offer_revenue === undefined) ? (
                      <span className="inline-flex items-center gap-1">
                        <span className="text-slate-400">-</span>
                        <span className="px-2 py-0.5 rounded-full text-xs font-semibold bg-amber-900 text-amber-200">
                          price pending
                        </span>
                      </span>
                    ) : (
                      <span className="text-slate-100">{fmtMoney(r.offer_revenue ?? r.revenue, rcur)}</span>
                    )}
                    {differs(r.actual_revenue, r.offer_revenue ?? r.revenue) && (
                      <div data-testid={`pnl-actual-revenue-${r.change_id}`} className="text-[11px] text-slate-500"
                        title="Revenue with the validation issue costs billed to the customer">
                        actual {fmtMoney(r.actual_revenue, rcur)}
                      </div>
                    )}
                  </td>
                  <td className="px-2 py-2.5 text-right text-slate-200 whitespace-nowrap">
                    {fmtMoney(r.planned_cost ?? r.total_cost, cur)}
                    {r.no_rate && (
                      <div data-testid={`pnl-no-rate-${r.change_id}`} className="text-[11px] text-amber-300"
                        title={r.warnings?.find((w) => w.code === 'no_rate')?.message}>
                        no rate, too low
                      </div>
                    )}
                  </td>
                  <td className="px-2 py-2.5 text-right text-slate-200 whitespace-nowrap">
                    {fmtMoney(r.actual_cost, cur)}
                    {otherCur && (
                      <div data-testid={`pnl-other-currency-${r.change_id}`}
                        className="flex items-center justify-end gap-1 text-[11px] text-amber-300"
                        title={otherCur.message}>
                        <CircleAlert aria-hidden="true" size={11} className="shrink-0" />
                        other currency left out
                        <span className="sr-only">: {otherCur.message}</span>
                      </div>
                    )}
                    {differs(r.forecast_cost, r.actual_cost) && (
                      <div data-testid={`pnl-forecast-cost-${r.change_id}`} className="text-[11px] text-slate-500"
                        title="Expected cost at release: open cost lines count at plan">
                        forecast {fmtMoney(r.forecast_cost, cur)}
                      </div>
                    )}
                  </td>
                  <td className="px-2 py-2.5 text-right whitespace-nowrap">
                    <span
                      className={`px-2.5 py-1 rounded-full text-xs font-semibold ${marginBadgeClasses(r.planned_margin ?? r.margin)}`}
                      title={r.branch === 'internal' ? 'vs. approved budget' : undefined}
                    >
                      {fmtMoney(r.planned_margin ?? r.margin, cur)}
                    </span>
                    {r.currency_mismatch && (
                      <div data-testid={`pnl-currency-mismatch-${r.change_id}`}
                        className="mt-1 text-[11px] text-amber-300"
                        title={r.warnings?.find((w) => w.code === 'currency_mismatch')?.message}>
                        {rcur} vs {cur}: no margin
                      </div>
                    )}
                  </td>
                  <td className={`px-2 py-2.5 text-right whitespace-nowrap ${marginAccent(shownMargin)}`}
                    data-testid={`pnl-actual-margin-${r.change_id}`}>
                    {fmtMoney(shownMargin, cur)}
                    {/* Only a running change has a forecast; a released or
                        closed one shows its booked result, unlabelled. */}
                    {running && shownMargin !== null && shownMargin !== undefined && (
                      <div data-testid={`pnl-margin-forecast-${r.change_id}`} className="text-[11px] text-slate-500"
                        title="Still running: open cost lines count at plan until release">
                        forecast{differs(r.actual_margin, shownMargin) ? `, to date ${fmtMoney(r.actual_margin, cur)}` : ''}
                      </div>
                    )}
                  </td>
                  <td className="px-2 py-2.5 text-right whitespace-nowrap">
                    {r.variance === null || r.variance === undefined ? (
                      <span className="text-slate-500">-</span>
                    ) : (
                      <span className={`rounded px-1.5 py-0.5 text-xs ${TONE_CLASS[tone]}`}>
                        {formatMoneyDelta(r.variance, cur)}
                      </span>
                    )}
                  </td>
                  <td className="px-2 py-2.5 text-right whitespace-nowrap" title={r.slip_unit}>
                    {r.slip_days === null || r.slip_days === undefined ? (
                      <span className="text-slate-500">-</span>
                    ) : (
                      <span className={r.slip_days > 0 ? 'text-rose-300' : 'text-emerald-400'}>
                        {formatDays(r.slip_days, { sign: true })}
                      </span>
                    )}
                  </td>
                </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
