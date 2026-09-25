/**
 * The validation issues of a change, above the checklist in the Release
 * tab's validation step. Open issues first, the most escalated on top;
 * closed ones fold away under one line.
 */
import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { validationIssuesApi, validationIssuesKey } from '../../../api/validationIssues'
import type { IssueOut } from '../../../types/validationIssue'
import { isIssueOpen, issueCode } from '../../../types/validationIssue'
import IssueCard from './IssueCard'
import RaiseIssueDialog from './RaiseIssueDialog'
import type { IssueViewer } from './issueModel'
import { STATUS_LABEL } from './issueModel'

/** Open first, then by escalation level, severity, number. */
export const sortIssues = (list: IssueOut[]) => [...list].sort((a, b) =>
  Number(isIssueOpen(b)) - Number(isIssueOpen(a))
  || (b.escalation_level ?? 1) - (a.escalation_level ?? 1)
  || b.severity - a.severity
  || a.number - b.number)

/** One release blocker line per open issue: "VI-2 open: Tool cannot run (fixing)". */
export const issueBlockers = (list: IssueOut[] = []): string[] =>
  sortIssues(list).filter(isIssueOpen)
    .map((i) => `${issueCode(i)} open: ${i.title} (${STATUS_LABEL[i.status].toLowerCase()})`)

/** Statuses in which an issue may be raised (spec §12 Raise). */
export const RAISE_STATUSES = ['in_validation', 'in_implementation']

export function useValidationIssues(changeId: number, enabled = true) {
  return useQuery({
    queryKey: validationIssuesKey(changeId),
    queryFn: () => validationIssuesApi.list(changeId),
    enabled,
  })
}

export default function IssuesPanel({
  changeId, changeStatus, departments, viewer, canRaise, releaseDueDate, focusIssueId = null,
  title = 'Validation issues', hint,
}: {
  changeId: number
  changeStatus: string
  departments: { id: number; name: string }[]
  viewer: IssueViewer
  /** Routed department members, PM, lead, admin. */
  canRaise: boolean
  releaseDueDate?: string | null
  /** Deep link ?issue=<id>: that card is opened, scrolled to and ringed. */
  focusIssueId?: number | null
  title?: string
  /** One muted line under the title (where the panel sits, what it is for). */
  hint?: string
}) {
  const { data: issues = [], isLoading } = useValidationIssues(changeId)
  const [raising, setRaising] = useState(false)
  const [showClosed, setShowClosed] = useState(false)
  const sorted = sortIssues(issues)
  const open = sorted.filter(isIssueOpen)
  const closed = sorted.filter((i) => !isIssueOpen(i))
  const raiseOk = canRaise && RAISE_STATUSES.includes(changeStatus)
  // A closed issue named by the deep link unfolds the closed list.
  useEffect(() => {
    if (focusIssueId != null && closed.some((i) => i.id === focusIssueId)) setShowClosed(true)
  }, [focusIssueId, closed.length]) // eslint-disable-line react-hooks/exhaustive-deps

  const card = (i: IssueOut) => (
    <IssueCard key={i.id} changeId={changeId} changeStatus={changeStatus} issue={i} viewer={viewer}
      departments={departments} releaseDueDate={releaseDueDate} highlight={focusIssueId === i.id} />
  )

  return (
    <section data-testid="validation-issues" className="space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-medium text-slate-100">{title}</span>
        {issues.length > 0 && (
          <span data-testid="validation-issues-count"
            className={`text-xs ${open.length ? 'text-amber-300' : 'text-emerald-400'}`}>
            {open.length ? `${open.length} open, release waits for them` : 'all closed'}
          </span>
        )}
        {raiseOk && (
          <button type="button" data-testid="issue-raise" onClick={() => setRaising(true)}
            className="ml-auto rounded-lg border border-slate-600 px-2.5 py-1 text-xs text-slate-200 hover:bg-slate-700">
            Raise issue
          </button>
        )}
      </div>

      {hint && <p className="text-xs text-slate-400">{hint}</p>}

      {isLoading ? null : issues.length === 0 ? (
        <p data-testid="validation-issues-empty" className="rounded-lg border border-dashed border-slate-700 px-3 py-2.5 text-xs text-slate-400">
          No issues. When a check fails, press "Raise issue" on that check: the failure gets an owner, a route to its fix
          and, if needed, the customer's decision.
        </p>
      ) : (
        <div className="space-y-2">
          {open.map(card)}
          {closed.length > 0 && (
            <>
              <button type="button" data-testid="validation-issues-closed-toggle" onClick={() => setShowClosed((x) => !x)}
                className="text-xs text-slate-400 hover:text-slate-200">
                {showClosed ? 'Hide' : 'Show'} {closed.length} closed issue{closed.length === 1 ? '' : 's'}
              </button>
              {showClosed && closed.map(card)}
            </>
          )}
        </div>
      )}

      <RaiseIssueDialog open={raising} changeId={changeId} departments={departments} onClose={() => setRaising(false)} />
    </section>
  )
}
