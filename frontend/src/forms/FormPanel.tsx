/**
 * FormPanel - slide-over for one SEP form instance: header (title, status,
 * owner, references), the rendered form, signatures, history and the
 * save/submit/reopen/sign/export actions.
 */
import { useEffect, useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import client, { API_BASE_URL } from '../api/client';
import FormRenderer from './FormRenderer';
import type { FormInstance, FormData } from './types';

const STATUS_STYLE: Record<string, string> = {
  draft: 'bg-amber-500/20 text-amber-300',
  reopened: 'bg-amber-500/20 text-amber-300',
  submitted: 'bg-emerald-600/20 text-emerald-300',
};

const errDetail = (e: unknown): string => {
  const d = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  if (typeof d === 'string') return d;
  const msg = (d as { message?: string } | undefined)?.message;
  return msg ?? 'Request failed';
};

export default function FormPanel({ instanceId, onClose }: { instanceId: number; onClose: () => void }) {
  const qc = useQueryClient();
  const [draft, setDraft] = useState<FormData | null>(null);

  const { data: inst } = useQuery({
    queryKey: ['form-instance', instanceId],
    queryFn: async () => (await client.get(`/v1/forms/instances/${instanceId}`)).data as FormInstance,
  });
  const { data: users = [] } = useQuery({
    queryKey: ['assignable-users'],
    queryFn: async () => (await client.get('/v1/lessons/assignable-users')).data as { id: number; name: string }[],
  });

  useEffect(() => { if (inst) setDraft(inst.data); }, [inst?.id, inst?.updated_at]);

  const refresh = () => {
    qc.invalidateQueries({ queryKey: ['form-instance', instanceId] });
    qc.invalidateQueries({ queryKey: ['sep'] });
    qc.invalidateQueries({ queryKey: ['forms'] });
    qc.invalidateQueries({ queryKey: ['my-forms'] });
  };
  const done = (label: string) => () => { toast.success(label); refresh(); };
  const fail = (e: unknown) => toast.error(errDetail(e));

  const save = useMutation({
    mutationFn: async () => client.patch(`/v1/forms/instances/${instanceId}`, { data: draft }),
    onSuccess: done('Saved'), onError: fail,
  });
  const submit = useMutation({
    mutationFn: async () => {
      await client.patch(`/v1/forms/instances/${instanceId}`, { data: draft });
      return client.post(`/v1/forms/instances/${instanceId}/submit`);
    },
    onSuccess: done('Submitted'), onError: fail,
  });
  const reopen = useMutation({
    mutationFn: async () => client.post(`/v1/forms/instances/${instanceId}/reopen`),
    onSuccess: done('Reopened'), onError: fail,
  });
  const sign = useMutation({
    mutationFn: async (role: string) => client.post(`/v1/forms/instances/${instanceId}/sign`, { role }),
    onSuccess: done('Signed'), onError: fail,
  });

  if (!inst || !draft) return <div className="p-4 text-slate-400 text-sm">Loading…</div>;
  const editable = inst.status !== 'submitted';
  const pendingRoles = Object.entries(inst.signatures).filter(([, s]) => !s).map(([r]) => r);

  return (
    <div className="fixed inset-y-0 right-0 w-full md:w-[46rem] bg-slate-800 border-l border-slate-700 shadow-xl z-40 flex flex-col">
      <div className="px-4 py-3 border-b border-slate-700 flex items-start gap-3">
        <div className="flex-1 min-w-0">
          <div className="text-slate-100 font-semibold">{inst.title}</div>
          <div className="text-xs text-slate-500">
            v{inst.version}{inst.implements ? ` · ${inst.implements}` : ''} · owner {inst.owner_name ?? '—'} · updated {inst.updated_at.slice(0, 10)} by {inst.updated_by_name ?? '—'}
          </div>
          {inst.references.length > 0 && (
            <div className="mt-1 flex flex-wrap gap-2 text-xs">
              {inst.references.map((r) => <span key={r.path} className="text-blue-400" title={r.path}>📎 {r.title}</span>)}
            </div>)}
        </div>
        <span className={`px-2 py-0.5 rounded text-xs ${STATUS_STYLE[inst.status]}`}>{inst.status}</span>
        <button onClick={onClose} className="text-slate-400 hover:text-slate-200" aria-label="close">✕</button>
      </div>
      <div className="flex-1 overflow-y-auto px-4 py-3">
        {inst.definition && (
          <FormRenderer body={inst.definition} data={draft} onChange={setDraft} readOnly={!editable} users={users} />
        )}
        {Object.keys(inst.signatures).length > 0 && (
          <div className="mt-5 text-xs flex flex-wrap gap-2">
            {Object.entries(inst.signatures).map(([role, s]) => s
              ? <span key={role} className="px-2 py-1 rounded bg-emerald-600/20 text-emerald-300">✓ {role.toUpperCase()}: {s.user_name} ({s.at.slice(0, 10)})</span>
              : <span key={role} className="px-2 py-1 rounded bg-slate-700 text-slate-400">{role.toUpperCase()}: pending</span>)}
          </div>)}
        {inst.events && (
          <details className="mt-5 text-xs text-slate-500"><summary className="cursor-pointer">History ({inst.events.length})</summary>
            <ul className="mt-1 space-y-0.5">{inst.events.map((e) => <li key={e.id}>{e.created_at.slice(0, 16).replace('T', ' ')} · {e.user_name} · {e.event}{e.role ? ` as ${e.role.toUpperCase()}` : ''}</li>)}</ul>
          </details>)}
      </div>
      <div className="px-4 py-3 border-t border-slate-700 flex flex-wrap gap-2 text-sm">
        {editable && <button onClick={() => save.mutate()} disabled={save.isPending} className="px-3 py-1 rounded border border-slate-600 text-slate-200 hover:border-slate-400">Save</button>}
        {editable && <button onClick={() => submit.mutate()} disabled={submit.isPending} className="px-3 py-1 rounded bg-blue-600 text-white hover:bg-blue-500">Submit</button>}
        {!editable && <button onClick={() => reopen.mutate()} disabled={reopen.isPending} className="px-3 py-1 rounded border border-amber-500/60 text-amber-300 hover:border-amber-400">Reopen</button>}
        {!editable && pendingRoles.map((r) => <button key={r} onClick={() => sign.mutate(r)} className="px-3 py-1 rounded border border-emerald-500/60 text-emerald-300">Sign as {r.toUpperCase()}</button>)}
        <a href={`${API_BASE_URL}/v1/forms/instances/${instanceId}/export.pdf`} target="_blank" rel="noreferrer" className="ml-auto px-3 py-1 rounded border border-slate-600 text-slate-300 hover:border-slate-400">Export PDF</a>
      </div>
    </div>
  );
}
