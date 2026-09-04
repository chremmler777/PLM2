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
const gatesOf = (g: FormGroup) => g.sep_items.map((r) => r.split(':')[0]).filter((v, i, a) => a.indexOf(v) === i);

const STATUS_DOT: Record<string, string> = { submitted: 'bg-emerald-400', draft: 'bg-amber-400', reopened: 'bg-amber-400' };

export default function ProjectFormsTab({ projectId }: { projectId: number }) {
  const qc = useQueryClient();
  const [open, setOpen] = useState<number | null>(null);
  const { data: groups = [], isLoading } = useQuery({
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

  if (isLoading) {
    return (
      <div className="space-y-2">
        {[0, 1, 2].map((i) => <div key={i} className="h-14 rounded-lg bg-slate-800/60 animate-pulse" />)}
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {sorted.map((g) => {
        const gates = gatesOf(g);
        const canCreate = g.cardinality === 'multi' || g.instances.length === 0;
        return (
          <div key={g.key} className="rounded-lg border border-slate-700/70 bg-slate-800 shadow-panel">
            <div className="flex items-center gap-3 px-4 py-2.5">
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="truncate text-sm font-medium text-slate-100">{g.title}</span>
                  {gates.length > 0
                    ? gates.map((gate) => (
                      <span key={gate} className="rounded-md border border-slate-700 bg-slate-900/60 px-1.5 py-0.5 font-mono text-[11px] text-slate-400">{gate}</span>))
                    : <span className="text-[11px] text-slate-500">not tied to a gate item</span>}
                </div>
                {g.implements && <div className="mt-0.5 font-mono text-[11px] text-slate-500">{g.implements}</div>}
              </div>
              {canCreate && (
                <button onClick={() => create.mutate(g.key)} disabled={create.isPending}
                  className="inline-flex items-center gap-1 rounded-lg border border-slate-600 px-2.5 py-1 text-xs font-medium text-slate-200 hover:bg-slate-700/60 hover:border-slate-500 active:scale-[0.98] transition-all duration-150 disabled:opacity-50">
                  <svg viewBox="0 0 16 16" className="h-3 w-3" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round"><path d="M8 3v10M3 8h10" /></svg>
                  New
                </button>)}
            </div>
            {g.instances.length > 0 && (
              <ul className="border-t border-slate-700/70">
                {g.instances.map((i) => (
                  <li key={i.id}>
                    <button onClick={() => setOpen(i.id)}
                      className="group flex w-full items-center gap-3 px-4 py-2 text-left text-sm hover:bg-slate-700/40 transition-colors duration-150">
                      <span className={`h-2 w-2 shrink-0 rounded-full ${STATUS_DOT[i.status] ?? 'bg-slate-500'}`} aria-hidden />
                      <span className="w-20 shrink-0 text-xs capitalize text-slate-300">{i.status}</span>
                      <span className="min-w-0 flex-1 truncate text-slate-200">{i.owner_name ?? 'unassigned'}</span>
                      <span className="font-mono text-xs text-slate-500 tabular-nums">{i.updated_at.slice(0, 10)}</span>
                      <svg viewBox="0 0 16 16" className="h-3.5 w-3.5 text-slate-600 group-hover:text-slate-300 transition-colors" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round"><path d="M6 4l4 4-4 4" /></svg>
                    </button>
                  </li>))}
              </ul>)}
          </div>
        );
      })}
      {open !== null && <FormPanel key={open} instanceId={open} onClose={() => setOpen(null)} />}
    </div>
  );
}
