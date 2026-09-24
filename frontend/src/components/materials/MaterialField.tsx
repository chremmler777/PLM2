/**
 * MaterialField - the article's material: picked from MaterialDB (the PLM
 * backend proxies the search) or explicitly new, not in MaterialDB yet.
 * Creating materials happens in MaterialDB, never here.
 */
import { useEffect, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import { refreshPartMaterial, searchMaterials, setPartMaterial, type MaterialInput, type PartMaterial } from '../../api/materials';
import { WORKSHEET_KEY } from '../../hooks/queries/useWorksheet';
import { apiErrorMessage } from '../../lib/apiError';
import MaterialValue from './MaterialValue';

type Mode = 'view' | 'search' | 'new';

export default function MaterialField({ partId, material }: { partId: number; material: PartMaterial }) {
  const qc = useQueryClient();
  const [mode, setMode] = useState<Mode>('view');
  const [query, setQuery] = useState('');
  const [debounced, setDebounced] = useState('');
  const [newText, setNewText] = useState('');

  useEffect(() => {
    const t = setTimeout(() => setDebounced(query.trim()), 250);
    return () => clearTimeout(t);
  }, [query]);

  const search = useQuery({
    queryKey: ['materialdb-search', debounced],
    queryFn: () => searchMaterials(debounced),
    enabled: mode === 'search' && debounced.length >= 2,
    retry: false,
  });

  const refetchPart = () => {
    qc.invalidateQueries({ queryKey: ['part', String(partId)] });
    qc.invalidateQueries({ queryKey: [WORKSHEET_KEY] });
  };
  const save = useMutation({
    mutationFn: (input: MaterialInput) => setPartMaterial(partId, input),
    onSuccess: () => {
      toast.success('Material saved');
      setMode('view');
      setQuery('');
      setNewText('');
      refetchPart();
    },
    onError: (e) => toast.error(apiErrorMessage(e, 'Could not save the material')),
  });
  const refresh = useMutation({
    mutationFn: () => refreshPartMaterial(partId),
    onSuccess: () => { toast.success('Material refreshed from MaterialDB'); refetchPart(); },
    onError: (e) => toast.error(apiErrorMessage(e, 'Could not refresh from MaterialDB')),
  });

  const tab = (m: Mode, label: string, testId: string) => (
    <button type="button" data-testid={testId} aria-pressed={mode === m} onClick={() => setMode(m)}
      className={`px-2 py-0.5 rounded text-xs ${mode === m ? 'bg-blue-600 text-white' : 'bg-slate-700 text-slate-300 hover:bg-slate-600'}`}>
      {label}
    </button>
  );

  return (
    <div>
      <div className="flex items-center gap-2 flex-wrap">
        <MaterialValue material={material} testId="material-value" />
        {mode === 'view' && (
          <button type="button" data-testid="material-change" onClick={() => setMode('search')}
            className="text-xs px-2 py-0.5 rounded bg-slate-700 hover:bg-slate-600 text-slate-200">
            {material.material_source ? 'Change' : '+ set'}
          </button>
        )}
        {mode === 'view' && material.material_source === 'materialdb' && (
          <button type="button" data-testid="material-refresh" disabled={refresh.isPending} onClick={() => refresh.mutate()}
            title="Read the label again from MaterialDB"
            className="text-xs px-2 py-0.5 rounded bg-slate-700 hover:bg-slate-600 text-slate-300 disabled:opacity-50">Refresh</button>
        )}
      </div>

      {mode !== 'view' && (
        <div className="mt-2 p-3 bg-slate-900 border border-slate-700 rounded space-y-2">
          <div className="flex gap-1">
            {tab('search', 'From MaterialDB', 'material-mode-search')}
            {tab('new', 'New material, not in MaterialDB', 'material-mode-new')}
          </div>
          {mode === 'search' ? (
            <div>
              <input data-testid="material-search-input" autoFocus type="search" value={query}
                placeholder="KTX number, trade name, grade, manufacturer"
                onChange={(e) => setQuery(e.target.value)}
                className="w-full bg-slate-800 border border-slate-600 rounded px-2 py-1 text-sm text-slate-100 placeholder-slate-500" />
              {search.isError && (
                <p data-testid="material-search-error" className="text-amber-300 text-xs mt-1">
                  {apiErrorMessage(search.error, 'MaterialDB search failed')}
                </p>
              )}
              {search.data && search.data.length === 0 && <p className="text-slate-500 text-xs mt-1">No material matches</p>}
              <div className="mt-1 max-h-48 overflow-y-auto">
                {search.data?.map((m) => (
                  <button key={m.id} type="button" data-testid={`material-hit-${m.id}`} disabled={save.isPending}
                    onClick={() => save.mutate({ source: 'materialdb', materialdb_id: m.id })}
                    className="block w-full text-left px-2 py-1 rounded text-sm text-slate-100 hover:bg-slate-700">
                    {m.label}
                    <span className="text-slate-500 text-xs"> {[m.manufacturer, m.family].filter(Boolean).join(', ')}</span>
                  </button>
                ))}
              </div>
            </div>
          ) : (
            <div className="flex gap-2">
              <input data-testid="material-new-input" autoFocus value={newText} maxLength={500}
                placeholder="e.g. PA6-GF15 acc. VW 50125"
                onChange={(e) => setNewText(e.target.value)}
                onKeyDown={(e) => { if (e.key === 'Enter' && newText.trim()) save.mutate({ source: 'new', new_text: newText.trim() }); }}
                className="flex-1 bg-slate-800 border border-slate-600 rounded px-2 py-1 text-sm text-slate-100 placeholder-slate-500" />
              <button type="button" data-testid="material-new-save" disabled={!newText.trim() || save.isPending}
                onClick={() => save.mutate({ source: 'new', new_text: newText.trim() })}
                className="text-sm px-2 py-1 rounded bg-blue-600 hover:bg-blue-500 disabled:bg-slate-600 text-white">Save</button>
            </div>
          )}
          <div className="flex justify-between">
            {material.material_source ? (
              <button type="button" data-testid="material-clear" disabled={save.isPending} onClick={() => save.mutate({ source: null })}
                className="text-xs text-red-300 hover:text-red-200">Remove material</button>
            ) : <span />}
            <button type="button" onClick={() => setMode('view')} className="text-xs px-2 py-1 rounded bg-slate-700 hover:bg-slate-600 text-slate-100">Cancel</button>
          </div>
        </div>
      )}
    </div>
  );
}
