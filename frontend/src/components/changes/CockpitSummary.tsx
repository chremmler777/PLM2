import type { ReactNode } from 'react'
import type { ChangeDetail, ChangeStatus, Gate, GateKey, MyAction, StageAssessment } from '../../types/change'
import { hasEnded, endLabel } from '../../lib/transitionRights'
import { STATUS_LABELS, STATUS_PILL, OFF_PATH_STATUSES, GATE_TARGET_STATUS, DECIDED_BY_MEETING, changeTabLabel, nextStatusesFor } from '../../lib/changeStatus'
import { t } from '../../i18n/cmLabels'
import { DeadlineEditor } from './DeadlineEditor'
import { QuotedFactChip } from './DeadlineChip'
import { StageResponsibleBadge } from './StageResponsibleBadge'
import type { WaitState } from '../../lib/waitStates'
import { formatDate } from '../../lib/format'
import { isIssueActionKind, issueTabFor } from '../../lib/issueTabs'
import { plantText } from '../../lib/plantName'

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
  /** May the viewer record the scoping meeting; others get a pointer, not an instruction. */
  canRecordMeeting?: boolean
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
  /** The assessment round (stage-state, or derived): decides the next step
      while the change is in assessment. */
  assessment?: StageAssessment | null
  /** Whether the viewer may move the change to a status (transition rights).
      A step the viewer may not take is not offered at all. */
  may?: (to: string) => boolean
  /** Why a hidden step is hidden, shown once under the next step. */
  mayNotText?: string
  /** A non-transition step (override, send letter) was clicked. */
  onStepAction?: (key: string) => void
  /** The lead line of the Status card (the lead picker when allowed). */
  leadSlot?: ReactNode
}

/** One next step: a place to go and do the work, or a status to move to. */
export type NextStep =
  | { kind: 'go'; key: string; label: string; tab: string }
  | { kind: 'advance'; to: ChangeStatus; label?: string; hint?: string }
  /** Not a button: what the step is waiting for (no primary while waiting). */
  | { kind: 'wait'; key: string; text: string }
  /** A button that opens a dialog of its own (override with a reason). */
  | { kind: 'action'; key: string; label: string; hint?: string }

/**
 * What the cockpit offers as the next step. Transitions that a dedicated act
 * drives (sending the offer moves quoting to quoted, the customer's answer and
 * the sign-offs gate the approval, "Timing validated" gates implementation)
 * are not raw buttons: the step points at where that act is done.
 */
