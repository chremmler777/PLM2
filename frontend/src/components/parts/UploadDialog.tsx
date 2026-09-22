/**
 * UploadDialog - put customer files on a part. Reads the customer index and
 * data kind from the filenames (per naming convention) to prefill; the user
 * picks the level: attach to the current revision, next customer major, or
 * next proposal. E-numbers are our filing order, the customer index is
 * informational and optional.
 */
import { useEffect, useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { toast } from 'sonner';
import client from '../../api/client';
import {
  defaultLevel, detectedIndex, inferFileType, nextMajorName, nextProposalName,
  type ParsedRow, type UploadLevel,
} from '../../lib/uploadLevel';

export interface UploadDialogProps {
  open: boolean;
  partId: number;
  currentRevision: { id: number; revision_name: string; customer_index?: string | null; phase: 'review' | 'official' };
  revisionNames: string[];
  officialOnly: boolean;
  projectNaming: 'vw' | 'scout' | null;
  initialFiles: File[];
  onClose(): void;
  onDone(targetRevisionId: number): void;
}

type FileType = 'cad' | 'drawing' | 'picture' | 'document';
interface Row { file: File; fileType: FileType }

const TYPE_OPTIONS: FileType[] = ['cad', 'drawing', 'picture', 'document'];
const ACCEPT = '.step,.stp,.iges,.igs,.stl,.jt,.catpart,.catproduct,.pdf,.dxf,.dwg,.png,.jpg,.jpeg,.gif,.webp,.docx,.xlsx,.pptx,.txt,.md,.csv';
const MAX_BYTES = 100 * 1024 * 1024;

const inputCls = 'mt-1 w-full p-2 rounded bg-slate-900 border border-slate-700 text-slate-100 text-sm';

export default function UploadDialog(props: UploadDialogProps) {
  const { open, partId, currentRevision, revisionNames, officialOnly, projectNaming, initialFiles, onClose, onDone } = props;
  const [rows, setRows] = useState<Row[]>(() => initialFiles.map((file) => ({ file, fileType: inferFileType(file.name) })));
  const [convention, setConvention] = useState<'vw' | 'scout' | 'none'>(projectNaming ?? 'none');
  const [level, setLevel] = useState<UploadLevel | null>(null); // null until the first parse decides the default
  const [statement, setStatement] = useState<'review' | 'official'>(officialOnly ? 'official' : 'review');
  const [receivedAt, setReceivedAt] = useState('');
  const [index, setIndex] = useState('');
  const [summary, setSummary] = useState('');
  const [progress, setProgress] = useState<{ done: number; total: number; error?: string } | null>(null);

  const names = rows.map((r) => r.file.name);
  const parse = useQuery({
    queryKey: ['parse-filenames', partId, convention, names],
    queryFn: async () => {
      const res = await client.get(`/v1/parts/${partId}/files/parse`, { params: { filenames: names, convention } });
      return res.data as { convention: string | null; conventions: Record<string, string>; rows: ParsedRow[] };
    },
    enabled: open && names.length > 0,
  });
  const parsedByName = useMemo(() => {
    const m = new Map<string, ParsedRow>();
    parse.data?.rows.forEach((r) => m.set(r.filename, r));
    return m;
  }, [parse.data]);
  const detected = useMemo(() => detectedIndex(parse.data?.rows ?? []), [parse.data]);
  const firstDate = parse.data?.rows.find((r) => r.dated)?.dated ?? null;

  // Prefill once per parse result: level, index, received date. The user's
  // later edits are not overwritten (level only set while null).
  useEffect(() => {
    if (!parse.data) return;
    setLevel((prev) => prev ?? defaultLevel(detected.index, currentRevision.customer_index));
    setIndex(detected.index ?? '');
    setReceivedAt(firstDate ?? new Date().toISOString().slice(0, 10));
  }, [parse.data, detected.index, firstDate, currentRevision.customer_index]);

  if (!open) return null;

  const effectiveStatement = officialOnly ? 'official' : statement;
  const majorName = nextMajorName(revisionNames, effectiveStatement);
  const proposalName = nextProposalName(revisionNames, currentRevision.revision_name);
  const currentLabel = currentRevision.customer_index
    ? `${currentRevision.revision_name} · ${currentRevision.customer_index}` : currentRevision.revision_name;

  const addFiles = (list: FileList | null) => {
    if (!list) return;
    const next: Row[] = [];
    Array.from(list).forEach((file) => {
      if (file.size > MAX_BYTES) { toast.error(`${file.name}: over 100MB`); return; }
      if (rows.some((r) => r.file.name === file.name)) return;
      next.push({ file, fileType: inferFileType(file.name) });
    });
    if (next.length) { setRows((r) => [...r, ...next]); setLevel(null); }
  };

  const submit = async () => {
    if (rows.length === 0 || !level) return;
    setProgress({ done: 0, total: rows.length });
    let targetId = currentRevision.id;
    try {
      if (level === 'major') {
        const res = await client.post(`/v1/parts/${partId}/revisions/customer-data`, {
          statement: effectiveStatement, received_at: receivedAt,
          customer_index: index.trim() || undefined, summary: summary.trim() || undefined,
        });
        targetId = res.data.id;
      } else if (level === 'proposal') {
        const res = await client.post(`/v1/parts/${partId}/revisions/proposals`, {
          parent_revision_id: currentRevision.id, summary: summary.trim() || undefined,
        });
        targetId = res.data.id;
      }
    } catch (error: unknown) {
      const msg = (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail || 'Could not create the revision';
      setProgress({ done: 0, total: rows.length, error: msg });
      return;
    }
    let done = 0;
    for (const row of rows) {
      const parsed = parsedByName.get(row.file.name);
      const fd = new FormData();
      fd.append('file', row.file);
      fd.append('file_type', row.fileType);
      if (parsed?.kind) fd.append('kind', parsed.kind);
      if (parsed?.kind_label) fd.append('note', parsed.kind_label);
      try {
        await client.post(`/v1/parts/${partId}/revisions/${targetId}/files`, fd, { headers: { 'Content-Type': 'multipart/form-data' } });
        done += 1;
        setProgress({ done, total: rows.length });
      } catch (error: unknown) {
        const msg = (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail || `Upload of ${row.file.name} failed`;
        setProgress({ done, total: rows.length, error: `${row.file.name}: ${msg}` });
        return;
      }
    }
    toast.success(`${done} file${done === 1 ? '' : 's'} uploaded`);
    onDone(targetId);
  };

  const busy = progress !== null && !progress.error;

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
      <div className="bg-slate-800 rounded-lg shadow-lg max-w-2xl w-full mx-4 p-6 space-y-4 max-h-[90vh] overflow-y-auto">
        <h3 className="text-lg font-bold text-slate-100">Upload files to {currentLabel}</h3>

        {/* Files */}
        <div className="space-y-1">
          {rows.map((row) => {
            const p = parsedByName.get(row.file.name);
            return (
              <div key={row.file.name} className="flex items-center gap-2 p-2 rounded bg-slate-900 border border-slate-700 text-xs">
                <div className="flex-1 min-w-0">
                  <p className="font-mono text-slate-100 truncate">{row.file.name}</p>
                  <div className="flex items-center gap-2 mt-1 text-slate-400">
                    <span>{(row.file.size / 1024 / 1024).toFixed(2)} MB</span>
                    {p?.kind && <span title={p.kind_label ?? undefined} className="px-1.5 py-0.5 rounded bg-blue-900/50 text-blue-300">{p.kind}</span>}
                    {p?.customer_index && <span className="px-1.5 py-0.5 rounded bg-slate-700 text-slate-200">{p.customer_index}</span>}
                  </div>
                  {p?.kind_label && <p className="text-slate-500 mt-1 truncate">{p.kind_label}</p>}
                </div>
                <select aria-label="File type" value={row.fileType} disabled={busy}
                  onChange={(e) => setRows((rs) => rs.map((r) => r === row ? { ...r, fileType: e.target.value as FileType } : r))}
                  className="px-2 py-1 rounded bg-slate-800 border border-slate-600 text-slate-100">
                  {TYPE_OPTIONS.map((t) => <option key={t} value={t}>{t}</option>)}
                </select>
                <button aria-label="Remove file" disabled={busy} onClick={() => { setRows((rs) => rs.filter((r) => r !== row)); setLevel(null); }}
                  className="px-2 py-1 rounded bg-slate-700 hover:bg-red-700 text-slate-200">×</button>
              </div>
            );
          })}
          <label className="block text-xs text-slate-400 border border-dashed border-slate-600 rounded p-2 text-center cursor-pointer hover:border-slate-500">
            + Add more files
            <input type="file" multiple accept={ACCEPT} className="hidden" disabled={busy} onChange={(e) => addFiles(e.target.files)} />
          </label>
          {parse.isError && <p className="text-xs text-red-400">Could not read the filenames, you can still upload.</p>}
        </div>

        {/* Convention */}
        <label className="block text-sm text-slate-400">Naming convention
          <select aria-label="Naming convention" value={convention} disabled={busy}
            onChange={(e) => { setConvention(e.target.value as 'vw' | 'scout' | 'none'); setLevel(null); }} className={inputCls}>
            <option value="none">None</option>
            {Object.entries(parse.data?.conventions ?? { vw: 'VW group', scout: 'Scout' }).map(([k, label]) => (
              <option key={k} value={k}>{label}</option>
            ))}
          </select>
          <span className="text-xs text-slate-500">Used to read the customer index and data kind from the filenames.</span>
        </label>
        {detected.mixed && (
          <p className="text-xs text-amber-300">The files carry different customer indexes. Check them, or split the upload.</p>
        )}

        {/* Level */}
        <fieldset className="space-y-2">
          <legend className="text-sm text-slate-400">Where do these files go?</legend>
          <label className="flex items-center gap-2 text-slate-100 text-sm">
            <input type="radio" name="level" checked={level === 'attach'} disabled={busy} onChange={() => setLevel('attach')} />
            Attach to {currentLabel}
          </label>
          <label className="flex items-center gap-2 text-slate-100 text-sm">
            <input type="radio" name="level" checked={level === 'major'} disabled={busy} onChange={() => setLevel('major')} />
            Next customer data → {majorName}
            <span className="text-xs text-slate-400">customer sent a new data state</span>
          </label>
          {level === 'major' && (
            <div className="ml-6 space-y-2">
              <div className="flex gap-4 text-sm text-slate-100">
                {(['review', 'official'] as const).map((s) => (
                  <label key={s} className={`flex items-center gap-1 ${officialOnly && s === 'review' ? 'opacity-40' : ''}`}>
                    <input type="radio" name="statement" checked={effectiveStatement === s} disabled={busy || (officialOnly && s === 'review')} onChange={() => setStatement(s)} />
                    <span className="capitalize">{s}</span>
                  </label>
                ))}
              </div>
              <label className="block text-sm text-slate-400">Received on
                <input aria-label="Received on" type="date" value={receivedAt} disabled={busy} onChange={(e) => setReceivedAt(e.target.value)} className={inputCls} />
              </label>
              <label className="block text-sm text-slate-400">Customer index
                <input aria-label="Customer index" value={index} disabled={busy} onChange={(e) => setIndex(e.target.value)} placeholder="optional" className={inputCls} />
                <span className="text-xs text-slate-500">
                  current {currentRevision.customer_index || 'none'} · detected {detected.index || (detected.mixed ? 'mixed' : 'none')}
                </span>
              </label>
              <label className="block text-sm text-slate-400">Summary (optional)
                <textarea value={summary} rows={2} disabled={busy} onChange={(e) => setSummary(e.target.value)} className={inputCls} />
              </label>
            </div>
          )}
          <label className="flex items-center gap-2 text-slate-100 text-sm">
            <input type="radio" name="level" checked={level === 'proposal'} disabled={busy} onChange={() => setLevel('proposal')} />
            Next proposal → {proposalName}
            <span className="text-xs text-slate-400">our own iteration, feasibility</span>
          </label>
          {level === 'proposal' && (
            <label className="ml-6 block text-sm text-slate-400">Summary (optional)
              <textarea value={summary} rows={2} disabled={busy} onChange={(e) => setSummary(e.target.value)} className={inputCls} />
            </label>
          )}
        </fieldset>

        {progress && (
          <p className={`text-sm ${progress.error ? 'text-red-400' : 'text-slate-300'}`}>
            {progress.done} of {progress.total} uploaded{progress.error ? ` · ${progress.error}` : ''}
          </p>
        )}

        <div className="flex justify-end gap-2">
          <button onClick={onClose} disabled={busy} className="px-4 py-2 rounded bg-slate-700 text-slate-100 hover:bg-slate-600">
            {progress?.error ? 'Close' : 'Cancel'}
          </button>
          <button onClick={submit} disabled={busy || rows.length === 0 || !level || (level === 'major' && !receivedAt)}
            className="px-4 py-2 rounded bg-blue-600 text-white hover:bg-blue-700 disabled:bg-slate-600">
            {busy ? 'Uploading…' : 'Upload'}
          </button>
        </div>
      </div>
    </div>
  );
}
