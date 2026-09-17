/**
 * ProjectSepSection - SEP Q-Gate panel (GB-DP-0001 stage-gate process).
 * Gate stepper with green/yellow/red status, per-gate checklist grouped by
 * department (tri-state items), forms tab, and PM+Quality dual sign-off.
 */
import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import client from '../api/client';
import { toast } from 'sonner';
import FormPanel from '../forms/FormPanel';
import ProjectFormsTab from '../forms/ProjectFormsTab';
import type { ItemFormInfo } from '../forms/types';

interface SepItem {
  id: number;
  gate_id: number;
  item_no: number;
  title_de: string;
  title_en: string;
  department: string;
  status: 'open' | 'done' | 'not_applicable';
  remark: string | null;
  responsible_id: number | null;
  responsible_name: string | null;
  completed_at: string | null;
  lessons_link: boolean;
  form: ItemFormInfo | null;
  references: { title: string; path: string }[];
}

interface SepGate {
  id: number;
  project_id: number;
  code: string;
  seq: number;
  phase_de: string;
  phase_en: string;
  status: 'pending' | 'in_progress' | 'closed';
  color: 'green' | 'yellow' | 'red';
  target_date: string | null;
  pm_signed_name: string | null;
  pm_signed_at: string | null;
  quality_signed_name: string | null;
  quality_signed_at: string | null;
  progress: { done: number; open: number; not_applicable: number; total: number; pct: number };
  open_risks: number;
  items: SepItem[];
}

interface SepState {
  active: boolean;
  gates: SepGate[];
  rollup?: { total: { done: number; open: number; total: number; pct: number } };
}

interface UserOption { id: number; name: string }

const COLOR_BG: Record<string, string> = {
  green: 'bg-emerald-500',
  yellow: 'bg-amber-400',
  red: 'bg-red-500',
};
const ITEM_STATES: Array<{ value: SepItem['status']; label: string; active: string }> = [
  { value: 'open', label: 'open', active: 'bg-amber-500 text-slate-900' },
  { value: 'done', label: 'done', active: 'bg-emerald-500 text-slate-900' },
  { value: 'not_applicable', label: 'n/a', active: 'bg-slate-400 text-slate-900' },
];

function fmtDate(iso: string | null): string {
  return iso ? iso.slice(0, 10) : '—';
}

function GateStepper({ gates, selected, onSelect }: {
  gates: SepGate[]; selected: number | null; onSelect: (id: number) => void;
}) {
  return (
    <div className="flex flex-wrap gap-1.5">
      {gates.map((g) => {
        const isSel = g.id === selected;
        const dot = g.status === 'pending' ? 'bg-slate-600' : COLOR_BG[g.color];
        return (
          <button
            key={g.id}
            onClick={() => onSelect(g.id)}
            title={`${g.phase_en} — ${g.progress.pct}% (${g.progress.done}/${g.progress.total - g.progress.not_applicable} done)`}
            className={`flex items-center gap-1.5 px-2.5 py-1.5 rounded border text-xs ${
              isSel ? 'border-blue-400 bg-slate-700' : 'border-slate-600 bg-slate-800 hover:border-slate-400'
            } ${g.status === 'closed' ? 'opacity-80' : ''}`}
          >
            <span className={`w-2.5 h-2.5 rounded-full ${dot}`} />
            <span className="text-slate-200 font-semibold">{g.code}</span>
            <span className="text-slate-400">{g.progress.pct}%</span>
            {g.status === 'closed' && <span className="text-emerald-400">🔒</span>}
          </button>
        );
      })}
    </div>
  );
}

