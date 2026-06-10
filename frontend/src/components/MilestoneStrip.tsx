/**
 * MilestoneStrip - project timing gates as a horizontal chip row.
 */
import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import client from '../api/client';
import { toast } from 'sonner';

interface Milestone {
  id: number;
  name: string;
  due_date: string;
  status: string;
  overdue: boolean;
}

export default function MilestoneStrip({ projectId }: { projectId: number }) {
  const queryClient = useQueryClient();
  const [showAdd, setShowAdd] = useState(false);
  const [form, setForm] = useState({ name: '', due_date: '' });

  const { data: milestones } = useQuery<Milestone[]>({
    queryKey: ['milestones', projectId],
    queryFn: async () => (await client.get(`/v1/timing/projects/${projectId}/milestones`)).data,
    enabled: !!projectId,
  });

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ['milestones', projectId] });
  const onError = (error: any) => toast.error(error.response?.data?.detail || 'Milestone action failed');

  const addMutation = useMutation({
    mutationFn: async () => {
      await client.post(`/v1/timing/projects/${projectId}/milestones`, {
        name: form.name,
        due_date: new Date(form.due_date).toISOString(),
      });
    },
    onSuccess: () => {
      invalidate();
      setForm({ name: '', due_date: '' });
      setShowAdd(false);
    },
    onError,
  });

  const toggleMutation = useMutation({
    mutationFn: async (m: Milestone) => {
      await client.patch(`/v1/timing/milestones/${m.id}`, {
        status: m.status === 'done' ? 'open' : 'done',
      });
    },
    onSuccess: invalidate,
    onError,
  });

  const deleteMutation = useMutation({
    mutationFn: async (id: number) => {
      await client.delete(`/v1/timing/milestones/${id}`);
    },
    onSuccess: invalidate,
    onError,
  });

  return (
    <div className="flex items-center gap-2 flex-wrap">
      {milestones?.map((m) => (
        <div
          key={m.id}
          className={`group flex items-center gap-1.5 px-2.5 py-1 rounded-full border text-xs ${
            m.status === 'done'
              ? 'bg-green-900/30 border-green-700 text-green-300'
              : m.overdue
                ? 'bg-red-900/30 border-red-700 text-red-300'
                : 'bg-slate-700/60 border-slate-600 text-slate-200'
          }`}
          title={m.overdue ? 'Overdue' : undefined}
        >
          <button
            onClick={() => toggleMutation.mutate(m)}
            title={m.status === 'done' ? 'Reopen' : 'Mark done'}
            className="hover:scale-110 transition"
          >
            {m.status === 'done' ? '✓' : m.overdue ? '⚠' : '◇'}
          </button>
          <span className="font-medium">{m.name}</span>
          <span className="opacity-70">{new Date(m.due_date).toLocaleDateString()}</span>
          <button
            onClick={() => deleteMutation.mutate(m.id)}
            className="opacity-0 group-hover:opacity-100 text-red-400 hover:text-red-300 transition"
            title="Delete milestone"
          >
            ✕
          </button>
        </div>
      ))}

      {showAdd ? (
        <div className="flex items-center gap-1.5">
          <input
            type="text"
            value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
            placeholder="Gate name"
            className="bg-slate-700 border border-slate-600 rounded px-2 py-1 text-slate-100 text-xs w-28"
          />
          <input
            type="date"
            value={form.due_date}
            onChange={(e) => setForm({ ...form, due_date: e.target.value })}
            className="bg-slate-700 border border-slate-600 rounded px-2 py-1 text-slate-100 text-xs"
          />
          <button
            onClick={() => addMutation.mutate()}
            disabled={!form.name.trim() || !form.due_date || addMutation.isPending}
            className="px-2 py-1 rounded bg-blue-600 hover:bg-blue-500 disabled:bg-slate-600 text-white text-xs"
          >
            Add
          </button>
          <button
            onClick={() => setShowAdd(false)}
            className="text-slate-400 hover:text-slate-200 text-xs"
          >
            ✕
          </button>
        </div>
      ) : (
        <button
          onClick={() => setShowAdd(true)}
          className="px-2.5 py-1 rounded-full border border-dashed border-slate-600 text-slate-400 hover:text-slate-200 hover:border-slate-500 text-xs"
        >
          + Gate
        </button>
      )}
    </div>
  );
}
