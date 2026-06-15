/**
 * ProjectChangesSection - Compact list of change requests for a project,
 * embedded on the project detail page. Mirrors the SEP/Lessons section style.
 */
import { useQuery } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { changesApi } from '../api/changes';

const STATUS_LABELS: Record<string, string> = {
  captured: 'Captured',
  in_assessment: 'In Assessment',
  costing: 'Costing',
  quoted: 'Quoted',
  approved: 'Approved',
  in_implementation: 'Implementing',
  in_validation: 'Validation',
  released: 'Released',
  closed: 'Closed',
  on_hold: 'On Hold',
  rejected: 'Rejected',
  cancelled: 'Cancelled',
};

export default function ProjectChangesSection({ projectId }: { projectId: number }) {
  const navigate = useNavigate();

  const { data: changes = [] } = useQuery({
    queryKey: ['changes', 'project', projectId],
    queryFn: () => changesApi.list({ project_id: projectId }),
    enabled: !!projectId,
  });

  return (
    <div className="mb-4 bg-slate-800 rounded-lg border border-slate-700 p-3">
      <div className="flex items-center gap-3 flex-wrap mb-2">
        <span className="text-sm font-semibold text-slate-300">🔄 Changes</span>
        <span className="text-xs text-slate-400">{changes.length} total</span>
        <button
          onClick={() => navigate('/changes')}
          className="text-xs text-blue-400 hover:text-blue-300 ml-auto"
        >
          View all →
        </button>
      </div>
      {changes.length === 0 ? (
        <p className="text-xs text-slate-500">No changes for this project.</p>
      ) : (
        <div className="divide-y divide-slate-700/60">
          {changes.slice(0, 8).map((c) => (
            <button
              key={c.id}
              onClick={() => navigate(`/changes/${c.id}`)}
              className="w-full text-left py-1.5 flex items-center gap-3 text-sm hover:bg-slate-700/30 rounded px-1"
            >
              <span className="font-mono text-xs text-blue-400 flex-shrink-0">{c.change_number}</span>
              <span className="text-slate-200 truncate flex-1">{c.title}</span>
              <span className="text-xs text-slate-400 flex-shrink-0">
                {STATUS_LABELS[c.status] ?? c.status}
              </span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
