/**
 * Reason for a date change after "Timing validated". Shows what the change
 * does, including the successors it carries along, before it is recorded:
 * each row reads finish before to finish after (the last day worked), since a
 * task that grows keeps its start and only its finish moves.
 */
import { useRef, useState } from 'react'
import Dialog from '../../common/Dialog'
import Button from '../../common/Button'
import { fmtShort, toDay } from '../../gantt/engine/calendar'

export interface MovedTask {
  id: string | number
  name: string
  /** Start before and after (ISO). */
  from: string
  to: string
  /** Last day before and after (ISO); the start stands in when missing. */
  fromEnd?: string
  toEnd?: string
  /** Slip in plan units (working days in a working calendar). */
  days: number
}

interface Props {
  open: boolean
  changed: MovedTask[]
  moved: MovedTask[]
  onSubmit: (reason: string) => void
  onClose: () => void
}

const signed = (n: number) => `${n > 0 ? '+' : ''}${n} d`

function Rows({ list, testId, label }: { list: MovedTask[]; testId: string; label: string }) {
  return (
    <table className="w-full text-xs" data-testid={testId}>
      <caption className="sr-only">{label}</caption>
      <thead className="sr-only">
        <tr><th scope="col">Task</th><th scope="col">Finish before and after</th><th scope="col">Slip</th></tr>
      </thead>
      <tbody>
        {list.map((m) => (
          <tr key={String(m.id)}>
            <td className="max-w-0 truncate py-0.5 pr-2 text-slate-200" title={m.name}>{m.name}</td>
            <td className="whitespace-nowrap py-0.5 pr-2 tabular-nums text-slate-400">
              {fmtShort(toDay(m.fromEnd ?? m.from))} <span className="text-slate-400">to</span> {fmtShort(toDay(m.toEnd ?? m.to))}
            </td>
            <td className={`w-14 whitespace-nowrap py-0.5 text-right tabular-nums ${m.days > 0 ? 'text-red-300' : m.days < 0 ? 'text-emerald-300' : 'text-slate-400'}`}>
              {signed(m.days)}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

export default function DeviationDialog({ open, changed, moved, onSubmit, onClose }: Props) {
  const [reason, setReason] = useState('')
  const ref = useRef<HTMLTextAreaElement>(null)
  const count = changed.length + moved.length
  // Matches the deviations list: one group per task you moved, the tasks it pushed under it.
  const grouping = count <= 1 ? ''
    : changed.length > 1 ? ` on all ${count} tasks; each task you moved becomes its own group, with the tasks it pushed under it`
      : ` on all ${count} tasks, as one group: your move and the tasks it pushed`
  const submit = () => { if (reason.trim()) { const r = reason.trim(); setReason(''); onSubmit(r) } }
  const close = () => { setReason(''); onClose() }
  return (
    <Dialog open={open} onClose={close} title="Record a deviation" size="lg" initialFocus={ref}
      closeOnBackdrop={false}
      description={`Timing is validated, so the move is recorded with your reason${grouping}. PM or Sales then decide each group: lock it or escalate it to the customer.`}
      footer={(
        <>
          <Button onClick={close}>Cancel</Button>
          <Button variant="primary" disabled={!reason.trim()} onClick={submit}>Save move</Button>
        </>
      )}>
      <div className="space-y-3">
        {changed.length > 0 && (
          <div>
            <p className="mb-1 text-[11px] text-slate-400">Finish, before and after</p>
            <Rows list={changed} testId="deviation-changed" label="Moved tasks" />
          </div>
        )}
        {moved.length > 0 && (
          <div>
            <p className="mb-1 text-[11px] text-slate-400">Pushed along by their links</p>
            <div className="max-h-40 overflow-y-auto overscroll-contain">
              <Rows list={moved} testId="deviation-successors" label="Successors moved along" />
            </div>
          </div>
        )}
        <div>
          <label className="mb-1 block text-sm text-slate-300" htmlFor="deviation-reason">Why does this move?</label>
          <textarea id="deviation-reason" ref={ref} value={reason} onChange={(e) => setReason(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); submit() } }}
            className="min-h-[80px] w-full rounded-lg border border-slate-600 bg-slate-900 p-2 text-sm text-slate-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400" />
        </div>
      </div>
    </Dialog>
  )
}