function ItemRow({ item, locked, users, projectId, onOpenForm }: {
  item: SepItem; locked: boolean; users: UserOption[]; projectId: number; onOpenForm: (id: number) => void;
}) {
  const queryClient = useQueryClient();
  const [remark, setRemark] = useState(item.remark ?? '');

  // The form behind a work package may not exist yet — first click creates it.
  // A racing second creation of a `single` form comes back as 409 with the
  // instance that won, so open that one instead of erroring.
  const openForm = useMutation({
    mutationFn: async () => {
      if (item.form?.instance_id) return { id: item.form.instance_id, created: false };
      const res = await client.post(`/v1/forms/projects/${projectId}/instances`, { key: item.form?.key });
      return { id: (res.data as { id: number }).id, created: true };
    },
    onSuccess: ({ id, created }) => {
      // Nothing changed server-side when the instance already existed.
      if (created) {
        queryClient.invalidateQueries({ queryKey: ['sep'] });
        queryClient.invalidateQueries({ queryKey: ['forms'] });
        queryClient.invalidateQueries({ queryKey: ['my-forms'] });
      }
      onOpenForm(id);
    },
    onError: (e: unknown) => {
      const d = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
      const existing = (d as { instance_id?: number } | undefined)?.instance_id;
      if (existing) onOpenForm(existing);
      else toast.error(typeof d === 'string' ? d : 'Could not open form');
    },
  });

  const update = useMutation({
    mutationFn: async (patch: Record<string, unknown>) =>
      client.patch(`/v1/sep/items/${item.id}`, patch),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['sep'] }),
    onError: (e: any) => toast.error(e.response?.data?.detail || 'Update failed'),
  });

  return (
    <div className="flex items-start gap-2 px-2 py-1.5 rounded bg-slate-900/40 text-sm">
      <span className="text-slate-500 text-xs w-6 text-right pt-0.5">{item.item_no}</span>
      <div className="flex-1 min-w-0">
        <div className="text-slate-200 leading-snug" title={item.title_de}>
          {item.title_en}
          {item.lessons_link && (
            <a href={`/lessons`} className="ml-1.5 text-xs text-blue-400 hover:text-blue-300" title="Linked to lessons learned reuse">
              📘 lessons
            </a>
          )}
          {item.form && (
            <button
              type="button"
              onClick={() => openForm.mutate()}
              className={`ml-1.5 inline-flex items-center gap-1 rounded-md border px-1.5 py-0.5 text-[11px] font-medium transition-colors duration-150 ${
                item.form.status === 'submitted'
                  ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300 hover:bg-emerald-500/20'
                  : 'border-sky-500/30 bg-sky-500/10 text-sky-300 hover:bg-sky-500/20'
              }`}
              title={item.form.title}
            >
              <svg viewBox="0 0 16 16" className="h-3 w-3" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"><path d="M4 2.5h5.5L13 6v7.5H4z M9.5 2.5V6H13 M6 9h4M6 11h4" /></svg>
              {item.form.status ?? 'open form'}
            </button>
          )}
          {item.references.map((r) => (
            <span key={r.path} className="ml-1.5 text-xs text-slate-500" title={r.path}>📎 {r.title}</span>
          ))}
        </div>
        {(item.remark || !locked) && (
          <input
            value={remark}
            disabled={locked}
            onChange={(e) => setRemark(e.target.value)}
            onBlur={() => remark !== (item.remark ?? '') && update.mutate({ remark })}
            placeholder="Remark / actions…"
            className="mt-0.5 w-full bg-transparent border-b border-slate-700/60 focus:border-slate-500 text-xs text-slate-400 placeholder-slate-600 outline-none disabled:border-transparent"
          />
        )}
      </div>
      <select
        value={item.responsible_id ?? ''}
        disabled={locked}
        onChange={(e) =>
          update.mutate(e.target.value ? { responsible_id: Number(e.target.value) } : { clear_responsible: true })
        }
        className="bg-slate-700 border border-slate-600 rounded text-xs text-slate-300 px-1 py-0.5 max-w-[110px] disabled:opacity-50"
      >
        <option value="">unassigned</option>
        {users.map((u) => <option key={u.id} value={u.id}>{u.name}</option>)}
      </select>
      <div className="flex rounded overflow-hidden border border-slate-600">
        {ITEM_STATES.map((s) => (
          <button
            key={s.value}
            disabled={locked}
            onClick={() => item.status !== s.value && update.mutate({ status: s.value })}
            className={`px-1.5 py-0.5 text-[11px] ${
              item.status === s.value ? s.active : 'bg-slate-800 text-slate-400 hover:bg-slate-700'
            } disabled:cursor-not-allowed`}
          >
            {s.label}
          </button>
        ))}
      </div>
    </div>
  );
}

