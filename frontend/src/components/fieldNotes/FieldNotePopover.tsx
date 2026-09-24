/**
 * FieldNotePopover - the comment thread and flag of one field, opened from a
 * FieldNoteMarker. Comments are append only; the flag is open, confirmed,
 * rejected or cleared.
 */
import { useEffect, useRef, useState } from 'react';
import { useFieldNoteActions, useFieldNoteThread } from '../../hooks/queries/useFieldNotes';
import { useFieldAudit } from '../../hooks/queries/useWorksheet';
import { apiErrorMessage } from '../../lib/apiError';
import { auditActionText, auditValueChange, excerpt } from '../worksheet/worksheetAudit';
import { FLAG_BUTTON, FLAG_LABELS, FLAGS, MAX_COMMENT_LENGTH, localDate, localDateTime } from '../../lib/fieldNotes';

export interface FieldNotePopoverProps {
  partId: number;
  fieldKey: string;
  label: string;
  /** Set: a collapsible History lists the field's audit log entries. */
  projectId?: number | null;
  position: { top: number; left: number };
  onClose(): void;
}

export default function FieldNotePopover({ partId, fieldKey, label, projectId = null, position, onClose }: FieldNotePopoverProps) {
  const ref = useRef<HTMLDivElement>(null);
  const [draft, setDraft] = useState('');
  const { data: thread, isLoading } = useFieldNoteThread(partId, fieldKey, true);
  const { addComment, setFlag } = useFieldNoteActions(partId, fieldKey);
  const [showHistory, setShowHistory] = useState(false);
  const history = useFieldAudit(projectId, partId, fieldKey, showHistory);

  useEffect(() => {
    const onDown = (e: MouseEvent) => {
      const target = e.target as HTMLElement | null;
      if (ref.current?.contains(target)) return;
      if (target?.closest?.('[data-note-marker]')) return; // the marker toggles itself
      onClose();
    };
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    document.addEventListener('mousedown', onDown);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onDown);
      document.removeEventListener('keydown', onKey);
    };
  }, [onClose]);

  const submit = () => {
    const body = draft.trim();
    if (!body) return;
    addComment.mutate(body, { onSuccess: () => setDraft('') });
  };
  const current = thread?.flag_status ?? null;
  const comments = thread?.comments ?? [];

  return (
    <div
      ref={ref}
      role="dialog"
      aria-label={`Notes on ${label}`}
      data-testid={`note-popover-${fieldKey}`}
      style={{ top: position.top, left: position.left }}
      onClick={(e) => e.stopPropagation()}
      onContextMenu={(e) => e.stopPropagation()}
      className="fixed z-50 w-80 bg-slate-800 border border-slate-600 rounded-lg shadow-xl p-3 text-sm text-left font-normal normal-case"
    >
      <div className="flex items-center justify-between mb-2">
        <span className="font-semibold text-slate-100">{label}</span>
        <button type="button" aria-label="Close" onClick={onClose} className="text-slate-400 hover:text-slate-200 text-lg leading-none">×</button>
      </div>
      <div className="flex flex-wrap gap-1 mb-1">
        {FLAGS.map((f) => (
          <button
            key={f}
            type="button"
            data-testid={`flag-${f}`}
            aria-pressed={current === f}
            disabled={setFlag.isPending}
            onClick={() => setFlag.mutate(f)}
            className={`px-2 py-0.5 rounded text-xs border ${current === f ? FLAG_BUTTON[f] : 'border-slate-600 text-slate-300 hover:bg-slate-700'}`}
          >
            {FLAG_LABELS[f]}
          </button>
        ))}
        <button
          type="button"
          data-testid="flag-clear"
          disabled={!current || setFlag.isPending}
          onClick={() => setFlag.mutate(null)}
          className="px-2 py-0.5 rounded text-xs border border-slate-600 text-slate-400 hover:bg-slate-700 disabled:opacity-40"
        >
          Clear flag
        </button>
      </div>
      {current && thread?.flag_set_by_name && (
        <p className="text-[11px] text-slate-500 mb-2">
          {FLAG_LABELS[current]} by {thread.flag_set_by_name}{thread.flag_set_at ? `, ${localDate(thread.flag_set_at)}` : ''}
        </p>
      )}
      <div data-testid="note-comments" className="max-h-56 overflow-y-auto space-y-2 my-2">
        {isLoading ? (
          <p className="text-slate-500">Loading...</p>
        ) : comments.length === 0 ? (
          <p className="text-slate-500">No comments yet</p>
        ) : (
          comments.map((c) => (
            <div key={c.id} className="bg-slate-900/60 rounded px-2 py-1">
              <div className="text-[11px] text-slate-500">{c.author_name ?? 'Unknown'}, {localDateTime(c.created_at)}</div>
              <div className="text-slate-200 whitespace-pre-wrap break-words">{c.body}</div>
            </div>
          ))
        )}
      </div>
      {projectId ? (
        <div className="mb-2">
          <button type="button" data-testid="note-history-toggle" aria-expanded={showHistory} onClick={() => setShowHistory((v) => !v)}
            className="text-[11px] text-slate-400 hover:text-slate-200">
            {showHistory ? '▾' : '▸'} History
          </button>
          {showHistory && (
            <div data-testid="note-history" className="max-h-32 overflow-y-auto mt-1 space-y-1 text-[11px] whitespace-normal break-words">
              {history.isLoading ? (
                <p className="text-slate-500">Loading...</p>
              ) : history.isError ? (
                <p className="text-red-400">{apiErrorMessage(history.error, 'Could not load the history')}</p>
              ) : !history.data?.entries.length ? (
                <p className="text-slate-500">No history yet</p>
              ) : (
                history.data.entries.map((e) => (
                  <div key={e.id} className="text-slate-300">
                    <span className="text-slate-500">{e.at ? localDateTime(e.at) : ''} {e.actor?.name ?? 'Unknown'}: </span>
                    {auditActionText(e)}
                    {auditValueChange(e) && <span className="text-slate-400"> {auditValueChange(e)}</span>}
                    {e.action === 'field_comment_added' && e.new_value && <span className="text-slate-400"> {excerpt(e.new_value, 60)}</span>}
                  </div>
                ))
              )}
            </div>
          )}
        </div>
      ) : null}
      <textarea
        aria-label="New comment"
        data-testid="note-comment-input"
        value={draft}
        maxLength={MAX_COMMENT_LENGTH}
        rows={2}
        placeholder="Add a comment (Ctrl+Enter to add)"
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={(e) => { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) submit(); }}
        className="w-full bg-slate-900 border border-slate-600 rounded px-2 py-1 text-slate-100 placeholder-slate-500"
      />
      <div className="flex justify-end mt-1">
        <button
          type="button"
          data-testid="note-comment-add"
          disabled={!draft.trim() || addComment.isPending}
          onClick={submit}
          className="px-2 py-1 rounded bg-blue-600 hover:bg-blue-500 disabled:bg-slate-600 text-white text-xs"
        >
          Add comment
        </button>
      </div>
    </div>
  );
}
