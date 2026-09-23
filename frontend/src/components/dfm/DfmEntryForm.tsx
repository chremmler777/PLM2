/**
 * DfmEntryForm - one ledger entry in `party`'s column: who it is addressed
 * to (the other two parties), a note, the mail date, files. With
 * supersedesId it records an update of an earlier entry in the same column.
 */
import { useRef, useState, type DragEvent } from 'react';
import { useMutation } from '@tanstack/react-query';
import { toast } from 'sonner';
import { createEntry, PARTIES, PARTY_LABELS, type DfmParty } from '../../api/dfm';
import { apiErrorMessage } from '../../lib/apiError';

interface Props {
  partId: number;
  topicId: number;
  party: DfmParty;
  supersedesId?: number | null;
  onDone(): void;
  onCancel(): void;
}

export default function DfmEntryForm({ partId, topicId, party, supersedesId = null, onDone, onCancel }: Props) {
  const others = PARTIES.filter((p) => p !== party);
  const [addressed, setAddressed] = useState<DfmParty[]>([]);
  const [note, setNote] = useState('');
  const [sentAt, setSentAt] = useState('');
  const [files, setFiles] = useState<File[]>([]);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const save = useMutation({
    mutationFn: () => createEntry(partId, topicId, { party, addressed_to: addressed, note, sent_at: sentAt, supersedes_id: supersedesId, files }),
    onSuccess: () => { toast.success(supersedesId ? 'Entry updated' : 'Entry recorded'); onDone(); },
    onError: (e) => toast.error(apiErrorMessage(e, 'Could not record the entry')),
  });

  const toggle = (p: DfmParty) =>
    setAddressed((cur) => (cur.includes(p) ? cur.filter((x) => x !== p) : [...others.filter((o) => o === p || cur.includes(o))]));

  const addFiles = (list: FileList | File[] | null) => {
    if (!list) return;
    setFiles((cur) => [...cur, ...Array.from(list)]);
  };

  const onDrop = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    addFiles(e.dataTransfer?.files ?? null);
  };

  const submit = () => {
    if (addressed.length === 0) { setError('Address the entry to at least one party'); return; }
    setError(null);
    save.mutate();
  };

  return (
    <div data-testid="dfm-entry-form" className="mt-2 p-3 rounded-lg border border-slate-600 bg-slate-900 text-sm">
      <div className="font-medium text-slate-100 mb-2">
        {supersedesId ? 'Update this entry' : '+ entry'} <span className="text-slate-400">· {PARTY_LABELS[party]}</span>
      </div>
      <div className="flex items-center gap-4 mb-2">
        <span className="text-slate-400">To</span>
        {others.map((p) => (
          <label key={p} className="flex items-center gap-1 text-slate-200">
            <input data-testid={`addressed-${p}`} type="checkbox" checked={addressed.includes(p)} onChange={() => toggle(p)} />
            {PARTY_LABELS[p]}
          </label>
        ))}
      </div>
      <textarea data-testid="dfm-note" value={note} onChange={(e) => setNote(e.target.value)} rows={3} placeholder="Note"
        className="w-full p-2 border border-slate-700 rounded bg-slate-800 text-slate-100 mb-2" />
      <div className="flex items-center gap-2 mb-2">
        <span className="text-slate-400">Sent / received</span>
        <input data-testid="dfm-sent-at" type="date" value={sentAt} onChange={(e) => setSentAt(e.target.value)}
          className="bg-slate-800 border border-slate-700 rounded px-2 py-1 text-slate-100" />
      </div>
      <div data-testid="dfm-dropzone" onDragOver={(e) => e.preventDefault()} onDrop={onDrop}
        onClick={() => inputRef.current?.click()}
        className="border border-dashed border-slate-600 rounded p-3 text-slate-400 text-center cursor-pointer hover:border-slate-400 mb-2">
        Drop files here or click to choose
        <input ref={inputRef} data-testid="dfm-files-input" type="file" multiple className="hidden"
          onChange={(e) => { addFiles(e.target.files); e.target.value = ''; }} />
      </div>
      {files.length > 0 && (
        <ul className="mb-2 text-slate-200">
          {files.map((f, i) => (
            <li key={`${f.name}-${i}`} className="flex items-center gap-2">
              <span className="font-mono text-xs">{f.name}</span>
              <button onClick={() => setFiles((cur) => cur.filter((_, j) => j !== i))} className="text-slate-500 hover:text-red-300">remove</button>
            </li>
          ))}
        </ul>
      )}
      {error && <div className="text-red-300 mb-2">{error}</div>}
      <div className="flex gap-2">
        <button data-testid="dfm-submit" onClick={submit} disabled={save.isPending}
          className="px-3 py-1 rounded bg-blue-600 hover:bg-blue-500 disabled:bg-slate-600 text-white">
          {supersedesId ? 'Record update' : 'Record entry'}
        </button>
        <button onClick={onCancel} className="px-3 py-1 rounded bg-slate-700 hover:bg-slate-600 text-slate-100">Cancel</button>
      </div>
    </div>
  );
}
