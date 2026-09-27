import { useState, useEffect, useId, useRef } from 'react';
import { TriangleAlert } from 'lucide-react';
import Dialog from '../common/Dialog';
import Button from '../common/Button';

interface Props {
  open: boolean;
  title: string;
  label: string;
  submitLabel?: string;
  /** Consequence of the action, shown above the memo box. Use for decisions
      that stop or restart the flow, so the cost is read before it is paid. */
  warning?: string;
  /** Styles the confirm button as destructive. */
  danger?: boolean;
  onSubmit: (reason: string) => void;
  onClose: () => void;
}

/**
 * Asks for the reason behind a decision, on the shared <Dialog>: Escape
 * cancels, focus starts in the memo box and stays inside, and it returns to
 * the button that opened it. A click outside does not close it, so a typed
 * reason is never lost to a stray click.
 */
export default function ReasonDialog({
  open, title, label, submitLabel = 'Submit', warning, danger, onSubmit, onClose,
}: Props) {
  const [reason, setReason] = useState('');
  const fieldId = useId();
  const memoRef = useRef<HTMLTextAreaElement>(null);
  useEffect(() => {
    if (open) setReason('');
  }, [open]);
  const ready = reason.trim().length > 0;
  const submit = () => {
    if (!ready) return;
    onSubmit(reason.trim());
    setReason('');
  };
  return (
    <Dialog open={open} onClose={onClose} title={title} closeOnBackdrop={false}
      initialFocus={memoRef as React.RefObject<HTMLElement>}
      footer={(
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button variant={danger ? 'danger' : 'primary'} disabled={!ready} onClick={submit}>
            {submitLabel}
          </Button>
        </>
      )}>
      {warning && (
        <p role="alert"
          className="mb-3 flex items-start gap-2 rounded-lg border border-amber-700/60 bg-amber-950/40 px-3 py-2 text-sm text-amber-200">
          <TriangleAlert aria-hidden="true" size={16} className="mt-0.5 shrink-0 text-amber-300" />
          <span>{warning}</span>
        </p>
      )}
      <label htmlFor={fieldId} className="mb-1 block text-sm text-slate-300">{label}</label>
      <textarea
        id={fieldId}
        ref={memoRef}
        className="min-h-[80px] w-full rounded-lg border border-slate-600 bg-slate-900 p-2 text-sm text-slate-100 placeholder-slate-500 focus:border-sky-500 focus:outline-none"
        value={reason}
        onChange={(e) => setReason(e.target.value)}
        onKeyDown={(e) => {
          // Ctrl/Cmd+Enter sends, the way a mail client does.
          if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); submit(); }
        }}
      />
    </Dialog>
  );
}
