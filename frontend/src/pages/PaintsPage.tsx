/**
 * PaintsPage - Paint catalog management
 */
import { Fragment, useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import * as paintsApi from '../api/paints';
import { apiErrorMessage } from '../lib/apiError';
import ColourSwatch from '../components/paint/ColourSwatch';
import type { Paint, PaintCreateRequest, PaintUpdateRequest, PaintType, PaintUsedIn } from '../types/paint';
import { PAINT_TYPE_LABEL } from '../types/paint';

const PAINT_TYPES: PaintType[] = ['primer', 'basecoat', 'clearcoat', 'one_coat', 'other'];

interface PaintFormState {
  name: string;
  paint_type: PaintType;
  colour_code: string;
  colour_name: string;
  colour_hex: string;
  supplier_text: string;
  spec_reference: string;
  notes: string;
}

const emptyForm = (): PaintFormState => ({
  name: '',
  paint_type: 'basecoat',
  colour_code: '',
  colour_name: '',
  colour_hex: '',
  supplier_text: '',
  spec_reference: '',
  notes: '',
});

const formFromPaint = (paint: Paint): PaintFormState => ({
  name: paint.name,
  paint_type: paint.paint_type,
  colour_code: paint.colour_code || '',
  colour_name: paint.colour_name || '',
  colour_hex: paint.colour_hex || '',
  supplier_text: paint.supplier_text || '',
  spec_reference: paint.spec_reference || '',
  notes: paint.notes || '',
});

function toPayload(form: PaintFormState): Omit<PaintCreateRequest, 'is_active'> {
  return {
    name: form.name,
    paint_type: form.paint_type,
    colour_code: form.colour_code || null,
    colour_name: form.colour_name || null,
    colour_hex: form.colour_hex || null,
    supplier_text: form.supplier_text || null,
    spec_reference: form.spec_reference || null,
    notes: form.notes || null,
  };
}

interface PaintFormFieldsProps {
  form: PaintFormState;
  setForm: (updater: (f: PaintFormState) => PaintFormState) => void;
}

function PaintFormFields({ form, setForm }: PaintFormFieldsProps) {
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-4">
        <div>
          <label htmlFor="paint-name" className="text-sm text-slate-400">Name *</label>
          <input
            id="paint-name"
            className="mt-1 w-full bg-slate-700 text-slate-100 rounded px-3 py-2 text-sm border border-slate-600 focus:outline-none focus:border-blue-500"
            value={form.name}
            onChange={e => setForm(f => ({ ...f, name: e.target.value }))}
            required
          />
        </div>
        <div>
          <label htmlFor="paint-type" className="text-sm text-slate-400">Type *</label>
          <select
            id="paint-type"
            className="mt-1 w-full bg-slate-700 text-slate-100 rounded px-3 py-2 text-sm border border-slate-600 focus:outline-none focus:border-blue-500"
            value={form.paint_type}
            onChange={e => setForm(f => ({ ...f, paint_type: e.target.value as PaintType }))}
          >
            {PAINT_TYPES.map(t => (
              <option key={t} value={t}>{PAINT_TYPE_LABEL[t]}</option>
            ))}
          </select>
        </div>
      </div>

      <div className="grid grid-cols-3 gap-4">
        <div>
          <label htmlFor="paint-colour-code" className="text-sm text-slate-400">Colour code</label>
          <input
            id="paint-colour-code"
            className="mt-1 w-full bg-slate-700 text-slate-100 rounded px-3 py-2 text-sm border border-slate-600 focus:outline-none focus:border-blue-500"
            value={form.colour_code}
            onChange={e => setForm(f => ({ ...f, colour_code: e.target.value }))}
            placeholder="RAL 9005"
          />
        </div>
        <div>
          <label htmlFor="paint-colour-name" className="text-sm text-slate-400">Colour name</label>
          <input
            id="paint-colour-name"
            className="mt-1 w-full bg-slate-700 text-slate-100 rounded px-3 py-2 text-sm border border-slate-600 focus:outline-none focus:border-blue-500"
            value={form.colour_name}
            onChange={e => setForm(f => ({ ...f, colour_name: e.target.value }))}
          />
        </div>
        <div>
          <label htmlFor="paint-colour-hex" className="text-sm text-slate-400">Colour hex</label>
          <input
            id="paint-colour-hex"
            className="mt-1 w-full bg-slate-700 text-slate-100 rounded px-3 py-2 text-sm border border-slate-600 focus:outline-none focus:border-blue-500"
            value={form.colour_hex}
            onChange={e => setForm(f => ({ ...f, colour_hex: e.target.value }))}
            placeholder="#RRGGBB"
            pattern="^#[0-9a-fA-F]{6}$"
            title="Six hex digits after a #, e.g. #0a0a0a"
          />
        </div>
      </div>

      <div className="grid grid-cols-2 gap-4">
        <div>
          <label htmlFor="paint-supplier" className="text-sm text-slate-400">Supplier</label>
          <input
            id="paint-supplier"
            className="mt-1 w-full bg-slate-700 text-slate-100 rounded px-3 py-2 text-sm border border-slate-600 focus:outline-none focus:border-blue-500"
            value={form.supplier_text}
            onChange={e => setForm(f => ({ ...f, supplier_text: e.target.value }))}
          />
        </div>
        <div>
          <label htmlFor="paint-spec" className="text-sm text-slate-400">Spec reference</label>
          <input
            id="paint-spec"
            className="mt-1 w-full bg-slate-700 text-slate-100 rounded px-3 py-2 text-sm border border-slate-600 focus:outline-none focus:border-blue-500"
            value={form.spec_reference}
            onChange={e => setForm(f => ({ ...f, spec_reference: e.target.value }))}
          />
        </div>
      </div>

      <div>
        <label htmlFor="paint-notes" className="text-sm text-slate-400">Notes</label>
        <textarea
          id="paint-notes"
          className="mt-1 w-full bg-slate-700 text-slate-100 rounded px-3 py-2 text-sm border border-slate-600 focus:outline-none focus:border-blue-500"
          value={form.notes}
          onChange={e => setForm(f => ({ ...f, notes: e.target.value }))}
          rows={2}
        />
      </div>
    </div>
  );
}

