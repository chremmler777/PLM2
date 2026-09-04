/**
 * ProjectFormsTab - every SEP form group of a project with its instances,
 * ordered by the first gate the group belongs to. "New" creates an instance
 * (a second `single` instance comes back as 409 pointing at the existing one).
 */
import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import client from '../api/client';
import FormPanel from './FormPanel';
import type { FormGroup, FormInstance } from './types';

const GATE_ORDER = ['K0/RG1', 'K/RG2', 'E/RG3', 'D/RG4', 'C/RG5', 'B/RG6', 'A/RG7'];
const gateIndex = (g: FormGroup) =>
  Math.min(...g.sep_items.map((r) => GATE_ORDER.indexOf(r.split(':')[0])).filter((i) => i >= 0), 99);

export default function ProjectFormsTab({ projectId }: { projectId: number }) {
  const qc = useQueryClient();
  const [open, setOpen] = useState<number | null>(null);
  const { data: groups = [] } = useQuery({
    queryKey: ['forms', projectId],
    queryFn: async () => (await client.get(`/v1/forms/projects/${projectId}`)).data as FormGroup[],
  });
  const create = useMutation({
    mutationFn: async (key: string) =>
      (await client.post(`/v1/forms/projects/${projectId}/instances`, { key })).data as FormInstance,
    onSuccess: (inst) => {
      qc.invalidateQueries({ queryKey: ['sep'] });
      qc.invalidateQueries({ queryKey: ['forms'] });
      qc.invalidateQueries({ queryKey: ['my-forms'] });
      setOpen(inst.id);
    },
    onError: (e: unknown) => {
      const d = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
      const existing = (d as { instance_id?: number } | undefined)?.instance_id;
      if (existing) setOpen(existing);
      else toast.error(typeof d === 'string' ? d : 'Could not create form');
    },
  });
  const sorted = [...groups].sort((a, b) => gateIndex(a) - gateIndex(b) || a.title.localeCompare(b.title));
  return (
    <div className="space-y-2">
      {sorted.map((g) => (
        <div key={g.key} className="rounded bg-slate-900/40 px-3 py-2">
          <div className="flex items-center gap-2">
            <div className="flex-1 text-sm text-slate-200">{g.title}
              <span className="ml-2 text-xs text-slate-500">{g.sep_items.map((r) => r.split(':')[0]).filter((v, i, a) => a.indexOf(v) === i).join(', ') || 'no gate item'}</span>
            </div>
            {(g.cardinality === 'multi' || g.instances.length === 0) && (
              <button onClick={() => create.mutate(g.key)} className="text-xs px-2 py-0.5 rounded border border-slate-600 text-slate-300 hover:border-slate-400">+ New</button>)}
          </div>
          {g.instances.map((i) => (
            <button key={i.id} onClick={() => setOpen(i.id)} className="mt-1 w-full text-left text-xs flex items-center gap-2 text-slate-300 hover:text-white">
              <span className={`px-1.5 rounded ${i.status === 'submitted' ? 'bg-emerald-600/20 text-emerald-300' : 'bg-amber-500/20 text-amber-300'}`}>{i.status}</span>
              <span>#{i.id} · {i.owner_name ?? '—'} · {i.updated_at.slice(0, 10)}</span>
            </button>))}
        </div>))}
      {open !== null && <FormPanel key={open} instanceId={open} onClose={() => setOpen(null)} />}
    </div>
  );
}
