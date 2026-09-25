import type { ChangeDetail, ChangeStatus, Gate, GateKey, MyAction } from '../../types/change'
import { STATUS_LABELS, STATUS_PILL, OFF_PATH_STATUSES, GATE_TARGET_STATUS, DECIDED_BY_MEETING, changeTabLabel, nextStatusesFor } from '../../lib/changeStatus'
import { t } from '../../i18n/cmLabels'
import { DeadlineEditor } from './DeadlineEditor'
import { QuotedFactChip } from './DeadlineChip'
import { StageResponsibleBadge } from './StageResponsibleBadge'
import type { WaitState } from '../../lib/waitStates'
import { formatDate } from '../../lib/format'
import { isIssueActionKind, issueTabFor } from '../../lib/issueTabs'

interface Props {
  change: ChangeDetail
  gates: Gate[]
  pendingDeviations: number
  impl?: { ready_to_go: boolean } | undefined
  onAdvance: (to: string) => void
  advancing: boolean
  /** Called with the gate's key when the user clicks a gate row — the page
      jumps to where the gate is decided (D1 tab). */
  onResolveGate?: (gateKey: GateKey) => void
  /** Called when the user clicks the impact-confirmation blocker row — the
      page jumps to the Impacted tab so it can be resolved in place. */
  onShowImpact?: () => void
  /** Task 19: the current user's open actions on this change (GET
      /my-actions). Renders as the topmost "Your actions" card when non-empty;
      hidden entirely otherwise. */
  actions?: MyAction[]
  /** Called with an action's target_tab when its button is clicked — the
      page jumps to where the action is performed. */
  onAction?: (targetTab: string, issueId?: number) => void
  /** F11: whether the current viewer can see the D1/Audit governance tabs.
      Gate rows jump there via onResolveGate — for viewers who can't see those
      tabs the row must not offer a dead-end jump affordance. Defaults to
      true so existing callers that don't pass it keep prior behavior. */
  canSeeGovernance?: boolean
  /** What the change is waiting on (resolveWaitStates). Listed under "Blocked
      by" — the one place a viewer looks to see why nothing is moving. */
  waits?: WaitState[]
  /** Called with a wait's tab when its row is clicked. */
  onGo?: (tab: string, issueId?: number) => void
  /**
   * Who may take a next step: null when the viewer may, otherwise the words
   * for the tooltip ("Needs Sales"). Keys are the step keys of nextStepFor
   * (`offer`, `answer`, `signoff`, `validate-timing`) or `to:<status>`.
   * Absent: everything is allowed (the backend still decides).
   */
  needs?: (step: string) => string | null
}

/** One next step: a place to go and do the work, or a status to move to. */
export type NextStep =
  | { kind: 'go'; key: string; label: string; tab: string }
  | { kind: 'advance'; to: ChangeStatus; label?: string; hint?: string }

/**
 * What the cockpit offers as the next step. Transitions that a dedicated act
 * drives (sending the offer moves quoting to quoted, the customer's answer and
 * the sign-offs gate the approval, "Timing validated" gates implementation)
 * are not raw buttons: the step points at where that act is done.
 */
export function nextStepFor(change: Pick<ChangeDetail, 'status' | 'customer_relevant' | 'customer_response'
  | 'pm_signed_by' | 'quality_signed_by' | 'timing_validated_at' | 'internal_approved_at'>
  & Partial<Pick<ChangeDetail, 'origin' | 'info_sent_at' | 'plan_published_at'>>): NextStep[] {
  const s = change.status
  // Mother plant (spec §14): scoping informs the team, then goes straight to
  // approved; the validated timing is told to the mother plant, not published.
  if (change.origin === 'mother_plant') {
    if (s === 'scoping') {
      return change.info_sent_at
        ? [{ kind: 'advance', to: 'approved' }]
        : [{ kind: 'go', key: 'info-send', label: 'Send information to the team', tab: 'mother' }]
    }
    if (s === 'approved' && change.timing_validated_at && !change.plan_published_at) {
      return [
        { kind: 'go', key: 'inform-mother', label: 'Inform the mother plant', tab: 'timing' },
        { kind: 'advance', to: 'in_implementation', label: t('cockpit.startImplementation') },
      ]
    }
  }
  if (s === 'costing') {
    // An internal change needs its costs approved (Approval tab) before it can
    // advance; a customer-relevant one moves straight to quoting.
    if (!change.customer_relevant && !change.internal_approved_at) {
      return [{ kind: 'go', key: 'internal-approval', label: t('internal.approve'), tab: 'offer' }]
    }
    return [{ kind: 'advance', to: change.customer_relevant ? 'quoting' : 'approved' }]
  }
  if (s === 'quoting') return [{ kind: 'go', key: 'offer', label: 'Build and send the offer', tab: 'offer' }]
  if (s === 'quoted') {
    if (change.customer_response === 'declined') return [{ kind: 'advance', to: 'rejected' }]
    if (change.customer_response !== 'accepted') {
      return [{ kind: 'go', key: 'answer', label: 'Record the customer answer', tab: 'offer' }]
    }
    if (!change.pm_signed_by || !change.quality_signed_by) {
      return [{ kind: 'go', key: 'signoff', label: 'Sign off (PM and Quality)', tab: 'offer' }]
    }
    return [{ kind: 'advance', to: 'approved' }]
  }
  if (s === 'approved' && !change.timing_validated_at) {
    // Timing validation gates implementation, but only softly on the backend:
    // offer "Start implementation" too so a refusal surfaces the deviation
    // banner (propose a deviation, then retry) instead of a dead end.
    return [
      { kind: 'go', key: 'validate-timing', label: 'Validate the timing', tab: 'timing' },
      {
        kind: 'advance', to: 'in_implementation',
        label: t('cockpit.startImplementation'), hint: t('cockpit.startImplementationHint'),
      },
    ]
  }
  return nextStatusesFor(s, change.origin).map((to) => ({ kind: 'advance', to }))
}

