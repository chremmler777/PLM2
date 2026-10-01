/**
 * EcrKpiBoardPage - the two ECR delivery KPIs side by side:
 *   RFQ on time:            quote sent by the customer's requested submission date
 *   Implementation on time: change released by the release deadline set at acceptance
 * Both judged by calendar day. Same hand-rolled Tailwind viz as ReportsPage /
 * LessonsKpiBoardPage (no chart library). No targets are drawn: they are still
 * to be defined (plan action KP), so rates stay neutral and only misses are red.
 */
import { useState } from 'react';
import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { reportsApi, type EcrKpi, type EcrKpiMiss, type EcrKpiTrendRow } from '../api/reports';
import { formatCalendarDate, formatDays, formatPercent, MONTHS } from '../lib/format';
import { STATUS_LABELS } from '../lib/changeStatus';
import type { ChangeStatus } from '../types/change';

type Kind = 'rfq' | 'implementation';

const WINDOWS = [
  { months: 3, label: '3 months' },
  { months: 6, label: '6 months' },
  { months: 12, label: '12 months' },
  { months: 0, label: 'All time' },
];

const KIND_LABEL: Record<Kind, string> = { rfq: 'RFQ', implementation: 'Implementation' };

const pct = (v: number | null) => (v === null ? '-' : formatPercent(v * 100, 0));
const monthLabel = (mk: string) => MONTHS[Number(mk.slice(5, 7)) - 1] ?? mk;

/** On-time vs late per month as stacked columns (green on time, red late). */
function MonthlyBars({ rows, kind }: { rows: EcrKpiTrendRow[]; kind: Kind }) {
  const k = kind === 'rfq' ? 'rfq' : 'impl';
  const data = rows.map((r) => ({
    month: r.month,
    onTime: r[`${k}_on_time` as const],
    late: r[`${k}_late` as const],
  }));
  const max = Math.max(1, ...data.map((d) => d.onTime + d.late));
  if (data.every((d) => d.onTime + d.late === 0)) {
    return <div className="text-sm text-slate-500">Nothing quoted or released against a deadline yet.</div>;
  }
  return (
    <div>
      <div className="flex items-end gap-1 h-24" role="img"
        aria-label={`${KIND_LABEL[kind]} on time and late per month, last 12 months`}>
        {data.map((d) => (
          <div key={d.month} className="flex-1 min-w-0 h-full flex flex-col justify-end"
            title={`${d.month}: ${d.onTime} on time, ${d.late} late`}>
            {d.late > 0 && (
              <div className="bg-red-500/80 rounded-t-sm" style={{ height: `${(d.late / max) * 100}%` }} />
            )}
            {d.onTime > 0 && (
              <div className={`bg-emerald-500/80 ${d.late > 0 ? '' : 'rounded-t-sm'}`}
                style={{ height: `${(d.onTime / max) * 100}%` }} />
            )}
            {d.onTime + d.late === 0 && <div className="h-px bg-slate-700" />}
          </div>
        ))}
      </div>
      <div className="flex gap-1 mt-1">
        {data.map((d) => (
          <span key={d.month} className="flex-1 min-w-0 text-center text-[10px] text-slate-500 truncate">
            {monthLabel(d.month)}
          </span>
        ))}
      </div>
    </div>
  );
}

