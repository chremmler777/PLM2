/**
 * SuppliersPage - supplier master data: list, create, edit, deactivate.
 */
import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import client from '../api/client';
import { toast } from 'sonner';

interface Supplier {
  id: number;
  name: string;
  code: string | null;
  contact_name: string | null;
  contact_email: string | null;
  phone: string | null;
  notes: string | null;
  is_active: boolean;
  part_count?: number;
}

interface SupplierPart {
  id: number;
  part_number: string;
  name: string;
  item_category: string;
  project_id: number;
}

function SupplierModal({ supplier, onClose }: { supplier: Supplier | null; onClose: () => void }) {
  const queryClient = useQueryClient();
  const [form, setForm] = useState({
    name: supplier?.name ?? '',
    code: supplier?.code ?? '',
    contact_name: supplier?.contact_name ?? '',
    contact_email: supplier?.contact_email ?? '',
    phone: supplier?.phone ?? '',
    notes: supplier?.notes ?? '',
  });

  const mutation = useMutation({
    mutationFn: async () => {
      const payload = {
        ...form,
        code: form.code || null,
        contact_name: form.contact_name || null,
        contact_email: form.contact_email || null,
        phone: form.phone || null,
        notes: form.notes || null,
      };
      if (supplier) await client.patch(`/v1/suppliers/${supplier.id}`, payload);
      else await client.post('/v1/suppliers', payload);
    },
    onSuccess: () => {
      toast.success(supplier ? 'Supplier updated' : 'Supplier created');
      queryClient.invalidateQueries({ queryKey: ['suppliers'] });
      onClose();
    },
    onError: (error: any) => {
      toast.error(error.response?.data?.detail || 'Failed to save supplier');
    },
  });

  return (
    <div className="fixed inset-0 z-50 bg-black/50 flex items-center justify-center" onClick={onClose}>
      <div
        className="bg-slate-800 rounded-lg border border-slate-700 p-6 max-w-md w-full mx-4"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 className="text-lg font-bold text-slate-100 mb-4">
          {supplier ? 'Edit Supplier' : 'New Supplier'}
        </h2>
        <div className="space-y-3">
          <input
            type="text"
            value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
            placeholder="Name *"
            className="w-full bg-slate-700 border border-slate-600 rounded px-3 py-2 text-slate-100 text-sm"
          />
          <div className="flex gap-3">
            <input
              type="text"
              value={form.code}
              onChange={(e) => setForm({ ...form, code: e.target.value })}
              placeholder="Vendor code / DUNS"
              className="flex-1 bg-slate-700 border border-slate-600 rounded px-3 py-2 text-slate-100 text-sm"
            />
            <input
              type="text"
              value={form.phone}
              onChange={(e) => setForm({ ...form, phone: e.target.value })}
              placeholder="Phone"
              className="flex-1 bg-slate-700 border border-slate-600 rounded px-3 py-2 text-slate-100 text-sm"
            />
          </div>
          <input
            type="text"
            value={form.contact_name}
            onChange={(e) => setForm({ ...form, contact_name: e.target.value })}
            placeholder="Contact person"
            className="w-full bg-slate-700 border border-slate-600 rounded px-3 py-2 text-slate-100 text-sm"
          />
          <input
            type="email"
            value={form.contact_email}
            onChange={(e) => setForm({ ...form, contact_email: e.target.value })}
            placeholder="Contact email"
            className="w-full bg-slate-700 border border-slate-600 rounded px-3 py-2 text-slate-100 text-sm"
          />
          <textarea
            value={form.notes}
            onChange={(e) => setForm({ ...form, notes: e.target.value })}
            placeholder="Notes"
            rows={2}
            className="w-full bg-slate-700 border border-slate-600 rounded px-3 py-2 text-slate-100 text-sm"
          />
        </div>
        <div className="flex gap-3 mt-5">
          <button
            onClick={onClose}
            className="flex-1 px-4 py-2 rounded border border-slate-600 text-slate-300 hover:bg-slate-700 text-sm font-medium"
          >
            Cancel
          </button>
          <button
            onClick={() => mutation.mutate()}
            disabled={form.name.trim().length < 2 || mutation.isPending}
            className="flex-1 px-4 py-2 rounded bg-blue-600 hover:bg-blue-500 disabled:bg-slate-600 text-white text-sm font-medium"
          >
            {mutation.isPending ? 'Saving...' : 'Save'}
          </button>
        </div>
      </div>
    </div>
  );
}

