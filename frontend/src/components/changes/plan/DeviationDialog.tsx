/**
 * Reason for a date change after "Timing validated". Shows what the change
 * does, including the successors it carries along, before it is recorded.
 */
import { useEffect, useRef, useState } from 'react'
import { fmtShort, toDay } from '../../gantt/engine/calendar'

export interface MovedTask { id: string | number; name: string; from: string; to: string; days: number }

interface Props {
  open: boolean
  changed: MovedTask[]
  moved: MovedTask[]
  onSubmit: (reason: string) => void
  onClose: () => void
}

const signed = (n: number) => `${n > 0 ? '+' : ''}${n} d`

export default function DeviationDialog({ open, changed, moved, onSubmit, onClose }: Props) {
  const [reason, setReason] = useState('')
  const ref = useRef<HTMLTextAreaElement>(null)
  useEffect(() => { if (open) { setReason(''); setTimeout(() => ref.current?.focus(), 0) } }, [open])
  if (!open) return null
  const row = (m: MovedTask) => (
    <li key={String(m.id)} className="flex items-center gap-2">
      <span className="min-w-0 flex-1 truncate text-slate-200">{m.name}</span>
      <span className="tabular-nums text-slate-400">{fmtShort(toDay(m.from))} to {fmtShort(toDay(m.to))}</span>
      <span className={`w-12 text-right tabular-nums ${m.days > 0 ? 'text-red-300' : 'text-emerald-300'}`}>{signed(m.days)}</span>
    </li>
  )
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50" role="dialog" aria-modal="true"
      aria-label="Record a deviation" onKeyDown={(e) => { if (e.key === 'Escape') { e.stopPropagation(); onClose() } }}>
      <div className="w-full max-w-lg rounded-xl bg-slate-800 p-5 shadow-xl">
        <h3 className="mb-2 text-base font-semibold text-slate-100">Record a deviation</h3>
        <p role="alert" className="mb-3 rounded-lg border border-amber-700/60 bg-amber-950/40 px-3 py-2 text-sm text-amber-200">
          Timing is validated. This is recorded as a deviation per task and PM/Sales decide to lock or escalate it.
        </p>
        {changed.length > 0 && (
          <ul className="mb-2 space-y-1 text-xs" data-testid="deviation-changed">{changed.map(row)}</ul>
        )}
        {moved.length > 0 && (
          <div className="mb-3">
            <p className="mb-1 text-xs font-medium text-slate-300">Moves successors too:</p>
            <ul className="max-h-40 space-y-1 overflow-y-auto text-xs" data-testid="deviation-successors">{moved.map(row)}</ul>
          </div>
        )}
        <label className="mb-1 block text-sm text-slate-400" htmlFor="deviation-reason">Why does this move?</label>
        <textarea id="deviation-reason" ref={ref} value={reason} onChange={(e) => setReason(e.target.value)}
          className="min-h-[80px] w-full rounded-lg border border-slate-600 bg-slate-900 p-2 text-sm text-slate-100" />
        <div className="mt-4 flex justify-end gap-2">
          <button type="button" className="rounded-lg border border-slate-600 px-3 py-1.5 text-sm text-slate-300 hover:bg-slate-700" onClick={onClose}>Cancel</button>
          <button type="button" className="rounded-lg bg-sky-600 px-3 py-1.5 text-sm text-white hover:bg-sky-500 disabled:opacity-50"
            disabled={!reason.trim()} onClick={() => onSubmit(reason.trim())}>Save move</button>
        </div>
      </div>
    </div>
  )
}