function KpiPanel({ title, question, kpi, kind, trend }: {
  title: string;
  question: string;
  kpi: EcrKpi;
  kind: Kind;
  trend: EcrKpiTrendRow[];
}) {
  const done = kpi.on_time + kpi.late;
  return (
    <section className="bg-slate-800 border border-slate-700 rounded-lg p-5" aria-label={title}>
      <h2 className="text-base font-semibold text-slate-100">{title}</h2>
      <p className="text-xs text-slate-400 mt-0.5">{question}</p>

      <div className="flex items-baseline gap-3 mt-4">
        <span className="text-5xl font-bold text-slate-100 tabular-nums" data-testid={`${kind}-rate`}>
          {pct(kpi.rate)}
        </span>
        <span className="text-sm text-slate-400 tabular-nums">
          {done === 0 ? 'nothing completed in this period' : `${kpi.on_time} of ${done} on time`}
        </span>
      </div>

      {done > 0 && (
        <div className="flex h-2 rounded-full overflow-hidden bg-slate-900 mt-3" aria-hidden>
          <div className="bg-emerald-500" style={{ width: `${(kpi.on_time / done) * 100}%` }} />
          <div className="bg-red-500" style={{ width: `${(kpi.late / done) * 100}%` }} />
        </div>
      )}

      <dl className="grid grid-cols-1 sm:grid-cols-3 gap-3 mt-5 text-sm">
        <div>
          <dt className="text-xs text-slate-400">Late</dt>
          <dd className={`text-lg font-semibold tabular-nums ${kpi.late > 0 ? 'text-red-400' : 'text-slate-200'}`}>
            {kpi.late}
            {kpi.avg_days_late !== null && (
              <span className="text-xs font-normal text-slate-400"> · avg {formatDays(kpi.avg_days_late)}</span>
            )}
          </dd>
        </div>
        <div>
          <dt className="text-xs text-slate-400">Overdue now</dt>
          <dd className={`text-lg font-semibold tabular-nums ${kpi.open_overdue > 0 ? 'text-red-400' : 'text-slate-200'}`}>
            {kpi.open_overdue}
          </dd>
        </div>
        <div>
          <dt className="text-xs text-slate-400">Due in 7 days</dt>
          <dd className={`text-lg font-semibold tabular-nums ${kpi.open_due_7d > 0 ? 'text-amber-300' : 'text-slate-200'}`}>
            {kpi.open_due_7d}
            <span className="text-xs font-normal text-slate-400"> of {kpi.open_total} open</span>
          </dd>
        </div>
      </dl>

      <div className="mt-5 pt-4 border-t border-slate-700/60">
        <div className="text-xs text-slate-400 mb-2">Last 12 months</div>
        <MonthlyBars rows={trend} kind={kind} />
      </div>
    </section>
  );
}

