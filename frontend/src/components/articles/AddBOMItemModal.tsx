/**
 * AddBOMItemModal - Two-step modal to add a part to BOM
 * Step 1: Search catalog or create new part
 * Step 2: Enter quantity + notes
 */
import { useState, useEffect, useRef } from 'react';
import { toast } from 'sonner';
import { useCatalogParts, useAddBOMItem, useCreateCatalogPart } from '../../hooks/queries/useBOM';
import * as bomApi from '../../api/bom';
import type { CatalogPartResponse, CatalogPartCreateRequest, PartTypeEnum } from '../../types/bom';

interface Props {
  articleId: number;
  revisionId: number;
  onClose: () => void;
}

function CreateInlineForm({
  onCreated,
  onCancel,
}: {
  onCreated: (part: CatalogPartResponse) => void;
  onCancel: () => void;
}) {
  const [form, setForm] = useState({
    part_number: '',
    name: '',
    description: '',
    part_type: 'purchased' as PartTypeEnum,
    supplier: '',
    unit: 'pcs',
  });
  const [warning, setWarning] = useState<string | null>(null);
  const [exactMatch, setExactMatch] = useState(false);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const createPart = useCreateCatalogPart();

  const handleChange = (field: string, value: string) => {
    setForm(f => ({ ...f, [field]: value }));

    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(async () => {
      if (field === 'part_number' && value) {
        const result = await bomApi.checkDuplicate({ part_number: value });
        setExactMatch(result.exact_match);
        setWarning(result.exact_match ? `"${value}" already exists` : null);
      }
      if (field === 'name' && value.length > 2) {
        const result = await bomApi.checkDuplicate({ name: value });
        if (result.similar_parts.length > 0 && !exactMatch) {
          setWarning(`Similar: ${result.similar_parts.map(p => p.name).join(', ')}`);
        }
      }
    }, 400);
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (exactMatch) return;
    const payload: CatalogPartCreateRequest = {
      part_number: form.part_number,
      name: form.name,
      description: form.description || null,
      part_type: form.part_type,
      supplier: form.supplier || null,
      unit: form.unit,
    };
    createPart.mutate(payload, {
      onSuccess: part => { toast.success('Part created'); onCreated(part); },
      onError: (err: any) => toast.error(err?.response?.data?.detail || 'Failed'),
    });
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-3 border-t border-slate-700 pt-3 mt-3">
      <p className="text-xs text-slate-400 font-medium uppercase tracking-wide">Create New Part</p>
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="text-xs text-slate-400">Part Number *</label>
          <input
            className="mt-1 w-full bg-slate-700 text-slate-100 rounded px-2 py-1.5 text-sm border border-slate-600 focus:outline-none focus:border-blue-500"
            value={form.part_number}
            onChange={e => handleChange('part_number', e.target.value)}
            required
          />
        </div>
        <div>
          <label className="text-xs text-slate-400">Unit *</label>
          <input
            className="mt-1 w-full bg-slate-700 text-slate-100 rounded px-2 py-1.5 text-sm border border-slate-600 focus:outline-none focus:border-blue-500"
            value={form.unit}
            onChange={e => handleChange('unit', e.target.value)}
            required
          />
        </div>
      </div>
      <div>
        <label className="text-xs text-slate-400">Name *</label>
        <input
          className="mt-1 w-full bg-slate-700 text-slate-100 rounded px-2 py-1.5 text-sm border border-slate-600 focus:outline-none focus:border-blue-500"
          value={form.name}
          onChange={e => handleChange('name', e.target.value)}
          required
        />
      </div>
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="text-xs text-slate-400">Type</label>
          <select
            className="mt-1 w-full bg-slate-700 text-slate-100 rounded px-2 py-1.5 text-sm border border-slate-600 focus:outline-none focus:border-blue-500"
            value={form.part_type}
            onChange={e => setForm(f => ({ ...f, part_type: e.target.value as PartTypeEnum }))}
          >
            <option value="purchased">Purchased</option>
            <option value="manufactured">Manufactured</option>
          </select>
        </div>
        <div>
          <label className="text-xs text-slate-400">Supplier</label>
          <input
            className="mt-1 w-full bg-slate-700 text-slate-100 rounded px-2 py-1.5 text-sm border border-slate-600 focus:outline-none focus:border-blue-500"
            value={form.supplier}
            onChange={e => setForm(f => ({ ...f, supplier: e.target.value }))}
          />
        </div>
      </div>
      {warning && <p className={`text-xs ${exactMatch ? 'text-red-400' : 'text-yellow-400'}`}>⚠ {warning}</p>}
      <div className="flex gap-2">
        <button type="button" onClick={onCancel} className="text-xs text-slate-400 hover:text-slate-200">
          Cancel
        </button>
        <button
          type="submit"
          disabled={createPart.isPending || exactMatch}
          className="px-3 py-1.5 bg-blue-600 text-white rounded text-xs hover:bg-blue-700 disabled:opacity-50"
        >
          {createPart.isPending ? 'Creating...' : 'Create & Select'}
        </button>
      </div>
    </form>
  );
}

