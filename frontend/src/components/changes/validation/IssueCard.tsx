/**
 * One validation issue: what failed, where it stands on the way to closed,
 * what the customer said, what it costs, what the recovery does to the
 * timing, and one primary button for the viewer's next act.
 */
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import { validationIssuesApi, validationIssuesKey } from '../../../api/validationIssues'
import type { IssueAct, IssueOut } from '../../../types/validationIssue'
import { isIssueOpen, issueCode } from '../../../types/validationIssue'
import { formatDate } from '../../../lib/format'
import { inputCls, sectionLabel } from '../offer/offerFormat'
import {
  ACT_LABEL, CATEGORY_LABEL, DECISION_CHIP, DECISION_LABEL, FIX_ROUTES, ROUTE, SEVERITY, STATUS_LABEL,
  issueActs, primaryAct, raiserBlocked, type IssueViewer,
} from './issueModel'
import IssueStepper from './IssueStepper'
import EscalationBadge from './EscalationBadge'
import EscalationHistory from './EscalationHistory'
import RecoverySummary from './RecoverySummary'
import RouteDialog from './RouteDialog'
import CustomerDecisionForm from './CustomerDecisionForm'
import CostForm, { CostLine } from './CostForm'
import ActionsChecklist from './ActionsChecklist'
import IssueDropzone from './IssueDropzone'
import { useIssueMutation } from './useIssueMutation'

/** Inline acts that are a single text: containment, root cause, closure note. */
type TextAct = 'contain' | 'root_cause' | 'close'
const TEXT_ACT: Record<TextAct, { placeholder: string; submit: string }> = {
  contain: { placeholder: 'Immediate action: hold parts, protect the bank, run the old state', submit: 'Save containment' },
  root_cause: { placeholder: 'Why it failed (5 why, measured, confirmed)', submit: 'Save root cause' },
  close: { placeholder: 'Closure note: how the fix was confirmed', submit: 'Close issue' },
}

function TextActForm({ act, onSubmit, onCancel, busy, issueId }: {
  act: TextAct; onSubmit: (text: string) => void; onCancel: () => void; busy: boolean; issueId: number
}) {
  const [text, setText] = useState('')
  return (
    <div data-testid={`issue-form-${act}-${issueId}`} className="space-y-2 rounded-lg border border-slate-700 bg-slate-900/40 p-3">
      <textarea autoFocus rows={2} value={text} onChange={(e) => setText(e.target.value)}
        data-testid={`issue-text-${act}-${issueId}`}
        placeholder={TEXT_ACT[act].placeholder} className={`${inputCls} w-full`} />
      <div className="flex items-center gap-2">
        <button type="button" data-testid={`issue-text-submit-${act}-${issueId}`}
          disabled={!text.trim() || busy} onClick={() => onSubmit(text.trim())}
          className="rounded-lg bg-sky-600 px-3 py-1 text-xs font-semibold text-white hover:bg-sky-500 disabled:opacity-50">
          {TEXT_ACT[act].submit}
        </button>
        <button type="button" onClick={onCancel} className="px-1 text-xs text-slate-400 hover:text-slate-200">Cancel</button>
      </div>
    </div>
  )
}

function Fact({ label, children, testId }: { label: string; children: React.ReactNode; testId?: string }) {
  return (
    <div data-testid={testId}>
      <div className={sectionLabel}>{label}</div>
      <div className="mt-0.5 text-xs text-slate-200 whitespace-pre-line">{children}</div>
    </div>
  )
}

const by = (name?: string | null, at?: string | null) =>
  name || at ? <span className="text-[11px] text-slate-500"> ({[name, at ? formatDate(at) : null].filter(Boolean).join(', ')})</span> : null

