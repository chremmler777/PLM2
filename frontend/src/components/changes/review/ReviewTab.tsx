/**
 * The Review tab of an engineering review (spec 2026-09-25 §17): the light
 * track of a new customer index. Development locks the impact (Impacted tab);
 * the departments serving the part answer "no impact" or "impact" with a
 * note. Every "no impact" activates the index and closes the change; any
 * impact is escalated to a full ECR by Development (the answers stay as the
 * scoping input). Rules live in the backend (/changes/{id}/review).
 */
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { intakeKeys, intakesApi, type ReviewAnswer, type ReviewState } from '../../../api/intakes'
import { formatDate } from '../../../lib/format'
import type { ChangeRequest } from '../../../types/change'

const errDetail = (e: unknown): string | undefined =>
  (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail

const card = 'rounded-lg border border-slate-700 bg-slate-800 p-4'

export default function ReviewTab({ change, onGoImpact }: { change: ChangeRequest; onGoImpact?: () => void }) {
  const qc = useQueryClient()
  const { data: state, isError } = useQuery({
    queryKey: intakeKeys.review(change.id), queryFn: () => intakesApi.review(change.id),
  })
  const refresh = (next: ReviewState) => {
    qc.setQueryData(intakeKeys.review(change.id), next)
    qc.invalidateQueries({ queryKey: ['change', change.id] })
    qc.invalidateQueries({ queryKey: ['change-my-actions', change.id] })
    qc.invalidateQueries({ queryKey: ['intakes'] })
  }
  const [escalating, setEscalating] = useState(false)
  const [escalateNote, setEscalateNote] = useState('')
  const escalate = useMutation({
    mutationFn: () => intakesApi.escalate(change.id, escalateNote.trim() || undefined),
    onSuccess: (next) => { refresh(next); setEscalating(false); toast.success('Escalated to a full ECR') },
    onError: (e) => toast.error(errDetail(e) ?? 'Could not escalate'),
  })

  if (isError) return <p className="text-sm text-red-300">Could not load the review.</p>
  if (!state) return <p className="text-sm text-slate-400">Loading…</p>

  const done = change.status === 'closed' || change.status === 'released'
  return (
    <div className="space-y-4" data-testid="review-tab">
      <section className={card}>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h3 className="text-xs uppercase tracking-wide text-slate-500">Engineering review</h3>
            <p className="mt-1 text-sm text-slate-200">
              {state.escalated
                ? `Escalated to a full ECR on ${formatDate(state.escalated_at)}. The answers below are the scoping input.`
                : done ? 'Every department answered "no impact": the new index is active and the review is closed.'
                : !state.impact_locked ? 'Development locks the impacted set first; then the departments serving it are asked.'
                : state.impact_count > 0 ? `${state.impact_count} impact reported: Development escalates this to a full ECR.`
                : state.open_count > 0 ? `Waiting on ${state.open_count} answer${state.open_count === 1 ? '' : 's'}. All "no impact" activates the index.`
                : 'All answered.'}
            </p>
          </div>
          {!state.impact_locked && !state.escalated && onGoImpact && (
            <button onClick={onGoImpact} data-testid="review-go-impact"
              className="rounded-lg bg-sky-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-sky-500">
              Lock the impact
            </button>
          )}
          {state.can_escalate && !state.escalated && (
            <button onClick={() => setEscalating(true)} data-testid="review-escalate"
              className={`rounded-lg px-3 py-1.5 text-sm font-medium ${state.impact_count > 0
                ? 'bg-amber-600 text-white hover:bg-amber-500'
                : 'border border-slate-600 text-slate-200 hover:bg-slate-700'}`}>
              Escalate to a full ECR
            </button>
          )}
        </div>
        {state.revisions.length > 0 && (
          <ul className="mt-3 flex flex-wrap gap-2 text-xs">
            {state.revisions.map((r) => (
              <li key={r.revision_id}>
                <Link to={`/parts/${r.part_id}`}
                  className={`rounded-full px-2 py-0.5 ${r.active
                    ? 'bg-emerald-900/50 text-emerald-200' : 'bg-amber-900/50 text-amber-200'}`}>
                  {r.part_number} index {r.revision_name}: {r.active ? 'active' : 'pending'}
                </Link>
              </li>
            ))}
          </ul>
        )}
        {escalating && (
          <div className="mt-3 rounded-lg border border-amber-700/60 bg-amber-950/30 p-3" data-testid="escalate-form">
            <p className="text-sm text-amber-100">
              The change becomes a full customer ECR in scoping (assessment, costing, quote, timing). Audited.
            </p>
            <textarea value={escalateNote} onChange={(e) => setEscalateNote(e.target.value)} rows={2}
              aria-label="Why escalate"
              placeholder={state.impact_count > 0 ? 'Optional note (the reported impacts are recorded)' : 'Why? (required: nobody reported an impact)'}
              className="mt-2 w-full rounded-md border border-slate-600 bg-slate-800 px-2 py-1.5 text-sm text-slate-100" />
            <div className="mt-2 flex justify-end gap-2">
              <button onClick={() => setEscalating(false)}
                className="rounded-lg border border-slate-600 px-3 py-1.5 text-sm text-slate-200 hover:bg-slate-800">Cancel</button>
              <button data-testid="escalate-confirm"
                disabled={escalate.isPending || (state.impact_count === 0 && !escalateNote.trim())}
                onClick={() => escalate.mutate()}
                className="rounded-lg bg-amber-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-amber-500 disabled:opacity-40">
                Escalate
              </button>
            </div>
          </div>
        )}
      </section>

      {state.answers.length > 0 && (
        <section className={card}>
          <h3 className="text-xs uppercase tracking-wide text-slate-500">Department answers</h3>
          <ul className="mt-2 divide-y divide-slate-700">
            {state.answers.map((a) => (
              <AnswerRow key={a.id} changeId={change.id} answer={a} onDone={refresh} />
            ))}
          </ul>
        </section>
      )}
    </div>
  )
}

function AnswerRow({ changeId, answer, onDone }: {
  changeId: number; answer: ReviewAnswer; onDone: (s: ReviewState) => void
}) {
  const [note, setNote] = useState(answer.note ?? '')
  const [editing, setEditing] = useState(false)
  const send = useMutation({
    mutationFn: (value: 'no_impact' | 'impact') =>
      intakesApi.answer(changeId, { department_id: answer.department_id, answer: value, note: note.trim() || undefined }),
    onSuccess: (next) => { onDone(next); setEditing(false) },
    onError: (e) => toast.error(errDetail(e) ?? 'Could not save the answer'),
  })
  const tone = answer.answer === 'impact' ? 'bg-amber-900/60 text-amber-200'
    : answer.answer === 'no_impact' ? 'bg-emerald-900/60 text-emerald-200' : 'bg-slate-700 text-slate-300'
  const open = answer.can_answer && (answer.answer === null || editing)
  return (
    <li className="py-3" data-testid={`review-row-${answer.department_id}`}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <span className="font-medium text-slate-100">{answer.department_name}</span>
          <span className={`ml-2 rounded-full px-2 py-0.5 text-xs ${tone}`}>{answer.answer_label ?? 'Open'}</span>
          {answer.answered_by_name && (
            <span className="ml-2 text-xs text-slate-500">{answer.answered_by_name}, {formatDate(answer.answered_at)}</span>
          )}
        </div>
        {answer.can_answer && answer.answer !== null && !editing && (
          <button onClick={() => setEditing(true)} className="text-xs text-sky-300 hover:underline">Change answer</button>
        )}
      </div>
      {answer.objects.length > 0 && (
        <p className="mt-1 text-xs text-slate-400">
          Concerns: {answer.objects.map((o) => `${o.number} ${o.name}`).join(', ')}
        </p>
      )}
      {answer.note && !open && <p className="mt-1 text-sm text-slate-300">{answer.note}</p>}
      {open && (
        <div className="mt-2 space-y-2">
          <textarea value={note} onChange={(e) => setNote(e.target.value)} rows={2}
            aria-label={`Note for ${answer.department_name}`}
            placeholder="Note (required for impact: what changes for us?)"
            className="w-full rounded-md border border-slate-600 bg-slate-900 px-2 py-1.5 text-sm text-slate-100" />
          <div className="flex gap-2">
            <button disabled={send.isPending} onClick={() => send.mutate('no_impact')}
              data-testid={`answer-no-impact-${answer.department_id}`}
              className="rounded-lg bg-emerald-700 px-3 py-1.5 text-sm font-medium text-white hover:bg-emerald-600 disabled:opacity-40">
              No impact
            </button>
            <button disabled={send.isPending || !note.trim()} onClick={() => send.mutate('impact')}
              data-testid={`answer-impact-${answer.department_id}`}
              className="rounded-lg bg-amber-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-amber-500 disabled:opacity-40">
              Impact
            </button>
          </div>
        </div>
      )}
      {!answer.can_answer && answer.answer === null && (
        <p className="mt-1 text-xs text-slate-500">Answered by a member of {answer.department_name}.</p>
      )}
    </li>
  )
}
