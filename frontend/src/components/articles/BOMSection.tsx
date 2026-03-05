/**
 * BOMSection - BOM tab content for an article revision
 */
import { useState } from 'react';
import { toast } from 'sonner';
import { useBOM, useUpdateBOMItem, useDeleteBOMItem } from '../../hooks/queries/useBOM';
import type { BOMItemResponse } from '../../types/bom';
import AddBOMItemModal from './AddBOMItemModal';

interface Props {
  articleId: number;
  revisionId: number;
}

interface EditRowState {
  itemId: number;
  quantity: string;
  notes: string;
}

export default function BOMSection({ articleId, revisionId }: Props) {
  const { data: bom, isLoading } = useBOM(articleId, revisionId);
  const updateItem = useUpdateBOMItem(articleId, revisionId);
  const deleteItem = useDeleteBOMItem(articleId, revisionId);
  const [showAddModal, setShowAddModal] = useState(false);
  const [editRow, setEditRow] = useState<EditRowState | null>(null);

  if (isLoading) return <div className="text-slate-400 text-sm p-4">Loading BOM...</div>;

  const items = bom?.items ?? [];

  const handleDelete = (item: BOMItemResponse) => {
    if (!confirm(`Remove "${item.name}" from BOM?`)) return;
    deleteItem.mutate(item.id, {
      onSuccess: () => toast.success('Item removed'),
      onError: () => toast.error('Failed to remove item'),
    });
  };

  const handleEditSave = (item: BOMItemResponse) => {
    if (!editRow) return;
    updateItem.mutate(
      {
        itemId: item.id,
        data: {
          quantity: parseFloat(editRow.quantity),
          notes: editRow.notes || null,
        },
      },
      {
        onSuccess: () => { toast.success('Updated'); setEditRow(null); },
        onError: () => toast.error('Failed to update'),
      }
    );
  };

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <div>
          <h3 className="text-slate-100 font-medium">Bill of Materials</h3>
          <p className="text-slate-400 text-xs mt-0.5">{items.length} item{items.length !== 1 ? 's' : ''}</p>
        </div>
        <button
          onClick={() => setShowAddModal(true)}
          className="px-3 py-1.5 bg-blue-600 text-white rounded text-sm hover:bg-blue-700"
        >
          + Add Part
        </button>
      </div>

      {items.length === 0 ? (
        <div className="text-center py-12 text-slate-500 text-sm">
          No parts in BOM yet. Click "Add Part" to get started.
        </div>
      ) : (
        <div className="bg-slate-800 rounded-xl border border-slate-700 overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-700">
                <th className="text-left px-3 py-2.5 text-slate-400 font-medium w-8">#</th>
                <th className="text-left px-3 py-2.5 text-slate-400 font-medium">Part Number</th>
                <th className="text-left px-3 py-2.5 text-slate-400 font-medium">Name</th>
                <th className="text-left px-3 py-2.5 text-slate-400 font-medium">Type</th>
                <th className="text-left px-3 py-2.5 text-slate-400 font-medium">Qty</th>
                <th className="text-left px-3 py-2.5 text-slate-400 font-medium">Unit</th>
                <th className="text-left px-3 py-2.5 text-slate-400 font-medium">Supplier</th>
                <th className="text-left px-3 py-2.5 text-slate-400 font-medium">Notes</th>
                <th className="text-left px-3 py-2.5 text-slate-400 font-medium">Actions</th>
              </tr>
            </thead>
            <tbody>
              {items.map((item, idx) => {
                const isEditing = editRow?.itemId === item.id;
                return (
                  <tr key={item.id} className="border-b border-slate-700/50 hover:bg-slate-700/20">
                    <td className="px-3 py-2.5 text-slate-500">{idx + 1}</td>
                    <td className="px-3 py-2.5 text-slate-300 font-mono text-xs">{item.part_number || '—'}</td>
                    <td className="px-3 py-2.5 text-slate-100">{item.name}</td>
                    <td className="px-3 py-2.5">
                      {item.part_type ? (
                        <span className={`px-1.5 py-0.5 rounded text-xs ${
                          item.part_type === 'purchased'
                            ? 'bg-blue-900/50 text-blue-300'
                            : 'bg-purple-900/50 text-purple-300'
                        }`}>{item.part_type}</span>
                      ) : '—'}
                    </td>
                    <td className="px-3 py-2.5">
                      {isEditing ? (
                        <input
                          type="number"
                          min="0.001"
                          step="any"
                          className="w-20 bg-slate-700 text-slate-100 rounded px-2 py-1 text-xs border border-slate-500"
                          value={editRow.quantity}
                          onChange={e => setEditRow(r => r ? { ...r, quantity: e.target.value } : r)}
                        />
                      ) : (
                        <span className="text-slate-200">{item.quantity}</span>
                      )}
                    </td>
                    <td className="px-3 py-2.5 text-slate-300">{item.unit}</td>
                    <td className="px-3 py-2.5 text-slate-400">{item.supplier || '—'}</td>
                    <td className="px-3 py-2.5">
                      {isEditing ? (
                        <input
                          className="w-32 bg-slate-700 text-slate-100 rounded px-2 py-1 text-xs border border-slate-500"
                          value={editRow.notes}
                          onChange={e => setEditRow(r => r ? { ...r, notes: e.target.value } : r)}
                          placeholder="Notes..."
                        />
                      ) : (
                        <span className="text-slate-400 text-xs">{item.notes || '—'}</span>
                      )}
                    </td>
                    <td className="px-3 py-2.5">
                      {isEditing ? (
                        <div className="flex gap-2">
                          <button
                            onClick={() => handleEditSave(item)}
                            disabled={updateItem.isPending}
                            className="text-xs text-green-400 hover:text-green-300 disabled:opacity-50"
                          >
                            Save
                          </button>
                          <button
                            onClick={() => setEditRow(null)}
                            className="text-xs text-slate-400 hover:text-slate-200"
                          >
                            Cancel
                          </button>
                        </div>
                      ) : (
                        <div className="flex gap-2">
                          <button
                            onClick={() => setEditRow({ itemId: item.id, quantity: String(item.quantity), notes: item.notes || '' })}
                            className="text-xs text-blue-400 hover:text-blue-300"
                          >
                            Edit
                          </button>
                          <button
                            onClick={() => handleDelete(item)}
                            className="text-xs text-red-400 hover:text-red-300"
                          >
                            Remove
                          </button>
                        </div>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {showAddModal && (
        <AddBOMItemModal
          articleId={articleId}
          revisionId={revisionId}
          onClose={() => setShowAddModal(false)}
        />
      )}
    </div>
  );
}