export default function IssueCard({
  changeId, changeStatus, issue, viewer, departments, releaseDueDate, defaultOpen,
}: {
  changeId: number
  changeStatus: string
  issue: IssueOut
  viewer: IssueViewer
  departments: { id: number; name: string }[]
  releaseDueDate?: string | null
  defaultOpen?: boolean
}) {
  const qc = useQueryClient()
  const open = isIssueOpen(issue)
  const [expanded, setExpanded] = useState(defaultOpen ?? open)
  const [active, setActive] = useState<IssueAct | null>(null)
  const code = issueCode(issue)

  const acts = issueActs(issue, viewer)
  // 4 eyes: a PM or lead who raised the issue sees the route step, but not as theirs.
  const fourEyes = open && !issue.route && !acts.includes('route')
    && (!!viewer.canManage) && raiserBlocked(issue, viewer)
  const primary = primaryAct(acts)
  const secondary = acts.filter((a) => a !== primary && !['attach', 'edit', 'escalate', 'add_action', 'action_done'].includes(a))
  const unacked = (issue.escalations ?? []).filter((e) => !e.acknowledged_at)
  const myAck = unacked.find((e) => e.can_acknowledge)

  const contain = useIssueMutation(changeId, (t: string) => validationIssuesApi.contain(changeId, issue.id, t),
    { error: 'Could not save the containment', onDone: () => setActive(null) })
  const rootCause = useIssueMutation(changeId, (t: string) => validationIssuesApi.rootCause(changeId, issue.id, t),
    { error: 'Could not save the root cause', onDone: () => setActive(null) })
  const close = useIssueMutation(changeId, (t: string) => validationIssuesApi.close(changeId, issue.id, t),
    { error: 'Could not close the issue', onDone: () => setActive(null) })
  const ack = useIssueMutation(changeId, (eid: number) => validationIssuesApi.acknowledge(changeId, issue.id, eid),
    { error: 'Could not acknowledge the escalation' })

  const run = (a: IssueAct) => {
    setExpanded(true)
    if (a === 'acknowledge' && myAck) { ack.mutate(myAck.id); return }
    if (a === 'action_done') {
      document.getElementById(`issue-actions-anchor-${issue.id}`)?.scrollIntoView?.({ behavior: 'smooth', block: 'center' })
      return
    }
    setActive(a)
  }

  const primaryButton = primary ? (
    <button type="button" data-testid={`issue-primary-${issue.id}`} data-act={primary}
      disabled={ack.isPending} onClick={() => run(primary)}
      className="rounded-lg bg-sky-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-sky-500 disabled:opacity-50">
      {ACT_LABEL[primary]}
    </button>
  ) : fourEyes ? (
    <button type="button" data-testid={`issue-primary-${issue.id}`} data-act="route" disabled
      title="You raised this issue. Another PM or the change lead decides the route (4 eyes)."
      className="cursor-not-allowed rounded-lg bg-sky-600 px-3 py-1.5 text-xs font-semibold text-white opacity-50">
      {ACT_LABEL.route}
    </button>
  ) : null

  const deptName = issue.department_name ?? departments.find((d) => d.id === issue.department_id)?.name ?? null
  const decision = issue.customer_decision

  return (
    <article data-testid={`issue-card-${issue.id}`} data-status={issue.status}
      className={`rounded-xl border ${open
        ? issue.escalation_level === 3 ? 'border-rose-900/70' : issue.escalation_level === 2 ? 'border-amber-900/60' : 'border-slate-700'
        : 'border-slate-800'} bg-slate-900/30`}>
      <header className="flex flex-wrap items-start gap-x-3 gap-y-2 px-4 py-3">
        <button type="button" onClick={() => setExpanded((x) => !x)} aria-expanded={expanded}
          aria-label={`${expanded ? 'Collapse' : 'Expand'} ${code}`}
          className="mt-0.5 text-slate-500 hover:text-slate-300">
          <span className={`inline-block transition-transform ${expanded ? 'rotate-90' : ''}`}>▸</span>
        </button>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-mono text-xs font-semibold text-slate-400">{code}</span>
            <h4 className={`text-sm font-medium ${open ? 'text-slate-100' : 'text-slate-400'}`}>{issue.title}</h4>
          </div>
          <div className="mt-1 flex flex-wrap items-center gap-1.5 text-[11px]">
            <span data-testid={`issue-severity-${issue.id}`}
              className={`rounded-md border px-1.5 py-0.5 ${SEVERITY[issue.severity].chip}`}>{SEVERITY[issue.severity].label}</span>
            {open && <EscalationBadge level={issue.escalation_level ?? 1} unacknowledged={unacked.length > 0} />}
            <span className="rounded-md border border-slate-700 px-1.5 py-0.5 text-slate-300">{STATUS_LABEL[issue.status]}</span>
            {issue.route && (
              <span data-testid={`issue-route-${issue.id}`} className="rounded-md border border-sky-900 bg-sky-950/40 px-1.5 py-0.5 text-sky-200">
                {ROUTE[issue.route].label}
              </span>
            )}
            {decision && (
              <span data-testid={`issue-decision-${issue.id}`} className={`rounded-md border px-1.5 py-0.5 ${DECISION_CHIP[decision]}`}>
                Customer: {DECISION_LABEL[decision]}
              </span>
            )}
            {!decision && issue.customer_inform && open && (
              <span className="rounded-md border border-slate-600 px-1.5 py-0.5 text-slate-300">Customer to be informed</span>
            )}
            <span className="text-slate-500">
              {CATEGORY_LABEL[issue.category]}{deptName ? ` · ${deptName}` : ''}
            </span>
          </div>
        </div>
        <div className="flex flex-col items-end gap-1">
          {primaryButton}
          {fourEyes && !primary && (
            <span data-testid={`issue-four-eyes-${issue.id}`} className="max-w-[16rem] text-right text-[11px] text-slate-500">
              You raised {code}: another PM or the lead decides the route.
            </span>
          )}
        </div>
      </header>

      <div className="border-t border-slate-800 px-4 py-2.5">
        <IssueStepper issue={issue} />
      </div>

      {expanded && (
        <div className="space-y-4 border-t border-slate-800 px-4 py-3">
          {active === 'contain' || active === 'root_cause' || active === 'close' ? (
            <TextActForm act={active} issueId={issue.id}
              busy={contain.isPending || rootCause.isPending || close.isPending}
              onCancel={() => setActive(null)}
              onSubmit={(t) => (active === 'contain' ? contain : active === 'root_cause' ? rootCause : close).mutate(t)} />
          ) : null}
          {active === 'customer' && (
            <CustomerDecisionForm changeId={changeId} issue={issue} releaseDueDate={releaseDueDate}
              onDone={() => setActive(null)} />
          )}
          {active === 'cost' && <CostForm changeId={changeId} issue={issue} onDone={() => setActive(null)} />}

          <div className="grid gap-3 sm:grid-cols-2">
            <Fact label="What happened">
              {issue.description}
              <span className="text-[11px] text-slate-500"> ({issue.created_by_name ?? '-'}, {formatDate(issue.created_at)})</span>
              {issue.affected_tool_ref && <div className="text-[11px] text-slate-400">Tool / equipment: {issue.affected_tool_ref}</div>}
              {issue.affected_part_number && <div className="text-[11px] text-slate-400">Part: {issue.affected_part_number}</div>}
            </Fact>
            <Fact label="Containment" testId={`issue-containment-${issue.id}`}>
              {issue.containment ? <>{issue.containment}{by(issue.contained_by_name, issue.contained_at)}</>
                : <span className="text-slate-500">{issue.severity === 3 ? 'Needed before the route: production is blocked.' : 'Not recorded.'}</span>}
            </Fact>
            <Fact label="Root cause" testId={`issue-rootcause-${issue.id}`}>
              {issue.root_cause ? <>{issue.root_cause}{by(issue.root_cause_by_name, issue.root_cause_at)}</>
                : <span className="text-slate-500">
                  {issue.route === 'customer_concession' ? 'Open; the customer accepts the part as it is.' : 'Owner department finds it before the route.'}
                </span>}
            </Fact>
            <Fact label="Route" testId={`issue-routefact-${issue.id}`}>
              {issue.route ? (
                <>
                  {ROUTE[issue.route].label}: {issue.route_reason}{by(issue.route_decided_by_name, issue.route_decided_at)}
                  {issue.supplier_name && (
                    <div className="text-[11px] text-slate-400">Supplier: {issue.supplier_name}{issue.chargeback ? ', chargeback' : ''}</div>
                  )}
                  {issue.follow_up_change_id && (
                    <div className="text-[11px]">
                      Follow-up:{' '}
                      <Link to={`/changes/${issue.follow_up_change_id}`} className="text-sky-300 hover:underline">
                        {issue.follow_up_change_number ?? `#${issue.follow_up_change_id}`}
                      </Link>
                    </div>
                  )}
                </>
              ) : <span className="text-slate-500">PM or the lead decides once cause{issue.severity === 3 ? ' and containment are' : ' is'} known.</span>}
            </Fact>
            {(issue.customer_inform || decision) && (
              <Fact label="Customer" testId={`issue-customer-${issue.id}`}>
                {decision ? (
                  <>
                    {DECISION_LABEL[decision]}{issue.customer_decision_note ? `: ${issue.customer_decision_note}` : ''}
                    {by(issue.customer_decided_by_name, issue.customer_decided_at)}
                    {issue.concession_until && <div className="text-[11px] text-slate-400">Concession until {formatDate(issue.concession_until)}</div>}
                  </>
                ) : <span className="text-slate-500">Sales records the customer's decision.</span>}
              </Fact>
            )}
            <Fact label="Extra cost">
              <CostLine issue={issue} canSeeCosts={!!viewer.canSeeCosts} />
            </Fact>
            {issue.closure_note && (
              <Fact label="Closed">
                {issue.closure_note}{by(issue.closed_by_name, issue.closed_at)}
              </Fact>
            )}
          </div>

          {issue.recovery && <RecoverySummary changeId={changeId} recovery={issue.recovery} />}

          {(issue.actions.length > 0 || (issue.route && FIX_ROUTES.includes(issue.route))) && (
            <div id={`issue-actions-anchor-${issue.id}`}>
              <ActionsChecklist changeId={changeId} issue={issue} viewer={viewer}
                canAdd={acts.includes('add_action')} departments={departments} />
            </div>
          )}

          <IssueDropzone changeId={changeId} issue={issue} canAttach={open && (acts.includes('attach') || acts.length > 0 || fourEyes)}
            onUploaded={() => qc.invalidateQueries({ queryKey: validationIssuesKey(changeId) })} />

          <EscalationHistory changeId={changeId} issue={issue} canEscalate={open && acts.includes('escalate')} />

          {secondary.length > 0 && (
            <div className="flex flex-wrap items-center gap-3 border-t border-slate-800 pt-2">
              <span className="text-[11px] text-slate-500">Also:</span>
              {secondary.map((a) => (
                <button key={a} type="button" data-testid={`issue-act-${a}-${issue.id}`} onClick={() => run(a)}
                  className="text-[11px] text-sky-300 hover:text-sky-200">{ACT_LABEL[a]}</button>
              ))}
            </div>
          )}
        </div>
      )}

      <RouteDialog open={active === 'route'} changeId={changeId} changeStatus={changeStatus} issue={issue}
        departments={departments} onClose={() => setActive(null)} />
    </article>
  )
}
