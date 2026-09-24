/**
 * ToolFieldsCard - the sold state of a tool: cavities, toolmaker, machine
 * tonnage class, target cycle time. Inline edits, one PUT per field with
 * only that key (the backend applies keys that are present). Cavities fall
 * back to the "n cavities" note on the produces relation until set here.
 */
import { useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import client from '../../api/client';
import { toast } from 'sonner';
import { useSuppliers } from '../../hooks/queries/useSuppliers';
import { usePartFieldNoteIndex } from '../../hooks/queries/useFieldNotes';
import { apiErrorMessage } from '../../lib/apiError';
import FieldNoteMarker from '../fieldNotes/FieldNoteMarker';

export interface ToolFieldValues {
  tool_cavities: number | null;
  toolmaker_id: number | null;
  tool_tonnage_class: number | null;
  tool_cycle_time_s: number | null;
}

export function cavitiesFromNotes(notes: (string | null | undefined)[]): number | null {
  let total = 0;
  let found = false;
  for (const n of notes) {
    const m = /(\d+)\s*cavit/i.exec(n ?? '');
    if (m) { total += parseInt(m[1], 10); found = true; }
  }
  return found ? total : null;
}

type NumericKey = 'tool_cavities' | 'tool_tonnage_class' | 'tool_cycle_time_s';

const NUMERIC: { key: NumericKey; fieldKey: string; id: string; label: string; unit: string; step: string; parse(v: string): number }[] = [
  { key: 'tool_cavities', fieldKey: 'tool.cavities', id: 'cavities', label: 'Cavities', unit: '', step: '1', parse: (v) => parseInt(v, 10) },
  { key: 'tool_tonnage_class', fieldKey: 'tool.tonnage_class', id: 'tonnage', label: 'Tonnage class', unit: 't', step: '1', parse: (v) => parseInt(v, 10) },
  { key: 'tool_cycle_time_s', fieldKey: 'tool.cycle_time_s', id: 'cycle', label: 'Target cycle time', unit: 's', step: '0.1', parse: (v) => parseFloat(v) },
];

interface Props {
  partId: number;
  values: ToolFieldValues;
  producedNotes: (string | null | undefined)[];
}

export default function ToolFieldsCard({ partId, values, producedNotes }: Props) {
  const queryClient = useQueryClient();
  const { data: suppliers } = useSuppliers();
  const notes = usePartFieldNoteIndex(partId);
  const [editing, setEditing] = useState<{ key: NumericKey; value: string } | null>(null);

  const save = useMutation({
    mutationFn: (payload: Partial<ToolFieldValues>) => client.put(`/v1/parts/${partId}`, payload),
    onSuccess: () => {
      toast.success('Tool data saved');
      setEditing(null);
      queryClient.invalidateQueries({ queryKey: ['part', String(partId)] });
    },
    onError: (e) => toast.error(apiErrorMessage(e, 'Could not save the tool data')),
  });

  const submitNumeric = (field: (typeof NUMERIC)[number], raw: string) => {
    const trimmed = raw.trim();
    if (trimmed === '') { save.mutate({ [field.key]: null }); return; }
    const n = field.parse(trimmed);
    if (Number.isNaN(n) || n <= 0) { toast.error(`${field.label} must be a positive number`); return; }
    save.mutate({ [field.key]: n });
  };

  const fallbackCavities = values.tool_cavities == null ? cavitiesFromNotes(producedNotes) : null;

  return (
    <div className="bg-slate-800 rounded-lg border border-slate-700 p-6 mb-8">
      <h2 className="text-xl font-bold text-slate-100 mb-4">Tool</h2>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        {NUMERIC.map((field) => {
          const current = values[field.key];
          const shown = current ?? (field.key === 'tool_cavities' ? fallbackCavities : null);
          const isEditing = editing?.key === field.key;
          return (
            <div key={field.key} data-field-key={field.fieldKey}>
              <div className="text-sm text-slate-400">
                {field.label}{field.unit ? ` (${field.unit})` : ''}
                <FieldNoteMarker partId={partId} fieldKey={field.fieldKey} label={field.label} note={notes.get(field.fieldKey)} />
              </div>
              {isEditing ? (
                <div className="flex items-center gap-2 mt-1">
                  <input data-testid={`tool-${field.id}-input`} autoFocus type="number" step={field.step} min="0"
                    value={editing.value} onChange={(e) => setEditing({ key: field.key, value: e.target.value })}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') submitNumeric(field, editing.value);
                      if (e.key === 'Escape') setEditing(null);
                    }}
                    className="w-24 bg-slate-900 border border-slate-600 rounded px-2 py-1 text-slate-100 text-sm" />
                  <button data-testid={`save-tool-${field.id}`} disabled={save.isPending}
                    onClick={() => submitNumeric(field, editing.value)}
                    className="text-sm px-2 py-1 rounded bg-blue-600 hover:bg-blue-500 disabled:bg-slate-600 text-white">Save</button>
                  <button onClick={() => setEditing(null)} className="text-sm px-2 py-1 rounded bg-slate-700 hover:bg-slate-600 text-slate-100">Cancel</button>
                </div>
              ) : (
                <button data-testid={`edit-tool-${field.id}`} title={`Edit ${field.label.toLowerCase()}`}
                  onClick={() => setEditing({ key: field.key, value: current == null ? '' : String(current) })}
                  className="block font-medium text-slate-100 hover:text-blue-300 mt-1">
                  {shown == null ? <span className="text-slate-500">+ set</span> : shown}
                </button>
              )}
              {field.key === 'tool_cavities' && current == null && fallbackCavities != null && (
                <div data-testid="cavities-fallback" className="text-xs text-amber-300 mt-0.5">from the produces note, not confirmed</div>
              )}
            </div>
          );
        })}
        <div data-field-key="tool.toolmaker">
          <div className="text-sm text-slate-400">
            Toolmaker
            <FieldNoteMarker partId={partId} fieldKey="tool.toolmaker" label="Toolmaker" note={notes.get('tool.toolmaker')} />
          </div>
          <select data-testid="toolmaker-select" value={values.toolmaker_id ?? ''} disabled={save.isPending}
            onChange={(e) => save.mutate({ toolmaker_id: e.target.value ? parseInt(e.target.value, 10) : null })}
            className="mt-1 w-full bg-slate-900 border border-slate-600 rounded px-2 py-1 text-slate-100 text-sm">
            <option value="">(not set)</option>
            {suppliers?.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
          </select>
        </div>
      </div>
    </div>
  );
}