function GateDetail({ gate, users }: { gate: SepGate; users: UserOption[] }) {
  const queryClient = useQueryClient();
  const [tab, setTab] = useState<'checklist' | 'forms'>('checklist');
  const [openForm, setOpenForm] = useState<number | null>(null);
  const locked = gate.status === 'closed';

  const signOff = useMutation({
    mutationFn: async (role: 'pm' | 'quality') =>
      client.post(`/v1/sep/gates/${gate.id}/sign-off`, { role }),
    onSuccess: (res) => {
      queryClient.invalidateQueries({ queryKey: ['sep'] });
      toast.success(res.data.status === 'closed' ? `Gate ${gate.code} closed 🔒` : 'Signed off');
    },
    onError: (e: any) => toast.error(e.response?.data?.detail || 'Sign-off rejected'),
  });

  const byDept = gate.items.reduce<Record<string, SepItem[]>>((acc, i) => {
    (acc[i.department] ??= []).push(i);
    return acc;
  }, {});

  return (
    <div className="mt-3 space-y-3">
      <div className="flex items-center gap-3 flex-wrap">
        <div className="flex-1 min-w-[200px]">
          <div className="text-sm text-slate-200 font-semibold">{gate.code} — {gate.phase_en}</div>
          <div className="text-xs text-slate-500">{gate.phase_de} · target {fmtDate(gate.target_date)}</div>
        </div>
        <div className="w-40 bg-slate-700 rounded-full h-2 overflow-hidden">
          <div
            className={`h-2 ${gate.status === 'pending' ? 'bg-slate-500' : COLOR_BG[gate.color]}`}
            style={{ width: `${gate.progress.pct}%` }}
          />
        </div>
        <span className="text-xs text-slate-400">
          {gate.progress.done} done · {gate.progress.open} open · {gate.progress.not_applicable} n/a
        </span>
      </div>

      <div className="flex items-center gap-2 text-xs">
        {(['pm', 'quality'] as const).map((role) => {
          const signedName = role === 'pm' ? gate.pm_signed_name : gate.quality_signed_name;
          const signedAt = role === 'pm' ? gate.pm_signed_at : gate.quality_signed_at;
          return signedName ? (
            <span key={role} className="px-2 py-1 rounded bg-emerald-600/20 text-emerald-300">
              ✓ {role === 'pm' ? 'PM' : 'Quality'}: {signedName} ({fmtDate(signedAt)})
            </span>
          ) : (
            <button
              key={role}
              disabled={gate.status !== 'in_progress' || signOff.isPending}
              onClick={() => signOff.mutate(role)}
              className="px-2 py-1 rounded border border-slate-600 text-slate-300 hover:border-slate-400 disabled:opacity-40"
            >
              Sign off as {role === 'pm' ? 'PM' : 'Quality'}
            </button>
          );
        })}
        {gate.color === 'yellow' && !locked && (
          <span className="text-amber-300">⚠ open items — sign-off needs a risk entry with action plan (≤14 days)</span>
        )}
        {gate.color === 'red' && !locked && (
          <span className="text-red-300">⛔ high risk live — see risk assessment form</span>
        )}
      </div>

      <div className="flex gap-2 border-b border-slate-700 text-xs">
        {(['checklist', 'forms'] as const).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`px-3 py-1.5 -mb-px border-b-2 ${
              tab === t ? 'border-blue-400 text-blue-300' : 'border-transparent text-slate-400 hover:text-slate-300'
            }`}
          >
            {t === 'checklist' ? `Checklist (${gate.progress.total})` : 'Forms'}
          </button>
        ))}
      </div>

      {tab === 'checklist' ? (
        <div className="space-y-3 max-h-[28rem] overflow-y-auto pr-1">
          {Object.entries(byDept).map(([dept, items]) => (
            <div key={dept}>
              <div className="text-[11px] uppercase tracking-wide text-slate-500 mb-1">
                {dept} ({items.filter((i) => i.status === 'done').length}/{items.length})
              </div>
              <div className="space-y-1">
                {items.map((i) => (
                  <ItemRow key={i.id} item={i} locked={locked} users={users}
                           projectId={gate.project_id} onOpenForm={setOpenForm} />
                ))}
              </div>
            </div>
          ))}
        </div>
      ) : (
        <ProjectFormsTab projectId={gate.project_id} />
      )}

      {openForm !== null && <FormPanel key={openForm} instanceId={openForm} onClose={() => setOpenForm(null)} />}
    </div>
  );
}