function MissesTable({ rows }: { rows: EcrKpiMiss[] }) {
  const [filter, setFilter] = useState<'all' | Kind>('all');
  const shown = filter === 'all' ? rows : rows.filter((r) => r.kind === filter);
  return (
    <section className="bg-slate-800 border border-slate-700 rounded-lg p-4" aria-label="Late and overdue">
      <div className="flex flex-wrap items-center justify-between gap-2 mb-3">
        <h2 className="text-sm font-semibold text-slate-200">Late and overdue</h2>
        <div className="flex rounded-md border border-slate-700 overflow-hidden text-xs" role="group" aria-label="Filter by deadline">
          {(['all', 'rfq', 'implementation'] as const).map((f) => (
            <button key={f} type="button" onClick={() => setFilter(f)} aria-pressed={filter === f}
              className={`px-2.5 py-1 whitespace-nowrap focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-400 ${
                filter === f ? 'bg-slate-700 text-slate-100' : 'text-slate-400 hover:text-slate-200'}`}>
              {f === 'all' ? 'All' : KIND_LABEL[f]}
            </button>
          ))}
        </div>
      </div>
      {shown.length === 0 ? (
        <div className="text-sm text-emerald-400 py-2">No missed deadlines in this period.</div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs text-slate-400 border-b border-slate-700">
                <th className="py-1.5 pr-3 font-normal">Change</th>
                <th className="py-1.5 pr-3 font-normal">Title</th>
                <th className="py-1.5 pr-3 font-normal">Project</th>
                <th className="py-1.5 pr-3 font-normal">Deadline</th>
                <th className="py-1.5 pr-3 font-normal">Due</th>
                <th className="py-1.5 pr-3 font-normal">Delivered</th>
                <th className="py-1.5 pr-3 font-normal text-right">Days late</th>
                <th className="py-1.5 font-normal">Lead</th>
              </tr>
            </thead>
            <tbody>
              {shown.map((r) => (
                <tr key={`${r.id}-${r.kind}`} className="border-b border-slate-700/50 last:border-0">
                  <td className="py-1.5 pr-3 whitespace-nowrap">
                    <Link to={`/changes/${r.id}`} className="text-blue-400 hover:underline">{r.change_number}</Link>
                  </td>
                  <td className="py-1.5 pr-3 text-slate-200 max-w-[260px] truncate" title={r.title}>{r.title}</td>
                  <td className="py-1.5 pr-3 text-slate-300 whitespace-nowrap">{r.project_number ?? '-'}</td>
                  <td className="py-1.5 pr-3 text-slate-300 whitespace-nowrap">{KIND_LABEL[r.kind]}</td>
                  <td className="py-1.5 pr-3 text-slate-300 whitespace-nowrap tabular-nums">{formatCalendarDate(r.due)}</td>
                  <td className="py-1.5 pr-3 whitespace-nowrap tabular-nums">
                    {r.done ? (
                      <span className="text-slate-300">{formatCalendarDate(r.done)}</span>
                    ) : (
                      <span className="text-red-400"
                        title={STATUS_LABELS[r.status as ChangeStatus] ?? r.status}>open</span>
                    )}
                  </td>
                  <td className="py-1.5 pr-3 text-right text-red-400 font-semibold tabular-nums">{r.days_late}</td>
                  <td className="py-1.5 text-slate-300 whitespace-nowrap">{r.lead_name ?? '-'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function ratio(onTime: number, late: number) {
  const n = onTime + late;
  if (n === 0) return <span className="text-slate-500">-</span>;
  return (
    <span className="tabular-nums">
      <span className="text-slate-100">{pct(onTime / n)}</span>
      <span className="text-slate-500 text-xs"> ({onTime}/{n})</span>
    </span>
  );
}

export default function EcrKpiBoardPage() {
  const [months, setMonths] = useState(12);
  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ['reports', 'ecr-kpis', months],
    queryFn: () => reportsApi.ecrKpis(months),
    refetchInterval: 60_000,
  });

  return (
    <div className="max-w-6xl mx-auto p-6">
      <div className="flex flex-wrap items-end justify-between gap-3 mb-5">
        <div>
          <h1 className="text-2xl font-semibold text-slate-100">ECR KPI Board</h1>
          <p className="text-sm text-slate-400 mt-1">
            On-time delivery of the RFQ and of the implementation, judged by calendar day.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <div className="flex flex-wrap rounded-md border border-slate-700 overflow-hidden text-xs" role="group" aria-label="Period">
            {WINDOWS.map((w) => (
              <button key={w.months} type="button" onClick={() => setMonths(w.months)} aria-pressed={months === w.months}
                className={`px-2.5 py-1.5 whitespace-nowrap focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-400 ${
                  months === w.months ? 'bg-slate-700 text-slate-100' : 'text-slate-400 hover:text-slate-200'}`}>
                {w.label}
              </button>
            ))}
          </div>
          <Link to="/reports" className="text-sm text-blue-400 hover:text-blue-300">Reports</Link>
        </div>
      </div>

      {isError ? (
        <div className="bg-slate-800 border border-red-900/50 rounded-lg p-4">
          <div className="text-sm text-red-400">The KPIs could not be loaded.</div>
          {error instanceof Error && <div className="text-xs text-slate-500 mt-1">{error.message}</div>}
          <button type="button" onClick={() => refetch()} className="mt-2 text-xs text-blue-400 hover:underline">
            Retry
          </button>
        </div>
      ) : isLoading || !data ? (
        <div className="text-sm text-slate-400">Loading KPIs…</div>
      ) : (
        <>
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 mb-4">
            <KpiPanel
              title="RFQ on time"
              question="Quote submitted by the date the customer requested."
              kpi={data.rfq} kind="rfq" trend={data.trend}
            />
            <KpiPanel
              title="Implementation on time"
              question="Change released by the release deadline set at acceptance."
              kpi={data.implementation} kind="implementation" trend={data.trend}
            />
          </div>

          <div className="mb-4">
            <MissesTable rows={data.late} />
          </div>

          <section className="bg-slate-800 border border-slate-700 rounded-lg p-4" aria-label="By project">
            <h2 className="text-sm font-semibold text-slate-200 mb-3">By project</h2>
            {data.by_project.length === 0 ? (
              <div className="text-sm text-slate-500">No completed deadlines in this period.</div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-left text-xs text-slate-400 border-b border-slate-700">
                      <th className="py-1.5 pr-3 font-normal">Project</th>
                      <th className="py-1.5 pr-3 font-normal text-right">RFQ on time</th>
                      <th className="py-1.5 font-normal text-right">Implementation on time</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.by_project.map((p) => (
                      <tr key={p.project_id ?? 'none'} className="border-b border-slate-700/50 last:border-0">
                        <td className="py-1.5 pr-3 text-slate-200">
                          {p.project_number ?? 'No project'}
                          {p.project_name && <span className="text-slate-400"> · {p.project_name}</span>}
                        </td>
                        <td className="py-1.5 pr-3 text-right">{ratio(p.rfq_on_time, p.rfq_late)}</td>
                        <td className="py-1.5 text-right">{ratio(p.impl_on_time, p.impl_late)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        </>
      )}
    </div>
  );
}
