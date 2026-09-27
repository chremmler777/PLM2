/**
 * Every responsible team confirms the detailed timing or raises a concern.
 * A confirmation counts for the plan revision it was given on; once the plan
 * changes it goes stale and the team is asked again.
 */
import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { planApi } from '../../../api/changePlan'
import type { FeedbackVerdict, PlanFeedback, PlanFeedbackRow } from '../../../types/changePlan'
import { formatDate } from '../../../lib/format'
import { btnSm } from '../../common/buttonStyles'
import { toastError } from '../../../lib/apiError'

interface Props {
  changeId: number
  feedback: PlanFeedback | undefined
  myDepartmentIds: number[]
  /** Admin may answer for any department (spec section 3). */
  isAdmin?: boolean
  /** Feedback is open (detailed plan exists, timing not validated yet). */
  canRespond: boolean
}

type Chip = 'confirmed' | 'concern' | 'waiting' | 'stale'

function chipOf(r: PlanFeedbackRow): Chip {
  if (!r.verdict) return 'waiting'
  if (r.stale) return 'stale'
  return r.verdict
}

const CHIP: Record<Chip, { label: string; cls: string }> = {
  confirmed: { label: 'Confirmed', cls: 'border-emerald-700 bg-emerald-950/50 text-emerald-200' },
  concern: { label: 'Concern', cls: 'border-rose-700 bg-rose-950/50 text-rose-200' },
  waiting: { label: 'Waiting', cls: 'border-slate-600 bg-slate-800 text-slate-300' },
  stale: { label: 'Plan changed after this confirmation', cls: 'border-amber-700 bg-amber-950/40 text-amber-200' },
}

export default function TeamFeedbackPanel({ changeId, feedback, myDepartmentIds, isAdmin = false, canRespond }: Props) {
  const qc = useQueryClient()
  const [concernFor, setConcernFor] = useState<number | null>(null)
  const [note, setNote] = useState('')

  const post = useMutation({
    mutationFn: (v: { department_id: number; verdict: FeedbackVerdict; note?: string }) =>
      planApi.postFeedback(changeId, v),
    onSuccess: () => {
      setConcernFor(null); setNote('')
      qc.invalidateQueries({ queryKey: ['change', changeId, 'plan-feedback'] })
      qc.invalidateQueries({ queryKey: ['change-my-actions', changeId] })
      qc.invalidateQueries({ queryKey: ['change', changeId] })
    },
    onError: (e: unknown) => toastError(e, 'Could not save your answer'),
  })

  const rows = feedback?.required ?? []
  const confirmed = rows.filter((r) => chipOf(r) === 'confirmed').length
  const concerns = rows.filter((r) => chipOf(r) === 'concern')

  return (
    <section className="rounded-lg border border-slate-700 bg-slate-800 p-4 space-y-3" data-testid="team-feedback">
      <div className="flex items-baseline justify-between gap-2">
        <h3 className="text-xs uppercase tracking-wide text-slate-400">Team confirmation</h3>
        {rows.length > 0 && (
          <span className="text-xs text-slate-400 tabular-nums">{confirmed} of {rows.length} confirmed</span>
        )}
      </div>

      {concerns.length > 0 && (
        <div className="rounded-md border border-rose-800 bg-rose-950/40 px-3 py-2 space-y-1" role="alert"
          data-testid="feedback-concerns">
          <p className="text-xs font-semibold text-rose-200">
            {concerns.length === 1 ? '1 team has a concern' : `${concerns.length} teams have concerns`} about the timing
          </p>
          {concerns.map((c) => (
            <p key={c.department_id} className="text-xs text-rose-100/90">
              <span className="font-medium">{c.department_name}:</span> {c.note}
            </p>
          ))}
        </div>
      )}

      {!feedback ? (
        <p className="text-sm text-slate-400">Loading confirmations…</p>
      ) : rows.length === 0 ? (
        <p className="text-sm text-slate-400">No team needs to confirm this plan.</p>
      ) : (
        <ul className="divide-y divide-slate-700/70">
          {rows.map((r) => {
            const chip = chipOf(r)
            const mine = isAdmin || myDepartmentIds.includes(r.department_id)
            const open = concernFor === r.department_id
            return (
              <li key={r.department_id} className="py-2" data-testid={`feedback-row-${r.department_id}`}>
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-sm text-slate-200 min-w-[140px]">{r.department_name}</span>
                  <span className={`rounded-full border px-2 py-0.5 text-[11px] ${CHIP[chip].cls}`}
                    data-testid={`feedback-chip-${r.department_id}`}>{CHIP[chip].label}</span>
                  {r.by_name && (
                    <span className="text-[11px] text-slate-400">{r.by_name}, {formatDate(r.at)}</span>
                  )}
                  {mine && canRespond && !open && (
                    <div className="ml-auto flex gap-2">
                      {chip !== 'confirmed' && (
                        <button type="button" disabled={post.isPending}
                          data-testid={`feedback-confirm-${r.department_id}`}
                          aria-label={`Confirm timing for ${r.department_name}`}
                          className={btnSm.primary}
                          onClick={() => post.mutate({ department_id: r.department_id, verdict: 'confirmed' })}>
                          Confirm timing
                        </button>
                      )}
                      <button type="button"
                        data-testid={`feedback-concern-${r.department_id}`}
                        aria-label={`Raise a timing concern for ${r.department_name}`}
                        className={btnSm.secondary}
                        onClick={() => { setConcernFor(r.department_id); setNote('') }}>
                        Raise concern
                      </button>
                    </div>
                  )}
                </div>
                {r.note && chip !== 'concern' && (
                  <p className="mt-1 text-xs text-slate-400">{r.note}</p>
                )}
                {open && (
                  <div className="mt-2 space-y-2">
                    <textarea autoFocus rows={2} value={note} onChange={(e) => setNote(e.target.value)}
                      aria-label="What is wrong with the timing?"
                      data-testid={`feedback-note-${r.department_id}`}
                      placeholder="What does not work, and what would? For example: tool rework needs 3 more weeks."
                      className="w-full rounded-md border border-slate-600 bg-slate-900 px-2 py-1 text-sm text-slate-100 placeholder-slate-500" />
                    <div className="flex justify-end gap-2">
                      <button type="button" className={btnSm.ghost}
                        onClick={() => setConcernFor(null)}>Cancel</button>
                      <button type="button" disabled={!note.trim() || post.isPending}
                        data-testid={`feedback-concern-submit-${r.department_id}`}
                        className={btnSm.primary}
                        onClick={() => post.mutate({ department_id: r.department_id, verdict: 'concern', note: note.trim() })}>
                        Send concern
                      </button>
                    </div>
                  </div>
                )}
              </li>
            )
          })}
        </ul>
      )}
    </section>
  )
}