/** "Decide 1 plan deviation(s)" reads "Decide 1 plan deviation"; 2 get their s. */
export const pluralizeLabel = (label: string): string =>
  label.replace(/\b(\d+)(\s+[^()\d]*?)\(s\)/g, (_m, n: string, word: string) => `${n}${word}${n === '1' ? '' : 's'}`)

export default function CockpitSummary({ change, gates, pendingDeviations, impl, onAdvance, advancing, onResolveGate, onShowImpact, actions = [], onAction, canSeeGovernance = true, waits = [], onGo, needs = () => null }: Props) {
  const motherPlant = change.origin === 'mother_plant'
  const next = nextStatusesFor(change.status, change.origin).filter((s) =>
    // Out of costing a customer change goes to Sales' quote creation; an
    // internal one is approved outright and never sees either quoting step.
    change.status !== 'costing'
      ? true
      : (change.customer_relevant
        ? s !== 'approved' && s !== 'quoted'
        : s !== 'quoted' && s !== 'quoting'))
  const openGates = gates.filter((g) => g.decision !== 'yes')
  // A gate only blocks when it guards a transition that's currently available —
  // gates seeded 'na' but guarding a later transition are just "outstanding later".
  const blockingGates = openGates.filter((g) => next.includes(GATE_TARGET_STATUS[g.gate_key]))
  const laterGates = openGates.filter((g) => !next.includes(GATE_TARGET_STATUS[g.gate_key]))
  const overdue = change.assessments.filter((a) => a.overdue).length
  // Blocks two transitions on the same signal: entering assessment (from scoping,
  // hard-gated) and kickoff (from approved, soft-guarded). Only meaningful once
  // there is an impacted set to lock.
  const impactUnconfirmed = !change.impact_confirmed_at
    && (change.impacted_items?.length ?? 0) > 0
    && (change.status === 'scoping' || change.status === 'approved')
  // Kickoff (captured -> scoping) needs a description, something attached, and —
  // for customer work — the quote-by date. The gate is soft on the backend, so
  // this warns and names what is missing rather than blocking the button.
  const kickoffMissing: string[] = change.status !== 'captured' ? [] : [
    ...(change.description?.trim() ? [] : [t('kickoff.description')]),
    ...((change.attachments?.length ?? 0) > 0 ? [] : [t('kickoff.attachment')]),
    ...(change.customer_relevant && !change.required_by_date ? [t('deadline.quote')] : []),
  ]
  // Held departments, open assessments, customer questions, … arrive as waits.
  const blockers = blockingGates.length + (pendingDeviations > 0 ? 1 : 0)
    + (overdue > 0 ? 1 : 0) + (impactUnconfirmed ? 1 : 0) + waits.length
  const steps = nextStepFor(change)
  const offPath = OFF_PATH_STATUSES.includes(change.status)

  // Same names as the tab bar.
  // Old names (commercial, implementation) resolve to the tab for the stage.
  const tabName = (tb: string) => changeTabLabel(tb, change.customer_relevant, change.status)

  const gateRow = (g: Gate, blocking: boolean) => {
    const label = (
      <>
        {blocking && '⚠ '}{t('cockpit.gate')} {t('gate.' + g.gate_key)}:{' '}
        <span className="uppercase">{g.decision}</span>
      </>
    )
    return (
      <li key={g.gate_key} className={blocking ? 'text-amber-300' : 'text-slate-400'}>
        {onResolveGate && canSeeGovernance ? (
          <button type="button"
            className="text-left hover:underline decoration-dotted underline-offset-2"
            onClick={() => onResolveGate(g.gate_key)}
            title={t('cockpit.resolveGate')}>
            {label} <span className="text-xs opacity-70">→ D1</span>
          </button>
        ) : label}
      </li>
    )
  }

  return (
    <div className="my-4">
      {actions.length > 0 && (
        <div className="bg-sky-950 border border-sky-700 rounded-lg p-4 mb-3">
          <h3 className="text-xs uppercase tracking-wide text-sky-300 mb-2">{t('actions.title')}</h3>
          <div className="flex flex-wrap gap-2">
            {actions.map((a, i) => (
              <button
                key={`${a.kind}-${a.assessment_id ?? a.task_id ?? a.deviation_id ?? a.gate_key ?? a.escalation_id ?? a.issue_id ?? i}`}
                type="button"
                data-testid={a.issue_id != null ? `action-${a.kind}-${a.issue_id}` : undefined}
                className="bg-sky-600 hover:bg-sky-500 text-white font-medium px-3 py-1.5 rounded-lg text-sm"
                // An issue act opens the tab that shows the issues now (Timing
                // during a loop back), whatever tab the server named.
                onClick={() => (isIssueActionKind(a.kind)
                  ? onAction?.(issueTabFor(change.status), a.issue_id ?? undefined)
                  : onAction?.(a.target_tab))}>
                {pluralizeLabel(a.label)}
              </button>
            ))}
          </div>
        </div>
      )}
      <div className="grid md:grid-cols-3 gap-3">
      <div className="bg-slate-800 rounded-lg border border-slate-700 p-4">
        <h3 className="text-xs uppercase tracking-wide text-slate-500 mb-2">{t('cockpit.where')}</h3>
        <span className={`px-2.5 py-1 rounded-full text-sm font-semibold ${STATUS_PILL[change.status]}`}>
          {STATUS_LABELS[change.status]}
        </span>
        {' '}
        <StageResponsibleBadge status={change.status} />
        {' '}
        {/* Phase-aware: release deadline once active, otherwise the frozen
            quote verdict, otherwise the quote deadline for customer work. */}
        {change.active_deadline === 'release' ? (
          <DeadlineEditor change={change} kind="release" />
        ) : change.quoted_on_time !== null ? (
          <QuotedFactChip change={change} />
        ) : change.customer_relevant ? (
          <DeadlineEditor change={change} kind="quote" />
        ) : motherPlant && change.mother_plant_sop ? (
          // Until approval makes it the release deadline, the SOP is a fact.
          <span data-testid="mother-plant-sop"
            className="inline-flex items-center rounded-full border border-purple-700/60 bg-purple-950/40 px-2 py-0.5 text-xs text-purple-200">
            SOP {formatDate(change.mother_plant_sop)}
          </span>
        ) : null}
        {motherPlant && (
          <p data-testid="mother-plant-origin" className="mt-2 text-xs text-purple-300">
            From the mother plant: {change.mother_plant_name ?? '-'}
            {change.mother_plant_ref ? ` · ${change.mother_plant_ref}` : ''}
          </p>
        )}
        <p className="mt-3 text-sm text-slate-300">
          {t('cockpit.lead')}: <span className="text-slate-100">{change.lead_name ?? '-'}</span>
        </p>
        <p className="mt-1 text-xs text-slate-500">
          {formatDate(change.created_at)} → {formatDate(change.updated_at)}
        </p>
      </div>

      <div className="bg-slate-800 rounded-lg border border-slate-700 p-4">
        <h3 className="text-xs uppercase tracking-wide text-slate-500 mb-2">{t('cockpit.blocking')}</h3>
        {blockers === 0 ? (
          <>
            <p className="text-sm text-emerald-400">✓ {t('cockpit.nothingBlocking')}</p>
            {laterGates.length > 0 && (
              <ul className="space-y-1.5 text-sm mt-2">
                {laterGates.map((g) => gateRow(g, false))}
              </ul>
            )}
          </>
        ) : (
          <ul className="space-y-1.5 text-sm">
            {waits.map((w) => (
              <li key={w.key} data-testid={`wait-${w.key}`}
                className={w.level === 3 ? 'text-rose-300 font-medium' : w.info ? 'text-slate-300' : 'text-amber-300'}>
                {w.tab && onGo ? (
                  <button type="button"
                    className="text-left hover:underline decoration-dotted underline-offset-2"
                    onClick={() => (w.issueId != null ? onGo(w.tab!, w.issueId) : onGo(w.tab!))}>
                    {w.info ? 'ℹ' : '⏳'} {w.text} <span className="text-xs opacity-70">→ {tabName(w.tab)}</span>
                  </button>
                ) : <>{w.info ? 'ℹ' : '⏳'} {w.text}</>}
              </li>
            ))}
            {blockingGates.map((g) => gateRow(g, true))}
            {pendingDeviations > 0 && (
              <li className="text-amber-300">⚠ {t('cockpit.pendingDeviations')}: {pendingDeviations}</li>
            )}
            {overdue > 0 && (
              <li className="text-red-400">⚠ {t('cockpit.overdueAssessments')}: {overdue}</li>
            )}
            {impactUnconfirmed && (
              <li className="text-amber-300">
                {onShowImpact ? (
                  <button type="button"
                    className="text-left hover:underline decoration-dotted underline-offset-2"
                    onClick={onShowImpact}>
                    ⚠ {t('impact.pending')} <span className="text-xs opacity-70">→ {t('impact.title')}</span>
                  </button>
                ) : <>⚠ {t('impact.pending')}</>}
              </li>
            )}
            {laterGates.map((g) => gateRow(g, false))}
          </ul>
        )}
      </div>

      <div className="bg-slate-800 rounded-lg border border-slate-700 p-4">
        <h3 className="text-xs uppercase tracking-wide text-slate-500 mb-2">{t('cockpit.next')}</h3>
        {impl?.ready_to_go && (
          <span className="inline-block mb-2 px-2.5 py-1 rounded-full text-xs font-semibold bg-emerald-900 text-emerald-200">
            ✓ {t('impl.readyToGo')}
          </span>
        )}
        {kickoffMissing.length > 0 && (
          <div data-testid="kickoff-hint"
            className="mb-2 rounded-lg border border-amber-700/60 bg-amber-950/30 p-2 text-xs">
            <p className="text-amber-200">⚠ {t('kickoff.title')}</p>
            <ul className="mt-1 list-disc list-inside text-amber-100/80">
              {kickoffMissing.map((m) => <li key={m}>{m}</li>)}
            </ul>
            <p className="mt-1 text-slate-400">{t('kickoff.soft')}</p>
          </div>
        )}
        {change.status === 'captured' && kickoffMissing.length === 0 && (
          <p data-testid="kickoff-ready" className="mb-2 text-xs text-emerald-400">
            ✓ {t('kickoff.ready')}
          </p>
        )}
        {DECIDED_BY_MEETING.includes(change.status) && !motherPlant ? (
          // The decision lives in the meeting record, not on a button here.
          <button
            className="text-left text-sm text-slate-300 hover:text-slate-100 underline decoration-dotted underline-offset-2"
            onClick={() => onAction?.('scoping')}>
            {t('cockpit.decideInMeeting')}
          </button>
        ) : offPath || steps.length === 0 ? (
          <p className="text-sm text-slate-400">{STATUS_LABELS[change.status]}</p>
        ) : (
          <div className="flex flex-col gap-2">
            {steps.map((st, i) => {
              const key = st.kind === 'go' ? st.key : `to:${st.to}`
              const denied = needs(key)
              const cls = i === 0
                ? 'bg-sky-600 hover:bg-sky-500 text-white font-semibold px-4 py-2 rounded-lg text-sm disabled:opacity-50 disabled:cursor-not-allowed disabled:hover:bg-sky-600'
                : 'border border-slate-600 text-slate-300 hover:bg-slate-700 px-4 py-2 rounded-lg text-sm disabled:opacity-50 disabled:cursor-not-allowed'
              return (
                <button key={key} type="button" data-testid={`next-${key.replace(':', '-')}`}
                  className={cls}
                  disabled={!!denied || (st.kind === 'advance' && advancing)}
                  title={denied ?? (st.kind === 'advance' ? st.hint : undefined) ?? undefined}
                  onClick={() => (st.kind === 'go' ? (onGo ?? onAction)?.(st.tab) : onAdvance(st.to))}>
                  {st.kind === 'go' ? st.label : (st.label ?? `→ ${STATUS_LABELS[st.to]}`)}
                </button>
              )
            })}
            {(() => {
              const why = steps.map((st) => needs(st.kind === 'go' ? st.key : `to:${st.to}`)).find(Boolean)
              return why ? <p data-testid="next-needs" className="text-xs text-slate-500">{why}</p> : null
            })()}
          </div>
        )}
      </div>
      </div>
    </div>
  )
}
