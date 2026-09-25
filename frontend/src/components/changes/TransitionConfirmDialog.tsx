import { useEffect, useId, useRef, useState, type ReactNode } from 'react'
import { useDialogFocus } from '../../hooks/useDialogFocus'

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
  /** Worth knowing before the step, never holding it (shown muted). */
  info?: string[]
  /** The step needs a reason on the record: a required memo box. */
  reason?: { label: string; placeholder?: string }
  /** The step is refused while anything is still open: the confirm button
      stays disabled until `open` is empty. */
  holdWhileOpen?: boolean
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
  const panelRef = useRef<HTMLDivElement>(null)
  const titleId = useId()
  const reasonId = useId()
  const [reason, setReason] = useState('')
  const open = !!confirm
  useEffect(() => { if (open) setReason('') }, [open])
  useDialogFocus(panelRef, open, onClose)
  if (!confirm) return null
  const held = !!confirm.holdWhileOpen && (confirm.loading || confirm.open.length > 0)
  const needsReason = !!confirm.reason && !reason.trim()
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4" role="dialog"
      aria-modal="true" aria-labelledby={titleId} data-testid={`confirm-${confirm.to}`}>
      <div ref={panelRef} className="w-full max-w-md rounded-xl bg-slate-800 p-5 shadow-xl">
        <h3 id={titleId} className="mb-2 text-base font-semibold text-slate-100">{confirm.title}</h3>
        <p role="alert" data-testid="confirm-consequence"
          className={`mb-3 rounded-lg border px-3 py-2 text-sm ${confirm.final
            ? 'border-red-800/70 bg-red-950/40 text-red-100'
            : 'border-amber-700/60 bg-amber-950/40 text-amber-200'}`}>
          {confirm.consequence}
        </p>
        {confirm.loading ? (
          <p className="text-xs text-slate-500">Checking what is still open</p>
        ) : confirm.open.length > 0 ? (
          <div>
            <p className="mb-1 text-xs uppercase tracking-wide text-slate-500">Still open</p>
            <ul data-testid="confirm-open" className="space-y-1 text-sm text-amber-200">
              {confirm.open.map((o) => <li key={o}>• {o}</li>)}
            </ul>
          </div>
        ) : confirm.allClear ? (
          <p data-testid="confirm-clear" className="text-sm text-emerald-300">✓ {confirm.allClear}</p>
        ) : null}
        {!confirm.loading && (confirm.info?.length ?? 0) > 0 && (
          <ul data-testid="confirm-info" className="mt-2 space-y-1 text-xs text-slate-400">
            {confirm.info!.map((o) => <li key={o}>ℹ {o}</li>)}
          </ul>
        )}
        {children}
        {confirm.reason && (
          <div className="mt-3">
            <label htmlFor={reasonId} className="mb-1 block text-sm text-slate-300">{confirm.reason.label}</label>
            <textarea id={reasonId} data-testid="confirm-reason" data-autofocus rows={3} required
              aria-required="true" value={reason} placeholder={confirm.reason.placeholder}
              onChange={(e) => setReason(e.target.value)}
              className="w-full rounded-lg border border-slate-600 bg-slate-900 p-2 text-sm text-slate-100 placeholder-slate-500" />
          </div>
        )}
        <div className="mt-4 flex justify-end gap-2">
          <button type="button" onClick={onClose}
            className="rounded-lg border border-slate-600 px-3 py-1.5 text-sm text-slate-300 hover:bg-slate-700">
            Not yet
          </button>
          <button type="button" data-testid="confirm-go" disabled={busy || held || needsReason}
            title={held ? 'Complete what is still open first' : needsReason ? 'Give a reason first' : undefined}
            onClick={() => onConfirm(confirm.reason ? reason.trim() : undefined)}
            className="rounded-lg bg-sky-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-sky-500 disabled:opacity-50">
            {confirm.confirmLabel}
          </button>
        </div>
      </div>
    </div>
  )
}
