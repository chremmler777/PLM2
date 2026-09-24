/**
 * ArticleTextField - one short text field of an article (colour code, grain)
 * shown as a button and edited inline like the Tier 1 number: Enter or Save
 * stores it (trimmed, empty clears), Escape or Cancel leaves it. The wrapper
 * carries data-field-key so ?focus= and the worksheet's Edit land on it.
 */
import { useState, type ReactNode } from 'react';
import { useMutation } from '@tanstack/react-query';
import { toast } from 'sonner';
import client from '../../api/client';
import { apiErrorMessage } from '../../lib/apiError';

export interface ArticleTextFieldProps {
  partId: number;
  field: 'colour_code' | 'grain';
  label: string;
  value: string | null | undefined;
  placeholder: string;
  title?: string;
  /** The FieldNoteMarker for part.<field>. */
  marker?: ReactNode;
  onSaved(): void;
}

export default function ArticleTextField({ partId, field, label, value, placeholder, title, marker, onSaved }: ArticleTextFieldProps) {
  const [editing, setEditing] = useState<string | null>(null);
  const save = useMutation({
    mutationFn: (v: string) => client.put(`/v1/parts/${partId}`, { [field]: v.trim() || null }),
    onSuccess: () => { toast.success(`${label} saved`); setEditing(null); onSaved(); },
    onError: (e) => toast.error(apiErrorMessage(e, `Could not save the ${label.toLowerCase()}`)),
  });
  return (
    <div data-field-key={`part.${field}`}>
      <div className="text-sm text-slate-400">{label}{marker}</div>
      {editing === null ? (
        <button type="button" data-testid={`edit-${field}`} title={title} onClick={() => setEditing(value ?? '')}
          className={`font-mono text-sm ${value ? 'font-medium text-slate-100' : 'text-slate-400'} hover:text-slate-200`}>
          {value || `+ ${label.toLowerCase()}`}
        </button>
      ) : (
        <div className="flex items-center gap-2">
          <input data-testid={`${field}-input`} autoFocus value={editing} placeholder={placeholder}
            onChange={(e) => setEditing(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') save.mutate(editing);
              if (e.key === 'Escape') setEditing(null);
            }}
            className="w-32 bg-slate-800 border border-slate-600 rounded px-2 py-1 text-slate-100 font-mono text-sm" />
          <button type="button" data-testid={`save-${field}`} disabled={save.isPending} onClick={() => save.mutate(editing)}
            className="text-sm px-2 py-1 rounded bg-blue-600 hover:bg-blue-500 disabled:bg-slate-600 text-white">Save</button>
          <button type="button" onClick={() => setEditing(null)}
            className="text-sm px-2 py-1 rounded bg-slate-700 hover:bg-slate-600 text-slate-100">Cancel</button>
        </div>
      )}
    </div>
  );
}
