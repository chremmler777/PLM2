import { useState } from 'react';
import client from '../../api/client';
import { revisionLabel } from './RevisionBadge';

export interface PackageRow {
  filename: string; part_id: number | null; part_number: string | null; customer_part_number: string | null;
  customer_index: string | null; current_revision: string | null; current_index: string | null;
  action: 'new_major' | 'unchanged' | 'unmatched' | 'error'; suggested_name: string | null; major: number | null; error: string | null;
}

interface Props {
  open: boolean; assemblyId: number;
  projectParts: { id: number; part_number: string; name: string }[];
  officialOnly?: boolean; onClose(): void;
  onDone(result: { created: unknown[]; kept: unknown[]; skipped: string[] }): void;
}

const ACTIONS: PackageRow['action'][] = ['new_major', 'unchanged', 'unmatched'];

export default function CustomerPackageDialog({ open, assemblyId, projectParts, officialOnly, onClose, onDone }: Props) {
  const [statement, setStatement] = useState<'review' | 'official'>(officialOnly ? 'official' : 'review');
  const [receivedAt, setReceivedAt] = useState(() => new Date().toISOString().slice(0, 10));
  const [packageIndex, setPackageIndex] = useState('');
  const [files, setFiles] = useState<File[]>([]);
  const [rows, setRows] = useState<PackageRow[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  if (!open) return null;
  const effective = officialOnly ? 'official' : statement;

  const base = () => {
    const fd = new FormData();
    fd.append('statement', effective);
    fd.append('received_at', receivedAt);
    files.forEach((f) => fd.append('files', f, f.name));
    return fd;
  };

  const preview = async () => {
    setBusy(true); setError(null);
    try {
      const fd = base();
      if (packageIndex.trim()) fd.append('package_index', packageIndex.trim());
      const res = await client.post(`/v1/parts/${assemblyId}/revisions/customer-package/preview`, fd, { headers: { 'Content-Type': 'multipart/form-data' } });
      setRows(res.data.rows);
    } catch (e) {
      setError((e as { response?: { data?: { detail?: string } } })?.response?.data?.detail || 'Preview failed');
    } finally { setBusy(false); }
  };

  const confirm = async () => {
    // Never drop a row on the way out: the backend's all-or-nothing rule only
    // covers the rows it is given, so an errored row has to keep the package
    // from being stored instead of quietly staying behind.
    if (!rows || rows.some((r) => r.action === 'error')) return;
    setBusy(true); setError(null);
    try {
      const fd = base();
      fd.append('rows', JSON.stringify(rows.map((r) => ({
        filename: r.filename, part_id: r.part_id, customer_index: r.customer_index, action: r.action, major: r.major }))));
      const res = await client.post(`/v1/parts/${assemblyId}/revisions/customer-package`, fd, { headers: { 'Content-Type': 'multipart/form-data' } });
      onDone(res.data);
    } catch (e) {
      const err = e as { response?: { status?: number; data?: { detail?: string; rows?: PackageRow[] } } };
      if (err.response?.status === 409 && err.response.data?.rows) setRows(err.response.data.rows);
      setError(err.response?.data?.detail || 'Storing failed');
    } finally { setBusy(false); }
  };

  /**
   * Any edit repairs the row: the message goes, and an errored row becomes a new major again.
   * The repair happens here, after the edit is merged, so no caller can re-assert 'error'.
   */
  const patch = (filename: string, p: Partial<PackageRow>) =>
    setRows((rs) => rs ? rs.map((r) => {
      if (r.filename !== filename) return r;
      const merged = { ...r, ...p, error: p.error ?? null };
      if (merged.action === 'error') merged.action = 'new_major';
      return merged;
    }) : rs);

  // A delivery where nothing changed is still a delivery: storing it writes
  // the "kept" changelog lines. What blocks storing is an errored row, or a
  // new major with no part to put it on.
  const canStore = !!rows
    && !rows.some((r) => r.action === 'error')
    && rows.some((r) => r.part_id != null && (r.action === 'new_major' || r.action === 'unchanged'))
    && !rows.some((r) => r.action === 'new_major' && r.part_id == null);

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
      <div className="bg-slate-800 rounded-lg shadow-lg max-w-4xl w-full mx-4 p-6 space-y-4 max-h-[90vh] overflow-auto">
        <h3 className="text-lg font-bold text-slate-100">Customer package received</h3>
        <input data-testid="package-files" type="file" multiple onChange={(e) => setFiles(Array.from(e.target.files ?? []))}
          className="block text-sm text-slate-300" />
        <fieldset className="space-y-2">
          <legend className="text-sm text-slate-400">What did the customer state?</legend>
          {(['review', 'official'] as const).map((s) => (
            <label key={s} className={`flex items-center gap-2 text-slate-100 ${officialOnly && s === 'review' ? 'opacity-40' : ''}`}>
              <input type="radio" name="package-statement" value={s} checked={effective === s}
                disabled={officialOnly && s === 'review'} onChange={() => setStatement(s)} />
              <span className="capitalize">{s}</span>
              <span className="text-xs text-slate-400">{s === 'review' ? '→ E-index, nothing binding' : '→ numeric index, released'}</span>
            </label>
          ))}
        </fieldset>
        <label className="block text-sm text-slate-400">Received on
          <input type="date" value={receivedAt} onChange={(e) => setReceivedAt(e.target.value)}
            className="mt-1 w-full p-2 rounded bg-slate-900 border border-slate-700 text-slate-100" />
        </label>
        <label className="block text-sm text-slate-400">Customer index (optional)
          <input value={packageIndex} onChange={(e) => setPackageIndex(e.target.value)} placeholder="package index, e.g. B"
            className="mt-1 w-full p-2 rounded bg-slate-900 border border-slate-700 text-slate-100" />
        </label>
        {!rows && (
          <div className="flex justify-end gap-2">
            <button onClick={onClose} className="px-4 py-2 rounded bg-slate-700 text-slate-100">Cancel</button>
            <button disabled={busy || files.length === 0 || !receivedAt} onClick={preview}
              className="px-4 py-2 rounded bg-blue-600 text-white disabled:bg-slate-600">{busy ? 'Checking…' : 'Check package'}</button>
          </div>
        )}
        {rows && (
          <table className="w-full text-sm">
            <thead className="text-slate-400 text-left"><tr>
              <th>File</th><th>Part</th><th>Current</th><th>Index</th><th>Action</th><th>Rev. no.</th><th>Result</th>
            </tr></thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.filename} data-testid={`row-${r.filename}`} className={r.action === 'error' ? 'bg-red-900/20' : ''}>
                  <td className="font-mono text-slate-100 truncate max-w-[16rem]" title={r.filename}>{r.filename}</td>
                  <td>
                    <select data-testid={`part-${r.filename}`} value={r.part_id ?? ''} className="bg-slate-900 border border-slate-700 rounded px-1 text-slate-100"
                      onChange={(e) => { const id = e.target.value ? parseInt(e.target.value, 10) : null;
                        const p = projectParts.find((x) => x.id === id);
                        patch(r.filename, { part_id: id, part_number: p?.part_number ?? null, action: id == null ? 'unmatched' : ((r.action === 'unmatched' || r.action === 'error') ? 'new_major' : r.action) }); }}>
                      <option value="">— not in project —</option>
                      {(r.part_id != null && !projectParts.some((p) => p.id === r.part_id)) && <option value={r.part_id}>{r.part_number}</option>}
                      {projectParts.map((p) => <option key={p.id} value={p.id}>{p.part_number} {p.name}</option>)}
                    </select>
                  </td>
                  <td className="font-mono text-slate-300">{revisionLabel(r.current_revision, r.current_index) || '—'}</td>
                  <td><input data-testid={`index-${r.filename}`} value={r.customer_index ?? ''} onChange={(e) => patch(r.filename, { customer_index: e.target.value || null })}
                    className="w-16 bg-slate-900 border border-slate-700 rounded px-1 text-slate-100" /></td>
                  <td>
                    <select data-testid={`action-${r.filename}`} value={r.action === 'error' ? 'new_major' : r.action}
                      onChange={(e) => patch(r.filename, { action: e.target.value as PackageRow['action'] })}
                      className="bg-slate-900 border border-slate-700 rounded px-1 text-slate-100">
                      {ACTIONS.map((a) => <option key={a} value={a}>{a === 'new_major' ? 'new major' : a}</option>)}
                    </select>
                  </td>
                  <td><input data-testid={`major-${r.filename}`} type="number" min={1} value={r.major ?? ''} placeholder={r.suggested_name?.replace(/^E/, '') ?? ''}
                    disabled={r.action !== 'new_major' && r.action !== 'error'} onChange={(e) => patch(r.filename, { major: e.target.value ? parseInt(e.target.value, 10) : null })}
                    className="w-16 bg-slate-900 border border-slate-700 rounded px-1 text-slate-100 disabled:opacity-40" /></td>
                  <td className="text-xs">
                    {r.action === 'error' && <span className="text-red-300">{r.error}</span>}
                    {r.action === 'new_major' && <span className="text-blue-300">→ {r.major ? `${effective === 'review' ? 'E' : ''}${r.major}` : (r.suggested_name ?? '?')}</span>}
                    {r.action === 'unchanged' && <span className="text-slate-400">kept {r.current_revision ?? '—'}</span>}
                    {r.action === 'unmatched' && <span className="text-slate-500">skipped</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {error && <p className="text-sm text-red-300">{error}</p>}
        {rows && (
          <div className="flex justify-between gap-2">
            <button onClick={() => setRows(null)} className="px-4 py-2 rounded bg-slate-700 text-slate-100">Back</button>
            <div className="flex gap-2">
              <button onClick={onClose} className="px-4 py-2 rounded bg-slate-700 text-slate-100">Cancel</button>
              <button disabled={busy || !canStore} onClick={confirm}
                className="px-4 py-2 rounded bg-blue-600 text-white disabled:bg-slate-600">{busy ? 'Storing…' : 'Store package'}</button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
