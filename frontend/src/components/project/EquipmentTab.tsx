/**
 * Equipment card: one gauge, assembly station or EOAT. Which tools it serves (one,
 * several or none: an assembly operation or assembly gauge needs no tool), which
 * articles it takes in or checks (assembly equipment with an amount per article),
 * and its history. Links come by drag and drop from the item list: a tool row adds a
 * served tool, an article row adds an article. Field edits go through a dialog that
 * asks whether it is a correction or a change; marking obsolete asks for a note.
 * The backend enforces the rights (equipment_rights.py); this only hides controls.
 */
import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import client from '../../api/client';
import { apiErrorMessage } from '../../lib/apiError';
import { formatDate, formatDateTime } from '../../lib/format';
import { useCanEditAssemblyEquipment, useCanEditGauges } from '../../hooks/queries/useToolRights';
import type { Part } from './projectTypes';

interface EquipmentRelation {
  id: number;
  relation_type: string;
  direction: 'outgoing' | 'incoming';
  other_part_id: number;
  other_part_number: string;
  other_part_name: string;
  other_item_category: string;
  other_customer_part_number?: string | null;
  quantity?: number | null;
}

interface HistoryEntry {
  id: number;
  at: string;
  by_name: string | null;
  kind: 'correction' | 'change' | 'obsolete' | 'reactivated' | null;
  description: string;
  note?: string | null;
}

const KIND_TAG: Record<string, { label: string; className: string }> = {
  correction: { label: 'Correction', className: 'bg-slate-600 text-slate-200' },
  change: { label: 'Change', className: 'bg-sky-900/60 text-sky-200' },
  obsolete: { label: 'Obsolete', className: 'bg-amber-900/60 text-amber-200' },
  reactivated: { label: 'Reactivated', className: 'bg-emerald-900/60 text-emerald-200' },
};

const INPUT = 'w-full bg-slate-700 border border-slate-600 rounded px-3 py-2 text-slate-100 text-sm';
const LABEL = 'block text-sm font-medium text-slate-300 mb-1';
const BTN = 'px-3 py-1 rounded text-xs font-medium';

/**
 * Gauge, EOAT or Assembly equipment. There is no EOAT category: an EOAT is assembly
 * equipment numbered <tool number>-1x, so only a number that starts like a tool number
 * counts (a freely typed "ASSY-OP-10" is an assembly operation, not an EOAT).
 */
export function equipmentKindLabel(part: Pick<Part, 'item_category' | 'part_number'>): string {
  if (part.item_category === 'gauge') return 'Gauge';
  return /^\d[\d-]*-1\d$/.test(part.part_number) ? 'EOAT' : 'Assembly equipment';
}

export interface EquipmentTabProps {
  projectId: number;
  part: Part;
  parts: Part[];
  /** The item-list row being dragged, so the card knows whether it can take the drop. */
  draggingPartId?: number | null;
  onDropDone?(): void;
  onOpenPart(partId: number): void;
}

