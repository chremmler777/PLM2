/**
 * Moldflow timing overview of a project (project status panel): one block per
 * tool, led by the customer identity ("<Brose no.> / <Scout no.> <name>" per
 * produced article, then "KTX <tool no.>"), one line per Moldflow version /
 * cavity layout. Tool editors (Tool Engineer or admin) edit in place: dates
 * and text on click (Enter or leaving the field saves, Escape cancels),
 * statuses with their select, a new version per tool. Everyone else reads.
 */
import { useRef, useState, type ReactNode } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import {
  articleIdentity, createMoldflow, deleteMoldflow, getProjectMoldflow, moldflowKey, nextVersion, updateMoldflow,
  MF_INPUT_LABELS, MF_INPUT_STATUSES, MF_STATUSES, MF_STATUS_LABELS, MF_STATUS_TONE,
  type MfDateKey, type MfInputStatus, type MfStatus, type MoldflowPatch, type MoldflowRow, type MoldflowTool,
} from '../../api/moldflow';
import { apiErrorMessage } from '../../lib/apiError';
import { WORKSHEET_KEY } from '../../hooks/queries/useWorksheet';
import { MF_TONE_CLASS } from './MoldflowStatusChip';
import MoldflowStatusChip from './MoldflowStatusChip';

const INPUT_TONE: Record<MfInputStatus, string> = {
  open: 'bg-slate-700 text-slate-300',
  in_progress: 'bg-amber-600/25 text-amber-200',
  ready: 'bg-emerald-900/50 text-emerald-200',
  'n/a': 'bg-slate-800 text-slate-500',
};
const INPUTS: { key: 'geometry_status' | 'gate_status' | 'udb_status'; short: string; label: string }[] = [
  { key: 'geometry_status', short: 'Geo', label: 'Geometry' },
  { key: 'gate_status', short: 'Gate', label: 'Gate' },
  { key: 'udb_status', short: 'UDB', label: 'UDB (material data)' },
];
const DATE_COLUMNS: { key: MfDateKey; label: string; title?: string }[] = [
  { key: 'mf_requested_on', label: 'MF requested' },
  { key: 'received_on', label: 'Received' },
  { key: 'ktx_review_on', label: 'KTX review' },
  { key: 'sent_customer_on', label: 'Sent to customer', title: 'Report sent to the customer (Brose)' },
];

type Save = (patch: MoldflowPatch) => void;

