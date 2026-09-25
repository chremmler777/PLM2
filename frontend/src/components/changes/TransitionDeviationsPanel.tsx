import { useEffect, useRef, useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { changesApi } from '../../api/changes'
import { apiErrorMessage } from '../../lib/apiError'
import { formatDateTime } from '../../lib/format'
import { STATUS_LABELS } from '../../lib/changeStatus'
import type { ChangeStatus, TransitionDeviation } from '../../types/change'

/**
 * Pending transition deviations ("go on although a guard says no"), where the
 * approver decides them: the reason, who asked, and Approve / Reject with an
 * optional note. "Decide deviation #n" in Your actions lands here. Whether
 * the viewer may decide is the backend's verdict (the deviation ids it lists
 * as the viewer's actions); everyone else reads who still has to.
 */
export default function TransitionDeviationsPanel({
  changeId, deviations, decidableIds, focusId, onFocused,
}: {
  changeId: number
  deviations: TransitionDeviation[]
  /** Deviation ids the viewer may decide (my-actions 'deviation_decision'). */
  decidableIds: number[]
  /** Scroll to and highlight this deviation once (from the action button). */
  focusId?: number | null
  onFocused?: () => void
}) {
  const qc = useQueryClient()
  const rootRef = useRef<HTMLElement>(null)
  const [notes, setNotes] = useState<Record<number, string>>({})
  const pending = deviations.filter((d) => d.status === 'pending')

  useEffect(() => {
    if (focusId === undefined || !rootRef.current) return
    const target = (focusId != null
      ? rootRef.current.querySelector<HTMLElement>(`[data-deviation="${focusId}"]`) : null) ?? rootRef.current
    target.scrollIntoView?.({ behavior: 'smooth', block: 'center' })
    target.focus?.({ preventScroll: true })
    onFocused?.()
  }, [focusId, onFocused])

  const decide = useMutation({
    mutationFn: (v: { id: number; decision: 'approved' | 'rejected' }) =>
      changesApi.decideDeviation(changeId, v.id, {
        decision: v.decision, ...(notes[v.id]?.trim() ? { note: notes[v.id].trim() } : {}),
      }),
    onSuccess: (_d, v) => {
      toast.success(v.decision === 'approved'
        ? 'Deviation approved: the step can be taken now'
        : 'Deviation rejected')
      qc.invalidateQueries({ queryKey: ['change', changeId] })
      qc.invalidateQueries({ queryKey: ['change-my-actions', changeId] })
    },
    onError: (e) => toast.error(apiErrorMessage(e, 'The decision failed')),
  })

  if (pending.length === 0) return null
  return (
    <section ref={rootRef} tabIndex={-1} data-testid="transition-deviations"
      aria-labelledby="transition-deviations-title"
      className="rounded-lg border border-amber-700/70 bg-amber-950/20 p-4 scroll-mt-4 focus:outline-none">
      <h3 id="transition-deviations-title" className="text-sm font-semibold text-amber-100">
        Deviation requests waiting for a decision
      </h3>
      <p className="mt-0.5 text-xs text-slate-400">
        A deviation lets the change take a step although a guard says it is not ready.
        Someone other than the requester decides it (4-eyes).
      </p>
      <ul className="mt-3 space-y-3">
        {pending.map((d) => {
          const mine = decidableIds.includes(d.id)
          const focused = focusId === d.id
          return (
            <li key={d.id} data-deviation={d.id} tabIndex={-1} data-testid={`deviation-${d.id}`}
              className={`rounded-lg border px-3 py-2 text-sm focus:outline-none ${focused
                ? 'border-sky-500 bg-slate-900/70' : 'border-slate-700 bg-slate-900/40'}`}>
              <p className="text-slate-200">
                <span className="font-mono text-slate-400">#{d.id}</span>{' '}
                Go to <span className="font-medium">{STATUS_LABELS[d.to_status as ChangeStatus] ?? d.to_status}</span>
                <span className="text-xs text-slate-500"> · asked {formatDateTime(d.proposed_at)}</span>
              </p>
              <p className="mt-1 whitespace-pre-wrap text-slate-300">{d.reason}</p>
              {mine ? (
                <div className="mt-2 flex flex-wrap items-center gap-2">
                  <input aria-label={`Note on deviation #${d.id}`} placeholder="Note (optional, recorded)"
                    value={notes[d.id] ?? ''} onChange={(e) => setNotes((m) => ({ ...m, [d.id]: e.target.value }))}
                    className="min-w-0 flex-1 rounded-lg border border-slate-600 bg-slate-900 px-2 py-1 text-xs text-slate-100 placeholder-slate-500" />
                  <button type="button" data-testid={`deviation-approve-${d.id}`} disabled={decide.isPending}
                    onClick={() => decide.mutate({ id: d.id, decision: 'approved' })}
                    className="rounded-lg bg-emerald-700 px-3 py-1 text-xs font-medium text-white hover:bg-emerald-600 disabled:opacity-50">
                    Approve
                  </button>
                  <button type="button" data-testid={`deviation-reject-${d.id}`} disabled={decide.isPending}
                    onClick={() => decide.mutate({ id: d.id, decision: 'rejected' })}
                    className="rounded-lg border border-red-700 px-3 py-1 text-xs text-red-200 hover:bg-red-900/30 disabled:opacity-50">
                    Reject
                  </button>
                </div>
              ) : (
                <p data-testid={`deviation-waiting-${d.id}`} className="mt-1 text-xs text-slate-500">
                  Waiting for the approver: the change lead, or an admin when the lead asked. Never the requester.
                </p>
              )}
            </li>
          )
        })}
      </ul>
    </section>
  )
}
