import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { changesApi } from '../api/changes';
import type { ChangeType } from '../types/change';
import { STATUS_LABELS } from '../lib/changeStatus';

const CHANGE_TYPES: { value: ChangeType; label: string }[] = [
  { value: 'physical_part', label: 'Physical Part' },
  { value: 'tooling', label: 'Tooling' },
  { value: 'document_spec', label: 'Document / Spec' },
  { value: 'process_im', label: 'Process / IM' },
  { value: 'packaging', label: 'Packaging' },
];

export default function ChangesPage() {
  const qc = useQueryClient();
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
          className="border rounded-lg px-3 py-2 text-sm"
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
        <p className="text-gray-500">Loading…</p>
      ) : (
        <div className="border rounded-xl overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 text-left text-gray-500">
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
                <tr key={c.id} className="border-t hover:bg-gray-50">
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
                <tr><td colSpan={5} className="px-4 py-8 text-center text-gray-400">No changes yet.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      )}

      {showCreate && (
        <CreateChangeModal
          onClose={() => setShowCreate(false)}
          onCreated={() => { setShowCreate(false); qc.invalidateQueries({ queryKey: ['changes'] }); }}
        />
      )}
    </div>
  );
}

function CreateChangeModal({ onClose, onCreated }: { onClose: () => void; onCreated: () => void }) {
  const [projectId, setProjectId] = useState('');
  const [title, setTitle] = useState('');
  const [changeType, setChangeType] = useState<ChangeType>('physical_part');
  const [reason, setReason] = useState('');

  const mutation = useMutation({
    mutationFn: () => changesApi.create({
      project_id: Number(projectId), title, change_type: changeType, reason,
    }),
    onSuccess: onCreated,
  });

  return (
    <div className="fixed inset-0 bg-black/30 flex items-center justify-center z-50">
      <div className="bg-white rounded-xl p-6 w-full max-w-md">
        <h2 className="text-lg font-semibold mb-4">New Change</h2>
        <label className="block text-sm mb-2">Project ID
          <input className="mt-1 w-full border rounded-lg px-3 py-2" value={projectId}
                 onChange={(e) => setProjectId(e.target.value)} />
        </label>
        <label className="block text-sm mb-2">Title
          <input className="mt-1 w-full border rounded-lg px-3 py-2" value={title}
                 onChange={(e) => setTitle(e.target.value)} />
        </label>
        <label className="block text-sm mb-2">Type
          <select className="mt-1 w-full border rounded-lg px-3 py-2" value={changeType}
                  onChange={(e) => setChangeType(e.target.value as ChangeType)}>
            {CHANGE_TYPES.map((t) => <option key={t.value} value={t.value}>{t.label}</option>)}
          </select>
        </label>
        <label className="block text-sm mb-4">Reason (a sentence is fine; a PPT can be attached later)
          <textarea className="mt-1 w-full border rounded-lg px-3 py-2" value={reason}
                    onChange={(e) => setReason(e.target.value)} />
        </label>
        <div className="flex justify-end gap-2">
          <button className="px-4 py-2 text-sm" onClick={onClose}>Cancel</button>
          <button
            className="px-4 py-2 rounded-lg bg-blue-600 text-white text-sm disabled:opacity-50"
            disabled={!projectId || !title || mutation.isPending}
            onClick={() => mutation.mutate()}
          >Create</button>
        </div>
      </div>
    </div>
  );
}