/** Shows the value; a click (editors only) turns it into a field. */
function Editable({ value, kind, label, canEdit, onSave, placeholder = '—', className = '', render }: {
  value: string | null; kind: 'date' | 'text' | 'area'; label: string; canEdit: boolean; onSave(v: string | null): void;
  placeholder?: string; className?: string; render?: (v: string) => ReactNode;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState('');
  const cancelled = useRef(false);
  const shown = value ? (render ? render(value) : value) : <span className="text-slate-600">{placeholder}</span>;
  if (!canEdit) return <span className={className}>{shown}</span>;
  if (!editing) {
    return (
      <button type="button" aria-label={`Edit ${label}`} title={value ? `${label}: ${value}` : `Set ${label}`}
        onClick={() => { cancelled.current = false; setDraft(value ?? ''); setEditing(true); }}
        className={`text-left rounded px-0.5 -mx-0.5 hover:bg-slate-700/70 focus-visible:outline focus-visible:outline-1 focus-visible:outline-blue-400 ${className}`}>
        {shown}
      </button>
    );
  }
  const commit = () => {
    setEditing(false);
    if (cancelled.current) return;
    const next = draft.trim() === '' ? null : draft.trim();
    if (next !== (value ?? null)) onSave(next);
  };
  const common = {
    'aria-label': label, autoFocus: true, value: draft, onBlur: commit,
    onChange: (e: { target: { value: string } }) => setDraft(e.target.value),
    onKeyDown: (e: React.KeyboardEvent) => {
      if (e.key === 'Escape') { e.preventDefault(); cancelled.current = true; setEditing(false); }
      if (e.key === 'Enter' && (kind !== 'area' || e.ctrlKey || e.metaKey)) { e.preventDefault(); commit(); }
    },
    className: 'w-full bg-slate-900 border border-slate-600 rounded px-1 py-0.5 text-xs text-slate-100 [color-scheme:dark]',
  };
  return kind === 'area' ? <textarea rows={3} {...common} /> : <input type={kind === 'date' ? 'date' : 'text'} {...common} />;
}

function InputBadge({ row, input, canEdit, save }: {
  row: MoldflowRow; input: (typeof INPUTS)[number]; canEdit: boolean; save: Save;
}) {
  const v = row[input.key];
  const cls = `px-1 rounded text-[10px] leading-4 ${INPUT_TONE[v]}`;
  const title = `${input.label}: ${MF_INPUT_LABELS[v]}`;
  if (!canEdit) return <span className={cls} title={title} data-testid={`mf-input-${input.short.toLowerCase()}`}>{input.short} {v === 'ready' ? 'ok' : MF_INPUT_LABELS[v]}</span>;
  return (
    <select aria-label={`${input.label} status`} title={title} value={v} data-testid={`mf-input-${input.short.toLowerCase()}`}
      onChange={(e) => save({ [input.key]: e.target.value as MfInputStatus })}
      className={`${cls} appearance-none cursor-pointer border-0 focus-visible:outline focus-visible:outline-1 focus-visible:outline-blue-400`}>
      {MF_INPUT_STATUSES.map((s) => <option key={s} value={s}>{input.short} {s === 'ready' ? 'ok' : MF_INPUT_LABELS[s]}</option>)}
    </select>
  );
}

function StatusCell({ row, canEdit, save }: { row: MoldflowRow; canEdit: boolean; save: Save }) {
  const differs = row.derived_status !== row.status;
  const hint = differs ? `Dates and inputs point to: ${MF_STATUS_LABELS[row.derived_status]}` : undefined;
  if (!canEdit) return <span title={hint}><MoldflowStatusChip status={row.status} /></span>;
  return (
    <select aria-label="Moldflow status" title={hint} value={row.status} data-testid="mf-status-select"
      onChange={(e) => save({ status: e.target.value as MfStatus })}
      className={`px-1.5 rounded text-[11px] leading-5 appearance-none cursor-pointer border-0 focus-visible:outline focus-visible:outline-1 focus-visible:outline-blue-400 ${MF_TONE_CLASS[MF_STATUS_TONE[row.status]]}`}>
      {MF_STATUSES.map((s) => <option key={s} value={s}>{MF_STATUS_LABELS[s]}</option>)}
    </select>
  );
}

function ToolIdentity({ t, projectCode }: { t: MoldflowTool; projectCode: string | null }) {
  return (
    <div className="min-w-0">
      {t.articles.length === 0 && <div className="text-slate-400">{t.tool.name}</div>}
      {t.articles.map((a) => (
        <div key={a.part_id} className="text-slate-100 truncate" title={articleIdentity(a, projectCode)}>
          {articleIdentity(a, projectCode)}
        </div>
      ))}
      <div className="text-slate-400">
        KTX <span className="font-mono text-slate-300">{t.tool.part_number}</span>
        {t.tool.cavities && <span className="text-slate-500"> · {t.tool.cavities} cav</span>}
      </div>
    </div>
  );
}

function RowCells({ row, canEdit, save, onDelete }: { row: MoldflowRow; canEdit: boolean; save: Save; onDelete(): void }) {
  return (
    <>
      <td className="px-2 py-1.5 align-top whitespace-nowrap">
        <span className="font-mono text-slate-200">{row.version}</span>
        <Editable value={row.cavity_layout} kind="text" label="Cavity layout" canEdit={canEdit} placeholder="layout"
          className="ml-1 text-slate-400" render={(v) => `(${v})`} onSave={(v) => save({ cavity_layout: v })} />
      </td>
      <td className="px-2 py-1.5 align-top">
        <div className="flex gap-1">
          {INPUTS.map((i) => <InputBadge key={i.key} row={row} input={i} canEdit={canEdit} save={save} />)}
        </div>
        <div className="mt-0.5 text-slate-300" title={row.udb_source ?? undefined}>
          <Editable value={row.material_label} kind="text" label="Material" canEdit={canEdit} placeholder="material"
            onSave={(v) => save({ material_label: v })} />
        </div>
      </td>
      {DATE_COLUMNS.map((d) => (
        <td key={d.key} className="px-2 py-1.5 align-top whitespace-nowrap tabular-nums text-slate-200">
          <Editable value={row[d.key]} kind="date" label={d.label} canEdit={canEdit} onSave={(v) => save({ [d.key]: v })} />
        </td>
      ))}
      <td className="px-2 py-1.5 align-top max-w-[14rem]">
        <div className="tabular-nums text-slate-200">
          <Editable value={row.customer_feedback_on} kind="date" label="Customer feedback date" canEdit={canEdit}
            onSave={(v) => save({ customer_feedback_on: v })} />
        </div>
        <Editable value={row.customer_feedback} kind="area" label="Customer feedback" canEdit={canEdit} placeholder="no feedback"
          className="block text-slate-400 whitespace-pre-line line-clamp-3" onSave={(v) => save({ customer_feedback: v })} />
      </td>
      <td className="px-2 py-1.5 align-top whitespace-nowrap tabular-nums text-slate-200">
        <Editable value={row.final_on} kind="date" label="Final" canEdit={canEdit} onSave={(v) => save({ final_on: v })} />
      </td>
      <td className="px-2 py-1.5 align-top"><StatusCell row={row} canEdit={canEdit} save={save} /></td>
      <td className="px-2 py-1.5 align-top max-w-[18rem]">
        <Editable value={row.blockers} kind="area" label="Blockers" canEdit={canEdit} placeholder="no blocker"
          className="block text-amber-300 whitespace-pre-line line-clamp-3" onSave={(v) => save({ blockers: v })} />
        <Editable value={row.owner} kind="text" label="Owner" canEdit={canEdit} placeholder="owner"
          className="block text-slate-400" onSave={(v) => save({ owner: v })} />
        {row.notes && <div className="text-slate-500 line-clamp-2" title={row.notes}>{row.notes}</div>}
      </td>
      <td className="px-1 py-1.5 align-top text-right">
        {canEdit && (
          <button type="button" aria-label={`Delete ${row.version}${row.cavity_layout ? ` (${row.cavity_layout})` : ''}`}
            title="Delete this Moldflow row" onClick={onDelete}
            className="px-1 text-slate-500 hover:text-red-300 focus-visible:outline focus-visible:outline-1 focus-visible:outline-blue-400">
            ×
          </button>
        )}
      </td>
    </>
  );
}

const HEADERS: { label: string; title?: string }[] = [
  { label: 'Tool' }, { label: 'Ver.' }, { label: 'Inputs', title: 'Geometry, gate and UDB state; material' },
  ...DATE_COLUMNS.map((d) => ({ label: d.label, title: d.title })),
  { label: 'Customer feedback' }, { label: 'V2 / final', title: 'Date the final Moldflow was accepted' },
  { label: 'Status' }, { label: 'Blockers / owner' }, { label: '' },
];

export default function MoldflowPanel({ projectId, projectCode = null }: { projectId: number; projectCode?: string | null }) {
  const qc = useQueryClient();
  const query = useQuery({ queryKey: moldflowKey(projectId), queryFn: () => getProjectMoldflow(projectId), enabled: !!projectId });
  const refresh = () => {
    qc.invalidateQueries({ queryKey: moldflowKey(projectId) });
    qc.invalidateQueries({ queryKey: [WORKSHEET_KEY, projectId] });
  };
  const onError = (e: unknown) => toast.error(apiErrorMessage(e, 'Moldflow change not saved'));
  const update = useMutation({
    mutationFn: ({ id, patch }: { id: number; patch: MoldflowPatch }) => updateMoldflow(id, patch),
    onSuccess: refresh, onError,
  });
  const create = useMutation({
    mutationFn: ({ toolId, version }: { toolId: number; version: string }) => createMoldflow(toolId, { version }),
    onSuccess: refresh, onError,
  });
  const remove = useMutation({ mutationFn: (id: number) => deleteMoldflow(id), onSuccess: refresh, onError });

  if (query.isLoading) return <p className="text-xs text-slate-400">Loading Moldflow…</p>;
  if (query.isError) return <p className="text-xs text-red-300">Moldflow overview could not be loaded: {apiErrorMessage(query.error)}</p>;
  const data = query.data;
  const tools = Array.isArray(data?.tools) ? data!.tools : [];
  const canEdit = !!data?.can_edit;
  if (tools.length === 0) return <p className="text-xs text-slate-400">This project has no tools yet.</p>;

  const confirmDelete = (r: MoldflowRow, tool: string) => {
    if (window.confirm(`Delete Moldflow ${r.version}${r.cavity_layout ? ` (${r.cavity_layout})` : ''} of tool ${tool}?`)) remove.mutate(r.id);
  };

  return (
    <div data-testid="moldflow-panel" className="text-xs">
      <div className="flex items-baseline gap-3 mb-2">
        <h3 className="text-sm font-semibold text-slate-100">Moldflow timing</h3>
        <span className="text-slate-400">Latest version per tool first; one line per version and cavity layout.</span>
      </div>
      <div className="overflow-x-auto">
        <table className="min-w-full border-collapse">
          <thead>
            <tr className="text-left text-[11px] text-slate-400 border-b border-slate-700">
              {HEADERS.map((h, i) => (
                <th key={i} scope="col" title={h.title}
                  className={`px-2 py-1 font-medium whitespace-nowrap ${i === 0 ? 'sticky left-0 z-10 bg-slate-800 min-w-[16rem]' : ''}`}>
                  {h.label}
                </th>
              ))}
            </tr>
          </thead>
          {tools.map((t) => {
            const rows = [...t.rows].reverse();  // newest version on top
            const add = canEdit && (
              <button type="button" data-testid={`mf-add-${t.tool.part_number}`} disabled={create.isPending}
                onClick={() => create.mutate({ toolId: t.tool.part_id, version: nextVersion(t.rows) })}
                className="mt-1 px-1.5 py-0.5 rounded bg-slate-700 hover:bg-slate-600 text-slate-200 disabled:opacity-50">
                + {nextVersion(t.rows)}
              </button>
            );
            return (
              <tbody key={t.tool.part_id} data-testid={`mf-tool-${t.tool.part_number}`} className="border-b border-slate-700">
                {rows.length === 0 ? (
                  <tr>
                    <th scope="row" className="sticky left-0 bg-slate-800 px-2 py-1.5 align-top text-left font-normal">
                      <ToolIdentity t={t} projectCode={projectCode} />{add}
                    </th>
                    <td colSpan={HEADERS.length - 1} className="px-2 py-1.5 align-top text-slate-500">No Moldflow yet</td>
                  </tr>
                ) : rows.map((r, i) => (
                  <tr key={r.id} data-testid={`mf-row-${r.id}`} className={i > 0 ? 'text-slate-400 [&_td]:opacity-80' : ''}>
                    {i === 0 && (
                      <th scope="row" rowSpan={rows.length}
                        className="sticky left-0 bg-slate-800 px-2 py-1.5 align-top text-left font-normal">
                        <ToolIdentity t={t} projectCode={projectCode} />{add}
                      </th>
                    )}
                    <RowCells row={r} canEdit={canEdit}
                      save={(patch) => update.mutate({ id: r.id, patch })}
                      onDelete={() => confirmDelete(r, t.tool.part_number)} />
                  </tr>
                ))}
              </tbody>
            );
          })}
        </table>
      </div>
    </div>
  );
}
