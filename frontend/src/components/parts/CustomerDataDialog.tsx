import { useState } from 'react';

export interface CustomerDataInput {
  statement: 'review' | 'official';
  received_at: string;
  customer_index?: string;
  summary?: string;
  major?: number;
}

interface Props {
  open: boolean;
  title: string;
  onClose(): void;
  onSubmit(v: CustomerDataInput): void;
  pending?: boolean;
  /** Once a part has official data the customer cannot go back to review. */
  officialOnly?: boolean;
  nextMajor?: { review: number; official: number };
}

export default function CustomerDataDialog({ open, title, onClose, onSubmit, pending, officialOnly, nextMajor }: Props) {
  const [statement, setStatement] = useState<'review' | 'official'>(officialOnly ? 'official' : 'review');
  const [receivedAt, setReceivedAt] = useState(() => new Date().toISOString().slice(0, 10));
  const [index, setIndex] = useState('');
  const [summary, setSummary] = useState('');
  const [major, setMajor] = useState('');
  if (!open) return null;
  const effective = officialOnly ? 'official' : statement;
  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
      <div className="bg-slate-800 rounded-lg shadow-lg max-w-md w-full mx-4 p-6 space-y-4">
        <h3 className="text-lg font-bold text-slate-100">{title}</h3>
        <fieldset className="space-y-2">
          <legend className="text-sm text-slate-400">What did the customer state?</legend>
          {(['review', 'official'] as const).map((s) => (
            <label key={s} className={`flex items-center gap-2 text-slate-100 ${officialOnly && s === 'review' ? 'opacity-40' : ''}`}>
              <input type="radio" name="statement" value={s} checked={effective === s}
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
        <label className="block text-sm text-slate-400">Revision number (optional)
          <input data-testid="major-input" type="number" min={1} value={major} onChange={(e) => setMajor(e.target.value)}
            placeholder={nextMajor ? String(nextMajor[effective]) : ''}
            className="mt-1 w-full p-2 rounded bg-slate-900 border border-slate-700 text-slate-100" />
          <span className="text-xs text-slate-500">Leave empty for the next free number. Must be above every existing {effective === 'review' ? 'E' : 'official'} revision.</span>
        </label>
        <label className="block text-sm text-slate-400">Customer index (optional)
          <input value={index} onChange={(e) => setIndex(e.target.value)} placeholder="e.g. B"
            className="mt-1 w-full p-2 rounded bg-slate-900 border border-slate-700 text-slate-100" />
        </label>
        <label className="block text-sm text-slate-400">Summary (optional)
          <textarea value={summary} onChange={(e) => setSummary(e.target.value)} rows={2}
            className="mt-1 w-full p-2 rounded bg-slate-900 border border-slate-700 text-slate-100" />
        </label>
        <div className="flex justify-end gap-2">
          <button onClick={onClose} className="px-4 py-2 rounded bg-slate-700 text-slate-100 hover:bg-slate-600">Cancel</button>
          <button disabled={pending || !receivedAt}
            onClick={() => onSubmit({ statement: effective, received_at: receivedAt, customer_index: index.trim() || undefined, summary: summary.trim() || undefined, major: major.trim() ? parseInt(major, 10) : undefined })}
            className="px-4 py-2 rounded bg-blue-600 text-white hover:bg-blue-700 disabled:bg-slate-600">
            {pending ? 'Saving…' : 'Save'}
          </button>
        </div>
      </div>
    </div>
  );
}