interface NewPaintModalProps {
  onClose: () => void;
}

function NewPaintModal({ onClose }: NewPaintModalProps) {
  const queryClient = useQueryClient();
  const [form, setForm] = useState<PaintFormState>(emptyForm());

  const createMutation = useMutation({
    mutationFn: (payload: PaintCreateRequest) => paintsApi.createPaint(payload),
    onSuccess: () => {
      toast.success('Paint created');
      queryClient.invalidateQueries({ queryKey: ['paints'] });
      onClose();
    },
    onError: (err: unknown) => toast.error(apiErrorMessage(err, 'Failed to create paint')),
  });

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    createMutation.mutate(toPayload(form));
  };

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50">
      <div className="bg-slate-800 rounded-xl p-6 w-full max-w-2xl border border-slate-700">
        <h2 className="text-lg font-semibold text-slate-100 mb-4">New Paint</h2>
        <form onSubmit={handleSubmit} className="space-y-4">
          <PaintFormFields form={form} setForm={setForm} />
          <div className="flex justify-end gap-3 pt-2">
            <button type="button" onClick={onClose} className="px-4 py-2 text-slate-300 hover:text-slate-100 text-sm">
              Cancel
            </button>
            <button
              type="submit"
              disabled={createMutation.isPending}
              className="px-4 py-2 bg-blue-600 text-white rounded-lg text-sm hover:bg-blue-700 disabled:opacity-50"
            >
              {createMutation.isPending ? 'Creating...' : 'Create'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

interface EditPaintModalProps {
  paint: Paint;
  onClose: () => void;
}

function EditPaintModal({ paint, onClose }: EditPaintModalProps) {
  const queryClient = useQueryClient();
  const [form, setForm] = useState<PaintFormState>(formFromPaint(paint));

  const updateMutation = useMutation({
    mutationFn: (payload: PaintUpdateRequest) => paintsApi.updatePaint(paint.id, payload),
    onSuccess: () => {
      toast.success('Paint updated');
      queryClient.invalidateQueries({ queryKey: ['paints'] });
      onClose();
    },
    onError: (err: unknown) => toast.error(apiErrorMessage(err, 'Failed to update paint')),
  });

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    updateMutation.mutate(toPayload(form));
  };

  const toggleActive = () => {
    updateMutation.mutate({ ...toPayload(form), is_active: !paint.is_active });
  };

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50">
      <div className="bg-slate-800 rounded-xl p-6 w-full max-w-2xl border border-slate-700">
        <h2 className="text-lg font-semibold text-slate-100 mb-4">Edit Paint: {paint.name}</h2>
        <form onSubmit={handleSubmit} className="space-y-4">
          <PaintFormFields form={form} setForm={setForm} />
          <div className="flex justify-between items-center pt-2">
            <button
              type="button"
              onClick={toggleActive}
              disabled={updateMutation.isPending}
              className="text-xs text-slate-400 hover:text-slate-200"
            >
              {paint.is_active ? 'Deactivate' : 'Reactivate'}
            </button>
            <div className="flex gap-3">
              <button type="button" onClick={onClose} className="px-4 py-2 text-slate-300 hover:text-slate-100 text-sm">
                Cancel
              </button>
              <button
                type="submit"
                disabled={updateMutation.isPending}
                className="px-4 py-2 bg-blue-600 text-white rounded-lg text-sm hover:bg-blue-700 disabled:opacity-50"
              >
                {updateMutation.isPending ? 'Saving...' : 'Save'}
              </button>
            </div>
          </div>
        </form>
      </div>
    </div>
  );
}

