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

const STATUS_STYLE: Record<string, { pill: string; dot: string }> = {
  draft: { pill: 'bg-amber-500/10 text-amber-300 border-amber-500/30', dot: 'bg-amber-400' },
  reopened: { pill: 'bg-amber-500/10 text-amber-300 border-amber-500/30', dot: 'bg-amber-400' },
  submitted: { pill: 'bg-emerald-500/10 text-emerald-300 border-emerald-500/30', dot: 'bg-emerald-400' },
};

const BTN = 'inline-flex items-center gap-1.5 rounded-lg px-3.5 py-2 text-sm font-medium transition-all duration-150 ' +
  'active:scale-[0.98] disabled:opacity-50 disabled:pointer-events-none';
const BTN_PRIMARY = `${BTN} bg-sky-600 text-white hover:bg-sky-500 shadow-panel`;
const BTN_SECONDARY = `${BTN} border border-slate-600 text-slate-200 hover:bg-slate-700/60 hover:border-slate-500`;
const BTN_AMBER = `${BTN} border border-amber-500/50 text-amber-300 hover:bg-amber-500/10 hover:border-amber-400`;
const BTN_EMERALD = `${BTN} border border-emerald-500/50 text-emerald-300 hover:bg-emerald-500/10 hover:border-emerald-400`;

