import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { changesApi } from '../api/changes';
import { STATUS_LABELS } from '../lib/changeStatus';
import StartChangeModal from '../components/changes/StartChangeModal';

export default function ChangesPage() {
  const [showCreate, setShowCreate] = useState(false);
  const [statusFilter, setStatusFilter] = useState<string>('');

  const { data: changes = [], isLoading } = useQuery({
    queryKey: ['changes', statusFilter],
    queryFn: () => changesApi.list(statusFilter ? { status: statusFilter } : {}),
  });

  return (
    <div className="max-w-6xl mx-auto p-6">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-semibold">Change Management</h1>
        <button
          className="px-4 py-2 rounded-lg bg-blue-600 text-white text-sm font-medium hover:bg-blue-700"
          onClick={() => setShowCreate(true)}
        >
          New Change
        </button>
      </div>

      <div className="mb-4">
        <select
          className="border border-slate-700 rounded-lg px-3 py-2 text-sm"
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
        >
          <option value="">All statuses</option>
          {Object.entries(STATUS_LABELS).map(([k, v]) => (
            <option key={k} value={k}>{v}</option>
          ))}
        </select>
      </div>

      {isLoading ? (
        <p className="text-slate-400">Loading…</p>
      ) : (
        <div className="border border-slate-700 rounded-xl overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-slate-700 text-left text-slate-400">
              <tr>
                <th className="px-4 py-3">Number</th>
                <th className="px-4 py-3">Title</th>
                <th className="px-4 py-3">Type</th>
                <th className="px-4 py-3">Status</th>
                <th className="px-4 py-3">Priority</th>
              </tr>
            </thead>
            <tbody>
              {changes.map((c) => (
                <tr key={c.id} className="border-t border-slate-700 hover:bg-slate-800/60">
                  <td className="px-4 py-3 font-mono">
                    <Link className="text-blue-600 hover:underline" to={`/changes/${c.id}`}>
                      {c.change_number}
                    </Link>
                  </td>
                  <td className="px-4 py-3">{c.title}</td>
                  <td className="px-4 py-3">{c.change_type}</td>
                  <td className="px-4 py-3">{STATUS_LABELS[c.status] ?? c.status}</td>
                  <td className="px-4 py-3">{c.priority}</td>
                </tr>
              ))}
              {changes.length === 0 && (
                <tr><td colSpan={5} className="px-4 py-8 text-center text-slate-400">No changes yet.</td></tr>
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
