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
}

export default function TransitionConfirmDialog({
  confirm, busy, onConfirm, onClose,
}: {
  confirm: TransitionConfirm | null
  busy?: boolean
  onConfirm: () => void
  onClose: () => void
}) {
  if (!confirm) return null
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4" role="dialog"
      aria-label={confirm.title} data-testid={`confirm-${confirm.to}`}>
      <div className="w-full max-w-md rounded-xl bg-slate-800 p-5 shadow-xl">
        <h3 className="mb-2 text-base font-semibold text-slate-100">{confirm.title}</h3>
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
        <div className="mt-4 flex justify-end gap-2">
          <button type="button" onClick={onClose}
            className="rounded-lg border border-slate-600 px-3 py-1.5 text-sm text-slate-300 hover:bg-slate-700">
            Not yet
          </button>
          <button type="button" data-testid="confirm-go" disabled={busy}
            onClick={onConfirm}
            className="rounded-lg bg-sky-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-sky-500 disabled:opacity-50">
            {confirm.confirmLabel}
          </button>
        </div>
      </div>
    </div>
  )
}
