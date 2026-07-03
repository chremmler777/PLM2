/**
 * ReportsPage - KPI dashboard over change pipeline, workload and cost.
 * Hand-rolled Tailwind viz (no chart library), structurally mirroring
 * LessonsKpiBoardPage: Tile (headline), BarChart (width-%), trend bars (height-%).
 * Every number links through to the filtered list behind it.
 */
import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { reportsApi } from '../api/reports';
import { STATUS_LABELS, STATUS_PILL } from '../lib/changeStatus';
import { DeadlineChip } from '../components/changes/DeadlineChip';
import { t } from '../i18n/cmLabels';
import type { ChangeStatus } from '../types/change';

const pct = (v: number | null) => (v === null ? '—' : `${Math.round(v * 100)}%`);
const fmtMoney = (v: number) => v.toLocaleString('de-DE');

function Tile({ title, value, sub, accent = 'text-slate-100' }: {
  title: string;
  value: string | number;
  sub?: string;
  accent?: string;
}) {
  return (
    <div className="bg-slate-800 border border-slate-700 rounded-lg p-4">
      <div className="text-xs text-slate-400 uppercase tracking-wide">{title}</div>
      <div className={`text-3xl font-bold mt-1 ${accent}`}>{value}</div>
      {sub && <div className="text-xs text-slate-500 mt-1">{sub}</div>}
    </div>
  );
}

/** Funnel bar: one row per lifecycle status, width % of max, zero rows muted. */
function FunnelChart({ rows }: { rows: { status: string; count: number }[] }) {
  const max = Math.max(...rows.map((r) => r.count), 1);
  return (
    <div className="bg-slate-800 border border-slate-700 rounded-lg p-4">
      <div className="text-xs text-slate-400 uppercase tracking-wide mb-3">{t('reports.pipeline')}</div>
      <div className="space-y-2">
        {rows.map((r) => {
          const label = STATUS_LABELS[r.status as ChangeStatus] ?? r.status;
          const pill = STATUS_PILL[r.status as ChangeStatus] ?? 'bg-slate-700 text-slate-200';
          const barBg = pill.split(' ').find((cls) => cls.startsWith('bg-')) ?? 'bg-slate-600';
          return (
            <Link
              key={r.status}
              to={`/changes?status=${r.status}`}
              className={`flex items-center gap-2 text-sm rounded hover:bg-slate-700/40 px-1 py-0.5 ${
                r.count === 0 ? 'opacity-40' : ''
              }`}
            >
              <span className="text-slate-300 w-32 truncate text-xs">{label}</span>
              <div className="flex-1 bg-slate-900 rounded h-4 overflow-hidden">
                <div
                  className={`h-4 rounded ${r.count === 0 ? 'bg-slate-700' : barBg}`}
                  style={{ width: `${(r.count / max) * 100}%` }}
                />
              </div>
              <span className="text-slate-200 text-xs w-6 text-right">{r.count}</span>
            </Link>
          );
        })}
      </div>
    </div>
  );
}

