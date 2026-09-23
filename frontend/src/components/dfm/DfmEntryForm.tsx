/**
 * DfmEntryForm - the guided form for one step of the DFM flow. Opened from
 * "+ New DFM" (an original: pick from and to) or from a card action, which
 * prefills kind, sender, addressee and reply link. The step is stated in
 * words at the top. With step.supersedes it records an update.
 */
import { useRef, useState, type DragEvent } from 'react';
import { useMutation } from '@tanstack/react-query';
import { toast } from 'sonner';
import { createEntry, PARTIES, PARTY_LABELS, type DfmParty } from '../../api/dfm';
import { apiErrorMessage } from '../../lib/apiError';
import { KIND_STYLE, others, stepSentence, type DfmStep } from './dfmFlow';

interface Props {
  partId: number;
  topicId: number;
  step: DfmStep;
  onDone(): void;
  onCancel(): void;
}

export default function DfmEntryForm({ partId, topicId, step, onDone, onCancel }: Props) {
  const [from, setFrom] = useState<DfmParty>(step.from);
  const [addressed, setAddressed] = useState<DfmParty[]>(step.to);
  const [note, setNote] = useState('');
  const [sentAt, setSentAt] = useState('');
  const [files, setFiles] = useState<File[]>([]);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const allowed = step.allowedTo ?? others(from);
  const ordered = (ps: DfmParty[]) => PARTIES.filter((p) => ps.includes(p));

  const save = useMutation({
    mutationFn: () => createEntry(partId, topicId, {
      party: from, addressed_to: ordered(addressed), note, sent_at: sentAt, files,
      kind: step.kind, reply_to_id: step.replyTo?.id ?? null, supersedes_id: step.supersedes?.id ?? null,
    }),
    onSuccess: () => { toast.success(step.supersedes ? 'Update recorded' : 'Step recorded'); onDone(); },
    onError: (e) => toast.error(apiErrorMessage(e, 'Could not record the step')),
  });

  const pickFrom = (p: DfmParty) => {
    setFrom(p);
    setAddressed((cur) => cur.filter((x) => x !== p));
  };
  const toggle = (p: DfmParty) => {
    if (step.lockedTo.includes(p)) return;
    setAddressed((cur) => (cur.includes(p) ? cur.filter((x) => x !== p) : [...cur, p]));
  };

  const addFiles = (list: FileList | File[] | null) => {
    if (!list) return;
    setFiles((cur) => [...cur, ...Array.from(list)]);
  };
  const onDrop = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    addFiles(e.dataTransfer?.files ?? null);
  };

  const submit = () => {
    if (addressed.length === 0) { setError('Address the message to at least one party'); return; }
    setError(null);
    save.mutate();
  };

  return (
    <div data-testid="dfm-entry-form" data-kind={step.kind}
      className={`mt-2 p-3 rounded-lg border-2 bg-slate-900 text-sm ${KIND_STYLE[step.kind].line}`}>
      <div data-testid="dfm-step-sentence" className="font-medium text-slate-100 mb-3">
        {stepSentence(step, from, ordered(addressed))}
      </div>
      {step.fromEditable && (
        <div className="flex items-center gap-4 mb-2">
          <span className="text-slate-400 w-12">From</span>
          {PARTIES.map((p) => (
            <label key={p} className="flex items-center gap-1 text-slate-200">
              <input data-testid={`dfm-from-${p}`} type="radio" name="dfm-from" checked={from === p} onChange={() => pickFrom(p)} />
              {PARTY_LABELS[p]}
            </label>
          ))}
        </div>
      )}
      <div className="flex items-center gap-4 mb-2">
        <span className="text-slate-400 w-12">To</span>
        {allowed.map((p) => (
          <label key={p} className="flex items-center gap-1 text-slate-200">
            <input data-testid={`addressed-${p}`} type="checkbox" checked={addressed.includes(p)}
              disabled={step.lockedTo.includes(p)} onChange={() => toggle(p)} />
            {PARTY_LABELS[p]}
            {(step.kind === 'answer' || step.kind === 'question') && !step.lockedTo.includes(p) && <span className="text-slate-500">(copy)</span>}
          </label>
        ))}
      </div>
      <textarea data-testid="dfm-note" value={note} onChange={(e) => setNote(e.target.value)} rows={3} placeholder="Note, e.g. DFM rev 1 or what was answered"
        className="w-full p-2 border border-slate-700 rounded bg-slate-800 text-slate-100 mb-2" />
      <div className="flex items-center gap-2 mb-2">
        <span className="text-slate-400">Mail date</span>
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
          {step.supersedes ? 'Record update' : 'Record step'}
        </button>
        <button onClick={onCancel} className="px-3 py-1 rounded bg-slate-700 hover:bg-slate-600 text-slate-100">Cancel</button>
      </div>
    </div>
  );
}
