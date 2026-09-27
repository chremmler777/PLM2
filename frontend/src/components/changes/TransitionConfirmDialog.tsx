import { useEffect, useId, useState, type ReactNode } from 'react'
import { AlertTriangle, Check, Hourglass, Info } from 'lucide-react'
import Dialog from '../common/Dialog'
import Button from '../common/Button'

/**
 * The last look before a step that cannot simply be undone: closing costing,
 * ending implementation, releasing, closing. States what is still open (so the
 * cost is read before it is paid) and what the step means, then asks.
 */
export interface TransitionConfirm {
  /** Target status. */
  to: string
  title: string
  /** What the step means, in plain words. */
  consequence: string
  /** What is still open right now; empty means nothing is. */
  open: string[]
  /** Shown when `open` is empty. */
  allClear?: string
  confirmLabel: string
  /** True when the step is final (release, close). */
  final?: boolean
  /** Still loading what is open. */
  loading?: boolean
  /** Worth a second look before the step, never holding it (shown in amber
      above the open list; e.g. a costing total of zero). */
  warning?: string
  /** Worth knowing before the step, never holding it (shown muted). */
  info?: string[]
  /** The step needs a reason on the record: a required memo box. */
  reason?: { label: string; placeholder?: string }
  /** The step is refused while anything is still open: the confirm button
      stays disabled until `open` is empty. */
  holdWhileOpen?: boolean
  /** The step cannot be taken right now for a reason stated here (e.g. its
      deviation is still waiting for the approver): shown, confirm disabled. */
  holdNote?: string
  /** Confirming asks for a deviation instead of taking the step (the page
      files it with the reason); the step itself follows once approved. */
  asksDeviation?: boolean
}

export default function TransitionConfirmDialog({
  confirm, busy, onConfirm, onClose, children,
}: {
  confirm: TransitionConfirm | null
  busy?: boolean
  /** Called with the memo when the step asks for one. */
  onConfirm: (reason?: string) => void
  onClose: () => void
  /** Fix-it-here controls under the open list (e.g. the missing description). */
  children?: ReactNode
}) {
  const reasonId = useId()
  const [reason, setReason] = useState('')
  const open = !!confirm
  useEffect(() => { if (open) setReason('') }, [open])
  if (!confirm) return null
  const held = (!!confirm.holdWhileOpen && (confirm.loading || confirm.open.length > 0)) || !!confirm.holdNote
  const needsReason = !!confirm.reason && !reason.trim()
  return (
    <Dialog open onClose={onClose} title={confirm.title} size="md" busy={busy} showClose={false}
      closeOnBackdrop={!confirm.reason} data-testid={`confirm-${confirm.to}`}
      footer={(
        <>
          <Button onClick={onClose} disabled={busy}>Not yet</Button>
          <Button variant="primary" data-testid="confirm-go" disabled={busy || held || needsReason}
            title={held ? confirm.holdNote ?? 'Complete what is still open first' : needsReason ? 'Give a reason first' : undefined}
            onClick={() => onConfirm(confirm.reason ? reason.trim() : undefined)}>
            {confirm.confirmLabel}
          </Button>
        </>
      )}>
      <p role="alert" data-testid="confirm-consequence"
        className={`mb-3 rounded-lg border px-3 py-2 text-sm ${confirm.final
          ? 'border-red-800/70 bg-red-950/40 text-red-100'
          : 'border-amber-700/60 bg-amber-950/40 text-amber-200'}`}>
        {confirm.consequence}
      </p>
      {!confirm.loading && confirm.warning && (
        <p data-testid="confirm-warning" className="mb-3 flex items-start gap-1.5 text-sm text-amber-200">
          <AlertTriangle aria-hidden="true" size={16} className="mt-0.5 shrink-0" /><span>{confirm.warning}</span>
        </p>
      )}
      {confirm.loading ? (
        <p className="text-xs text-slate-400">Checking what is still open…</p>
      ) : confirm.open.length > 0 ? (
        <div>
          <p className="mb-1 text-xs font-medium text-slate-400">Still open</p>
          <ul data-testid="confirm-open" className="list-disc space-y-1 pl-5 text-sm text-amber-200 marker:text-amber-400">
            {confirm.open.map((o) => <li key={o}>{o}</li>)}
          </ul>
        </div>
      ) : confirm.allClear ? (
        <p data-testid="confirm-clear" className="flex items-start gap-1.5 text-sm text-emerald-300">
          <Check aria-hidden="true" size={16} className="mt-0.5 shrink-0" /><span>{confirm.allClear}</span>
        </p>
      ) : null}
      {!confirm.loading && (confirm.info?.length ?? 0) > 0 && (
        <ul data-testid="confirm-info" className="mt-2 space-y-1 text-xs text-slate-400">
          {confirm.info!.map((o) => (
            <li key={o} className="flex items-start gap-1.5">
              <Info aria-hidden="true" size={12} className="mt-0.5 shrink-0" /><span>{o}</span>
            </li>
          ))}
        </ul>
      )}
      {children}
      {confirm.holdNote && (
        <p data-testid="confirm-hold" className="mt-3 flex items-start gap-1.5 text-sm text-amber-200">
          <Hourglass aria-hidden="true" size={14} className="mt-0.5 shrink-0" /><span>{confirm.holdNote}</span>
        </p>
      )}
      {confirm.reason && (
        <div className="mt-3">
          <label htmlFor={reasonId} className="mb-1 block text-sm text-slate-300">{confirm.reason.label}</label>
          <textarea id={reasonId} data-testid="confirm-reason" data-autofocus rows={3} required
            aria-required="true" value={reason} placeholder={confirm.reason.placeholder}
            onChange={(e) => setReason(e.target.value)}
            className="w-full rounded-lg border border-slate-600 bg-slate-900 p-2 text-sm text-slate-100 placeholder-slate-500 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400" />
        </div>
      )}
    </Dialog>
  )
}
