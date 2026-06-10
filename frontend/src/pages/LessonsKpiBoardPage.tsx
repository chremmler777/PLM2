/**
 * LessonsKpiBoardPage - governance KPI board for the lessons learned process.
 * Tile style: big-number cards + bar breakdowns + accountability tables.
 */
import { useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import client from '../api/client';

interface Kpis {
  total_lessons: number;
  avg_time_to_review_days: number | null;
  avg_time_to_close_days: number | null;
  on_time_close_rate: number | null;
  implementation_rate: number | null;
  action_completion_rate: number | null;
  open_actions: number;
  overdue_actions: number;
  overdue_by_assignee: { assignee_id: number | null; name: string; count: number }[];
  overdue_by_department: { department_id: number | null; name: string; count: number }[];
  by_category: Record<string, number>;
  by_severity: Record<string, number>;
  by_status: Record<string, number>;
  by_month: Record<string, number>;
  heatmap: Record<string, Record<string, number>>;
  cycle_time_trend: Record<string, number>;
  by_reject_category: Record<string, number>;
  references_total: number;
  reuse_rate: number | null;
  unlinked: number;
  in_review_queue: number;
  stale_lessons: number;
}

const HEATMAP_SEVERITIES = ['critical', 'high', 'medium', 'low'];
const HEATMAP_CATEGORIES = [
  'design', 'manufacturing', 'quality', 'supplier',
  'logistics', 'project_management', 'tooling', 'other',
];

/** Severity x category matrix with color intensity. */
function Heatmap({ data }: { data: Record<string, Record<string, number>> }) {
  const max = Math.max(
    1,
    ...HEATMAP_SEVERITIES.flatMap((s) => HEATMAP_CATEGORIES.map((c) => data[s]?.[c] ?? 0))
  );
  const cellColor = (v: number) => {
    if (v === 0) return 'bg-slate-900 text-slate-700';
    const intensity = v / max;
    if (intensity > 0.66) return 'bg-red-600/70 text-white';
    if (intensity > 0.33) return 'bg-amber-600/60 text-white';
    return 'bg-blue-600/40 text-slate-100';
  };
  return (
    <div className="bg-slate-800 border border-slate-700 rounded-lg p-4 overflow-x-auto">
      <div className="text-xs text-slate-400 uppercase tracking-wide mb-3">Severity × category heatmap</div>
      <table className="text-xs">
        <thead>
          <tr>
            <th />
            {HEATMAP_CATEGORIES.map((c) => (
              <th key={c} className="px-1 pb-2 text-slate-400 font-normal rotate-0 text-center min-w-[68px]">
                {label(c)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {HEATMAP_SEVERITIES.map((s) => (
            <tr key={s}>
              <td className="pr-2 py-0.5 text-slate-300 text-right">{label(s)}</td>
              {HEATMAP_CATEGORIES.map((c) => {
                const v = data[s]?.[c] ?? 0;
                return (
                  <td key={c} className="p-0.5">
                    <div className={`rounded h-8 flex items-center justify-center font-semibold ${cellColor(v)}`}>
                      {v || ''}
                    </div>
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** Capture-to-close cycle time per month as vertical bars. */
function CycleTrend({ data }: { data: Record<string, number> }) {
  const entries = Object.entries(data);
  const max = Math.max(...entries.map(([, v]) => v), 1);
  return (
    <div className="bg-slate-800 border border-slate-700 rounded-lg p-4">
      <div className="text-xs text-slate-400 uppercase tracking-wide mb-3">
        Cycle time trend (avg days capture → closed)
      </div>
      {entries.length === 0 ? (
        <div className="text-xs text-slate-500">No closed lessons yet.</div>
      ) : (
        <div className="flex items-end gap-2 h-32">
          {entries.map(([month, days]) => (
            <div key={month} className="flex flex-col items-center gap-1 flex-1 min-w-0">
              <span className="text-xs text-slate-300">{days}d</span>
              <div
                className="w-full max-w-[48px] bg-teal-500 rounded-t"
                style={{ height: `${Math.max(6, (days / max) * 100)}%` }}
              />
              <span className="text-[10px] text-slate-500">{month}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

const label = (s: string) => s.replace(/_/g, ' ');
const pct = (v: number | null) => (v === null ? '—' : `${Math.round(v * 100)}%`);

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

function BarChart({ title, data, colorFor }: {
  title: string;
  data: Record<string, number>;
  colorFor?: (key: string) => string;
}) {
  const entries = Object.entries(data).sort((a, b) => b[1] - a[1]);
  const max = Math.max(...entries.map(([, v]) => v), 1);
  return (
    <div className="bg-slate-800 border border-slate-700 rounded-lg p-4">
      <div className="text-xs text-slate-400 uppercase tracking-wide mb-3">{title}</div>
      <div className="space-y-2">
        {entries.map(([key, value]) => (
          <div key={key} className="flex items-center gap-2 text-sm">
            <span className="text-slate-300 w-32 truncate text-xs">{label(key)}</span>
            <div className="flex-1 bg-slate-900 rounded h-4 overflow-hidden">
              <div
                className={`h-4 rounded ${colorFor ? colorFor(key) : 'bg-blue-500'}`}
                style={{ width: `${(value / max) * 100}%` }}
              />
            </div>
            <span className="text-slate-200 text-xs w-6 text-right">{value}</span>
          </div>
        ))}
        {entries.length === 0 && <div className="text-xs text-slate-500">No data yet.</div>}
      </div>
    </div>
  );
}

function AccountabilityTable({ title, rows }: {
  title: string;
  rows: { name: string; count: number }[];
}) {
  return (
    <div className="bg-slate-800 border border-slate-700 rounded-lg p-4">
      <div className="text-xs text-slate-400 uppercase tracking-wide mb-3">{title}</div>
      {rows.length === 0 ? (
        <div className="text-xs text-emerald-400">Nothing overdue 🎉</div>
      ) : (
        <table className="w-full text-sm">
          <tbody>
            {rows.map((r, i) => (
              <tr key={i} className="border-b border-slate-700/50 last:border-0">
                <td className="py-1.5 text-slate-200">{r.name}</td>
                <td className="py-1.5 text-right text-red-400 font-semibold">{r.count}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

export default function LessonsKpiBoardPage() {
  const navigate = useNavigate();
  const { data: kpis, isLoading } = useQuery({
    queryKey: ['lesson-kpis'],
    queryFn: async () => (await client.get('/v1/lessons/kpis')).data as Kpis,
    refetchInterval: 60_000,
  });

  if (isLoading || !kpis) {
    return <div className="p-6 text-slate-400 text-sm">Loading KPI board…</div>;
  }

  return (
    <div className="p-6">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h1 className="text-xl font-bold text-slate-100">Lessons Learned — KPI Board</h1>
          <p className="text-sm text-slate-400">Process governance: review speed, implementation, accountability, reuse.</p>
        </div>
        <button
          onClick={() => navigate('/lessons')}
          className="text-sm text-blue-400 hover:text-blue-300"
        >
          ← Back to lessons
        </button>
      </div>

      {/* Headline tiles */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4">
        <Tile
          title="Time to review"
          value={kpis.avg_time_to_review_days === null ? '—' : `${kpis.avg_time_to_review_days}d`}
          sub="avg capture → accepted"
          accent={kpis.avg_time_to_review_days !== null && kpis.avg_time_to_review_days > 30 ? 'text-amber-300' : 'text-slate-100'}
        />
        <Tile
          title="Time to close"
          value={kpis.avg_time_to_close_days === null ? '—' : `${kpis.avg_time_to_close_days}d`}
          sub={`avg capture → closed · ${pct(kpis.on_time_close_rate)} on time vs target`}
          accent={kpis.on_time_close_rate !== null && kpis.on_time_close_rate < 0.7 ? 'text-amber-300' : 'text-slate-100'}
        />
        <Tile
          title="Overdue actions"
          value={kpis.overdue_actions}
          sub={`${kpis.open_actions} open total · ${pct(kpis.action_completion_rate)} completed`}
          accent={kpis.overdue_actions > 0 ? 'text-red-400' : 'text-emerald-400'}
        />
        <Tile
          title="Reuse rate"
          value={pct(kpis.reuse_rate)}
          sub={`${kpis.references_total} gate/kickoff references`}
          accent={kpis.reuse_rate !== null && kpis.reuse_rate > 0 ? 'text-emerald-400' : 'text-slate-100'}
        />
      </div>

      <div className="grid grid-cols-2 md:grid-cols-5 gap-3 mb-4">
        <Tile title="Total lessons" value={kpis.total_lessons} />
        <Tile
          title="Review queue"
          value={kpis.in_review_queue}
          sub="awaiting triage"
          accent={kpis.in_review_queue > 0 ? 'text-amber-300' : 'text-slate-100'}
        />
        <Tile
          title="Implementation"
          value={pct(kpis.implementation_rate)}
          sub="accepted lessons closed"
          accent={kpis.implementation_rate !== null && kpis.implementation_rate < 0.5 ? 'text-amber-300' : 'text-emerald-400'}
        />
        <Tile
          title="Stale"
          value={kpis.stale_lessons}
          sub="stuck in review/verification"
          accent={kpis.stale_lessons > 0 ? 'text-red-400' : 'text-emerald-400'}
        />
        <Tile
          title="Unlinked backlog"
          value={kpis.unlinked}
          sub="lessons without a PLM project"
          accent={kpis.unlinked > 0 ? 'text-amber-300' : 'text-emerald-400'}
        />
      </div>

      {/* Heatmap + cycle trend */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-3 mb-4">
        <Heatmap data={kpis.heatmap} />
        <CycleTrend data={kpis.cycle_time_trend} />
      </div>

      {/* Breakdowns */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-3 mb-4">
        <BarChart title="By status" data={kpis.by_status} />
        <BarChart title="Captured per month" data={kpis.by_month} />
        <BarChart title="Rejections by reason" data={kpis.by_reject_category} />
      </div>

      {/* Accountability */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        <AccountabilityTable title="Overdue actions by assignee" rows={kpis.overdue_by_assignee} />
        <AccountabilityTable title="Overdue actions by department" rows={kpis.overdue_by_department} />
      </div>
    </div>
  );
}