export default function ProjectSepSection({ projectId }: { projectId: number }) {
  const queryClient = useQueryClient();
  const [expanded, setExpanded] = useState(false);
  const [selectedGate, setSelectedGate] = useState<number | null>(null);

  const { data: sep } = useQuery({
    queryKey: ['sep', projectId],
    queryFn: async () => (await client.get(`/v1/sep/projects/${projectId}`)).data as SepState,
  });

  const { data: users } = useQuery({
    queryKey: ['assignable-users'],
    queryFn: async () => (await client.get('/v1/lessons/assignable-users')).data as UserOption[],
  });

  const activate = useMutation({
    mutationFn: async () => client.post(`/v1/sep/projects/${projectId}/activate`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['sep'] });
      toast.success('SEP activated: 7 gates, 232 work items');
    },
    onError: (e: any) => toast.error(e.response?.data?.detail || 'Activation failed'),
  });

  if (!sep) return null;

  if (!sep.active) {
    return (
      <div className="mb-4 bg-slate-800 rounded-lg border border-slate-700 p-3 flex items-center gap-3">
        <span className="text-sm font-semibold text-slate-300">🚦 SEP Q-Gates</span>
        <span className="text-xs text-slate-500 flex-1">
          Stage-gate process per GB-DP-0001 (7 gates, 232 work items) not active for this project.
        </span>
        <button
          onClick={() => activate.mutate()}
          disabled={activate.isPending}
          className="text-xs px-3 py-1 rounded bg-blue-600 hover:bg-blue-500 text-white disabled:opacity-50"
        >
          Activate SEP
        </button>
      </div>
    );
  }

  const current = sep.gates.find((g) => g.status === 'in_progress');
  const gate = sep.gates.find((g) => g.id === (selectedGate ?? current?.id)) ?? sep.gates[0];

  return (
    <div className="mb-4 bg-slate-800 rounded-lg border border-slate-700 p-3">
      <div className="flex items-center gap-3 flex-wrap mb-2">
        <button onClick={() => setExpanded(!expanded)} className="text-sm font-semibold text-slate-300">
          🚦 SEP Q-Gates {expanded ? '▾' : '▸'}
        </button>
        {current && <span className="text-xs text-slate-400">current: <span className="text-slate-200">{current.code}</span></span>}
        {sep.rollup && (
          <span className="text-xs text-slate-400 ml-auto">
            total {sep.rollup.total.pct}% · {sep.rollup.total.done}/{sep.rollup.total.total} work packages
          </span>
        )}
      </div>
      <GateStepper
        gates={sep.gates}
        selected={gate?.id ?? null}
        onSelect={(id) => { setSelectedGate(id); setExpanded(true); }}
      />
      {expanded && gate && <GateDetail gate={gate} users={users ?? []} />}
    </div>
  );
}
