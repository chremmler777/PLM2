/**
 * One validation issue: what failed, where it stands on the way to closed,
 * what the customer said, what it costs, what the recovery does to the
 * timing, and one primary button for the viewer's next act.
 */
import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import { validationIssuesApi, validationIssuesKey } from '../../../api/validationIssues'
import type { IssueAct, IssueOut } from '../../../types/validationIssue'
import { isIssueOpen, issueCode } from '../../../types/validationIssue'
import { formatCalendarDate, formatDate } from '../../../lib/format'
import { inputCls, sectionLabel } from '../offer/offerFormat'
import {
  ACT_LABEL, CATEGORY_LABEL, DECISION_CHIP, DECISION_LABEL, FIX_ROUTES, ROUTE, SEVERITY,
  issueActs, issueNeedsAck, issuePrimaryAct, raiserBlocked, recheckTarget, statusChipLabel, type IssueViewer,
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
import IssueEditForm from './IssueEditForm'
import { useIssueMutation } from './useIssueMutation'
import { ChevronRight } from 'lucide-react'
import { btnSm } from '../../common/buttonStyles'

/** Inline acts that are a single text: containment, root cause, closure note. */
type TextAct = 'contain' | 'root_cause' | 'close'
const TEXT_ACT: Record<TextAct, { label: string; placeholder: string; submit: string }> = {
  contain: { label: 'Containment', placeholder: 'Immediate action: hold parts, protect the bank, run the old state', submit: 'Save containment' },
  root_cause: { label: 'Root cause', placeholder: 'Why it failed (5 why, measured, confirmed)', submit: 'Save root cause' },
  close: { label: 'Closure note', placeholder: 'Closure note: how the fix was confirmed', submit: 'Close issue' },
}

function TextActForm({ act, onSubmit, onCancel, busy, issueId }: {
  act: TextAct; onSubmit: (text: string) => void; onCancel: () => void; busy: boolean; issueId: number
}) {
  const [text, setText] = useState('')
  return (
    <div data-testid={`issue-form-${act}-${issueId}`} className="space-y-2 rounded-lg border border-slate-700 bg-slate-900/40 p-3">
      <textarea autoFocus rows={2} value={text} onChange={(e) => setText(e.target.value)}
        data-testid={`issue-text-${act}-${issueId}`} aria-label={TEXT_ACT[act].label}
        placeholder={TEXT_ACT[act].placeholder} className={`${inputCls} w-full`} />
      <div className="flex items-center gap-2">
        <button type="button" data-testid={`issue-text-submit-${act}-${issueId}`}
          disabled={!text.trim() || busy} onClick={() => onSubmit(text.trim())}
          className={btnSm.primary}>
          {TEXT_ACT[act].submit}
        </button>
        <button type="button" onClick={onCancel} className={btnSm.ghost}>Cancel</button>
      </div>
    </div>
  )
}

/** Sales confirms the customer-paid fix went out as a quote (POST fix-quoted). */
function QuoteFixForm({ changeId, issue, onDone }: { changeId: number; issue: IssueOut; onDone: () => void }) {
  const [note, setNote] = useState('')
  const quote = useIssueMutation(changeId, () => validationIssuesApi.fixQuoted(changeId, issue.id, note.trim()),
    { error: 'Could not record the quote', onDone })
  return (
    <div role="dialog" aria-label={`Quote the fix of ${issueCode(issue)}`} data-testid={`issue-quote-form-${issue.id}`}
      className="space-y-2 rounded-lg border border-sky-800/70 bg-sky-950/20 p-3">
      <p className="text-xs text-slate-200">
        The customer pays this fix. Confirm that the quote for it went to the customer: it is recorded on {issueCode(issue)}
        {' '}and Sales' task closes. This cannot be taken back.
      </p>
      <input data-testid={`issue-quote-note-${issue.id}`} value={note} onChange={(e) => setNote(e.target.value)}
        placeholder="Quote number, sent to whom (optional)" aria-label="Quote note" className={`${inputCls} w-full`} />
      <div className="flex items-center gap-2">
        <button type="button" data-testid={`issue-quote-confirm-${issue.id}`} disabled={quote.isPending}
          onClick={() => quote.mutate(undefined)}
          className={btnSm.primary}>
          Fix quoted to the customer
        </button>
        <button type="button" onClick={onDone} className={btnSm.ghost}>Cancel</button>
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
  name || at ? <span className="text-[11px] text-slate-400"> ({[name, at ? formatDate(at) : null].filter(Boolean).join(', ')})</span> : null

export default function IssueCard({
  changeId, changeStatus, issue, viewer, departments, releaseDueDate, defaultOpen, highlight = false,
}: {
  changeId: number
  changeStatus: string
  issue: IssueOut
  viewer: IssueViewer
  departments: { id: number; name: string }[]
  releaseDueDate?: string | null
  defaultOpen?: boolean
  /** Deep link target (?issue=<id>): scrolled to, opened and ringed. */
  highlight?: boolean
}) {
  const qc = useQueryClient()
  const open = isIssueOpen(issue)
  const [expanded, setExpanded] = useState(defaultOpen ?? (open || highlight))
  const [active, setActive] = useState<IssueAct | 'quote_fix' | null>(null)
  /** Bumped to open the add-action row of the checklist (add_action act). */
  const [addRequest, setAddRequest] = useState(0)
  const ref = useRef<HTMLElement>(null)
  useEffect(() => {
    if (!highlight) return
    setExpanded(true)
    ref.current?.scrollIntoView?.({ behavior: 'smooth', block: 'start' })
  }, [highlight])
  const code = issueCode(issue)
  // A failed re-check sends the issue back to fixing: the "answer the check
  // again" note it opened no longer applies.
  useEffect(() => {
    if (issue.status !== 'revalidation') setActive((a) => (a === 'recheck' ? null : a))
  }, [issue.status])

  const acts = issueActs(issue, viewer)
  // 4 eyes: a PM or lead who raised the issue sees the route step, but not as theirs.
  const fourEyes = open && !issue.route && !acts.includes('route')
    && (!!viewer.canManage) && raiserBlocked(issue, viewer)
  const primary = issuePrimaryAct(issue, acts)
  const secondary = acts.filter((a) => a !== primary && !['attach', 'edit', 'escalate', 'add_action', 'action_done'].includes(a))
  const extra = issue.extra_acts ?? []
  // quote_fix and a late cost still land after the issue is closed
  const canQuote = extra.includes('quote_fix') && !issue.fix_quoted_at
  const canLateCost = !open && extra.includes('cost')
  const costSet = issue.cost_set ?? issue.extra_cost != null
  const checkRow = recheckTarget(issue)
  const canEdit = open && acts.includes('edit')
  const myAck = (issue.escalations ?? []).find((e) => !e.acknowledged_at && e.can_acknowledge)
  // Fixed during the loop back: the re-check waits for validation (the
  // backend offers no act in implementation), so the card names the step.
  const recheckWaits = open && issue.status === 'revalidation' && changeStatus === 'in_implementation'
    && !acts.includes('recheck')

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
    if (a === 'action_done' || a === 'add_action') {
      if (a === 'add_action') setAddRequest((n) => n + 1)
      document.getElementById(`issue-actions-anchor-${issue.id}`)?.scrollIntoView?.({ behavior: 'smooth', block: 'center' })
      return
    }
    if (a === 'recheck' && checkRow) {
      // the linked check lives in the validation panel on the same tab
      document.querySelector(`[data-testid="${checkRow}"]`)?.scrollIntoView?.({ behavior: 'smooth', block: 'center' })
    }
    setActive(a)
  }

  const primaryButton = !primary && canQuote ? (
    <button type="button" data-testid={`issue-primary-${issue.id}`} data-act="quote_fix"
      onClick={() => { setExpanded(true); setActive('quote_fix') }}
      className={btnSm.primary}>
      Quote the fix
    </button>
  ) : primary ? (
    <button type="button" data-testid={`issue-primary-${issue.id}`} data-act={primary}
      disabled={ack.isPending} onClick={() => run(primary)}
      className={btnSm.primary}>
      {ACT_LABEL[primary]}
    </button>
  ) : recheckWaits ? (
    <span data-testid={`issue-recheck-waits-${issue.id}`}
      className="max-w-[18rem] text-right text-[11px] text-slate-400">
      Fix done. The check is answered again once the change is back in validation.
    </span>
  ) : fourEyes ? (
    <button type="button" data-testid={`issue-primary-${issue.id}`} data-act="route" disabled
      title="You raised this issue. Another PM or the change lead decides the route (4 eyes)."
      className={btnSm.primary}>
      {ACT_LABEL.route}
    </button>
  ) : null

  const deptName = issue.department_name ?? departments.find((d) => d.id === issue.department_id)?.name ?? null
  const decision = issue.customer_decision

  return (
    <article ref={ref} data-testid={`issue-card-${issue.id}`} data-status={issue.status}
      data-highlight={highlight ? 'true' : undefined}
      className={`scroll-mt-4 rounded-xl border ${highlight ? 'ring-2 ring-sky-500/70 ' : ''}${open
        ? issue.escalation_level === 3 ? 'border-rose-900/70' : issue.escalation_level === 2 ? 'border-amber-900/60' : 'border-slate-700'
        : 'border-slate-800'} bg-slate-900/30`}>
      <header className="flex flex-wrap items-start gap-x-3 gap-y-2 px-4 py-3">
        <button type="button" onClick={() => setExpanded((x) => !x)} aria-expanded={expanded}
          aria-label={`${expanded ? 'Collapse' : 'Expand'} ${code}`}
          className="mt-0.5 rounded text-slate-400 hover:text-slate-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400">
          <ChevronRight aria-hidden="true" size={16} className={`transition-transform ${expanded ? 'rotate-90' : ''}`} />
        </button>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-mono text-xs font-semibold text-slate-300">{code}</span>
            <h4 className={`text-sm font-medium ${open ? 'text-slate-100' : 'text-slate-400'}`}>{issue.title}</h4>
          </div>
          <div className="mt-1 flex flex-wrap items-center gap-1.5 text-[11px]">
            <span data-testid={`issue-severity-${issue.id}`} title={`Severity ${issue.severity} of 3: ${SEVERITY[issue.severity].label}`}
              className={`rounded-md border px-1.5 py-0.5 ${SEVERITY[issue.severity].chip}`}>
              <span className="sr-only">Severity: </span>{SEVERITY[issue.severity].label}
            </span>
            {open && <EscalationBadge level={issue.escalation_level ?? 1} unacknowledged={issueNeedsAck(issue)} />}
            <span data-testid={`issue-status-${issue.id}`}
              className="rounded-md border border-slate-700 px-1.5 py-0.5 text-slate-300">{statusChipLabel(issue)}</span>
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
            <span className="text-slate-400">
              {CATEGORY_LABEL[issue.category]}{deptName ? ` · ${deptName}` : ''}
            </span>
          </div>
        </div>
        <div className="flex flex-col items-end gap-1">
          {primaryButton}
          {fourEyes && !primary && (
            <span data-testid={`issue-four-eyes-${issue.id}`} className="max-w-[16rem] text-right text-[11px] text-slate-400">
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
          {active === 'cost' && <CostForm changeId={changeId} issue={issue} late={!open} onDone={() => setActive(null)} />}
          {active === 'recheck' && (
            <div data-testid={`issue-recheck-${issue.id}`} role="note"
              className="flex items-start gap-2 rounded-lg border border-sky-800/70 bg-sky-950/20 p-3 text-xs text-slate-200">
              <p className="flex-1">
                Answer the check{issue.check?.label ? <> <span className="font-medium">{issue.check.label}</span></> : ''}
                {issue.check?.department_name ? ` (${issue.check.department_name})` : ''} again in the validation checks.
                A pass closes {code}; a fail sends it back to fixing.
              </p>
              <button type="button" onClick={() => setActive(null)} className="px-1 text-slate-400 hover:text-slate-200">Dismiss</button>
            </div>
          )}
          {active === 'edit' && (
            <IssueEditForm changeId={changeId} issue={issue} departments={departments} onDone={() => setActive(null)} />
          )}
          {active === 'quote_fix' && <QuoteFixForm changeId={changeId} issue={issue} onDone={() => setActive(null)} />}

          <div className="grid gap-3 sm:grid-cols-2">
            <Fact label="What happened">
              {issue.description}
              <span className="text-[11px] text-slate-400"> ({issue.created_by_name ?? '-'}, {formatDate(issue.created_at)})</span>
              {issue.affected_tool_ref && <div className="text-[11px] text-slate-400">Tool / equipment: {issue.affected_tool_ref}</div>}
              {issue.affected_part_number && <div className="text-[11px] text-slate-400">Part: {issue.affected_part_number}</div>}
            </Fact>
            <Fact label="Containment" testId={`issue-containment-${issue.id}`}>
              {issue.containment ? <>{issue.containment}{by(issue.contained_by_name, issue.contained_at)}</>
                : <span className="text-slate-400">{issue.severity === 3 ? 'Needed before the route: production is blocked.' : 'Not recorded.'}</span>}
            </Fact>
            <Fact label="Root cause" testId={`issue-rootcause-${issue.id}`}>
              {issue.root_cause ? <>{issue.root_cause}{by(issue.root_cause_by_name, issue.root_cause_at)}</>
                : <span className="text-slate-400">
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
              ) : <span className="text-slate-400">PM or the lead decides once cause{issue.severity === 3 ? ' and containment are' : ' is'} known.</span>}
            </Fact>
            {(issue.customer_inform || decision) && (
              <Fact label="Customer" testId={`issue-customer-${issue.id}`}>
                {decision ? (
                  <>
                    {DECISION_LABEL[decision]}{issue.customer_decision_note ? `: ${issue.customer_decision_note}` : ''}
                    {by(issue.customer_decided_by_name, issue.customer_decided_at)}
                    {issue.concession_until && <div className="text-[11px] text-slate-400">Concession until {formatCalendarDate(issue.concession_until)}</div>}
                  </>
                ) : <span className="text-slate-400">Sales records the customer's decision.</span>}
              </Fact>
            )}
            <Fact label="Extra cost">
              <CostLine issue={issue} canSeeCosts={!!viewer.canSeeCosts} />
              {issue.fix_quoted_at && (
                <div data-testid={`issue-fix-quoted-${issue.id}`} className="text-[11px] text-slate-400">
                  Fix quoted to the customer{by(issue.fix_quoted_by_name, issue.fix_quoted_at)}
                </div>
              )}
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
                canAdd={acts.includes('add_action')} departments={departments} addRequest={addRequest} />
            </div>
          )}

          <IssueDropzone changeId={changeId} issue={issue} viewer={viewer} canAttach={open && (acts.includes('attach') || acts.length > 0 || fourEyes)}
            onUploaded={() => qc.invalidateQueries({ queryKey: validationIssuesKey(changeId) })} />

          <EscalationHistory changeId={changeId} issue={issue} canEscalate={open && acts.includes('escalate')}
            canDeescalate={open && extra.includes('deescalate')} />

          {(secondary.length > 0 || canEdit || (canQuote && !!primary) || canLateCost) && (
            <div className="flex flex-wrap items-center gap-3 border-t border-slate-800 pt-2">
              <span className="text-[11px] text-slate-400">Also:</span>
              {secondary.map((a) => (
                <button key={a} type="button" data-testid={`issue-act-${a}-${issue.id}`} onClick={() => run(a)}
                  className="text-[11px] text-sky-300 hover:text-sky-200">{ACT_LABEL[a]}</button>
              ))}
              {canQuote && !!primary && (
                <button type="button" data-testid={`issue-act-quote_fix-${issue.id}`} onClick={() => setActive('quote_fix')}
                  className="text-[11px] text-sky-300 hover:text-sky-200">Quote the fix</button>
              )}
              {canLateCost && (
                <button type="button" data-testid={`issue-act-late-cost-${issue.id}`} onClick={() => setActive('cost')}
                  className="text-[11px] text-sky-300 hover:text-sky-200">{costSet ? 'Correct the cost' : 'Record a late cost'}</button>
              )}
              {canEdit && (
                <button type="button" data-testid={`issue-act-edit-${issue.id}`} onClick={() => setActive('edit')}
                  className="text-[11px] text-sky-300 hover:text-sky-200">Edit issue</button>
              )}
            </div>
          )}
        </div>
      )}

      <RouteDialog open={active === 'route'} changeId={changeId} changeStatus={changeStatus} issue={issue}
        departments={departments} onClose={() => setActive(null)} />
    </article>
  )
}
