/**
 * Sales records what the customer said (spec §12 Customer, §12a new timing).
 * A concession is accepted only with the customer's mail filed into the
 * issue; a new timing carries the new release date.
 */
import { useState } from 'react'
import { validationIssuesApi } from '../../../api/validationIssues'
import type { CustomerDecision, IssueOut } from '../../../types/validationIssue'
import { formatDate } from '../../../lib/format'
import { inputCls } from '../offer/offerFormat'
import { DECISION_LABEL } from './issueModel'
import { useIssueMutation } from './useIssueMutation'

const OPTIONS: CustomerDecision[] = ['accept_deviation', 'require_fix', 'new_timing', 'pending']

export const hasCustomerMail = (i: IssueOut) => (i.attachments ?? []).some((a) => a.kind === 'customer_email')

/** Why this decision cannot be saved yet, or null. */
export function customerDecisionBlocked(i: IssueOut, d: CustomerDecision | null, note: string, newDate: string): string | null {
  if (!d) return 'Pick what the customer decided'
  if (!note.trim()) return 'Add a note (what was agreed, with whom)'
  if (d === 'accept_deviation' && i.route === 'customer_concession' && !hasCustomerMail(i)) {
    return 'File the customer mail into this issue first'
  }
  if (d === 'new_timing' && !newDate) return 'Enter the new release date'
  return null
}

export default function CustomerDecisionForm({ changeId, issue, releaseDueDate, onDone }: {
  changeId: number
  issue: IssueOut
  /** The current release deadline, to set the new date against. */
  releaseDueDate?: string | null
  onDone?: () => void
}) {
  const [decision, setDecision] = useState<CustomerDecision | null>(null)
  const [note, setNote] = useState('')
  const [until, setUntil] = useState('')
  const [newDate, setNewDate] = useState('')
  const save = useIssueMutation(changeId, () => validationIssuesApi.customer(changeId, issue.id, {
    decision: decision!, note: note.trim(),
    ...(decision === 'accept_deviation' && until ? { concession_until: until } : {}),
    ...(decision === 'new_timing' ? { new_release_due_date: newDate } : {}),
  }), { error: 'Could not record the customer decision', onDone })

  const blocked = customerDecisionBlocked(issue, decision, note, newDate)
  const deadline = releaseDueDate ?? issue.recovery?.release_due_date ?? null

  return (
    <div data-testid={`issue-customer-form-${issue.id}`} className="space-y-2 rounded-lg border border-slate-700 bg-slate-900/40 p-3">
      <div role="radiogroup" aria-label="Customer decision" className="flex flex-wrap gap-1.5">
        {OPTIONS.map((d) => (
          <button key={d} type="button" role="radio" aria-checked={decision === d}
            data-testid={`customer-decision-${d}`} onClick={() => setDecision(d)}
            className={`rounded-md border px-2.5 py-1 text-xs ${decision === d
              ? 'border-sky-600 bg-sky-950/40 text-sky-100' : 'border-slate-700 text-slate-300 hover:border-slate-600'}`}>
            {DECISION_LABEL[d]}
          </button>
        ))}
      </div>
      {decision === 'require_fix' && issue.route === 'customer_concession' && (
        <p className="text-[11px] text-amber-300">
          The concession is off: the route is decided again and the issue goes to level 3.
        </p>
      )}
      {decision === 'accept_deviation' && (
        <label className="flex flex-wrap items-center gap-2 text-xs text-slate-400">
          Concession until (empty = permanent)
          <input type="date" data-testid="customer-concession-until" value={until}
            onChange={(e) => setUntil(e.target.value)} className={inputCls} />
        </label>
      )}
      {decision === 'new_timing' && (
        <label className="flex flex-wrap items-center gap-2 text-xs text-slate-400">
          New release date
          <input type="date" data-testid="customer-new-date" value={newDate}
            onChange={(e) => setNewDate(e.target.value)} className={inputCls} />
          <span className="text-[11px] text-slate-500">
            Now {formatDate(deadline)}. Updates the release deadline (reason "VI-{issue.number}").
          </span>
        </label>
      )}
      <textarea data-testid="customer-note" rows={2} value={note} onChange={(e) => setNote(e.target.value)}
        placeholder="What the customer said, who, when" className={`${inputCls} w-full`} />
      <div className="flex flex-wrap items-center gap-2">
        <button type="button" data-testid="customer-submit" disabled={!!blocked || save.isPending}
          onClick={() => save.mutate(undefined)}
          className="rounded-lg bg-sky-600 px-3 py-1 text-xs font-semibold text-white hover:bg-sky-500 disabled:opacity-50">
          Record decision
        </button>
        {blocked && <span data-testid="customer-blocked" className="text-[11px] text-slate-500">{blocked}</span>}
      </div>
    </div>
  )
}
