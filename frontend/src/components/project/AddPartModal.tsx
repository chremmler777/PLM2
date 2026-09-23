/** "+ Add Part" dialog: any controlled item category, optional parent sub-assembly. */
import { useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import client from '../../api/client';
import { useCatalogParts } from '../../hooks/queries/useProjectDetail';
import { useSuppliers } from '../../hooks/queries/useSuppliers';
import type { Part } from './projectTypes';

export default function AddPartModal({
  projectId,
  parts,
  isOpen,
  onClose,
}: {
  projectId: number;
  parts: Part[] | undefined;
  isOpen: boolean;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const { data: catalogParts } = useCatalogParts();
  const { data: suppliers } = useSuppliers();
  const [formData, setFormData] = useState({
    part_number: '',
    customer_part_number: '',
    tier1_part_number: '',
    name: '',
    part_type: 'purchased',
    supplier: '',
    supplier_id: '',
    description: '',
    parent_part_id: '',
    catalog_part_id: '',
    item_category: 'article',
    calibration_interval_months: '',
  });

  const createMutation = useMutation({
    mutationFn: async (data: typeof formData) => {
      const payload: Record<string, unknown> = {
        project_id: projectId,
        part_number: data.part_number,
        customer_part_number: data.customer_part_number || null,
        tier1_part_number: data.tier1_part_number || null,
        name: data.name,
        part_type: data.part_type,
        supplier: data.supplier || null,
        description: data.description || null,
        data_classification: 'confidential',
        item_category: data.item_category,
      };
      if (data.supplier_id) {
        payload.supplier_id = parseInt(data.supplier_id, 10);
      }
      if (data.parent_part_id) {
        payload.parent_part_id = parseInt(data.parent_part_id, 10);
      }
      if (data.item_category === 'gauge' && data.calibration_interval_months) {
        payload.calibration_interval_months = parseInt(data.calibration_interval_months, 10);
      }
      const res = await client.post('/v1/parts', payload);
      return res.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['parts', projectId] });
      setFormData({
        part_number: '',
        customer_part_number: '',
        tier1_part_number: '',
        name: '',
        part_type: 'purchased',
        supplier: '',
        supplier_id: '',
        description: '',
        parent_part_id: '',
        catalog_part_id: '',
        item_category: 'article',
        calibration_interval_months: '',
      });
      onClose();
    },
  });

  if (!isOpen) return null;

  const subAssemblies = parts?.filter((p) => p.part_type === 'sub_assembly') || [];

  return (
    <div className="fixed inset-0 z-40 bg-black/50 flex items-center justify-center">
      <div className="bg-slate-800 rounded-lg border border-slate-700 p-6 max-w-md w-full mx-4">
        <h2 className="text-xl font-bold text-slate-100 mb-4">Add New Item</h2>

        <div className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-slate-300 mb-1">Item Category *</label>
            <select
              value={formData.item_category}
              onChange={(e) => setFormData({ ...formData, item_category: e.target.value })}
              className="w-full bg-slate-700 border border-slate-600 rounded px-3 py-2 text-slate-100 text-sm"
            >
              <option value="article">📄 Article (product part)</option>
              <option value="tool">🔧 Tool (die, mold, fixture)</option>
              <option value="assembly_equipment">🏗️ Assembly Equipment</option>
              <option value="gauge">📏 Gauge (calibration controlled)</option>
            </select>
          </div>

          {formData.item_category === 'gauge' && (
            <div>
              <label className="block text-sm font-medium text-slate-300 mb-1">Calibration Interval (months)</label>
              <input
                type="number"
                min="1"
                max="120"
                value={formData.calibration_interval_months}
                onChange={(e) => setFormData({ ...formData, calibration_interval_months: e.target.value })}
                className="w-full bg-slate-700 border border-slate-600 rounded px-3 py-2 text-slate-100 text-sm"
                placeholder="e.g., 12"
              />
            </div>
          )}
          <div>
            <label className="block text-sm font-medium text-slate-300 mb-1">Part Number *</label>
            <input
              type="text"
              value={formData.part_number}
              onChange={(e) => setFormData({ ...formData, part_number: e.target.value })}
              className="w-full bg-slate-700 border border-slate-600 rounded px-3 py-2 text-slate-100 text-sm"
              placeholder="e.g., P-001"
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-slate-300 mb-1">Customer Part Number</label>
            <input
              type="text"
              data-testid="add-part-customer-number"
              value={formData.customer_part_number}
              onChange={(e) => setFormData({ ...formData, customer_part_number: e.target.value })}
              className="w-full bg-slate-700 border border-slate-600 rounded px-3 py-2 text-slate-100 text-sm"
              placeholder="e.g., 3CR.807.425"
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-slate-300 mb-1">Tier 1 Part Number</label>
            <input
              type="text"
              data-testid="add-part-tier1-number"
              value={formData.tier1_part_number}
              onChange={(e) => setFormData({ ...formData, tier1_part_number: e.target.value })}
              className="w-full bg-slate-700 border border-slate-600 rounded px-3 py-2 text-slate-100 text-sm"
              placeholder="e.g., S00H54-110 (when we are Tier 2)"
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-slate-300 mb-1">Name *</label>
            <input
              type="text"
              value={formData.name}
              onChange={(e) => setFormData({ ...formData, name: e.target.value })}
              className="w-full bg-slate-700 border border-slate-600 rounded px-3 py-2 text-slate-100 text-sm"
              placeholder="e.g., Housing"
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-slate-300 mb-1">Type *</label>
            <select
              value={formData.part_type}
              onChange={(e) => setFormData({ ...formData, part_type: e.target.value })}
              className="w-full bg-slate-700 border border-slate-600 rounded px-3 py-2 text-slate-100 text-sm"
            >
              <option value="purchased">Purchased</option>
              <option value="internal_mfg">Internal Manufacturing</option>
              <option value="sub_assembly">Sub-Assembly</option>
            </select>
          </div>

          {formData.part_type === 'purchased' && (
            <div>
              <label className="block text-sm font-medium text-slate-300 mb-1">Catalog Part</label>
              <select
                value={formData.catalog_part_id}
                onChange={(e) => {
                  const selectedId = e.target.value;
                  const selected = catalogParts?.find((p) => p.id === parseInt(selectedId, 10));
                  if (selected) {
                    setFormData({
                      ...formData,
                      catalog_part_id: selectedId,
                      part_number: selected.part_number,
                      name: selected.name,
                      supplier: selected.supplier || '',
                    });
                  } else {
                    setFormData({ ...formData, catalog_part_id: selectedId, part_number: '', name: '', supplier: '' });
                  }
                }}
                className="w-full bg-slate-700 border border-slate-600 rounded px-3 py-2 text-slate-100 text-sm"
              >
                <option value="">-- Create new purchased part --</option>
                {catalogParts?.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.part_number} - {p.name}
                  </option>
                ))}
              </select>
              {!formData.catalog_part_id && (
                <p className="text-xs text-slate-400 mt-1">Or fill in the details below to create a new part</p>
              )}
            </div>
          )}

          {formData.part_type === 'purchased' && (
            <div>
              <label className="block text-sm font-medium text-slate-300 mb-1">Supplier</label>
              <select
                value={formData.supplier_id}
                onChange={(e) => setFormData({ ...formData, supplier_id: e.target.value })}
                className="w-full bg-slate-700 border border-slate-600 rounded px-3 py-2 text-slate-100 text-sm"
              >
                <option value="">No supplier</option>
                {suppliers?.map((s) => (
                  <option key={s.id} value={s.id}>{s.name}</option>
                ))}
              </select>
            </div>
          )}

          {subAssemblies.length > 0 && (
            <div>
              <label className="block text-sm font-medium text-slate-300 mb-1">Parent Sub-Assembly (optional)</label>
              <select
                value={formData.parent_part_id}
                onChange={(e) => setFormData({ ...formData, parent_part_id: e.target.value })}
                className="w-full bg-slate-700 border border-slate-600 rounded px-3 py-2 text-slate-100 text-sm"
              >
                <option value="">None (top-level)</option>
                {subAssemblies.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.part_number} - {p.name}
                  </option>
                ))}
              </select>
            </div>
          )}

          <div>
            <label className="block text-sm font-medium text-slate-300 mb-1">Description</label>
            <textarea
              value={formData.description}
              onChange={(e) => setFormData({ ...formData, description: e.target.value })}
              className="w-full bg-slate-700 border border-slate-600 rounded px-3 py-2 text-slate-100 text-sm"
              placeholder="Optional description"
              rows={3}
            />
          </div>
        </div>

        <div className="flex gap-3 mt-6">
          <button
            onClick={onClose}
            className="flex-1 px-4 py-2 rounded border border-slate-600 text-slate-300 hover:bg-slate-700 text-sm font-medium"
          >
            Cancel
          </button>
          <button
            onClick={() => createMutation.mutate(formData)}
            disabled={createMutation.isPending || !formData.part_number || !formData.name}
            className="flex-1 px-4 py-2 rounded bg-blue-600 hover:bg-blue-500 disabled:bg-slate-600 text-white text-sm font-medium"
          >
            {createMutation.isPending ? 'Creating...' : 'Add Part'}
          </button>
        </div>
      </div>
    </div>
  );
}
