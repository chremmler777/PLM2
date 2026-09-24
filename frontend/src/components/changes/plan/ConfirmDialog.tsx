import { useEffect, useRef } from 'react'

interface Props {
  open: boolean
  title: string
  body?: string
  confirmLabel?: string
  danger?: boolean
  onConfirm: () => void
  onClose: () => void
}

/** Small yes/no dialog in the app's dark style (no window.confirm). */
export default function ConfirmDialog({ open, title, body, confirmLabel = 'Confirm', danger, onConfirm, onClose }: Props) {
  const okRef = useRef<HTMLButtonElement>(null)
  useEffect(() => { if (open) okRef.current?.focus() }, [open])
  if (!open) return null
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50" role="dialog" aria-modal="true"
      aria-label={title}
      onKeyDown={(e) => { if (e.key === 'Escape') { e.stopPropagation(); onClose() } }}>
      <div className="w-full max-w-sm rounded-xl border border-slate-700 bg-slate-800 p-5 shadow-xl">
        <h3 className="text-sm font-semibold text-slate-100">{title}</h3>
        {body && <p className="mt-2 text-sm text-slate-400">{body}</p>}
        <div className="mt-4 flex justify-end gap-2">
          <button type="button" onClick={onClose}
            className="rounded-lg border border-slate-600 px-3 py-1.5 text-sm text-slate-300 hover:bg-slate-700">Cancel</button>
          <button ref={okRef} type="button" onClick={() => { onConfirm(); onClose() }}
            data-testid="confirm-ok"
            className={`rounded-lg px-3 py-1.5 text-sm text-white ${danger ? 'bg-red-700 hover:bg-red-600' : 'bg-sky-600 hover:bg-sky-500'}`}>
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  )
}
