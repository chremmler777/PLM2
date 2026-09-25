/**
 * After "Timing validated" every date move is a deviation with a reason.
 * PM/Sales either lock it (accepted internally) or escalate it to the
 * customer, which opens a customer escalation.
 */
import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { planApi } from '../../../api/changePlan'
import type { DeviationStatus, PlanDeviation } from '../../../types/changePlan'
import ReasonDialog from '../ReasonDialog'
import { toDay } from '../plan/ganttMath'
import { formatDate } from '../../../lib/format'

/** dd.mm.yyyy from a day number (days since 1970-01-01, UTC). */
const fmtDay = (day: number) => formatDate(new Date(day * 86_400_000).toISOString().slice(0, 10))

const errDetail = (e: unknown): string | undefined =>
  (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail

interface Props {
  changeId: number
  deviations: PlanDeviation[]
  canDecide: boolean
  /** The change status: deviations are decided only while the work runs. */
  status?: string
}

/** Lock / escalate exist while the plan is live: approved to validation. */
const DECIDING: string[] = ['approved', 'in_implementation', 'in_validation']

/** Inclusive last day of an exclusive [start, end) span; a milestone sits on its start. */
const lastDay = (start: number, end: number) => (end > start ? end - 1 : end)

const STATUS: Record<DeviationStatus, { label: string; cls: string }> = {
  open: { label: 'Open', cls: 'border-amber-700 bg-amber-950/40 text-amber-200' },
  locked: { label: 'Locked', cls: 'border-slate-600 bg-slate-800 text-slate-300' },
  escalated: { label: 'Escalated', cls: 'border-rose-700 bg-rose-950/50 text-rose-200' },
}

const signed = (n: number) => (n > 0 ? `+${n}` : String(n))

export default function DeviationsPanel({ changeId, deviations, canDecide: mayDecide, status }: Props) {
  const canDecide = mayDecide && (status == null || DECIDING.includes(status))
  const qc = useQueryClient()
  const [lockFor, setLockFor] = useState<number | null>(null)
  const [lockNote, setLockNote] = useState('')
  const [escalateFor, setEscalateFor] = useState<number | null>(null)

  const done = () => {
    qc.invalidateQueries({ queryKey: ['change', changeId, 'plan-deviations'] })
    qc.invalidateQueries({ queryKey: ['change', changeId, 'impl-escalations'] })
    qc.invalidateQueries({ queryKey: ['change-my-actions', changeId] })
    qc.invalidateQueries({ queryKey: ['change', changeId] })
  }
  const lock = useMutation({
    mutationFn: (v: { id: number; note?: string }) => planApi.lockDeviation(changeId, v.id, v.note),
    onSuccess: () => { setLockFor(null); setLockNote(''); done() },
    onError: (e: unknown) => toast.error(errDetail(e) ?? 'Could not lock the deviation'),
  })
  const escalate = useMutation({
    mutationFn: (v: { id: number; note: string }) => planApi.escalateDeviation(changeId, v.id, v.note),
    onSuccess: () => { setEscalateFor(null); done() },
    onError: (e: unknown) => toast.error(errDetail(e) ?? 'Could not escalate the deviation'),
  })

  const open = deviations.filter((d) => d.status === 'open').length

  return (
    <section className="rounded-lg border border-slate-700 bg-slate-800 p-4 space-y-3" data-testid="deviations-panel">
      <div className="flex items-baseline justify-between gap-2">
        <h3 className="text-xs uppercase tracking-wide text-slate-500">Deviations from the baseline</h3>
        {open > 0 && <span className="text-xs text-amber-300">{open} open</span>}
      </div>
      {deviations.length === 0 ? (
        <p className="text-sm text-slate-400">
          No deviations. Every date change after the timing was validated shows up here with its reason.
        </p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="text-left text-[10px] uppercase tracking-wide text-slate-500">
                <th className="py-1 pr-2 font-medium">Task</th>
                <th className="py-1 pr-2 font-medium">Baseline end to new end</th>
                <th className="py-1 pr-2 font-medium text-right">Slip</th>
                <th className="py-1 pr-2 font-medium text-right">Finish</th>
                <th className="py-1 pr-2 font-medium">Reason</th>
                <th className="py-1 pr-2 font-medium">Status</th>
                {canDecide && <th className="py-1 font-medium" />}
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-700/70">
              {deviations.map((d) => {
                const ns = toDay(d.new_start)
                const ne = toDay(d.new_end)
                const baseEnd = ne - d.slip_days
                const span = ne - ns
                return (
                  <tr key={d.id} className="align-top" data-testid={`deviation-${d.id}`}>
                    <td className="py-2 pr-2 text-slate-200">{d.task_name}</td>
                    <td className="py-2 pr-2 whitespace-nowrap text-slate-300 tabular-nums">
                      {fmtDay(span > 0 ? baseEnd - 1 : baseEnd)} <span className="text-slate-500">to</span> {fmtDay(lastDay(ns, ne))}
                    </td>
                    <td className={`py-2 pr-2 text-right tabular-nums ${d.slip_days > 0 ? 'text-red-300 font-semibold' : 'text-slate-300'}`}
                      data-testid={`deviation-slip-${d.id}`}>
                      {signed(d.slip_days)} d
                    </td>
                    <td className={`py-2 pr-2 text-right tabular-nums ${d.finish_impact_days > 0 ? 'text-red-300' : 'text-slate-400'}`}>
                      {d.finish_impact_days === 0 ? 'none' : `${signed(d.finish_impact_days)} d`}
                    </td>
                    <td className="py-2 pr-2 text-slate-300 max-w-[260px]">
                      <p>{d.reason}</p>
                      {d.created_by_name && <p className="text-[11px] text-slate-500">{d.created_by_name}</p>}
                      {d.decision_note && (
                        <p className="mt-1 text-[11px] text-slate-400">
                          {d.decided_by_name ? `${d.decided_by_name}: ` : ''}{d.decision_note}
                        </p>
                      )}
                    </td>
                    <td className="py-2 pr-2">
                      <span className={`rounded-full border px-2 py-0.5 text-[11px] ${STATUS[d.status].cls}`}>
                        {STATUS[d.status].label}
                      </span>
                    </td>
                    {canDecide && (
                      <td className="py-2 whitespace-nowrap text-right">
                        {d.status === 'open' && lockFor !== d.id && (
                          <div className="flex justify-end gap-1.5">
                            <button type="button" data-testid={`deviation-lock-${d.id}`}
                              aria-label={`Lock deviation on ${d.task_name}`}
                              className="rounded-md border border-slate-600 px-2 py-1 text-xs text-slate-200 hover:bg-slate-700"
                              onClick={() => { setLockFor(d.id); setLockNote('') }}>Lock</button>
                            <button type="button" data-testid={`deviation-escalate-${d.id}`}
                              aria-label={`Escalate deviation on ${d.task_name} to the customer`}
                              className="rounded-md border border-rose-700 px-2 py-1 text-xs text-rose-200 hover:bg-rose-950/50"
                              onClick={() => setEscalateFor(d.id)}>Escalate to customer</button>
                          </div>
                        )}
                        {lockFor === d.id && (
                          <div className="flex items-center justify-end gap-1.5">
                            <input value={lockNote} onChange={(e) => setLockNote(e.target.value)} autoFocus
                              placeholder="Note (optional)" aria-label="Lock note"
                              className="w-40 rounded-md border border-slate-600 bg-slate-900 px-2 py-1 text-xs text-slate-100 placeholder-slate-500" />
                            <button type="button" className="text-xs text-slate-400 hover:text-slate-200"
                              onClick={() => setLockFor(null)}>Cancel</button>
                            <button type="button" disabled={lock.isPending} data-testid={`deviation-lock-confirm-${d.id}`}
                              className="rounded-md bg-sky-600 px-2 py-1 text-xs text-white hover:bg-sky-500 disabled:opacity-50"
                              onClick={() => lock.mutate({ id: d.id, note: lockNote.trim() || undefined })}>Lock</button>
                          </div>
                        )}
                      </td>
                    )}
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
      <ReasonDialog open={escalateFor != null} title="Escalate to the customer"
        label="What does Sales tell the customer?"
        warning="This opens a customer escalation for the implementation and marks the deviation escalated."
        submitLabel="Escalate" danger
        onSubmit={(note) => { if (escalateFor != null) escalate.mutate({ id: escalateFor, note }) }}
        onClose={() => setEscalateFor(null)} />
    </section>
  )
}