export default function AddBOMItemModal({ articleId, revisionId, onClose }: Props) {
  const [step, setStep] = useState<1 | 2>(1);
  const [search, setSearch] = useState('');
  const [selectedPart, setSelectedPart] = useState<CatalogPartResponse | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [quantity, setQuantity] = useState('1');
  const [notes, setNotes] = useState('');
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [debouncedSearch, setDebouncedSearch] = useState('');

  const { data: parts } = useCatalogParts({
    search: debouncedSearch || undefined,
    is_active: true,
  });

  const addItem = useAddBOMItem(articleId, revisionId);

  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => setDebouncedSearch(search), 300);
    return () => { if (debounceRef.current) clearTimeout(debounceRef.current); };
  }, [search]);

  const handleSelectPart = (part: CatalogPartResponse) => {
    setSelectedPart(part);
    setStep(2);
    setShowCreate(false);
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedPart) return;
    addItem.mutate(
      {
        catalog_part_id: selectedPart.id,
        quantity: parseFloat(quantity),
        notes: notes || null,
      },
      {
        onSuccess: () => { toast.success('Part added to BOM'); onClose(); },
        onError: () => toast.error('Failed to add part'),
      }
    );
  };

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50">
      <div className="bg-slate-800 rounded-xl p-6 w-full max-w-lg border border-slate-700 max-h-[90vh] overflow-y-auto">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold text-slate-100">
            {step === 1 ? 'Select Part' : `Add: ${selectedPart?.name}`}
          </h2>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-200 text-lg">×</button>
        </div>

        {step === 1 && (
          <div>
            <input
              className="w-full bg-slate-700 text-slate-100 rounded px-3 py-2 text-sm border border-slate-600 focus:outline-none focus:border-blue-500 mb-3"
              placeholder="Search by name or part number..."
              value={search}
              onChange={e => setSearch(e.target.value)}
              autoFocus
            />

            <div className="space-y-1 max-h-60 overflow-y-auto">
              {(parts ?? []).length === 0 && debouncedSearch && (
                <p className="text-slate-400 text-sm text-center py-4">No parts found</p>
              )}
              {(parts ?? []).map(part => (
                <button
                  key={part.id}
                  onClick={() => handleSelectPart(part)}
                  className="w-full text-left px-3 py-2 rounded bg-slate-700/50 hover:bg-slate-700 transition"
                >
                  <div className="flex items-center justify-between">
                    <div>
                      <span className="text-slate-100 text-sm font-medium">{part.name}</span>
                      <span className="text-slate-400 text-xs ml-2 font-mono">{part.part_number}</span>
                    </div>
                    <div className="flex items-center gap-2 text-xs">
                      <span className={`px-1.5 py-0.5 rounded ${
                        part.part_type === 'purchased' ? 'bg-blue-900/50 text-blue-300' : 'bg-purple-900/50 text-purple-300'
                      }`}>{part.part_type}</span>
                      <span className="text-slate-400">{part.unit}</span>
                    </div>
                  </div>
                  {part.supplier && <p className="text-slate-500 text-xs mt-0.5">{part.supplier}</p>}
                </button>
              ))}
            </div>

            {!showCreate ? (
              <button
                onClick={() => setShowCreate(true)}
                className="mt-3 text-sm text-blue-400 hover:text-blue-300"
              >
                + Create New Part
              </button>
            ) : (
              <CreateInlineForm
                onCreated={handleSelectPart}
                onCancel={() => setShowCreate(false)}
              />
            )}
          </div>
        )}

        {step === 2 && selectedPart && (
          <form onSubmit={handleSubmit} className="space-y-4">
            <div className="bg-slate-700/50 rounded-lg p-3 text-sm">
              <div className="flex items-center justify-between">
                <span className="text-slate-100 font-medium">{selectedPart.name}</span>
                <span className="text-slate-400 font-mono text-xs">{selectedPart.part_number}</span>
              </div>
              {selectedPart.supplier && (
                <p className="text-slate-400 text-xs mt-1">Supplier: {selectedPart.supplier}</p>
              )}
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="text-sm text-slate-400">Quantity *</label>
                <input
                  type="number"
                  min="0.001"
                  step="any"
                  className="mt-1 w-full bg-slate-700 text-slate-100 rounded px-3 py-2 text-sm border border-slate-600 focus:outline-none focus:border-blue-500"
                  value={quantity}
                  onChange={e => setQuantity(e.target.value)}
                  required
                  autoFocus
                />
              </div>
              <div>
                <label className="text-sm text-slate-400">Unit</label>
                <input
                  className="mt-1 w-full bg-slate-600 text-slate-400 rounded px-3 py-2 text-sm border border-slate-600 cursor-not-allowed"
                  value={selectedPart.unit}
                  readOnly
                />
              </div>
            </div>

            <div>
              <label className="text-sm text-slate-400">Notes</label>
              <textarea
                className="mt-1 w-full bg-slate-700 text-slate-100 rounded px-3 py-2 text-sm border border-slate-600 focus:outline-none focus:border-blue-500"
                value={notes}
                onChange={e => setNotes(e.target.value)}
                rows={2}
                placeholder="Optional notes..."
              />
            </div>

            <div className="flex justify-between">
              <button
                type="button"
                onClick={() => setStep(1)}
                className="text-sm text-slate-400 hover:text-slate-200"
              >
                ← Back
              </button>
              <div className="flex gap-3">
                <button type="button" onClick={onClose} className="px-4 py-2 text-slate-300 text-sm">
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={addItem.isPending}
                  className="px-4 py-2 bg-blue-600 text-white rounded-lg text-sm hover:bg-blue-700 disabled:opacity-50"
                >
                  {addItem.isPending ? 'Adding...' : 'Add to BOM'}
                </button>
              </div>
            </div>
          </form>
        )}
      </div>
    </div>
  );
}