interface UsedInRowProps {
  paintId: number;
}

function UsedInRow({ paintId }: UsedInRowProps) {
  const { data: usedIn, isLoading } = useQuery<PaintUsedIn[]>({
    queryKey: ['paints', paintId, 'used-in'],
    queryFn: () => paintsApi.paintUsedIn(paintId),
  });

  return (
    <tr className="bg-slate-900/40">
      <td colSpan={7} className="px-4 py-3">
        {isLoading ? (
          <div className="text-slate-500 text-sm">Loading used-in...</div>
        ) : !usedIn || usedIn.length === 0 ? (
          <div className="text-slate-500 text-sm">Not used on any part.</div>
        ) : (
          <table className="w-full text-xs">
            <thead>
              <tr className="text-slate-500">
                <th className="text-left px-2 py-1 font-medium">Part Number</th>
                <th className="text-left px-2 py-1 font-medium">Name</th>
                <th className="text-left px-2 py-1 font-medium">Project</th>
                <th className="text-left px-2 py-1 font-medium">Layer</th>
              </tr>
            </thead>
            <tbody>
              {usedIn.map(u => (
                <tr key={`${u.part_id}-${u.layer_order}`}>
                  <td className="px-2 py-1 text-slate-200 font-mono">{u.part_number}</td>
                  <td className="px-2 py-1 text-slate-300">{u.name}</td>
                  <td className="px-2 py-1 text-slate-400">{u.project_code}</td>
                  <td className="px-2 py-1 text-slate-400">{u.layer_order}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </td>
    </tr>
  );
}

export default function PaintsPage() {
  const [search, setSearch] = useState('');
  const [showInactive, setShowInactive] = useState(false);
  const [showNewModal, setShowNewModal] = useState(false);
  const [editPaint, setEditPaint] = useState<Paint | null>(null);
  const [expandedId, setExpandedId] = useState<number | null>(null);

  const { data: paints, isLoading } = useQuery<Paint[]>({
    queryKey: ['paints', { search, showInactive }],
    queryFn: () =>
      paintsApi.listPaints({
        activeOnly: !showInactive,
        q: search || undefined,
      }),
  });

  const toggleExpanded = (id: number) => {
    setExpandedId(prev => (prev === id ? null : id));
  };

  return (
    <div className="p-6">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-slate-100">Paint Catalog</h1>
          <p className="text-slate-400 text-sm mt-1">Master data for paints — link from any part's paint setup</p>
        </div>
        <button
          onClick={() => setShowNewModal(true)}
          className="px-4 py-2 bg-blue-600 text-white rounded-lg text-sm font-medium hover:bg-blue-700"
        >
          + New Paint
        </button>
      </div>

      <div className="flex gap-3 mb-4">
        <input
          className="bg-slate-700 text-slate-100 rounded px-3 py-2 text-sm border border-slate-600 focus:outline-none focus:border-blue-500 w-64"
          placeholder="Search by name or colour code..."
          value={search}
          onChange={e => setSearch(e.target.value)}
        />
        <label className="flex items-center gap-2 text-sm text-slate-400 cursor-pointer">
          <input
            type="checkbox"
            checked={showInactive}
            onChange={e => setShowInactive(e.target.checked)}
            className="rounded"
          />
          Show inactive
        </label>
      </div>

      {isLoading ? (
        <div className="text-slate-400 text-sm">Loading...</div>
      ) : (
        <div className="bg-slate-800 rounded-xl border border-slate-700 overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-700">
                <th className="text-left px-4 py-3 text-slate-400 font-medium">Name</th>
                <th className="text-left px-4 py-3 text-slate-400 font-medium">Type</th>
                <th className="text-left px-4 py-3 text-slate-400 font-medium">Colour</th>
                <th className="text-left px-4 py-3 text-slate-400 font-medium">Supplier</th>
                <th className="text-left px-4 py-3 text-slate-400 font-medium">Spec</th>
                <th className="text-left px-4 py-3 text-slate-400 font-medium">Status</th>
                <th className="text-left px-4 py-3 text-slate-400 font-medium">Actions</th>
              </tr>
            </thead>
            <tbody>
              {(paints ?? []).length === 0 ? (
                <tr>
                  <td colSpan={7} className="px-4 py-8 text-center text-slate-500">
                    No paints found. Create your first paint.
                  </td>
                </tr>
              ) : (
                (paints ?? []).map(paint => (
                  <Fragment key={paint.id}>
                    <tr className="border-b border-slate-700/50 hover:bg-slate-700/30">
                      <td className="px-4 py-3 text-slate-100">
                        <button
                          type="button"
                          onClick={() => toggleExpanded(paint.id)}
                          className="text-left hover:text-blue-300"
                        >
                          {paint.name}
                        </button>
                      </td>
                      <td className="px-4 py-3">
                        <span className="px-2 py-0.5 rounded text-xs font-medium bg-purple-900/50 text-purple-300">
                          {PAINT_TYPE_LABEL[paint.paint_type]}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-slate-300">
                        <div className="flex items-center gap-2">
                          <ColourSwatch hex={paint.colour_hex} code={paint.colour_code} />
                          {paint.colour_code || '—'}
                        </div>
                      </td>
                      <td className="px-4 py-3 text-slate-300">{paint.supplier_text || '—'}</td>
                      <td className="px-4 py-3 text-slate-300">{paint.spec_reference || '—'}</td>
                      <td className="px-4 py-3">
                        {paint.is_active ? (
                          <span className="text-green-400 text-xs">Active</span>
                        ) : (
                          <span className="text-slate-500 text-xs">Inactive</span>
                        )}
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex gap-2">
                          <button
                            onClick={() => setEditPaint(paint)}
                            className="text-xs text-blue-400 hover:text-blue-300"
                          >
                            Edit
                          </button>
                        </div>
                      </td>
                    </tr>
                    {expandedId === paint.id && <UsedInRow paintId={paint.id} />}
                  </Fragment>
                ))
              )}
            </tbody>
          </table>
        </div>
      )}

      {showNewModal && <NewPaintModal onClose={() => setShowNewModal(false)} />}
      {editPaint && <EditPaintModal paint={editPaint} onClose={() => setEditPaint(null)} />}
    </div>
  );
}
