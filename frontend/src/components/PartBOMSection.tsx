/**
 * PartBOMSection - Revision-scoped BOM editor for sub-assemblies.
 * Items reference project parts, catalog parts, or free text.
 */
import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import client from '../api/client';
import { toast } from 'sonner';

interface BOMItem {
  id: number;
  revision_id: number;
  child_part_id: number | null;
  catalog_part_id: number | null;
  item_number: string;
  name: string;
  quantity: number;
  unit: string;
  position: number;
  notes: string | null;
  child_part_number: string | null;
  child_part_type: string | null;
  catalog_part_number: string | null;
  catalog_supplier: string | null;
}

interface ProjectPartOption {
  id: number;
  part_number: string;
  name: string;
}

interface CatalogPartOption {
  id: number;
  part_number: string;
  name: string;
  supplier: string | null;
}

interface Props {
  partId: number;
  revisionId: number;
  revisionName?: string;
  locked: boolean;
  projectParts: ProjectPartOption[];
}

function useBOMItems(revisionId: number) {
  return useQuery<BOMItem[]>({
    queryKey: ['part-bom', revisionId],
    queryFn: async () => {
      const res = await client.get(`/v1/parts/revisions/${revisionId}/bom`);
      return res.data;
    },
    enabled: !!revisionId,
  });
}

function QuantityCell({ item, locked }: { item: BOMItem; locked: boolean }) {
  const queryClient = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState(String(item.quantity));

  const updateMutation = useMutation({
    mutationFn: async (quantity: number) => {
      await client.put(`/v1/parts/bom-items/${item.id}`, { quantity });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['part-bom', item.revision_id] });
      setEditing(false);
    },
    onError: (error: any) => {
      toast.error(error.response?.data?.detail || 'Failed to update quantity');
      setValue(String(item.quantity));
      setEditing(false);
    },
  });

  const commit = () => {
    const qty = parseFloat(value);
    if (isNaN(qty) || qty <= 0) {
      setValue(String(item.quantity));
      setEditing(false);
      return;
    }
    if (qty === item.quantity) {
      setEditing(false);
      return;
    }
    updateMutation.mutate(qty);
  };

  if (locked || !editing) {
    return (
      <button
        onClick={() => !locked && setEditing(true)}
        className={`text-right w-full ${locked ? 'cursor-default' : 'hover:text-blue-300 cursor-pointer'}`}
        title={locked ? undefined : 'Click to edit'}
      >
        {item.quantity}
      </button>
    );
  }

  return (
    <input
      autoFocus
      type="number"
      min="0"
      step="any"
      value={value}
      onChange={(e) => setValue(e.target.value)}
      onBlur={commit}
      onKeyDown={(e) => {
        if (e.key === 'Enter') commit();
        if (e.key === 'Escape') {
          setValue(String(item.quantity));
          setEditing(false);
        }
      }}
      className="w-16 bg-slate-600 border border-blue-500 rounded px-1 py-0.5 text-right text-slate-100 text-xs"
    />
  );
}