export default function SuppliersPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [showInactive, setShowInactive] = useState(false);
  const [editing, setEditing] = useState<Supplier | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [expandedId, setExpandedId] = useState<number | null>(null);

  const { data: suppliers, isLoading } = useQuery<Supplier[]>({
    queryKey: ['suppliers', showInactive],
    queryFn: async () =>
      (await client.get(`/v1/suppliers?include_inactive=${showInactive}`)).data,
  });

  const { data: supplierParts } = useQuery<SupplierPart[]>({
    queryKey: ['supplier-parts', expandedId],
    queryFn: async () => (await client.get(`/v1/suppliers/${expandedId}/parts`)).data,
    enabled: !!expandedId,
  });

  const toggleActive = useMutation({
    mutationFn: async (s: Supplier) => {
      await client.patch(`/v1/suppliers/${s.id}`, { is_active: !s.is_active });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['suppliers'] });
    },
    onError: (error: any) => {
      toast.error(error.response?.data?.detail || 'Failed to update supplier');
    },
  });

  return (
    <div className="p-6 bg-slate-900 min-h-screen">
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold text-slate-100">Suppliers</h1>
          <p className="text-slate-400 text-sm mt-1">Vendor master data</p>
        </div>
        <div className="flex items-center gap-3">
          <label className="flex items-center gap-2 text-sm text-slate-400 cursor-pointer">
            <input
              type="checkbox"
              checked={showInactive}
              onChange={(e) => setShowInactive(e.target.checked)}
              className="accent-blue-600"
            />
            Show inactive
          </label>
          <button
            onClick={() => setShowCreate(true)}
            className="px-4 py-2 rounded bg-blue-600 hover:bg-blue-500 text-white text-sm font-medium"
          >
            + New Supplier
          </button>
        </div>
      </div>

      {isLoading ? (
        <p className="text-slate-400">Loading...</p>
      ) : !suppliers || suppliers.length === 0 ? (
        <p className="text-slate-500">No suppliers yet</p>
      ) : (
        <div className="space-y-2">
          {suppliers.map((s) => (
            <div key={s.id} className="bg-slate-800 rounded-lg border border-slate-700">
              <div className="flex items-center justify-between p-4">
                <button
                  onClick={() => setExpandedId(expandedId === s.id ? null : s.id)}
                  className="flex-1 text-left min-w-0"
                >
                  <span className="text-slate-100 font-medium">{s.name}</span>
                  {s.code && <span className="text-slate-400 text-xs font-mono ml-2">{s.code}</span>}
                  {!s.is_active && (
                    <span className="ml-2 px-1.5 py-0.5 rounded bg-red-900/40 text-red-300 text-xs">inactive</span>
                  )}
                  <span className="text-slate-500 text-xs ml-2">
                    {s.part_count ?? 0} part{(s.part_count ?? 0) === 1 ? '' : 's'}
                  </span>
                  {s.contact_email && (
                    <p className="text-slate-400 text-xs mt-0.5">
                      {s.contact_name ? `${s.contact_name} · ` : ''}{s.contact_email}
                    </p>
                  )}
                </button>
                <div className="flex gap-2 flex-shrink-0">
                  <button
                    onClick={() => setEditing(s)}
                    className="px-2 py-1 rounded border border-slate-600 text-slate-300 hover:bg-slate-700 text-xs font-medium"
                  >
                    Edit
                  </button>
                  <button
                    onClick={() => toggleActive.mutate(s)}
                    className={`px-2 py-1 rounded text-xs font-medium text-white ${
                      s.is_active ? 'bg-red-600/80 hover:bg-red-600' : 'bg-green-600/80 hover:bg-green-600'
                    }`}
                  >
                    {s.is_active ? 'Deactivate' : 'Activate'}
                  </button>
                </div>
              </div>
              {expandedId === s.id && (
                <div className="border-t border-slate-700 p-3">
                  {!supplierParts || supplierParts.length === 0 ? (
                    <p className="text-slate-500 text-xs">No parts sourced from this supplier</p>
                  ) : (
                    <div className="flex flex-wrap gap-2">
                      {supplierParts.map((p) => (
                        <button
                          key={p.id}
                          onClick={() => navigate(`/projects/${p.project_id}?part=${p.id}`)}
                          className="px-2 py-1 rounded bg-slate-700/60 hover:bg-slate-700 border border-slate-600 text-xs text-slate-200"
                        >
                          {p.name} <span className="text-slate-400 font-mono">{p.part_number}</span>
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {(showCreate || editing) && (
        <SupplierModal
          supplier={editing}
          onClose={() => {
            setShowCreate(false);
            setEditing(null);
          }}
        />
      )}
    </div>
  );
}
