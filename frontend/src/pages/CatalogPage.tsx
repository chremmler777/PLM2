/**
 * CatalogPage - Parts catalog management
 */
import { useState } from 'react';
import { toast } from 'sonner';
import { useCatalogParts, useCreateCatalogPart, useUpdateCatalogPart, useDeactivateCatalogPart } from '../hooks/queries/useBOM';
import * as bomApi from '../api/bom';
import type { CatalogPartResponse, CatalogPartCreateRequest, PartTypeEnum } from '../types/bom';

interface PartFormState {
  part_number: string;
  name: string;
  description: string;
  part_type: PartTypeEnum;
  supplier: string;
  unit: string;
}

const emptyForm = (): PartFormState => ({
  part_number: '',
  name: '',
  description: '',
  part_type: 'purchased',
  supplier: '',
  unit: 'pcs',
});

interface NewPartModalProps {
  onClose: () => void;
  onCreated: () => void;
}

function NewPartModal({ onClose, onCreated }: NewPartModalProps) {
  const [form, setForm] = useState<PartFormState>(emptyForm());
  const [duplicateWarning, setDuplicateWarning] = useState<string | null>(null);
  const [exactMatch, setExactMatch] = useState(false);
  const createPart = useCreateCatalogPart();

  const handleFieldChange = async (field: keyof PartFormState, value: string) => {
    const updated = { ...form, [field]: value };
    setForm(updated);

    if (field === 'part_number' && value.length > 0) {
      const result = await bomApi.checkDuplicate({ part_number: value });
      setExactMatch(result.exact_match);
      if (result.exact_match) {
        setDuplicateWarning(`Part number "${value}" already exists.`);
      } else {
        setDuplicateWarning(null);
      }
    }

    if (field === 'name' && value.length > 2) {
      const result = await bomApi.checkDuplicate({ name: value });
      if (result.similar_parts.length > 0) {
        setDuplicateWarning(`Similar parts exist: ${result.similar_parts.map(p => p.name).join(', ')}`);
      } else if (!exactMatch) {
        setDuplicateWarning(null);
      }
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
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
      onSuccess: () => {
        toast.success('Part created');
        onCreated();
        onClose();
      },
      onError: (err: any) => {
        const detail = err?.response?.data?.detail || 'Failed to create part';
        toast.error(detail);
      },
    });
  };

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50">
      <div className="bg-slate-800 rounded-xl p-6 w-full max-w-lg border border-slate-700">
        <h2 className="text-lg font-semibold text-slate-100 mb-4">New Catalog Part</h2>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="text-sm text-slate-400">Part Number *</label>
              <input
                className="mt-1 w-full bg-slate-700 text-slate-100 rounded px-3 py-2 text-sm border border-slate-600 focus:outline-none focus:border-blue-500"
                value={form.part_number}
                onChange={e => handleFieldChange('part_number', e.target.value)}
                required
              />
            </div>
            <div>
              <label className="text-sm text-slate-400">Unit *</label>
              <input
                className="mt-1 w-full bg-slate-700 text-slate-100 rounded px-3 py-2 text-sm border border-slate-600 focus:outline-none focus:border-blue-500"
                value={form.unit}
                onChange={e => handleFieldChange('unit', e.target.value)}
                placeholder="pcs, kg, m..."
                required
              />
            </div>
          </div>

          <div>
            <label className="text-sm text-slate-400">Name *</label>
            <input
              className="mt-1 w-full bg-slate-700 text-slate-100 rounded px-3 py-2 text-sm border border-slate-600 focus:outline-none focus:border-blue-500"
              value={form.name}
              onChange={e => handleFieldChange('name', e.target.value)}
              required
            />
          </div>

          <div>
            <label className="text-sm text-slate-400">Description</label>
            <textarea
              className="mt-1 w-full bg-slate-700 text-slate-100 rounded px-3 py-2 text-sm border border-slate-600 focus:outline-none focus:border-blue-500"
              value={form.description}
              onChange={e => setForm(f => ({ ...f, description: e.target.value }))}
              rows={2}
            />
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="text-sm text-slate-400">Type *</label>
              <select
                className="mt-1 w-full bg-slate-700 text-slate-100 rounded px-3 py-2 text-sm border border-slate-600 focus:outline-none focus:border-blue-500"
                value={form.part_type}
                onChange={e => setForm(f => ({ ...f, part_type: e.target.value as PartTypeEnum }))}
              >
                <option value="purchased">Purchased</option>
                <option value="manufactured">Manufactured</option>
              </select>
            </div>
            <div>
              <label className="text-sm text-slate-400">Supplier</label>
              <input
                className="mt-1 w-full bg-slate-700 text-slate-100 rounded px-3 py-2 text-sm border border-slate-600 focus:outline-none focus:border-blue-500"
                value={form.supplier}
                onChange={e => setForm(f => ({ ...f, supplier: e.target.value }))}
                placeholder="For purchased parts"
              />
            </div>
          </div>

          {duplicateWarning && (
            <p className={`text-sm ${exactMatch ? 'text-red-400' : 'text-yellow-400'}`}>
              ⚠ {duplicateWarning}
            </p>
          )}

          <div className="flex justify-end gap-3 pt-2">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 text-slate-300 hover:text-slate-100 text-sm"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={createPart.isPending || exactMatch}
              className="px-4 py-2 bg-blue-600 text-white rounded-lg text-sm hover:bg-blue-700 disabled:opacity-50"
            >
              {createPart.isPending ? 'Creating...' : 'Create Part'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

interface EditPartModalProps {
  part: CatalogPartResponse;
  onClose: () => void;
}

function EditPartModal({ part, onClose }: EditPartModalProps) {
  const [form, setForm] = useState({
    name: part.name,
    description: part.description || '',
    part_type: part.part_type,
    supplier: part.supplier || '',
    unit: part.unit,
  });
  const updatePart = useUpdateCatalogPart(part.id);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    updatePart.mutate(
      {
        name: form.name,
        description: form.description || null,
        part_type: form.part_type,
        supplier: form.supplier || null,
        unit: form.unit,
      },
      {
        onSuccess: () => { toast.success('Part updated'); onClose(); },
        onError: () => toast.error('Failed to update part'),
      }
    );
  };

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50">
      <div className="bg-slate-800 rounded-xl p-6 w-full max-w-lg border border-slate-700">
        <h2 className="text-lg font-semibold text-slate-100 mb-4">Edit Part: {part.part_number}</h2>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="text-sm text-slate-400">Name *</label>
            <input
              className="mt-1 w-full bg-slate-700 text-slate-100 rounded px-3 py-2 text-sm border border-slate-600 focus:outline-none focus:border-blue-500"
              value={form.name}
              onChange={e => setForm(f => ({ ...f, name: e.target.value }))}
              required
            />
          </div>
          <div>
            <label className="text-sm text-slate-400">Description</label>
            <textarea
              className="mt-1 w-full bg-slate-700 text-slate-100 rounded px-3 py-2 text-sm border border-slate-600 focus:outline-none focus:border-blue-500"
              value={form.description}
              onChange={e => setForm(f => ({ ...f, description: e.target.value }))}
              rows={2}
            />
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="text-sm text-slate-400">Type</label>
              <select
                className="mt-1 w-full bg-slate-700 text-slate-100 rounded px-3 py-2 text-sm border border-slate-600 focus:outline-none focus:border-blue-500"
                value={form.part_type}
                onChange={e => setForm(f => ({ ...f, part_type: e.target.value as PartTypeEnum }))}
              >
                <option value="purchased">Purchased</option>
                <option value="manufactured">Manufactured</option>
              </select>
            </div>
            <div>
              <label className="text-sm text-slate-400">Unit</label>
              <input
                className="mt-1 w-full bg-slate-700 text-slate-100 rounded px-3 py-2 text-sm border border-slate-600 focus:outline-none focus:border-blue-500"
                value={form.unit}
                onChange={e => setForm(f => ({ ...f, unit: e.target.value }))}
              />
            </div>
          </div>
          <div>
            <label className="text-sm text-slate-400">Supplier</label>
            <input
              className="mt-1 w-full bg-slate-700 text-slate-100 rounded px-3 py-2 text-sm border border-slate-600 focus:outline-none focus:border-blue-500"
              value={form.supplier}
              onChange={e => setForm(f => ({ ...f, supplier: e.target.value }))}
            />
          </div>
          <div className="flex justify-end gap-3 pt-2">
            <button type="button" onClick={onClose} className="px-4 py-2 text-slate-300 hover:text-slate-100 text-sm">
              Cancel
            </button>
            <button
              type="submit"
              disabled={updatePart.isPending}
              className="px-4 py-2 bg-blue-600 text-white rounded-lg text-sm hover:bg-blue-700 disabled:opacity-50"
            >
              {updatePart.isPending ? 'Saving...' : 'Save'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

export default function CatalogPage() {
  const [search, setSearch] = useState('');
  const [typeFilter, setTypeFilter] = useState<string>('');
  const [showInactive, setShowInactive] = useState(false);
  const [showNewModal, setShowNewModal] = useState(false);
  const [editPart, setEditPart] = useState<CatalogPartResponse | null>(null);

  const { data: parts, isLoading, refetch } = useCatalogParts({
    search: search || undefined,
    part_type: typeFilter || undefined,
    is_active: showInactive ? undefined : true,
  });

  const deactivate = useDeactivateCatalogPart();

  const handleDeactivate = (part: CatalogPartResponse) => {
    if (!confirm(`Deactivate "${part.name}"? It will no longer appear in BOM search.`)) return;
    deactivate.mutate(part.id, {
      onSuccess: () => toast.success('Part deactivated'),
      onError: () => toast.error('Failed to deactivate part'),
    });
  };

  return (
    <div className="p-6">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-slate-100">Purchased Parts Library</h1>
          <p className="text-slate-400 text-sm mt-1">Central repository of reusable purchased parts — link from any project</p>
        </div>
        <button
          onClick={() => setShowNewModal(true)}
          className="px-4 py-2 bg-blue-600 text-white rounded-lg text-sm font-medium hover:bg-blue-700"
        >
          + New Part
        </button>
      </div>

      {/* Filters */}
      <div className="flex gap-3 mb-4">
        <input
          className="bg-slate-700 text-slate-100 rounded px-3 py-2 text-sm border border-slate-600 focus:outline-none focus:border-blue-500 w-64"
          placeholder="Search by name or part number..."
          value={search}
          onChange={e => setSearch(e.target.value)}
        />
        <select
          className="bg-slate-700 text-slate-100 rounded px-3 py-2 text-sm border border-slate-600 focus:outline-none focus:border-blue-500"
          value={typeFilter}
          onChange={e => setTypeFilter(e.target.value)}
        >
          <option value="">All types</option>
          <option value="purchased">Purchased</option>
          <option value="manufactured">Manufactured</option>
        </select>
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

      {/* Table */}
      {isLoading ? (
        <div className="text-slate-400 text-sm">Loading...</div>
      ) : (
        <div className="bg-slate-800 rounded-xl border border-slate-700 overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-700">
                <th className="text-left px-4 py-3 text-slate-400 font-medium">Part Number</th>
                <th className="text-left px-4 py-3 text-slate-400 font-medium">Name</th>
                <th className="text-left px-4 py-3 text-slate-400 font-medium">Type</th>
                <th className="text-left px-4 py-3 text-slate-400 font-medium">Unit</th>
                <th className="text-left px-4 py-3 text-slate-400 font-medium">Supplier</th>
                <th className="text-left px-4 py-3 text-slate-400 font-medium">Status</th>
                <th className="text-left px-4 py-3 text-slate-400 font-medium">Actions</th>
              </tr>
            </thead>
            <tbody>
              {(parts ?? []).length === 0 ? (
                <tr>
                  <td colSpan={7} className="px-4 py-8 text-center text-slate-500">
                    No parts found. Create your first part.
                  </td>
                </tr>
              ) : (
                (parts ?? []).map(part => (
                  <tr key={part.id} className="border-b border-slate-700/50 hover:bg-slate-700/30">
                    <td className="px-4 py-3 text-slate-100 font-mono">{part.part_number}</td>
                    <td className="px-4 py-3 text-slate-200">{part.name}</td>
                    <td className="px-4 py-3">
                      <span className={`px-2 py-0.5 rounded text-xs font-medium ${
                        part.part_type === 'purchased'
                          ? 'bg-blue-900/50 text-blue-300'
                          : 'bg-purple-900/50 text-purple-300'
                      }`}>
                        {part.part_type}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-slate-300">{part.unit}</td>
                    <td className="px-4 py-3 text-slate-300">{part.supplier || '—'}</td>
                    <td className="px-4 py-3">
                      {part.is_active ? (
                        <span className="text-green-400 text-xs">Active</span>
                      ) : (
                        <span className="text-slate-500 text-xs">Inactive</span>
                      )}
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex gap-2">
                        <button
                          onClick={() => setEditPart(part)}
                          className="text-xs text-blue-400 hover:text-blue-300"
                        >
                          Edit
                        </button>
                        {part.is_active && (
                          <button
                            onClick={() => handleDeactivate(part)}
                            className="text-xs text-red-400 hover:text-red-300"
                          >
                            Deactivate
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      )}

      {showNewModal && (
        <NewPartModal onClose={() => setShowNewModal(false)} onCreated={() => refetch()} />
      )}
      {editPart && (
        <EditPartModal part={editPart} onClose={() => setEditPart(null)} />
      )}
    </div>
  );
}