export default function EquipmentTab({ projectId, part, parts, draggingPartId = null, onDropDone, onOpenPart }: EquipmentTabProps) {
  const queryClient = useQueryClient();
  const isGauge = part.item_category === 'gauge';
  const canEditGauges = useCanEditGauges();
  const canEditAssemblyEquipment = useCanEditAssemblyEquipment();
  const canEdit = isGauge ? canEditGauges : canEditAssemblyEquipment;
  const obsolete = !!part.obsolete_at;
  const editable = canEdit && !obsolete;
  const articleLink = isGauge ? 'checks' : 'assembles';
  const [dragOver, setDragOver] = useState(false);
  const [dialog, setDialog] = useState<'edit' | 'obsolete' | null>(null);

  const { data: relations } = useQuery({
    queryKey: ['part-relations', part.id],
    queryFn: async () => (await client.get(`/v1/parts/${part.id}/relations`)).data as EquipmentRelation[],
  });
  const { data: history } = useQuery({
    queryKey: ['part-history', part.id],
    queryFn: async () => (await client.get(`/v1/parts/${part.id}/history`)).data as HistoryEntry[],
  });
  const own = (relations ?? []).filter((r) => r.direction === 'outgoing');
  const tools = own.filter((r) => r.relation_type === 'serves');
  const articles = own.filter((r) => r.relation_type === articleLink);

  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ['part-relations'] });
    queryClient.invalidateQueries({ queryKey: ['part-history', part.id] });
    queryClient.invalidateQueries({ queryKey: ['project-structure', projectId] });
    queryClient.invalidateQueries({ queryKey: ['parts', projectId] });
  };
  const onError = (fallback: string) => (error: unknown) => { toast.error(apiErrorMessage(error, fallback)); };

  const linkMutation = useMutation({
    mutationFn: async ({ other, relationType }: { other: Part; relationType: string }) => {
      await client.post(`/v1/parts/${part.id}/relations`, { to_part_id: other.id, relation_type: relationType });
    },
    onSuccess: (_d, { other, relationType }) => {
      toast.success(relationType === 'serves'
        ? `Linked: ${part.part_number} serves tool ${other.part_number}`
        : `Linked: ${part.part_number} ${relationType} ${other.part_number}`);
      refresh();
    },
    onError: onError('Failed to link the items'),
  });
  const unlinkMutation = useMutation({
    mutationFn: async (relationId: number) => { await client.delete(`/v1/parts/relations/${relationId}`); },
    onSuccess: refresh,
    onError: onError('Failed to remove the link'),
  });
  const quantityMutation = useMutation({
    mutationFn: async ({ relationId, quantity }: { relationId: number; quantity: number }) => {
      await client.patch(`/v1/parts/relations/${relationId}`, { quantity });
    },
    onSuccess: refresh,
    onError: onError('Failed to save the amount'),
  });
  const reactivateMutation = useMutation({
    mutationFn: async () => { await client.post(`/v1/parts/${part.id}/reactivate`, {}); },
    onSuccess: () => { toast.success(`${part.part_number} is back in use`); refresh(); },
    onError: onError('Failed to reactivate'),
  });

  // What a dragged item-list row would become here: a tool is served, an article is taken in or checked.
  const dragged = draggingPartId === null ? undefined : parts.find((p) => p.id === draggingPartId);
  const dropType = !dragged || dragged.id === part.id || dragged.obsolete_at ? null
    : dragged.item_category === 'tool' ? 'serves'
      : dragged.item_category === 'article' ? articleLink : null;
  const alreadyLinked = !!dragged && !!dropType
    && own.some((r) => r.relation_type === dropType && r.other_part_id === dragged.id);
  const acceptsDrop = editable && !!dropType && !alreadyLinked;

  const onDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(false);
    if (acceptsDrop && dragged && dropType) linkMutation.mutate({ other: dragged, relationType: dropType });
    onDropDone?.();
  };

  const saveQuantity = (rel: EquipmentRelation, raw: string, reset: () => void) => {
    const quantity = Number(raw);
    if (!raw.trim() || !Number.isFinite(quantity) || quantity <= 0) {
      toast.error('The amount must be greater than 0.');
      reset();
      return;
    }
    if (quantity !== rel.quantity) quantityMutation.mutate({ relationId: rel.id, quantity });
  };

  return (
    <>
      <section
        data-testid="equipment-card"
        aria-label={`Equipment ${part.part_number}`}
        onDragOver={(e) => { if (acceptsDrop) { e.preventDefault(); setDragOver(true); } }}
        onDragLeave={() => setDragOver(false)}
        onDrop={onDrop}
        className={`rounded-lg border p-4 space-y-4 transition ${
          dragOver && acceptsDrop ? 'bg-green-900/30 border-green-500' : 'bg-slate-800 border-slate-700'
        }`}
      >
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <p className="text-xs text-slate-400">{equipmentKindLabel(part)}</p>
            <h3 className="text-sm font-semibold text-slate-100 truncate">
              <span className="font-mono">{part.part_number}</span> {part.name}
            </h3>
            {obsolete && (
              <p data-testid="equipment-obsolete" className="mt-1 inline-block rounded bg-amber-900/60 px-2 py-0.5 text-xs text-amber-200">
                obsolete since {formatDate(part.obsolete_at)}
              </p>
            )}
          </div>
          {canEdit && (
            <div className="flex flex-shrink-0 gap-2">
              {obsolete ? (
                <button type="button" onClick={() => reactivateMutation.mutate()} disabled={reactivateMutation.isPending}
                  className={`${BTN} bg-blue-600 hover:bg-blue-500 disabled:bg-slate-600 text-white`}>
                  Reactivate
                </button>
              ) : (
                <>
                  <button type="button" onClick={() => setDialog('edit')}
                    className={`${BTN} bg-blue-600 hover:bg-blue-500 text-white`}>
                    Change
                  </button>
                  <button type="button" onClick={() => setDialog('obsolete')}
                    className={`${BTN} border border-slate-600 text-slate-300 hover:bg-slate-700`}>
                    Mark obsolete
                  </button>
                </>
              )}
            </div>
          )}
        </div>

        <div data-testid="equipment-tools">
          <h4 className="text-xs font-semibold uppercase tracking-wide text-slate-400 mb-1.5">Serves tools</h4>
          <div className="flex flex-wrap items-center gap-1.5 text-sm">
            {tools.length === 0 && (
              <span className="text-slate-500">{isGauge ? 'No tool: assembly gauge' : 'No tool: assembly operation'}</span>
            )}
            {tools.map((t) => (
              <span key={t.id} className="inline-flex items-center gap-1 rounded bg-slate-700 pl-2 pr-1 py-0.5 text-slate-100">
                <button type="button" onClick={() => onOpenPart(t.other_part_id)} className="hover:text-sky-300">
                  <span className="font-mono">{t.other_part_number}</span> {t.other_part_name}
                </button>
                {editable && (
                  <button type="button" aria-label={`Remove tool ${t.other_part_number}`}
                    onClick={() => unlinkMutation.mutate(t.id)} disabled={unlinkMutation.isPending}
                    className="px-1 text-slate-400 hover:text-red-300">
                    ✕
                  </button>
                )}
              </span>
            ))}
          </div>
        </div>

        <div data-testid="equipment-articles">
          <h4 className="text-xs font-semibold uppercase tracking-wide text-slate-400 mb-1.5">
            Articles {isGauge ? 'checked' : 'taken in'}
          </h4>
          {articles.length === 0 ? (
            <p className="text-sm text-slate-500">No article linked yet</p>
          ) : (
            <ul className="space-y-1.5">
              {articles.map((a) => (
                <li key={a.id} className="flex items-center gap-2 p-2 bg-slate-700/50 rounded border border-slate-600 text-sm">
                  <button type="button" onClick={() => onOpenPart(a.other_part_id)} className="flex-1 min-w-0 text-left hover:text-sky-300">
                    {a.other_customer_part_number && (
                      <span className="font-mono text-slate-100">{a.other_customer_part_number} </span>
                    )}
                    <span className={`font-mono ${a.other_customer_part_number ? 'text-slate-400 text-xs' : 'text-slate-100'}`}>{a.other_part_number}</span>
                    <span className="text-slate-300"> {a.other_part_name}</span>
                  </button>
                  {!isGauge && (
                    <input
                      key={`${a.id}-${a.quantity}`}
                      type="number" min="0.001" step="any"
                      aria-label={`Amount of ${a.other_part_number}`}
                      defaultValue={a.quantity ?? ''}
                      disabled={!editable}
                      onBlur={(e) => { const el = e.currentTarget; saveQuantity(a, el.value, () => { el.value = String(a.quantity ?? ''); }); }}
                      onKeyDown={(e) => { if (e.key === 'Enter') e.currentTarget.blur(); }}
                      className="w-20 flex-shrink-0 bg-slate-700 border border-slate-600 rounded px-2 py-1 text-right text-slate-100 text-sm tabular-nums disabled:opacity-60"
                    />
                  )}
                  {editable && (
                    <button type="button" aria-label={`Remove article ${a.other_part_number}`}
                      onClick={() => unlinkMutation.mutate(a.id)} disabled={unlinkMutation.isPending}
                      className="flex-shrink-0 px-1 text-xs text-red-400 hover:text-red-300">
                      ✕
                    </button>
                  )}
                </li>
              ))}
            </ul>
          )}
        </div>

        {editable && (
          <p className="text-[11px] text-slate-500">
            Drag an article or a tool from the item list onto this card to link it.
          </p>
        )}
      </section>

      <section className="bg-slate-800 rounded-lg border border-slate-700 p-4" aria-label="History">
        <h3 className="text-sm font-semibold text-slate-200 mb-3">History</h3>
        {!history || history.length === 0 ? (
          <p className="text-slate-500 text-sm">No changes logged yet</p>
        ) : (
          <ul data-testid="equipment-history" className="space-y-1.5">
            {history.map((h) => {
              const tag = h.kind ? KIND_TAG[h.kind] : undefined;
              return (
                <li key={h.id} className="p-2 bg-slate-700/50 rounded border border-slate-600 text-sm">
                  <div className="flex items-center gap-2 text-xs text-slate-400">
                    <span className="tabular-nums">{formatDateTime(h.at)}</span>
                    {h.by_name && <span>{h.by_name}</span>}
                    {tag && <span className={`ml-auto rounded px-1.5 py-0.5 font-medium ${tag.className}`}>{tag.label}</span>}
                  </div>
                  <p className="mt-1 text-slate-200">{h.description}</p>
                  {h.note && h.kind !== 'obsolete' && h.kind !== 'reactivated' && (
                    <p className="mt-0.5 text-xs text-slate-400">{h.note}</p>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </section>

      {dialog === 'edit' && <EditDialog part={part} onClose={() => setDialog(null)} onSaved={refresh} />}
      {dialog === 'obsolete' && <ObsoleteDialog part={part} onClose={() => setDialog(null)} onSaved={refresh} />}
    </>
  );
}

function DialogFrame({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="fixed inset-0 z-40 bg-black/50 flex items-center justify-center">
      <div role="dialog" aria-modal="true" aria-label={title}
        className="bg-slate-800 rounded-lg border border-slate-700 p-6 max-w-md w-full mx-4 max-h-[90vh] overflow-y-auto">
        <h2 className="text-xl font-bold text-slate-100 mb-4">{title}</h2>
        {children}
      </div>
    </div>
  );
}

function DialogButtons({ onClose, onSave, saving, disabled, saveLabel }: {
  onClose(): void; onSave(): void; saving: boolean; disabled: boolean; saveLabel: string;
}) {
  return (
    <div className="flex gap-3 mt-6">
      <button type="button" onClick={onClose}
        className="flex-1 px-4 py-2 rounded border border-slate-600 text-slate-300 hover:bg-slate-700 text-sm font-medium">
        Cancel
      </button>
      <button type="button" onClick={onSave} disabled={saving || disabled}
        className="flex-1 px-4 py-2 rounded bg-blue-600 hover:bg-blue-500 disabled:bg-slate-600 text-white text-sm font-medium">
        {saving ? 'Saving...' : saveLabel}
      </button>
    </div>
  );
}

/** Name, number, description (gauge: calibration interval) with the required choice Correction / Change. */
function EditDialog({ part, onClose, onSaved }: { part: Part; onClose(): void; onSaved(): void }) {
  const isGauge = part.item_category === 'gauge';
  const [form, setForm] = useState({
    name: part.name,
    part_number: part.part_number,
    description: part.description ?? '',
    calibration_interval_months: part.calibration_interval_months ? String(part.calibration_interval_months) : '',
  });
  const [kind, setKind] = useState<'' | 'correction' | 'change'>('');
  const [note, setNote] = useState('');

  const save = useMutation({
    mutationFn: async () => {
      const payload: Record<string, unknown> = { change_kind: kind, change_note: note.trim() || null };
      if (form.name.trim() !== part.name) payload.name = form.name.trim();
      if (form.part_number.trim() !== part.part_number) payload.part_number = form.part_number.trim();
      if (form.description.trim() !== (part.description ?? '')) payload.description = form.description.trim();
      const interval = form.calibration_interval_months ? parseInt(form.calibration_interval_months, 10) : null;
      if (isGauge && interval && interval !== part.calibration_interval_months) payload.calibration_interval_months = interval;
      await client.put(`/v1/parts/${part.id}`, payload);
    },
    onSuccess: () => { toast.success('Saved'); onSaved(); onClose(); },
    onError: (error: unknown) => { toast.error(apiErrorMessage(error, 'Failed to save')); },
  });

  const changed = form.name.trim() !== part.name || form.part_number.trim() !== part.part_number
    || form.description.trim() !== (part.description ?? '')
    || (isGauge && form.calibration_interval_months !== (part.calibration_interval_months ? String(part.calibration_interval_months) : ''));
  const noteMissing = kind === 'change' && !note.trim();
  const blocked = !changed || !kind || noteMissing || !form.name.trim() || !form.part_number.trim();

  return (
    <DialogFrame title={`Change ${part.part_number}`}>
      <div className="space-y-4">
        <div>
          <label htmlFor="equipment-edit-number" className={LABEL}>Number *</label>
          <input id="equipment-edit-number" type="text" value={form.part_number}
            onChange={(e) => setForm({ ...form, part_number: e.target.value })} className={INPUT} />
        </div>
        <div>
          <label htmlFor="equipment-edit-name" className={LABEL}>Name *</label>
          <input id="equipment-edit-name" type="text" value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })} className={INPUT} />
        </div>
        <div>
          <label htmlFor="equipment-edit-description" className={LABEL}>Description</label>
          <textarea id="equipment-edit-description" rows={3} value={form.description}
            onChange={(e) => setForm({ ...form, description: e.target.value })} className={INPUT} />
        </div>
        {isGauge && (
          <div>
            <label htmlFor="equipment-edit-interval" className={LABEL}>Calibration Interval (months)</label>
            <input id="equipment-edit-interval" type="number" min="1" max="120" value={form.calibration_interval_months}
              onChange={(e) => setForm({ ...form, calibration_interval_months: e.target.value })} className={INPUT} />
          </div>
        )}
        <fieldset>
          <legend className={LABEL}>What is this? *</legend>
          <div className="space-y-1.5 text-sm text-slate-200">
            <label className="flex items-center gap-2">
              <input type="radio" name="equipment-edit-kind" checked={kind === 'correction'}
                onChange={() => setKind('correction')} className="accent-sky-500" />
              Correction <span className="text-slate-400">(it was entered wrong)</span>
            </label>
            <label className="flex items-center gap-2">
              <input type="radio" name="equipment-edit-kind" checked={kind === 'change'}
                onChange={() => setKind('change')} className="accent-sky-500" />
              Change <span className="text-slate-400">(the equipment itself changed)</span>
            </label>
          </div>
        </fieldset>
        <div>
          <label htmlFor="equipment-edit-note" className={LABEL}>Note{kind === 'change' ? ' *' : ''}</label>
          <textarea id="equipment-edit-note" rows={2} value={note} onChange={(e) => setNote(e.target.value)}
            placeholder={kind === 'change' ? 'What changed on the equipment' : 'Optional'} className={INPUT} />
        </div>
        {changed && !kind && <p className="text-xs text-amber-300">Say whether this is a correction or a change.</p>}
        {noteMissing && <p className="text-xs text-amber-300">A change needs a short note.</p>}
      </div>
      <DialogButtons onClose={onClose} onSave={() => save.mutate()} saving={save.isPending} disabled={blocked} saveLabel="Save" />
    </DialogFrame>
  );
}

function ObsoleteDialog({ part, onClose, onSaved }: { part: Part; onClose(): void; onSaved(): void }) {
  const [note, setNote] = useState('');
  const save = useMutation({
    mutationFn: async () => { await client.post(`/v1/parts/${part.id}/obsolete`, { note: note.trim() }); },
    onSuccess: () => { toast.success(`${part.part_number} is marked obsolete`); onSaved(); onClose(); },
    onError: (error: unknown) => { toast.error(apiErrorMessage(error, 'Failed to mark obsolete')); },
  });
  return (
    <DialogFrame title={`Mark ${part.part_number} obsolete`}>
      <p className="text-sm text-slate-300 mb-4">
        The item stays in PLM, greyed. It takes no new links and cannot be changed until it is reactivated.
      </p>
      <label htmlFor="equipment-obsolete-note" className={LABEL}>Why is it obsolete? *</label>
      <textarea id="equipment-obsolete-note" rows={3} value={note} onChange={(e) => setNote(e.target.value)} className={INPUT} />
      <DialogButtons onClose={onClose} onSave={() => save.mutate()} saving={save.isPending} disabled={!note.trim()} saveLabel="Mark obsolete" />
    </DialogFrame>
  );
}
