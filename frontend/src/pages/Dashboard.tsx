/**
 * Dashboard - System overview: counts, active workflows, department queues,
 * and recent activity across all parts.
 */
import { useQuery } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import client from '../api/client';

interface DashboardData {
  counts: {
    projects: number;
    parts: number;
    revisions: number;
    frozen_revisions: number;
    active_workflows: number;
  };
  active_workflows: {
    instance_id: number;
    template_name: string;
    part_id: number;
    part_number: string;
    part_name: string;
    project_id: number;
    revision_name: string;
    current_stage: number;
    total_stages: number;
    open_tasks: number;
    started_at: string | null;
  }[];
  department_queues: { department_id: number; name: string; open_tasks: number }[];
  recent_activity: {
    id: number;
    action: string;
    description: string;
    part_id: number;
    part_name: string;
    project_id: number;
    performed_at: string | null;
  }[];
}

function actionColor(action: string): string {
  if (action.includes('file')) return 'bg-blue-900/50 text-blue-300';
  if (action.includes('bom')) return 'bg-purple-900/50 text-purple-300';
  if (action === 'created') return 'bg-green-900/50 text-green-300';
  if (action === 'approved' || action === 'frozen') return 'bg-emerald-900/50 text-emerald-300';
  if (action === 'rejected' || action === 'cancelled') return 'bg-red-900/50 text-red-300';
  return 'bg-slate-600 text-slate-200';
}

function StatCard({ label, value, accent }: { label: string; value: number; accent?: string }) {
  return (
    <div className="bg-slate-800 rounded-lg border border-slate-700 p-4">
      <p className={`text-3xl font-bold ${accent ?? 'text-slate-100'}`}>{value}</p>
      <p className="text-slate-400 text-sm mt-1">{label}</p>
    </div>
  );
}

export default function Dashboard() {
  const navigate = useNavigate();

  const { data, isLoading } = useQuery<DashboardData>({
    queryKey: ['dashboard'],
    queryFn: async () => (await client.get('/v1/dashboard')).data,
    refetchInterval: 30_000,
  });

  if (isLoading || !data) {
    return <div className="p-6 text-slate-400">Loading dashboard...</div>;
  }

  return (
    <div className="p-6 bg-slate-900 min-h-screen">
      <h1 className="text-3xl font-bold text-slate-100 mb-6">Dashboard</h1>

      {/* Stat cards */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-4 mb-6">
        <StatCard label="Projects" value={data.counts.projects} />
        <StatCard label="Parts" value={data.counts.parts} />
        <StatCard label="Revisions" value={data.counts.revisions} />
        <StatCard label="Frozen" value={data.counts.frozen_revisions} accent="text-green-400" />
        <StatCard label="Active Workflows" value={data.counts.active_workflows} accent="text-blue-400" />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Active workflows */}
        <div className="lg:col-span-2 bg-slate-800 rounded-lg border border-slate-700 p-4">
          <h2 className="text-sm font-semibold text-slate-300 uppercase tracking-wide mb-3">
            Active Workflows
          </h2>
          {data.active_workflows.length === 0 ? (
            <p className="text-slate-500 text-sm py-4">No workflows running</p>
          ) : (
            <div className="space-y-2">
              {data.active_workflows.map((wf) => (
                <button
                  key={wf.instance_id}
                  onClick={() => navigate(`/projects/${wf.project_id}`)}
                  className="w-full text-left p-3 bg-slate-700/50 hover:bg-slate-700 rounded border border-slate-600 transition"
                >
                  <div className="flex items-center justify-between mb-2">
                    <div className="min-w-0">
                      <span className="text-slate-100 font-medium">{wf.part_name}</span>
                      <span className="text-slate-400 text-xs font-mono ml-2">{wf.part_number}</span>
                      <span className="text-slate-400 text-xs ml-2">· {wf.revision_name}</span>
                    </div>
                    <span className="text-xs text-slate-400 flex-shrink-0">
                      {wf.template_name} — stage {wf.current_stage}/{wf.total_stages}
                    </span>
                  </div>
                  <div className="flex items-center gap-3">
                    <div className="flex-1 h-1.5 bg-slate-600 rounded overflow-hidden">
                      <div
                        className="h-full bg-blue-500 transition-all"
                        style={{ width: `${Math.min((wf.current_stage / Math.max(wf.total_stages, 1)) * 100, 100)}%` }}
                      />
                    </div>
                    <span className="text-xs text-amber-300 flex-shrink-0">
                      {wf.open_tasks} open task{wf.open_tasks === 1 ? '' : 's'}
                    </span>
                  </div>
                </button>
              ))}
            </div>
          )}

          {/* Department queues */}
          <h2 className="text-sm font-semibold text-slate-300 uppercase tracking-wide mt-6 mb-3">
            Open Tasks by Department
          </h2>
          {data.department_queues.length === 0 ? (
            <p className="text-slate-500 text-sm py-2">No open tasks</p>
          ) : (
            <div className="flex flex-wrap gap-2">
              {data.department_queues.map((q) => (
                <button
                  key={q.department_id}
                  onClick={() => navigate('/my-tasks')}
                  className="px-3 py-2 bg-slate-700/50 hover:bg-slate-700 rounded border border-slate-600 text-sm transition"
                >
                  <span className="text-slate-200">{q.name}</span>
                  <span className="ml-2 px-1.5 py-0.5 rounded bg-amber-900/50 text-amber-300 text-xs font-bold">
                    {q.open_tasks}
                  </span>
                </button>
              ))}
            </div>
          )}
        </div>

        {/* Recent activity */}
        <div className="bg-slate-800 rounded-lg border border-slate-700 p-4">
          <h2 className="text-sm font-semibold text-slate-300 uppercase tracking-wide mb-3">
            Recent Activity
          </h2>
          {data.recent_activity.length === 0 ? (
            <p className="text-slate-500 text-sm py-4">No activity yet</p>
          ) : (
            <div className="space-y-2 max-h-[32rem] overflow-y-auto">
              {data.recent_activity.map((entry) => (
                <button
                  key={entry.id}
                  onClick={() => navigate(`/projects/${entry.project_id}`)}
                  className="w-full text-left p-2.5 bg-slate-700/40 hover:bg-slate-700 rounded border border-slate-700 transition"
                >
                  <div className="flex items-center justify-between gap-2 mb-1">
                    <span className={`px-1.5 py-0.5 rounded text-xs font-medium ${actionColor(entry.action)}`}>
                      {entry.action.replace(/_/g, ' ')}
                    </span>
                    <span className="text-slate-500 text-xs flex-shrink-0">
                      {entry.performed_at ? new Date(entry.performed_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : ''}
                    </span>
                  </div>
                  <p className="text-slate-300 text-xs leading-snug">{entry.description}</p>
                  <p className="text-slate-500 text-xs mt-0.5">{entry.part_name}</p>
                </button>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