export default function PartBOMSection({ partId, revisionId, revisionName, locked, projectParts }: Props) {
  const queryClient = useQueryClient();
  const { data: items, isLoading } = useBOMItems(revisionId);
  const [showAdd, setShowAdd] = useState(false);
  const [source, setSource] = useState<'project' | 'catalog' | 'free'>('project');
  const [form, setForm] = useState({ refId: '', name: '', quantity: '1', unit: 'pcs', notes: '' });

  const { data: catalogParts } = useQuery<CatalogPartOption[]>({
    queryKey: ['catalog-parts'],
    queryFn: async () => (await client.get('/v1/catalog-parts?is_active=true')).data,
    enabled: showAdd && source === 'catalog',
  });

  const resetForm = () => {
    setForm({ refId: '', name: '', quantity: '1', unit: 'pcs', notes: '' });
    setShowAdd(false);
  };

  const addMutation = useMutation({
    mutationFn: async () => {
      const payload: any = {
        quantity: parseFloat(form.quantity) || 1,
        unit: form.unit || 'pcs',
        notes: form.notes || null,
      };
      if (source === 'project') payload.child_part_id = parseInt(form.refId, 10);
      else if (source === 'catalog') payload.catalog_part_id = parseInt(form.refId, 10);
      else payload.name = form.name;
      await client.post(`/v1/parts/${partId}/revisions/${revisionId}/bom`, payload);
    },
    onSuccess: () => {
      toast.success('BOM item added');
      queryClient.invalidateQueries({ queryKey: ['part-bom', revisionId] });
      resetForm();
    },
    onError: (error: any) => {
      toast.error(error.response?.data?.detail || 'Failed to add BOM item');
    },
  });

  const deleteMutation = useMutation({
    mutationFn: async (itemId: number) => {
      await client.delete(`/v1/parts/bom-items/${itemId}`);
    },
    onSuccess: () => {
      toast.success('BOM item removed');
      queryClient.invalidateQueries({ queryKey: ['part-bom', revisionId] });
    },
    onError: (error: any) => {
      toast.error(error.response?.data?.detail || 'Failed to remove BOM item');
    },
  });

  const canSubmit =
    (source === 'free' ? form.name.trim().length > 0 : form.refId !== '') &&
    parseFloat(form.quantity) > 0;

  const availableParts = projectParts.filter((p) => p.id !== partId);

  return (
    <div className="bg-slate-800 rounded-lg border border-slate-700 p-4">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-semibold text-slate-200">
          BOM{revisionName ? <span className="text-slate-400 font-normal"> — {revisionName}</span> : null}
          {locked && <span className="ml-2 text-xs text-amber-400">🔒 read-only</span>}
        </h3>
        {!locked && !showAdd && (
          <button
            onClick={() => setShowAdd(true)}
            className="px-3 py-1 rounded bg-blue-600 hover:bg-blue-500 text-white text-xs font-medium"
          >
            + Add Item
          </button>
        )}
      </div>

      {isLoading ? (
        <p className="text-slate-500 text-sm">Loading...</p>
      ) : !items || items.length === 0 ? (
        <p className="text-slate-500 text-sm">No BOM items yet</p>
      ) : (
        <table className="w-full text-xs">
          <thead>
            <tr className="text-slate-400 border-b border-slate-700">
              <th className="text-left py-1.5 pr-2 font-medium w-12">Pos</th>
              <th className="text-left py-1.5 pr-2 font-medium">Item</th>
              <th className="text-right py-1.5 pr-2 font-medium w-16">Qty</th>
              <th className="text-left py-1.5 pr-2 font-medium w-12">Unit</th>
              <th className="text-left py-1.5 pr-2 font-medium">Notes</th>
              {!locked && <th className="w-8"></th>}
            </tr>
          </thead>
          <tbody>
            {items.map((item) => (
              <tr key={item.id} className="border-b border-slate-700/50 text-slate-200">
                <td className="py-1.5 pr-2 text-slate-400 font-mono">{item.item_number}</td>
                <td className="py-1.5 pr-2">
                  <span className="font-medium">{item.name}</span>
                  <span className="text-slate-500 ml-1 font-mono">
                    {item.child_part_number || item.catalog_part_number || ''}
                  </span>
                  {item.catalog_supplier && (
                    <span className="text-slate-500 ml-1">({item.catalog_supplier})</span>
                  )}
                </td>
                <td className="py-1.5 pr-2 text-right">
                  <QuantityCell item={item} locked={locked} />
                </td>
                <td className="py-1.5 pr-2 text-slate-400">{item.unit}</td>
                <td className="py-1.5 pr-2 text-slate-400 truncate max-w-[140px]">{item.notes || ''}</td>
                {!locked && (
                  <td className="py-1.5 text-right">
                    <button
                      onClick={() => deleteMutation.mutate(item.id)}
                      disabled={deleteMutation.isPending}
                      className="text-red-400 hover:text-red-300 text-xs"
                      title="Remove item"
                    >
                      ✕
                    </button>
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {showAdd && !locked && (
        <div className="mt-3 p-3 bg-slate-700/50 rounded border border-slate-600 space-y-2">
          <div className="flex gap-2">
            {(['project', 'catalog', 'free'] as const).map((s) => (
              <button
                key={s}
                onClick={() => {
                  setSource(s);
                  setForm({ ...form, refId: '', name: '' });
                }}
                className={`px-2 py-1 rounded text-xs font-medium ${
                  source === s ? 'bg-blue-600 text-white' : 'bg-slate-600 text-slate-300 hover:bg-slate-500'
                }`}
              >
                {s === 'project' ? 'Project Part' : s === 'catalog' ? 'Catalog Part' : 'Free Text'}
              </button>
            ))}
          </div>

          {source === 'project' && (
            <select
              value={form.refId}
              onChange={(e) => setForm({ ...form, refId: e.target.value })}
              className="w-full bg-slate-700 border border-slate-600 rounded px-2 py-1.5 text-slate-100 text-xs"
            >
              <option value="">-- Select project part --</option>
              {availableParts.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.part_number} — {p.name}
                </option>
              ))}
            </select>
          )}
          {source === 'catalog' && (
            <select
              value={form.refId}
              onChange={(e) => setForm({ ...form, refId: e.target.value })}
              className="w-full bg-slate-700 border border-slate-600 rounded px-2 py-1.5 text-slate-100 text-xs"
            >
              <option value="">-- Select catalog part --</option>
              {catalogParts?.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.part_number} — {p.name}
                  {p.supplier ? ` (${p.supplier})` : ''}
                </option>
              ))}
            </select>
          )}
          {source === 'free' && (
            <input
              type="text"
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
              placeholder="Item name, e.g. Adhesive tape"
              className="w-full bg-slate-700 border border-slate-600 rounded px-2 py-1.5 text-slate-100 text-xs"
            />
          )}

          <div className="flex gap-2">
            <input
              type="number"
              min="0"
              step="any"
              value={form.quantity}
              onChange={(e) => setForm({ ...form, quantity: e.target.value })}
              placeholder="Qty"
              className="w-20 bg-slate-700 border border-slate-600 rounded px-2 py-1.5 text-slate-100 text-xs"
            />
            <input
              type="text"
              value={form.unit}
              onChange={(e) => setForm({ ...form, unit: e.target.value })}
              placeholder="Unit"
              className="w-20 bg-slate-700 border border-slate-600 rounded px-2 py-1.5 text-slate-100 text-xs"
            />
            <input
              type="text"
              value={form.notes}
              onChange={(e) => setForm({ ...form, notes: e.target.value })}
              placeholder="Notes (optional)"
              className="flex-1 bg-slate-700 border border-slate-600 rounded px-2 py-1.5 text-slate-100 text-xs"
            />
          </div>

          <div className="flex gap-2 justify-end">
            <button
              onClick={resetForm}
              className="px-3 py-1 rounded border border-slate-600 text-slate-300 hover:bg-slate-700 text-xs font-medium"
            >
              Cancel
            </button>
            <button
              onClick={() => addMutation.mutate()}
              disabled={!canSubmit || addMutation.isPending}
              className="px-3 py-1 rounded bg-blue-600 hover:bg-blue-500 disabled:bg-slate-600 text-white text-xs font-medium"
            >
              {addMutation.isPending ? 'Adding...' : 'Add'}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