const detailOf = (e: unknown) => (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;

const errDetail = (e: unknown): string => {
  const d = detailOf(e);
  if (typeof d === 'string') return d;
  const msg = (d as { message?: string } | undefined)?.message;
  return msg ?? 'Request failed';
};

// Submit answers a 422 with the paths that are still empty; naming them saves
// the user hunting through the form for what the message only counts.
const submitError = (e: unknown): string => {
  const missing = (detailOf(e) as { missing?: unknown[] } | undefined)?.missing;
  const base = errDetail(e);
  return Array.isArray(missing) && missing.length > 0 ? `${base}: ${missing.join(', ')}` : base;
};

const fmtDate = (iso: string) => iso.slice(0, 10);
const fmtStamp = (iso: string) => iso.slice(0, 16).replace('T', ' ');

const EVENT_LABEL: Record<string, string> = {
  created: 'created', saved: 'saved', submitted: 'submitted', reopened: 'reopened', signed: 'signed',
};

function Spinner() {
  return <span className="inline-block h-3.5 w-3.5 animate-spin rounded-full border-2 border-current border-t-transparent" aria-hidden />;
}

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

  // Reset the working copy only when a different instance or a newer server
  // revision arrives — depending on `inst` itself would clobber every keystroke.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { if (inst) setDraft(inst.data); }, [inst?.id, inst?.updated_at]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

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
    onSuccess: done('Submitted'), onError: (e: unknown) => toast.error(submitError(e)),
  });
  const reopen = useMutation({
    mutationFn: async () => client.post(`/v1/forms/instances/${instanceId}/reopen`),
    onSuccess: done('Reopened'), onError: fail,
  });
  const sign = useMutation({
    mutationFn: async (role: string) => client.post(`/v1/forms/instances/${instanceId}/sign`, { role }),
    onSuccess: done('Signed'), onError: fail,
  });

  const dirty = inst !== undefined && draft !== null && JSON.stringify(draft) !== JSON.stringify(inst.data);
  const editable = inst ? inst.status !== 'submitted' : false;
  const pendingRoles = inst ? Object.entries(inst.signatures).filter(([, s]) => !s).map(([r]) => r) : [];
  const status = inst ? STATUS_STYLE[inst.status] ?? STATUS_STYLE.draft : STATUS_STYLE.draft;

  return (
    <div className="fixed inset-0 z-50 flex justify-end" role="dialog" aria-modal="true" aria-label={inst?.title ?? 'Form'}>
      <div className="absolute inset-0 bg-slate-950/60 backdrop-blur-[2px] form-panel-fade" onClick={onClose} aria-hidden />
      <aside className="relative flex h-full w-full flex-col bg-slate-800 border-l border-slate-700 shadow-lift md:w-[min(84rem,calc(100vw-3rem))] form-panel-slide">
        {!inst || !draft ? (
          <div className="flex flex-1 flex-col">
            <div className="px-5 py-4 border-b border-slate-700 space-y-2">
              <div className="h-5 w-56 rounded bg-slate-700/60 animate-pulse" />
              <div className="h-3 w-80 rounded bg-slate-700/40 animate-pulse" />
            </div>
            <div className="p-5 space-y-4">
              <div className="h-40 rounded-lg bg-slate-700/30 animate-pulse" />
              <div className="h-56 rounded-lg bg-slate-700/30 animate-pulse" />
            </div>
            <p className="sr-only">Loading…</p>
          </div>
        ) : (
          <>
            <header className="px-5 pt-4 pb-3 border-b border-slate-700">
              <div className="flex items-start gap-3">
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <h2 className="text-lg font-semibold tracking-tight text-slate-50">{inst.title}</h2>
                    <span className={`inline-flex items-center gap-1.5 rounded-md border px-2 py-0.5 text-xs font-medium ${status.pill}`}>
                      <span className={`h-1.5 w-1.5 rounded-full ${status.dot}`} aria-hidden />
                      {inst.status}
                    </span>
                    {dirty && editable && (
                      <span className="text-xs text-amber-300/80">unsaved changes</span>)}
                  </div>
                  <dl className="mt-1.5 flex flex-wrap gap-x-4 gap-y-0.5 text-xs text-slate-400">
                    <div className="flex gap-1"><dt className="text-slate-500">Version</dt><dd className="font-mono text-slate-300">v{inst.version}</dd></div>
                    {inst.implements && (
                      <div className="flex gap-1"><dt className="text-slate-500">Implements</dt><dd className="font-mono text-slate-300">{inst.implements}</dd></div>)}
                    <div className="flex gap-1"><dt className="text-slate-500">Owner</dt><dd className="text-slate-300">{inst.owner_name ?? '—'}</dd></div>
                    <div className="flex gap-1"><dt className="text-slate-500">Updated</dt><dd className="text-slate-300">{fmtDate(inst.updated_at)} by {inst.updated_by_name ?? '—'}</dd></div>
                  </dl>
                  {inst.references.length > 0 && (
                    <div className="mt-2 flex flex-wrap gap-1.5">
                      {inst.references.map((r) => (
                        <span key={r.path} title={r.path}
                          className="inline-flex items-center gap-1 rounded-md border border-slate-700 bg-slate-900/60 px-2 py-0.5 text-[11px] text-slate-300">
                          <svg viewBox="0 0 16 16" className="h-3 w-3 text-slate-500" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"><path d="M10.5 5.5l-4 4a1.5 1.5 0 002.1 2.1l4.5-4.5a3 3 0 00-4.2-4.2L4 7.8a4.5 4.5 0 006.4 6.4l3.6-3.6" /></svg>
                          {r.title}
                        </span>))}
                    </div>)}
                </div>
                <button onClick={onClose} aria-label="close" title="Close (Esc)"
                  className="-mr-1 -mt-1 rounded-lg p-1.5 text-slate-400 hover:bg-slate-700/60 hover:text-slate-100 transition-colors duration-150">
                  <svg viewBox="0 0 16 16" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round"><path d="M4 4l8 8M12 4l-8 8" /></svg>
                </button>
              </div>
            </header>

            <div className="flex-1 overflow-y-auto bg-slate-900/40 px-5 py-5">
              {inst.definition && (
                <FormRenderer body={inst.definition} data={draft} onChange={setDraft} readOnly={!editable} users={users} />
              )}

              {Object.keys(inst.signatures).length > 0 && (
                <section className="mt-7 rounded-lg border border-slate-700/70 bg-slate-800 p-4 shadow-panel">
                  <h4 className="mb-3 text-sm font-semibold tracking-tight text-slate-100">Signatures</h4>
                  <ul className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                    {Object.entries(inst.signatures).map(([role, s]) => (
                      <li key={role} className={`flex items-center gap-3 rounded-lg border px-3 py-2 ${s ? 'border-emerald-500/30 bg-emerald-500/5' : 'border-slate-700 bg-slate-900/40'}`}>
                        <span className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-full ${s ? 'bg-emerald-500/15 text-emerald-300' : 'bg-slate-700/60 text-slate-500'}`}>
                          {s
                            ? <svg viewBox="0 0 16 16" className="h-3.5 w-3.5" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M3 8.5l3 3 7-7" /></svg>
                            : <svg viewBox="0 0 16 16" className="h-3.5 w-3.5" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round"><circle cx="8" cy="8" r="5.5" /><path d="M8 5.5V8l1.8 1.2" /></svg>}
                        </span>
                        <div className="min-w-0">
                          <div className="text-xs font-medium uppercase tracking-wider text-slate-400">{role}</div>
                          <div className={`truncate text-sm ${s ? 'text-slate-100' : 'text-slate-500'}`}>
                            {s ? `${s.user_name ?? 'unknown'} · ${fmtDate(s.at)}` : 'pending'}
                          </div>
                        </div>
                      </li>))}
                  </ul>
                </section>)}

              {inst.events && inst.events.length > 0 && (
                <details className="group mt-7 rounded-lg border border-slate-700/70 bg-slate-800 shadow-panel">
                  <summary className="flex cursor-pointer select-none items-center gap-2 px-4 py-3 text-sm font-semibold tracking-tight text-slate-100">
                    <svg viewBox="0 0 16 16" className="h-3.5 w-3.5 text-slate-500 transition-transform duration-200 group-open:rotate-90" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round"><path d="M6 4l4 4-4 4" /></svg>
                    History
                    <span className="font-mono text-xs font-normal text-slate-500">({inst.events.length})</span>
                  </summary>
                  <ol className="border-t border-slate-700/70 px-4 py-3">
                    {inst.events.map((e) => (
                      <li key={e.id} className="relative flex gap-3 py-1 text-xs">
                        <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-slate-600" aria-hidden />
                        <span className="font-mono text-slate-500 tabular-nums">{fmtStamp(e.created_at)}</span>
                        <span className="text-slate-300">
                          {`${e.user_name ?? 'unknown'} ${EVENT_LABEL[e.event] ?? e.event}${e.role ? ` as ${e.role.toUpperCase()}` : ''}`}
                        </span>
                      </li>))}
                  </ol>
                </details>)}
            </div>

            <footer className="flex flex-wrap items-center gap-2 border-t border-slate-700 bg-slate-800 px-5 py-3">
              {editable && (
                <button onClick={() => save.mutate()} disabled={save.isPending} className={BTN_SECONDARY}>
                  {save.isPending && <Spinner />}Save
                </button>)}
              {editable && (
                <button onClick={() => submit.mutate()} disabled={submit.isPending} className={BTN_PRIMARY}>
                  {submit.isPending && <Spinner />}Submit
                </button>)}
              {!editable && (
                <button onClick={() => reopen.mutate()} disabled={reopen.isPending} className={BTN_AMBER}>
                  {reopen.isPending && <Spinner />}Reopen
                </button>)}
              {!editable && pendingRoles.map((r) => (
                <button key={r} onClick={() => sign.mutate(r)} disabled={sign.isPending} className={BTN_EMERALD}>
                  Sign as {r.toUpperCase()}
                </button>))}
              <a href={`${API_BASE_URL}/v1/forms/instances/${instanceId}/export.pdf`} target="_blank" rel="noreferrer"
                className={`${BTN_SECONDARY} ml-auto`}>
                <svg viewBox="0 0 16 16" className="h-3.5 w-3.5 text-slate-400" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"><path d="M8 2v8m0 0l3-3m-3 3L5 7M3 11v2h10v-2" /></svg>
                Export PDF
              </a>
            </footer>
          </>
        )}
      </aside>
    </div>
  );
}
