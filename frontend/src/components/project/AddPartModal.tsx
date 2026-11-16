/**
 * "+ Add Part" dialog: any controlled item category, optional parent sub-assembly.
 * It offers only the kinds the viewer may create (tools: Tool Engineer; gauges: APQP or
 * Project Manager; assembly equipment and EOATs: Manufacturing Engineer or Project
 * Manager; an admin all). A gauge, EOAT or station can name the tool it serves: the
 * dialog then fills in the next free number of that tool (asked from the server, which
 * looks across all projects; the project's own list is the stand-in until it answers)
 * and links the two. A tool is optional: an assembly operation or an assembly gauge has
 * none and is numbered on the project code (<code>-60, ... for equipment, <code>-70, ...
 * for gauges). The tool is picked from a list that narrows as you type, not a long
 * dropdown. Equipment shows only the fields it has (no customer number, type, catalog
 * part or supplier); after creating it the page opens its BOM, where the articles are
 * dragged in.
 */
import { useEffect, useRef, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import client from '../../api/client';
import { apiErrorMessage } from '../../lib/apiError';
import { comparePartNumbers } from '../../lib/partDisplay';
import { useCanEditAssemblyEquipment, useCanEditGauges, useCanEditTools } from '../../hooks/queries/useToolRights';
import {
  EQUIPMENT_KINDS, categoryOfKind, familyOfKind, noToolFamilyOfKind, suggestEquipmentNumber, type ItemKind,
} from './equipmentNumbers';
import { useCatalogParts } from '../../hooks/queries/useProjectDetail';
import { useSuppliers } from '../../hooks/queries/useSuppliers';
import type { Part } from './projectTypes';

const EMPTY_FORM = {
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
  kind: 'article' as ItemKind,
  /** The tool a gauge, EOAT or station serves; empty = free number, no link. */
  serves_tool_id: '',
  /** Assembly equipment only: in-cell station (-2x) or secondary station (-3x). */
  station: '2' as '2' | '3',
  calibration_interval_months: '',
};

export default function AddPartModal({
  projectId,
  projectCode,
  parts,
  isOpen,
  onClose,
  onCreated,
}: {
  projectId: number;
  /** Base of the number of equipment without a tool: <project code>-60, -70, ... */
  projectCode?: string;
  parts: Part[] | undefined;
  isOpen: boolean;
  onClose: () => void;
  /** The new item's id, so the page can select it; for equipment it also opens the BOM. */
  onCreated?: (partId: number, isEquipment: boolean) => void;
}) {
  const queryClient = useQueryClient();
  const { data: catalogParts } = useCatalogParts();
  const { data: suppliers } = useSuppliers();
  const canEditTools = useCanEditTools();
  const canEditGauges = useCanEditGauges();
  const canEditAssemblyEquipment = useCanEditAssemblyEquipment();
  const [formData, setFormData] = useState(EMPTY_FORM);
  const [toolSearch, setToolSearch] = useState('');
  /** The number the dialog last filled in itself; a number the user typed is never replaced. */
  const lastSuggestion = useRef('');
  const tools = (parts ?? []).filter((p) => p.item_category === 'tool')
    .sort((a, b) => comparePartNumbers(a.part_number, b.part_number));
  const servedTool = (data: typeof formData) =>
    EQUIPMENT_KINDS.has(data.kind) ? tools.find((t) => String(t.id) === data.serves_tool_id) : undefined;

  /**
   * What the number hangs on: the served tool (families 1 to 4), or the project code
   * when the item serves no tool (family 6 assembly operation, 7 assembly gauge).
   */
  const numberBase = (data: typeof formData): { base: string | null; family: number; toolId: number | null } | null => {
    if (!EQUIPMENT_KINDS.has(data.kind)) return null;
    const tool = servedTool(data);
    if (tool) return { base: tool.part_number, family: familyOfKind(data.kind, data.station)!, toolId: tool.id };
    return { base: projectCode ?? null, family: noToolFamilyOfKind(data.kind), toolId: null };
  };

  /** After the kind, the tool or the station type changed: put the next free number in (it stays editable). */
  const withSuggestedNumber = (next: typeof formData): typeof formData => {
    const target = numberBase(next);
    const suggestion = target?.base
      ? suggestEquipmentNumber(target.base, target.family, (parts ?? []).map((p) => p.part_number))
      : null;
    // A number the user typed stays; one the dialog filled in follows the new choice.
    const ours = next.part_number === '' || next.part_number === lastSuggestion.current;
    if (!suggestion) {
      if (!ours) return next;
      lastSuggestion.current = '';
      return { ...next, part_number: '' };
    }
    lastSuggestion.current = suggestion;
    return { ...next, part_number: suggestion };
  };

  // The server knows the numbers of every project; its answer replaces the stand-in
  // unless the user has typed a number of their own in the meantime.
  const target = numberBase(formData);
  const { data: serverNumber } = useQuery({
    queryKey: ['next-equipment-number', projectId, target?.toolId ?? null, target?.family ?? null],
    queryFn: async () => (await client.get('/v1/parts/next-equipment-number', {
      params: target!.toolId !== null
        ? { tool_id: target!.toolId, family: target!.family }
        : { project_id: projectId, family: target!.family },
    })).data as { number?: string | null; base?: string },
    enabled: isOpen && !!target,
    staleTime: 0,
  });
  // All ten numbers of the family are used: say so and let the user type one.
  const familyFull = !!target && !!serverNumber && serverNumber.number === null;
  const fullBase = serverNumber?.base ?? target?.base ?? '';
  useEffect(() => {
    if (!serverNumber || !target) return;
    const number = serverNumber.number;
    if (number === undefined) return;
    setFormData((current) => {
      const ours = current.part_number === '' || current.part_number === lastSuggestion.current;
      if (!ours || current.part_number === (number ?? '')) return current;
      lastSuggestion.current = number ?? '';
      return { ...current, part_number: number ?? '' };
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [serverNumber, target?.toolId, target?.family]);

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
        item_category: categoryOfKind(data.kind),
      };
      if (data.supplier_id) {
        payload.supplier_id = parseInt(data.supplier_id, 10);
      }
      if (data.parent_part_id) {
        payload.parent_part_id = parseInt(data.parent_part_id, 10);
      }
      if (data.kind === 'gauge' && data.calibration_interval_months) {
        payload.calibration_interval_months = parseInt(data.calibration_interval_months, 10);
      }
      const res = await client.post('/v1/parts', payload);
      const tool = servedTool(data);
      if (tool) {
        // The part exists now; a refused link must not look like a failed create.
        try {
          await client.post(`/v1/parts/${res.data.id}/relations`, { to_part_id: tool.id, relation_type: 'serves' });
        } catch (error) {
          toast.error(`${data.part_number} was created, but the link to tool ${tool.part_number} failed: ${apiErrorMessage(error, 'please link it on the item')}`);
        }
      }
      return res.data;
    },
    onSuccess: async (created: { id?: number } | undefined) => {
      // The list first, so the page finds the new item when it selects it.
      await queryClient.invalidateQueries({ queryKey: ['parts', projectId] });
      queryClient.invalidateQueries({ queryKey: ['project-structure', projectId] });
      queryClient.invalidateQueries({ queryKey: ['part-relations'] });
      queryClient.invalidateQueries({ queryKey: ['next-equipment-number'] });
      setFormData(EMPTY_FORM);
      setToolSearch('');
      onClose();
      if (created?.id) onCreated?.(created.id, EQUIPMENT_KINDS.has(formData.kind));
    },
    onError: (error: unknown) => {
      toast.error(apiErrorMessage(error, 'Failed to create the item'));
    },
  });

  if (!isOpen) return null;

  const isEquipment = EQUIPMENT_KINDS.has(formData.kind);
  const subAssemblies = parts?.filter((p) => p.part_type === 'sub_assembly') || [];

  return (
    <div className="fixed inset-0 z-40 bg-black/50 flex items-center justify-center">
      <div role="dialog" aria-modal="true" aria-label="Add New Item"
        className="bg-slate-800 rounded-lg border border-slate-700 p-6 max-w-md w-full mx-4 max-h-[92vh] overflow-y-auto">
        <h2 className="text-xl font-bold text-slate-100 mb-4">Add New Item</h2>

        <div className="space-y-4">
          <div>
            <label htmlFor="add-part-kind" className="block text-sm font-medium text-slate-300 mb-1">Item Category *</label>
            <select
              id="add-part-kind"
              value={formData.kind}
              onChange={(e) => {
                const kind = e.target.value as ItemKind;
                setFormData(withSuggestedNumber({
                  ...formData, kind, serves_tool_id: EQUIPMENT_KINDS.has(kind) ? formData.serves_tool_id : '',
                }));
              }}
              className="w-full bg-slate-700 border border-slate-600 rounded px-3 py-2 text-slate-100 text-sm"
            >
              <option value="article">📄 Article (product part)</option>
              {canEditTools && <option value="tool">🔧 Tool (die, mold, fixture)</option>}
              {canEditAssemblyEquipment && <option value="assembly_equipment">🏗️ Assembly Equipment</option>}
              {canEditAssemblyEquipment && <option value="eoat">🦾 EOAT (end of arm tool)</option>}
              {canEditGauges && <option value="gauge">📏 Gauge (calibration controlled)</option>}
            </select>
          </div>

          {EQUIPMENT_KINDS.has(formData.kind) && (
            <div>
              <label htmlFor="add-part-serves-tool" className="block text-sm font-medium text-slate-300 mb-1">Serves tool</label>
              <input
                id="add-part-serves-tool"
                type="search"
                value={toolSearch}
                onChange={(e) => setToolSearch(e.target.value)}
                placeholder="Type a tool number or name to narrow the list"
                className="w-full bg-slate-700 border border-slate-600 rounded-t px-3 py-2 text-slate-100 text-sm placeholder:text-slate-400 focus:border-sky-400 focus:outline-none"
              />
              <ul role="listbox" aria-label="Tools" data-testid="serves-tool-list"
                className="max-h-44 overflow-y-auto rounded-b border border-t-0 border-slate-600 bg-slate-900/40 text-sm">
                {[{ id: '', label: formData.kind === 'gauge' ? 'No tool (assembly gauge)' : 'No tool (assembly operation)' },
                  ...tools.map((t) => ({ id: String(t.id), label: `${t.part_number} - ${t.name}` }))]
                  .filter((o) => o.id === formData.serves_tool_id
                    || toolSearch.toLowerCase().split(/\s+/).filter(Boolean).every((w) => o.label.toLowerCase().includes(w)))
                  .map((o) => {
                    const selected = o.id === formData.serves_tool_id;
                    return (
                      <li key={o.id || 'none'} role="option" aria-selected={selected}>
                        <button type="button"
                          onClick={() => setFormData(withSuggestedNumber({ ...formData, serves_tool_id: o.id }))}
                          className={`block w-full truncate px-3 py-1.5 text-left ${
                            selected ? 'bg-blue-600 text-white' : 'text-slate-200 hover:bg-slate-700'
                          }`}>
                          {o.label}
                        </button>
                      </li>
                    );
                  })}
              </ul>
              <p data-testid="serves-tool-help" className="text-xs text-slate-400 mt-1">
                {formData.serves_tool_id
                  ? 'The next free number of this tool is filled in below and the item is linked to the tool. More tools can be added on its card.'
                  : familyFull
                    ? `All numbers ${fullBase}-${target!.family}0 to -${target!.family}9 are used, type a number.`
                    : 'No tool is needed. A number on the project code is filled in below; you can change it.'}
              </p>
            </div>
          )}

          {formData.kind === 'assembly_equipment' && formData.serves_tool_id && (
            <div>
              <label htmlFor="add-part-station" className="block text-sm font-medium text-slate-300 mb-1">Station type</label>
              <select
                id="add-part-station"
                value={formData.station}
                onChange={(e) => setFormData(withSuggestedNumber({ ...formData, station: e.target.value as '2' | '3' }))}
                className="w-full bg-slate-700 border border-slate-600 rounded px-3 py-2 text-slate-100 text-sm"
              >
                <option value="2">In-cell station (-20, -21, ...)</option>
                <option value="3">Secondary station (-30, -31, ...)</option>
              </select>
            </div>
          )}

          {formData.kind === 'gauge' && (
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
            <label htmlFor="add-part-number" className="block text-sm font-medium text-slate-300 mb-1">Part Number *</label>
            <input
              id="add-part-number"
              type="text"
              value={formData.part_number}
              onChange={(e) => setFormData({ ...formData, part_number: e.target.value })}
              className="w-full bg-slate-700 border border-slate-600 rounded px-3 py-2 text-slate-100 text-sm"
              placeholder="e.g., P-001"
            />
          </div>

          {!isEquipment && (<>
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

          </>)}

          <div>
            <label htmlFor="add-part-name" className="block text-sm font-medium text-slate-300 mb-1">Name *</label>
            <input
              id="add-part-name"
              type="text"
              value={formData.name}
              onChange={(e) => setFormData({ ...formData, name: e.target.value })}
              className="w-full bg-slate-700 border border-slate-600 rounded px-3 py-2 text-slate-100 text-sm"
              placeholder="e.g., Housing"
            />
          </div>

          {!isEquipment && (<>
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

          </>)}

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
            {createMutation.isPending ? 'Creating...' : isEquipment ? 'Create and open BOM' : 'Add Part'}
          </button>
        </div>
      </div>
    </div>
  );
}
