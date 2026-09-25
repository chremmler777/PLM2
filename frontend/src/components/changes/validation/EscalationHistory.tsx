/**
 * Every level change of an issue, newest first, with who was told and who
 * acknowledged it. Named roles acknowledge here; PM, lead and Sales may raise
 * the level by hand with a reason.
 */
import { useState } from 'react'
import { validationIssuesApi } from '../../../api/validationIssues'
import type { EscalationLevel, IssueOut } from '../../../types/validationIssue'
import { issueCode } from '../../../types/validationIssue'
import { formatDate, formatDateTime } from '../../../lib/format'
import { inputCls, sectionLabel } from '../offer/offerFormat'
import EscalationBadge from './EscalationBadge'
import { useIssueMutation } from './useIssueMutation'

export default function EscalationHistory({ changeId, issue, canEscalate }: {
  changeId: number
  issue: IssueOut
  canEscalate: boolean
}) {
  const rows = [...(issue.escalations ?? [])].sort((a, b) => b.created_at.localeCompare(a.created_at))
  const [escalating, setEscalating] = useState(false)
  const [reason, setReason] = useState('')
  const current = issue.escalation_level ?? 1
  const nextLevel = Math.min(3, current + 1) as EscalationLevel

  const ack = useIssueMutation(changeId,
    (eid: number) => validationIssuesApi.acknowledge(changeId, issue.id, eid),
    { error: 'Could not acknowledge the escalation' })
  const escalate = useIssueMutation(changeId,
    () => validationIssuesApi.escalate(changeId, issue.id, { level: nextLevel, reason: reason.trim() }),
    { error: 'Could not escalate', onDone: () => { setEscalating(false); setReason('') } })

  return (
    <div data-testid={`issue-escalations-${issue.id}`} className="space-y-2">
      <div className="flex items-center gap-2">
        <span className={sectionLabel}>Escalation</span>
        {canEscalate && current < 3 && !escalating && (
          <button type="button" data-testid={`issue-escalate-${issue.id}`}
            onClick={() => setEscalating(true)}
            className="ml-auto text-[11px] text-slate-400 hover:text-slate-200">
            Escalate to L{nextLevel}
          </button>
        )}
      </div>
      {rows.length === 0 ? (
        <p className="text-xs text-slate-500">Level 1: the owner department and PM know about {issueCode(issue)}.</p>
      ) : (
        <ol className="space-y-1.5">
          {rows.map((e) => (
            <li key={e.id} data-testid={`escalation-${e.id}`}
              className="flex flex-wrap items-start gap-2 rounded-lg border border-slate-800 bg-slate-900/40 px-2.5 py-1.5">
              <EscalationBadge level={e.level} compact unacknowledged={!e.acknowledged_at} />
              <div className="min-w-0 flex-1 text-xs">
                <div className="text-slate-200">{e.reason}</div>
                <div className="text-[11px] text-slate-500">
                  {formatDateTime(e.created_at)}{e.created_by_name ? `, ${e.created_by_name}` : ', automatic'}
                  {e.notified ? `. Told: ${e.notified}` : ''}
                </div>
                {e.acknowledged_at && (
                  <div data-testid={`escalation-acked-${e.id}`} className="text-[11px] text-emerald-400/90">
                    Acknowledged by {e.acknowledged_by_name ?? '-'}, {formatDate(e.acknowledged_at)}
                  </div>
                )}
              </div>
              {!e.acknowledged_at && e.can_acknowledge && (
                <button type="button" data-testid={`escalation-ack-${e.id}`}
                  disabled={ack.isPending} onClick={() => ack.mutate(e.id)}
                  className="rounded-md border border-slate-600 px-2 py-0.5 text-[11px] text-slate-200 hover:bg-slate-700 disabled:opacity-50">
                  Acknowledge
                </button>
              )}
            </li>
          ))}
        </ol>
      )}
      {escalating && (
        <div className="flex flex-wrap items-center gap-2">
          <input autoFocus data-testid={`issue-escalate-reason-${issue.id}`} value={reason}
            onChange={(ev) => setReason(ev.target.value)}
            placeholder={`Why L${nextLevel}? (required)`} className={`${inputCls} min-w-0 flex-1`} />
          <button type="button" data-testid={`issue-escalate-confirm-${issue.id}`}
            disabled={!reason.trim() || escalate.isPending} onClick={() => escalate.mutate(undefined)}
            className="rounded-lg bg-amber-700 px-2.5 py-1 text-xs text-white hover:bg-amber-600 disabled:opacity-50">
            Escalate
          </button>
          <button type="button" onClick={() => setEscalating(false)}
            className="px-1 text-xs text-slate-400 hover:text-slate-200">Cancel</button>
        </div>
      )}
    </div>
  )
}