/** Released-per-month as vertical bars (height %). */
function ThroughputTrend({ data }: { data: { month: string; released: number }[] }) {
  const max = Math.max(...data.map((d) => d.released), 1);
  return (
    <div className="bg-slate-800 border border-slate-700 rounded-lg p-4">
      <div className="text-xs text-slate-400 uppercase tracking-wide mb-3">{t('reports.throughput')}</div>
      {data.length === 0 ? (
        <div className="text-xs text-slate-500">{t('reports.empty')}</div>
      ) : (
        <div className="flex items-end gap-2 h-32">
          {data.map((d) => (
            <div key={d.month} className="flex flex-col items-center gap-1 flex-1 min-w-0">
              <span className="text-xs text-slate-300">{d.released}</span>
              <div
                className="w-full max-w-[48px] bg-teal-500 rounded-t"
                style={{ height: `${Math.max(6, (d.released / max) * 100)}%` }}
              />
              <span className="text-[10px] text-slate-500">{d.month}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function StageDaysTable({ rows }: { rows: { from_status: string; to_status: string; avg_days: number }[] }) {
  return (
    <div className="bg-slate-800 border border-slate-700 rounded-lg p-4">
      <div className="text-xs text-slate-400 uppercase tracking-wide mb-3">{t('reports.stageDays')}</div>
      {rows.length === 0 ? (
        <div className="text-xs text-slate-500">{t('reports.empty')}</div>
      ) : (
        <table className="w-full text-sm">
          <tbody>
            {rows.map((r, i) => (
              <tr key={i} className="border-b border-slate-700/50 last:border-0">
                <td className="py-1.5 text-slate-300 text-xs">
                  {STATUS_LABELS[r.from_status as ChangeStatus] ?? r.from_status}
                  {' → '}
                  {STATUS_LABELS[r.to_status as ChangeStatus] ?? r.to_status}
                </td>
                <td className="py-1.5 text-right text-slate-100 font-semibold">{r.avg_days}d</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

function WorkloadTable({ title, rows }: {
  title: string;
  rows: { name: string; open: number; overdue: number }[];
}) {
  return (
    <div className="bg-slate-800 border border-slate-700 rounded-lg p-4">
      <div className="text-xs text-slate-400 uppercase tracking-wide mb-3">{title}</div>
      {rows.length === 0 ? (
        <div className="text-xs text-slate-500">{t('reports.empty')}</div>
      ) : (
        <table className="w-full text-sm">
          <thead>
            <tr className="text-slate-500 text-xs">
              <th className="text-left font-normal pb-1">Name</th>
              <th className="text-right font-normal pb-1">Open</th>
              <th className="text-right font-normal pb-1">Overdue</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={i} className="border-b border-slate-700/50 last:border-0">
                <td className="py-1.5 text-slate-200">{r.name}</td>
                <td className="py-1.5 text-right text-slate-200">{r.open}</td>
                <td className={`py-1.5 text-right font-semibold ${r.overdue > 0 ? 'text-red-400' : 'text-slate-500'}`}>
                  {r.overdue}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

function AtRiskList({ rows }: {
  rows: { id: number; change_number: string; title: string; required_by_date: string | null; state: string }[];
}) {
  return (
    <div className="bg-slate-800 border border-slate-700 rounded-lg p-4">
      <div className="text-xs text-slate-400 uppercase tracking-wide mb-3">{t('reports.atRisk')}</div>
      {rows.length === 0 ? (
        <div className="text-xs text-emerald-400">Nothing at risk 🎉</div>
      ) : (
        <table className="w-full text-sm">
          <tbody>
            {rows.map((c) => (
              <tr key={c.id} className="border-b border-slate-700/50 last:border-0">
                <td className="py-1.5">
                  <Link to={`/changes/${c.id}`} className="text-blue-400 hover:underline">
                    {c.change_number}
                  </Link>
                </td>
                <td className="py-1.5 text-slate-200 truncate max-w-[200px]">{c.title}</td>
                <td className="py-1.5 text-right">
                  <DeadlineChip date={c.required_by_date} state={c.state} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

function CostBars({ title, rows }: {
  title: string;
  rows: { name: string; budget?: number; actual: number }[];
}) {
  const max = Math.max(...rows.map((r) => Math.max(r.budget ?? 0, r.actual)), 1);
  return (
    <div className="bg-slate-800 border border-slate-700 rounded-lg p-4">
      <div className="text-xs text-slate-400 uppercase tracking-wide mb-3">{title}</div>
      {rows.length === 0 ? (
        <div className="text-xs text-slate-500">{t('reports.empty')}</div>
      ) : (
        <div className="space-y-3">
          {rows.map((r, i) => (
            <div key={i} className="text-sm">
              <div className="flex justify-between text-xs text-slate-300 mb-1">
                <span className="truncate">{r.name}</span>
                <span>
                  {r.budget !== undefined && (
                    <span className="text-slate-500 mr-2">{t('reports.budget')} {fmtMoney(r.budget)}</span>
                  )}
                  <span className={r.budget !== undefined && r.actual > r.budget ? 'text-red-400 font-semibold' : 'text-slate-200'}>
                    {t('reports.actual')} {fmtMoney(r.actual)}
                  </span>
                </span>
              </div>
              <div className="flex-1 bg-slate-900 rounded h-3 overflow-hidden relative">
                <div
                  className={`h-3 rounded ${r.budget !== undefined && r.actual > r.budget ? 'bg-red-500' : 'bg-blue-500'}`}
                  style={{ width: `${(r.actual / max) * 100}%` }}
                />
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export default function ReportsPage() {
  const { data: pipeline, isLoading: pipelineLoading } = useQuery({
    queryKey: ['reports', 'pipeline'],
    queryFn: reportsApi.pipeline,
  });
  const { data: workload, isLoading: workloadLoading } = useQuery({
    queryKey: ['reports', 'workload'],
    queryFn: reportsApi.workload,
  });
  const { data: cost, isLoading: costLoading } = useQuery({
    queryKey: ['reports', 'cost'],
    queryFn: reportsApi.cost,
  });

  return (
    <div className="max-w-6xl mx-auto p-6">
      <h1 className="text-2xl font-semibold mb-6">{t('reports.title')}</h1>

      {/* Pipeline */}
      <section className="mb-8">
        <h2 className="text-sm font-semibold text-slate-300 uppercase tracking-wide mb-3">{t('reports.pipeline')}</h2>
        {pipelineLoading || !pipeline ? (
          <div className="text-sm text-slate-400">Loading…</div>
        ) : (
          <>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-3">
              <Tile
                title={t('reports.onTime')}
                value={pct(pipeline.on_time_rate)}
                sub="releases meeting required-by date"
                accent={pipeline.on_time_rate !== null && pipeline.on_time_rate < 0.7 ? 'text-amber-300' : 'text-emerald-400'}
              />
            </div>
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-3">
              <div className="lg:col-span-1">
                <FunnelChart rows={pipeline.funnel} />
              </div>
              <ThroughputTrend data={pipeline.throughput} />
              <StageDaysTable rows={pipeline.avg_stage_days} />
            </div>
          </>
        )}
      </section>

      {/* Workload */}
      <section className="mb-8">
        <h2 className="text-sm font-semibold text-slate-300 uppercase tracking-wide mb-3">{t('reports.workload')}</h2>
        {workloadLoading || !workload ? (
          <div className="text-sm text-slate-400">Loading…</div>
        ) : (
          <>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-3">
              <Tile
                title={t('reports.escalations')}
                value={workload.escalation_count}
                accent={workload.escalation_count > 0 ? 'text-red-400' : 'text-emerald-400'}
              />
            </div>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
              <WorkloadTable
                title={t('reports.departments')}
                rows={workload.departments.map((d) => ({ name: d.name, open: d.open, overdue: d.overdue }))}
              />
              <WorkloadTable
                title={t('reports.owners')}
                rows={workload.owners.map((o) => ({ name: o.owner_name, open: o.open, overdue: o.overdue }))}
              />
              <AtRiskList rows={workload.at_risk_changes} />
            </div>
          </>
        )}
      </section>

      {/* Cost */}
      <section>
        <h2 className="text-sm font-semibold text-slate-300 uppercase tracking-wide mb-3">{t('reports.cost')}</h2>
        {costLoading || !cost ? (
          <div className="text-sm text-slate-400">Loading…</div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <CostBars
              title={t('reports.projects')}
              rows={cost.projects.map((p) => ({ name: p.name, budget: p.budget, actual: p.actual }))}
            />
            <CostBars
              title={t('reports.plants')}
              rows={cost.plants.map((p) => ({ name: p.name, actual: p.actual }))}
            />
          </div>
        )}
      </section>
    </div>
  );
}
