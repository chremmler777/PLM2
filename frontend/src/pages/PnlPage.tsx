/**
 * PnlPage - P&L (Profit & Loss) dashboard over the change portfolio.
 * Mirrors ReportsPage tile/card patterns. Live-computed backend aggregates
 * (Task 1/2); this page is a thin read view + filter bar + row table.
 *
 * IMPORTANT semantics: for internal-branch changes, "revenue" is the PM-approved
 * budget snapshot, not a sale price - so "margin" there means "vs. approved
 * budget", never "profit". This is called out in the table header/tooltip.
 */
import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import client from '../api/client';
import { pnlApi } from '../api/pnl';
import { STATUS_LABELS, STATUS_PILL } from '../lib/changeStatus';
import type { ChangeStatus } from '../types/change';
import type { PnlBranch, PnlStatusGroup, PnlFilters } from '../types/pnl';

const fmtMoney = (v: number | null | undefined) =>
  v === null || v === undefined ? '—' : v.toLocaleString('de-DE');

const fmtPct = (v: number | null | undefined) =>
  v === null || v === undefined ? '—' : `${v.toFixed(1)}%`;

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

function SplitCard({ title, revenue, totalCost, margin, marginPct }: {
  title: string;
  revenue: number;
  totalCost: number;
  margin: number;
  marginPct: number | null;
}) {
  return (
    <div className="bg-slate-800 border border-slate-700 rounded-lg p-4">
      <div className="text-xs text-slate-400 uppercase tracking-wide mb-2">{title}</div>
      <div className="flex items-center justify-between text-sm">
        <span className="text-slate-400">Revenue</span>
        <span className="text-slate-100 font-semibold">{fmtMoney(revenue)}</span>
      </div>
      <div className="flex items-center justify-between text-sm">
        <span className="text-slate-400">Total cost</span>
        <span className="text-slate-100 font-semibold">{fmtMoney(totalCost)}</span>
      </div>
      <div className="flex items-center justify-between text-sm">
        <span className="text-slate-400">Margin</span>
        <span className={`font-semibold ${marginAccent(margin)}`}>
          {fmtMoney(margin)} ({fmtPct(marginPct)})
        </span>
      </div>
    </div>
  );
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
  const rows = changesData?.rows ?? [];

  return (
    <div className="max-w-6xl mx-auto p-6">
      <h1 className="text-2xl font-semibold mb-6">P&amp;L</h1>

      {/* Filter bar */}
      <div className="flex flex-wrap items-center gap-3 mb-6">
        <select
          className="bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-200"
          value={projectId}
          onChange={(e) => setProjectId(e.target.value ? Number(e.target.value) : '')}
        >
          <option value="">All projects</option>
          {projects?.map((p) => (
            <option key={p.id} value={p.id}>{p.name}</option>
          ))}
        </select>

        <select
          aria-label="Plant"
          className="bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-200"
          value={plantId}
          onChange={(e) => setPlantId(e.target.value ? Number(e.target.value) : '')}
        >
          <option value="">All plants</option>
          {plants?.map((p) => (
            <option key={p.id} value={p.id}>{p.name}</option>
          ))}
        </select>

        <div className="flex rounded-lg border border-slate-700 overflow-hidden">
          {BRANCH_OPTIONS.map((opt) => (
            <button
              key={opt.label}
              type="button"
              onClick={() => setBranch(opt.value)}
              aria-pressed={branch === opt.value}
              className={`px-3 py-2 text-sm font-medium ${
                branch === opt.value ? 'bg-sky-500/20 text-sky-300' : 'bg-slate-800 text-slate-400 hover:text-slate-200'
              }`}
            >
              {opt.label}
            </button>
          ))}
        </div>

        <div className="flex rounded-lg border border-slate-700 overflow-hidden">
          {STATUS_GROUP_OPTIONS.map((opt) => (
            <button
              key={opt.label}
              type="button"
              onClick={() => setStatusGroup(opt.value)}
              aria-pressed={statusGroup === opt.value}
              className={`px-3 py-2 text-sm font-medium ${
                statusGroup === opt.value ? 'bg-sky-500/20 text-sky-300' : 'bg-slate-800 text-slate-400 hover:text-slate-200'
              }`}
            >
              {opt.label}
            </button>
          ))}
        </div>

        <label className="flex items-center gap-2 text-sm text-slate-400">
          From
          <input
            aria-label="From"
            type="date"
            className="bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-200"
            value={dateFrom}
            onChange={(e) => setDateFrom(e.target.value)}
          />
        </label>

        <label className="flex items-center gap-2 text-sm text-slate-400">
          To
          <input
            aria-label="To"
            type="date"
            className="bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-200"
            value={dateTo}
            onChange={(e) => setDateTo(e.target.value)}
          />
        </label>
      </div>

      {/* Summary tiles */}
      {summaryLoading || !summary ? (
        <div className="text-sm text-slate-400 mb-6">Loading…</div>
      ) : (
        <>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-3">
            <Tile
              title="Revenue"
              value={fmtMoney(summary.totals.revenue)}
              sub="incl. internal budgets"
              subClassName="text-[10px] text-slate-500"
            />
            <Tile
              title="Cost"
              value={fmtMoney(summary.totals.total_cost)}
              sub={`Int. ${fmtMoney(summary.totals.internal_cost)} · Ext. ${fmtMoney(summary.totals.external_cost)}`}
            />
            <Tile
              title="Margin"
              value={fmtMoney(summary.totals.margin)}
              accent={marginAccent(summary.totals.margin)}
            />
            <Tile title="Margin %" value={fmtPct(summary.totals.margin_pct)} accent={marginAccent(summary.totals.margin)} />
          </div>

          {/* Pipeline vs. Realized */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3 mb-6">
            <SplitCard
              title="Pipeline"
              revenue={summary.pipeline.revenue}
              totalCost={summary.pipeline.total_cost}
              margin={summary.pipeline.margin}
              marginPct={summary.pipeline.margin_pct}
            />
            <SplitCard
              title="Realized"
              revenue={summary.realized.revenue}
              totalCost={summary.realized.total_cost}
              margin={summary.realized.margin}
              marginPct={summary.realized.margin_pct}
            />
          </div>
        </>
      )}

      {/* Row table */}
      {rowsLoading ? (
        <div className="text-sm text-slate-400">Loading…</div>
      ) : (
        <div className="border border-slate-700 rounded-xl overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-slate-700 text-left text-slate-400">
              <tr>
                <th className="px-4 py-3">Change #</th>
                <th className="px-4 py-3">Title</th>
                <th className="px-4 py-3">Branch</th>
                <th className="px-4 py-3">Status</th>
                <th className="px-4 py-3 text-right">Revenue</th>
                <th className="px-4 py-3 text-right">Int. cost</th>
                <th className="px-4 py-3 text-right">Ext. cost</th>
                <th
                  className="px-4 py-3 text-right"
                  title="For internal changes, margin means vs. approved budget, not profit"
                >
                  Margin
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.change_id} className="border-t border-slate-700 hover:bg-slate-800/60">
                  <td className="px-4 py-3 font-mono">
                    <Link className="text-blue-400 hover:underline" to={`/changes/${r.change_id}?tab=commercial`}>
                      {r.change_number}
                    </Link>
                  </td>
                  <td className="px-4 py-3 text-slate-200 truncate max-w-[240px]">{r.title}</td>
                  <td className="px-4 py-3">
                    <span
                      className={`px-2 py-0.5 rounded-full text-xs font-semibold ${
                        r.branch === 'internal' ? 'bg-violet-900 text-violet-200' : 'bg-blue-900 text-blue-200'
                      }`}
                      title={r.branch === 'internal' ? 'Internal: margin vs. approved budget' : undefined}
                    >
                      {r.branch === 'internal' ? 'Internal' : 'Customer'}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    <span className={`px-2.5 py-1 rounded-full text-xs font-semibold ${STATUS_PILL[r.status as ChangeStatus]}`}>
                      {STATUS_LABELS[r.status as ChangeStatus] ?? r.status}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-right">
                    {r.pending_price ? (
                      <span className="inline-flex items-center gap-1">
                        <span className="text-slate-400">—</span>
                        <span className="px-2 py-0.5 rounded-full text-xs font-semibold bg-amber-900 text-amber-200">
                          price pending
                        </span>
                      </span>
                    ) : (
                      <span className="text-slate-100">{fmtMoney(r.revenue)}</span>
                    )}
                  </td>
                  <td className="px-4 py-3 text-right text-slate-200">{fmtMoney(r.internal_cost)}</td>
                  <td className="px-4 py-3 text-right text-slate-200">{fmtMoney(r.external_cost)}</td>
                  <td className="px-4 py-3 text-right">
                    <span
                      className={`px-2.5 py-1 rounded-full text-xs font-semibold ${marginBadgeClasses(r.margin)}`}
                      title={r.branch === 'internal' ? 'vs. approved budget' : undefined}
                    >
                      {fmtMoney(r.margin)}
                    </span>
                  </td>
                </tr>
              ))}
              {rows.length === 0 && (
                <tr><td colSpan={8} className="px-4 py-8 text-center text-slate-400">No changes in scope.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