export function nextStepFor(change: Pick<ChangeDetail, 'status' | 'customer_relevant' | 'customer_response'
  | 'pm_signed_by' | 'quality_signed_by' | 'timing_validated_at' | 'internal_approved_at'>
  & Partial<Pick<ChangeDetail, 'origin' | 'info_sent_at' | 'plan_published_at' | 'rejection_sent_at'
    | 'costing_pending_department_ids' | 'impact_confirmed_at' | 'mother_plant_name'>>,
  assessment?: StageAssessment | null): NextStep[] {
  const s = change.status
  // The assessment round (spec §16 P1 6/8): no primary while departments are
  // still answering; a not-feasible answer offers the three ways out; a full
  // round closes into costing.
  if (s === 'in_assessment' && assessment) {
    const n = assessment.waiting_on.length
    if (assessment.not_feasible.length > 0 && assessment.override !== 'approved') {
      // Three equal ways out, none of them pre-chosen: no primary button.
      const who = assessment.not_feasible.map((d) => d.department_name ?? `#${d.department_id}`).join(', ')
      return [
        { kind: 'wait', key: 'not-feasible', text: t('next.notFeasible').replace('{x}', who) },
        ...(n > 0 ? [{ kind: 'wait' as const, key: 'waiting', text: t('next.waitingOn').replace('{n}', String(n)).replace('{s}', n === 1 ? '' : 's') }] : []),
        { kind: 'advance', to: 'rejected', label: t('next.reject') },
        { kind: 'advance', to: 'scoping', label: t('next.backToScoping') },
        assessment.override === 'pending'
          ? { kind: 'wait', key: 'override-pending', text: t('next.overridePending') }
          : { kind: 'action', key: 'override-costing', label: t('next.override'), hint: t('next.overrideHint') },
      ]
    }
    if (n > 0 || !assessment.all_submitted) {
      return [
        { kind: 'wait', key: 'waiting', text: t('next.waitingOn').replace('{n}', String(n)).replace('{s}', n === 1 ? '' : 's') },
        { kind: 'advance', to: 'rejected', label: t('next.reject') },
      ]
    }
    if (assessment.routing_deviation_pending) {
      return [
        { kind: 'wait', key: 'routing', text: t('next.waitingRouting') },
        { kind: 'advance', to: 'rejected', label: t('next.reject') },
      ]
    }
    return [
      { kind: 'advance', to: 'costing', label: t('next.closeAssessment') },
      { kind: 'advance', to: 'rejected', label: t('next.reject') },
    ]
  }
  // Capture: kick off scoping, or reject outright (the customer withdrew
  // before anyone met). Sales, PM, the lead and admin; `may` hides it from
  // everyone else.
  // Engineering review (spec §17): Development locks the impact, the
  // departments answer; the answers release it (or Development escalates).
  if (change.origin === 'engineering_review') {
    if (s === 'scoping') {
      return change.impact_confirmed_at
        ? [{ kind: 'go', key: 'review', label: 'Answer the review', tab: 'review' }]
        : [{ kind: 'go', key: 'lock-impact', label: 'Lock the impacted set (Development)', tab: 'impacted' }]
    }
    if (s === 'captured') return [{ kind: 'advance', to: 'scoping' }]
    return []
  }
  if (s === 'captured' && change.origin !== 'mother_plant') {
    return [
      { kind: 'advance', to: 'scoping' },
      { kind: 'advance', to: 'rejected', label: t('next.reject') },
    ]
  }
  // A rejected customer change still owes the customer its letter.
  if (s === 'rejected' && change.customer_relevant && !change.rejection_sent_at) {
    return [{ kind: 'go', key: 'send-rejection', label: t('next.sendRejection'), tab: 'scoping' }]
  }
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
        { kind: 'go', key: 'inform-mother', label: plantText('mp.inform', change.mother_plant_name), tab: 'timing' },
        { kind: 'advance', to: 'in_implementation', label: t('cockpit.startImplementation') },
      ]
    }
  }
  if (s === 'costing') {
    // Departments still owe their cost input: that is the step, no primary
    // "-> Quote creation" ahead of it (the move stays offered, secondary).
    const owed = change.costing_pending_department_ids?.length ?? 0
    if (owed > 0) {
      return [
        { kind: 'wait', key: 'costing-input', text: t('next.waitingCostInput')
          .replace('{n}', String(owed)).replace('{s}', owed === 1 ? '' : 's') },
        ...(!change.customer_relevant && !change.internal_approved_at ? []
          : [{ kind: 'advance' as const, to: (change.customer_relevant ? 'quoting' : 'approved') as ChangeStatus }]),
      ]
    }
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

export default function CockpitSummary({ change, gates, pendingDeviations, impl, onAdvance, advancing, onResolveGate, onShowImpact, actions = [], onAction, canSeeGovernance = true, canRecordMeeting = true, waits = [], onGo, needs = () => null, assessment = null, may = () => true, mayNotText, onStepAction, leadSlot }: Props) {
  const motherPlant = change.origin === 'mother_plant'
  const next = nextStatusesFor(change.status, change.origin).filter((s) =>
    // Out of costing a customer change goes to Sales' quote creation; an
    // internal one is approved outright and never sees either quoting step.
    change.status !== 'costing'
      ? true
      : (change.customer_relevant
        ? s !== 'approved' && s !== 'quoted'
        : s !== 'quoted' && s !== 'quoting'))
  const ended = hasEnded(change)
  const openGates = gates.filter((g) => g.decision !== 'yes')
  // A gate only blocks when it guards a transition that's currently available —
  // gates seeded 'na' but guarding a later transition are just "outstanding later".
  const blockingGates = openGates.filter((g) => next.includes(GATE_TARGET_STATUS[g.gate_key]))
  // A gate nobody has set ("NA") guarding a later step is noise, not news:
  // only a later gate that was actually answered No is worth a line.
  const laterGates = openGates.filter((g) => !next.includes(GATE_TARGET_STATUS[g.gate_key])
    && g.decision === 'no')
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
    // Kickoff wants a lead (soft): scoping is the lead's to run.
    ...(change.lead_id == null ? [t('cockpit.noLead')] : []),
  ]
  // Held departments, open assessments, customer questions, … arrive as waits.
  const blockers = blockingGates.length + (pendingDeviations > 0 ? 1 : 0)
    + (overdue > 0 ? 1 : 0) + (impactUnconfirmed ? 1 : 0) + waits.length
  // Steps the viewer may not take are not offered (spec §16 P1 4).
  const allSteps = nextStepFor(change, assessment)
  // A not-feasible answer is the lead's and PM's call (reject, back to
  // scoping, or a deviation to costing). Anyone else reads who decides
  // instead of "choose how to go on" with nothing to choose.
  const decidesNotFeasible = may('rejected') || may('scoping')
  const notFeasibleWho = (assessment?.not_feasible ?? [])
    .map((d) => d.department_name ?? `#${d.department_id}`).join(', ')
  const steps = allSteps
    .filter((st) => st.kind !== 'advance' || may(st.to))
    .filter((st) => decidesNotFeasible || !(st.kind === 'action' && st.key === 'override-costing'))
    .map((st) => (!decidesNotFeasible && st.kind === 'wait' && st.key === 'not-feasible'
      ? { ...st, text: t('next.notFeasibleNotYours').replace('{x}', notFeasibleWho) } : st))
  const hiddenSteps = allSteps.length - steps.length
  const buttons = steps.filter((st): st is Exclude<NextStep, { kind: 'wait' }> => st.kind !== 'wait')
  const offPath = OFF_PATH_STATUSES.includes(change.status)

  // Same names as the tab bar.
  // Old names (commercial, implementation) resolve to the tab for the stage.
  const tabName = (tb: string) => changeTabLabel(tb, change.customer_relevant, change.status, change.mother_plant_name)

  const gateRow = (g: Gate, blocking: boolean) => {
    // In words: "Release gate not decided yet", "Release gate answered No".
    const label = (
      <>
        {blocking && '⚠ '}{t('gate.' + g.gate_key)} {t('cockpit.gateWord')}:{' '}
        {g.decision === 'no' ? t('cockpit.gateNo') : t('cockpit.gateOpen')}
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

  // Project team (spec §18): items where the viewer is only backup (the
  // project has another responsible for the role) are listed apart, muted,
  // with the main's name; they stay actionable.
  const mainActions = actions.filter((a) => a.role !== 'backup')
  const backupActions = actions.filter((a) => a.role === 'backup')
  const actionKey = (a: MyAction, i: number) =>
    `${a.kind}-${a.assessment_id ?? a.task_id ?? a.deviation_id ?? a.gate_key ?? a.escalation_id ?? a.issue_id ?? i}`
  // An issue act opens the tab that shows the issues now (Timing during a
  // loop back), whatever tab the server named.
  const runAction = (a: MyAction) => (isIssueActionKind(a.kind)
    ? onAction?.(issueTabFor(change.status), a.issue_id ?? undefined)
    : onAction?.(a.target_tab))
  const backupGroup = (
    <div data-testid="backup-actions">
      <h3 className="text-xs uppercase tracking-wide text-slate-400 mb-2">{t('actions.asBackup')}</h3>
      <div className="flex flex-wrap gap-2">
        {backupActions.map((a, i) => (
          <button
            key={actionKey(a, i)}
            type="button"
            title={t('team.backupHint')}
            className="border border-slate-600 text-slate-300 hover:bg-slate-700 px-3 py-1.5 rounded-lg text-sm text-left"
            onClick={() => runAction(a)}>
            {pluralizeLabel(a.label)}
            {a.main_name && (
              <span className="block text-xs text-slate-400">{t('team.main').replace('{x}', a.main_name)}</span>
            )}
          </button>
        ))}
      </div>
    </div>
  )

  return (
    <div className="my-4">
      {mainActions.length > 0 && (
        <div data-testid="your-actions" className="bg-sky-950 border border-sky-700 rounded-lg p-4 mb-3">
          <h3 className="text-xs uppercase tracking-wide text-sky-300 mb-2">{t('actions.title')}</h3>
          <div className="flex flex-wrap gap-2">
            {mainActions.map((a, i) => (
              <button
                key={actionKey(a, i)}
                type="button"
                data-testid={a.issue_id != null ? `action-${a.kind}-${a.issue_id}` : undefined}
                className="bg-sky-600 hover:bg-sky-500 text-white font-medium px-3 py-1.5 rounded-lg text-sm"
                onClick={() => runAction(a)}>
                {pluralizeLabel(a.label)}
              </button>
            ))}
          </div>
          {backupActions.length > 0 && <div className="mt-3 pt-3 border-t border-sky-900">{backupGroup}</div>}
        </div>
      )}
      {mainActions.length === 0 && backupActions.length > 0 && (
        <div className="bg-slate-800/60 border border-slate-700 rounded-lg p-4 mb-3">{backupGroup}</div>
      )}
      <div className="grid md:grid-cols-3 gap-3">
      <div className="bg-slate-800 rounded-lg border border-slate-700 p-4">
        <h3 className="text-xs uppercase tracking-wide text-slate-500 mb-2">{t('cockpit.where')}</h3>
        <span data-testid="status-pill" className={`px-2.5 py-1 rounded-full text-sm font-semibold ${
          endLabel(change) ? 'bg-red-900 text-red-100' : STATUS_PILL[change.status]}`}>
          {endLabel(change) ?? STATUS_LABELS[change.status]}
        </span>
        {' '}
        <StageResponsibleBadge status={change.status} origin={change.origin} />
        {' '}
        {/* Phase-aware: release deadline once active, otherwise the frozen
            quote verdict, otherwise the quote deadline for customer work. */}
        {ended ? null : change.active_deadline === 'release' ? (
          <DeadlineEditor change={change} kind="release" />
        ) : change.quoted_on_time !== null ? (
          <QuotedFactChip change={change} />
        ) : change.customer_relevant ? (
          <DeadlineEditor change={change} kind="quote" />
        ) : motherPlant && change.mother_plant_sop ? (
          // Until approval makes it the release deadline, the SOP is a fact.
          <span data-testid="mother-plant-sop"
            className="inline-flex items-center rounded-full border border-purple-700/60 bg-purple-950/40 px-2 py-0.5 text-xs text-purple-200">
            {plantText('mp.sop', change.mother_plant_name)} {formatDate(change.mother_plant_sop)}
          </span>
        ) : null}
        {motherPlant && (
          <p data-testid="mother-plant-origin" className="mt-2 text-xs text-purple-300">
            {plantText('mp.from', change.mother_plant_name)}
            {change.mother_plant_ref ? ` · ${change.mother_plant_ref}` : ''}
          </p>
        )}
        <div className="mt-3 text-sm text-slate-300">
          {leadSlot ?? (
            <p>{t('cockpit.lead')}: <span className="text-slate-100">{change.lead_name ?? t('cockpit.noLead')}</span></p>
          )}
        </div>
        <p data-testid="status-dates" className="mt-1 text-xs text-slate-500">
          {t('cockpit.created')} {formatDate(change.created_at)} · {t('cockpit.updated')} {formatDate(change.updated_at)}
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
                    {w.info ? 'ℹ' : '⏳'} {w.text} <span className="text-xs opacity-70 whitespace-nowrap">→ {tabName(w.tab)}</span>
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
            <p className="mt-1 text-slate-400">{t(motherPlant ? 'kickoff.hard' : 'kickoff.soft')}</p>
          </div>
        )}
        {change.status === 'captured' && kickoffMissing.length === 0 && (
          <p data-testid="kickoff-ready" className="mb-2 text-xs text-emerald-400">
            ✓ {t('kickoff.ready')}
          </p>
        )}
        {DECIDED_BY_MEETING.includes(change.status) && !motherPlant && change.origin !== 'engineering_review' ? (
          // The decision lives in the meeting record, not on a button here.
          <button
            className="text-left text-sm text-slate-300 hover:text-slate-100 underline decoration-dotted underline-offset-2"
            onClick={() => onAction?.('scoping')}>
            {canRecordMeeting ? t('cockpit.decideInMeeting') : t('cockpit.meetingDecides')}
          </button>
        ) : (offPath && steps.length === 0) || allSteps.length === 0 ? (
          <p className="text-sm text-slate-400">
            {ended ? t('next.ended') : STATUS_LABELS[change.status]}
          </p>
        ) : (
          <div className="flex flex-col gap-2">
            {steps.filter((st) => st.kind === 'wait').map((st) => (
              <p key={st.key} data-testid={`next-wait-${st.key}`}
                className="rounded-lg border border-slate-700 bg-slate-900/40 px-3 py-2 text-sm text-slate-300">
                ⏳ {st.kind === 'wait' ? st.text : ''}
              </p>
            ))}
            {buttons.map((st) => {
              const key = st.kind === 'go' || st.kind === 'action' ? st.key : `to:${st.to}`
              const denied = st.kind === 'action' ? null : needs(key)
              // While the step waits there is no primary button at all.
              const primary = steps[0] === st
              const cls = primary
                ? 'bg-sky-600 hover:bg-sky-500 text-white font-semibold px-4 py-2 rounded-lg text-sm disabled:opacity-50 disabled:cursor-not-allowed disabled:hover:bg-sky-600'
                : 'border border-slate-600 text-slate-300 hover:bg-slate-700 px-4 py-2 rounded-lg text-sm disabled:opacity-50 disabled:cursor-not-allowed'
              return (
                <button key={key} type="button" data-testid={`next-${key.replace(':', '-')}`}
                  className={cls}
                  disabled={!!denied || (st.kind === 'advance' && advancing)}
                  title={denied ?? (st.kind === 'advance' || st.kind === 'action' ? st.hint : undefined) ?? undefined}
                  onClick={() => (st.kind === 'go' ? (onGo ?? onAction)?.(st.tab)
                    : st.kind === 'action' ? onStepAction?.(st.key) : onAdvance(st.to))}>
                  {st.kind === 'go' || st.kind === 'action' ? st.label : (st.label ?? `→ ${STATUS_LABELS[st.to]}`)}
                </button>
              )
            })}
            {(() => {
              const why = buttons.map((st) => (st.kind === 'go' ? needs(st.key)
                : st.kind === 'advance' ? needs(`to:${st.to}`) : null)).find(Boolean)
                ?? (hiddenSteps > 0 && buttons.length === 0 ? mayNotText ?? t('next.notYours') : null)
              return why ? <p data-testid="next-needs" className="text-xs text-slate-500">{why}</p> : null
            })()}
          </div>
        )}
      </div>
      </div>
    </div>
  )
}
