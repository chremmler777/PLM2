/** Changelog of one part in a modal (the context menu's "View Changelog"). */
import { useChangelog } from '../../hooks/queries/useProjectDetail';

export function ChangelogList({ partId }: { partId: number }) {
  const { data: entries, isLoading } = useChangelog(partId);
  if (isLoading) return <p className="text-slate-400 text-sm">Loading...</p>;
  if (!entries || entries.length === 0) return <p className="text-slate-500 text-sm">No changelog entries yet</p>;
  return (
    <div className="space-y-2">
      {[...entries].reverse().map((entry) => (
        <div key={entry.id} className="p-3 bg-slate-700/50 rounded border border-slate-600 text-sm">
          <div className="flex items-center justify-between">
            <span className="px-2 py-0.5 rounded text-xs font-medium bg-slate-600 text-slate-200">
              {entry.action.replace(/_/g, ' ')}
            </span>
            <span className="text-slate-500 text-xs">
              {new Date(entry.performed_at).toLocaleString()}
            </span>
          </div>
          <p className="text-slate-200 mt-1.5">{entry.action_description}</p>
          {entry.performed_by_user && (
            <p className="text-slate-500 text-xs mt-1">by {entry.performed_by_user}</p>
          )}
        </div>
      ))}
    </div>
  );
}

export default function ChangelogModal({ partId, onClose }: { partId: number; onClose: () => void }) {
  return (
    <div className="fixed inset-0 z-40 bg-black/50 flex items-center justify-center" onClick={onClose}>
      <div
        className="bg-slate-800 rounded-lg border border-slate-700 p-6 max-w-2xl w-full mx-4 max-h-[80vh] flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-xl font-bold text-slate-100">Changelog</h2>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-200 text-xl leading-none">×</button>
        </div>
        <div className="overflow-y-auto">
          <ChangelogList partId={partId} />
        </div>
      </div>
    </div>
  );
}
