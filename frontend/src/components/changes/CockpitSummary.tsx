import { useId, useRef, useState, type ReactNode } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { AlertTriangle, ArrowRight, Ban, Check, Hourglass, Info, TriangleAlert } from 'lucide-react'
import { changesApi } from '../../api/changes'
import Dialog from '../common/Dialog'
import Button from '../common/Button'
import { toastError } from '../../lib/apiError'
import type { ChangeDetail, ChangeStatus, Gate, GateKey, MyAction, StageAssessment } from '../../types/change'
import { hasEnded, endLabel } from '../../lib/transitionRights'
import { STATUS_LABELS, STATUS_PILL, OFF_PATH_STATUSES, GATE_TARGET_STATUS, DECIDED_BY_MEETING, changeTabLabel, nextStatusesFor, transitionLabel } from '../../lib/changeStatus'
import { btnBase, btnSizes, btnSm, buttonClass, type ButtonSize } from '../common/buttonStyles'
import { t } from '../../i18n/cmLabels'
import { DeadlineEditor } from './DeadlineEditor'
import { QuotedFactChip } from './DeadlineChip'
import { StageResponsibleBadge } from './StageResponsibleBadge'
import type { WaitState } from '../../lib/waitStates'
import { formatCalendarDate, formatDate } from '../../lib/format'
import { isIssueActionKind, issueTabFor } from '../../lib/issueTabs'
import { plantText } from '../../lib/plantName'
import PendingRemovalChip from './PendingRemovalChip'

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
  /** Worth a look before a step, never holding it (e.g. "Close costing" with a
      total of zero): shown as a note beside the step, the button stays live.
      Same keys as `needs`. */
  warns?: (step: string) => string | null
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
  /** A "Decide deviation #n" action or the pending-deviations line was
      clicked: the page opens the decision panel on that deviation. */
  onDecideDeviation?: (deviationId?: number) => void
  /** Target statuses of the change's transition deviations by state. A gate
      is a soft guard on the backend: an approved deviation to its target
      lets the held step through, so the step stays live. */
  deviationTargets?: { approved: string[]; pending: string[] }
  /** "Ask for a deviation" on a gate held step: the page asks for one to
      that status (the gate's key names what holds it). */
  onAskDeviation?: (to: ChangeStatus, gateKey: GateKey) => void
  /** The engineering review's answers (spec §17): the next step waits once
      the viewer's own answer is in. */
  review?: ReviewProgress | null
  /** `compact`: the slim sticky bar on every tab but Overview (status, the
      blockers count, the one next step). Same logic, same source. */
  variant?: 'full' | 'compact'
  /** Compact bar: the blockers count and the actions count lead to Overview. */
  onShowOverview?: () => void
}

/** What the cockpit needs of the engineering review state. */
export interface ReviewProgress {
  open_count: number
  impact_count: number
  escalated?: boolean
  can_escalate?: boolean
  answers?: { answer: string | null; can_answer: boolean }[]
}

/** Your-actions kinds that are the same job as a next step: listed once, as the step. */
const SAME_JOB_AS_STEP: Record<string, string[]> = {
  // create_quote is the task list's name for offer_build (backend
  // STAGE_TASK_EQUIV); either one is the "Build and send the offer" step.
  offer: ['offer_build', 'create_quote'],
  'validate-timing': ['timing_validate'],
  'lock-impact': ['impact_confirm'],
  review: ['review_answer'],
  'send-rejection': ['send_rejection'],
  'info-send': ['info_send'],
  'inform-mother': ['inform_mother_plant'],
  answer: ['customer_response'],
  // Advance steps are keyed "to:<status>": handing over to scoping is the
  // kickoff task.
  'to:scoping': ['kickoff'],
}

/** A gate's state in words, keyed on its decision like the backend's gate_message:
    'no' answered No, 'na' not answered Yes (it is n/a), none not decided yet. */
export const gateStateText = (decision: string | null | undefined): string =>
  t(decision === 'no' ? 'cockpit.gateStateNo' : decision === 'na' ? 'cockpit.gateStateOpen' : 'cockpit.gateStateNone')
const gateRowText = (decision: string | null | undefined): string =>
  t(decision === 'no' ? 'cockpit.gateNo' : decision === 'na' ? 'cockpit.gateOpen' : 'cockpit.gateNone')

/** "1 blocker", "3 blockers". */
const plural = (text: string, n: number) => text.replace('{n}', String(n)).replace('{s}', n === 1 ? '' : 's')

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
  assessment?: StageAssessment | null, review?: ReviewProgress | null): NextStep[] {
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
      if (!change.impact_confirmed_at) {
        return [{ kind: 'go', key: 'lock-impact', label: t('next.lockImpact'), tab: 'impacted' }]
      }
      // Once the viewer's answer is in, the step is waiting, not "answer".
      const mineOpen = !review || (review.answers ?? []).some((a) => a.can_answer && a.answer == null)
      if (mineOpen) return [{ kind: 'go', key: 'review', label: t('next.answerReview'), tab: 'review' }]
      if (review.open_count > 0) {
        return [{ kind: 'wait', key: 'review-answers', text: plural(t('next.waitingReview'), review.open_count) }]
      }
      if (review.impact_count > 0 && !review.escalated) {
        return review.can_escalate
          ? [{ kind: 'go', key: 'review-escalate', label: t('next.reviewImpact'), tab: 'review' }]
          : [{ kind: 'wait', key: 'review-escalate', text: t('next.reviewImpactWait') }]
      }
      return [{ kind: 'wait', key: 'review-done', text: t('next.reviewDone') }]
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

/** Classes of the step buttons: wrap long labels instead of overflowing the card. */
const stepCls = (primary: boolean, size: ButtonSize = 'md') => buttonClass(primary ? 'primary' : 'secondary', size,
  size === 'md' ? 'h-auto min-h-9 whitespace-normal py-2 text-center' : '')
/** The viewer's own actions: an accent, not a second primary. */
const actionCls = `${btnBase} ${btnSizes.md} h-auto min-h-9 whitespace-normal py-1.5 text-left `
  + 'border border-sky-700 bg-sky-900/40 text-sky-100 hover:bg-sky-800/60'
const linkRow = 'inline-flex items-start gap-1.5 text-left hover:underline decoration-dotted underline-offset-2 '
  + 'rounded focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400'
/** Where a row leads, inline after its text so it wraps with it: "-> Release". */
const Where = ({ to }: { to: string }) => (
  <span className="ml-1 inline-flex items-center gap-0.5 whitespace-nowrap align-baseline text-xs opacity-70">
    <ArrowRight aria-hidden="true" size={11} className="self-center" />{to}
  </span>
)

/** One blocker, as the Blocked-by card and the "Resolve first" button both read it. */
interface Blocker { key: string; text: string; go?: () => void }

export default function CockpitSummary({ change, gates, pendingDeviations, impl, onAdvance, advancing, onResolveGate, onShowImpact, actions = [], onAction, canSeeGovernance = true, canRecordMeeting = true, waits = [], onGo, needs = () => null, warns = () => null, assessment = null, may = () => true, mayNotText, onStepAction, leadSlot, onDecideDeviation, deviationTargets, onAskDeviation, review = null, variant = 'full', onShowOverview }: Props) {
  const motherPlant = change.origin === 'mother_plant'
  /** The late flag whose "Take off routing" dialog is open. */
  const [takeOff, setTakeOff] = useState<MyAction | null>(null)
  // A late flag whose row a pending deviation already asks to take off shows
  // that, not a second "Take off routing". Routing is read only when a late
  // flag is there (same cache as the assessment tab).
  const hasLate = actions.some((a) => a.kind === 'late_assessment' && a.department_id != null)
  const { data: routing } = useQuery({
    queryKey: ['change-routing', change.id],
    queryFn: () => changesApi.getRouting(change.id),
    enabled: hasLate,
  })
  const removalPending = (a: MyAction) => routing?.deviation_status === 'pending_approval'
    && (routing.stages ?? []).some((s) => s.departments.some((d) => d.pending_removal
      && (a.assessment_id != null ? d.assessment_id === a.assessment_id
        : d.department_id === a.department_id && (a.stage_order == null || s.stage_order === a.stage_order))))
  const next = nextStatusesFor(change.status, change.origin).filter((s) =>
    // Out of costing a customer change goes to Sales' quote creation; an
    // internal one is approved outright and never sees either quoting step.
    change.status !== 'costing'
      ? true
      : (change.customer_relevant
        ? s !== 'approved' && s !== 'quoted'
        : s !== 'quoted' && s !== 'quoting'))
  const ended = hasEnded(change)
  // The gate is a soft guard (ChangeService._guard): an approved transition
  // deviation to its target lets the step through.
  const deviationCovers = (to: string) => deviationTargets?.approved.includes(to) ?? false
  const deviationAsked = (to: string) => deviationTargets?.pending.includes(to) ?? false
  const openGates = gates.filter((g) => g.decision !== 'yes')
  // A gate only blocks when it guards a transition that's currently available
  // and no approved deviation covers it; gates seeded 'na' but guarding a
  // later transition are just "outstanding later".
  const blockingGates = openGates.filter((g) => next.includes(GATE_TARGET_STATUS[g.gate_key])
    && !deviationCovers(GATE_TARGET_STATUS[g.gate_key]))
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
  // Kickoff (captured -> scoping) needs a description, something attached, and,
  // for customer work, the quote-by date. The gate is soft on the backend, so
  // this warns and names what is missing rather than blocking the button.
  const kickoffMissing: string[] = change.status !== 'captured' ? [] : [
    ...(change.description?.trim() ? [] : [t('kickoff.description')]),
    ...((change.attachments?.length ?? 0) > 0 ? [] : [t('kickoff.attachment')]),
    ...(change.customer_relevant && !change.required_by_date ? [t('deadline.quote')] : []),
    // Kickoff wants a lead (soft): scoping is the lead's to run.
    ...(change.lead_id == null ? [t('cockpit.noLead')] : []),
  ]
  const gateText = (g: Gate) => `${t('gate.' + g.gate_key)} ${t('cockpit.gateWord')}: ${gateRowText(g.decision)}`
  // One list of what holds the change up. The Blocked-by card, the count in
  // the compact bar and the "Resolve first" button all read it, so the next
  // step can never look free while blockers are listed next to it.
  const hardBlockers: Blocker[] = [
    ...waits.filter((w) => !w.info).map((w) => ({
      key: `wait-${w.key}`, text: w.text,
      go: w.tab && onGo ? () => (w.issueId != null ? onGo(w.tab!, w.issueId) : onGo(w.tab!)) : undefined,
    })),
    ...blockingGates.map((g) => ({
      key: `gate-${g.gate_key}`, text: gateText(g),
      go: onResolveGate && canSeeGovernance ? () => onResolveGate(g.gate_key) : undefined,
    })),
    ...(pendingDeviations > 0 ? [{
      key: 'deviations', text: `${t('cockpit.pendingDeviations')}: ${pendingDeviations}`,
      go: onDecideDeviation ? () => onDecideDeviation() : undefined,
    }] : []),
    ...(overdue > 0 ? [{
      key: 'overdue', text: `${t('cockpit.overdueAssessments')}: ${overdue}`,
      go: onGo ? () => onGo('assessments') : undefined,
    }] : []),
    ...(impactUnconfirmed ? [{ key: 'impact', text: t('impact.pending'), go: onShowImpact }] : []),
  ]
  // Held departments, open assessments, customer questions, … arrive as waits;
  // the ones that hold nothing (info) are listed apart and never counted.
  const infoWaits = waits.filter((w) => w.info)
  // Steps the viewer may not take are not offered (spec §16 P1 4).
  const allSteps = nextStepFor(change, assessment, review)
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
  // A status move is not the primary while anything is listed as blocking:
  // the primary becomes "Resolve n blockers first" and leads to the first one.
  // The move stays offered (secondary): the guards are soft, and a refused
  // move offers a deviation.
  const demoted = hardBlockers.length > 0 && steps[0]?.kind === 'advance'
  const lead = hardBlockers.find((b) => b.go) ?? hardBlockers[0]
  const meetingDecides = DECIDED_BY_MEETING.includes(change.status) && !motherPlant
    && change.origin !== 'engineering_review'

  // Same names as the tab bar.
  // Old names (commercial, implementation) resolve to the tab for the stage.
  const tabName = (tb: string) => changeTabLabel(tb, change.customer_relevant, change.status, change.mother_plant_name)

  const gateRow = (g: Gate, blocking: boolean) => {
    // In words: "Release gate not answered Yes (it is n/a)", "Release gate answered No".
    const label = (
      <>
        {blocking && <AlertTriangle aria-hidden="true" size={14} className="mt-0.5 shrink-0" />}
        <span>{gateText(g)}{onResolveGate && canSeeGovernance ? <Where to="D1" /> : null}</span>
      </>
    )
    return (
      <li key={g.gate_key} data-blocking={blocking ? 'true' : undefined}
        className={blocking ? 'text-amber-300' : 'text-slate-400'}>
        {onResolveGate && canSeeGovernance ? (
          <button type="button" className={linkRow}
            onClick={() => onResolveGate(g.gate_key)}
            title={t('cockpit.resolveGate')}>
            {label}
          </button>
        ) : <span className="inline-flex items-start gap-1.5">{label}</span>}
      </li>
    )
  }

  // Project team (spec §18): items where the viewer is only backup (the
  // project has another responsible for the role) are listed apart, muted,
  // with the main's name; they stay actionable. An action that is the same
  // job as a next-step button is listed once, as the step.
  const stepKeys = buttons.map((st) => (st.kind === 'advance' ? `to:${st.to}` : st.key))
  const sameJob = (a: MyAction) => stepKeys.some((k) => (SAME_JOB_AS_STEP[k] ?? []).includes(a.kind))
  const shownActions = actions.filter((a) => !sameJob(a))
  const mainActions = shownActions.filter((a) => a.role !== 'backup')
  const backupActions = shownActions.filter((a) => a.role === 'backup')
  const actionKey = (a: MyAction, i: number) =>
    `${a.kind}-${a.assessment_id ?? a.task_id ?? a.deviation_id ?? a.gate_key ?? a.escalation_id ?? a.issue_id ?? a.department_id ?? a.offer_id ?? i}`
  // An issue act opens the tab that shows the issues now (Timing during a
  // loop back), whatever tab the server named.
  const runAction = (a: MyAction) => (isIssueActionKind(a.kind)
    ? onAction?.(issueTabFor(change.status), a.issue_id ?? undefined)
    // A deviation is decided in its own panel, not just "somewhere on Overview".
    : a.kind === 'deviation_decision' && onDecideDeviation
      ? onDecideDeviation(a.deviation_id ?? undefined)
      : onAction?.(a.target_tab))
  // A gate constrains its target transition hard (backend: no row decided
  // 'yes', no move). A step it holds is not a live button: it is disabled with
  // the gate's reason, and the way to D1 is right under it.
  const gateHolding = (to: ChangeStatus): Gate | undefined =>
    gates.find((g) => GATE_TARGET_STATUS[g.gate_key] === to && g.decision !== 'yes')
  const gateState = (g: Gate) => gateStateText(g.decision)
  const gateWhy = (g: Gate, mine = true) => t(mine ? 'cockpit.gateHolds' : 'cockpit.gateHoldsNotYours')
    .replace('{gate}', t('gate.' + g.gate_key))
    .replace('{state}', gateState(g))

  /** Why a step cannot be taken by this viewer right now, or null. */
  const deniedFor = (st: Exclude<NextStep, { kind: 'wait' }>): string | null => {
    const key = st.kind === 'go' || st.kind === 'action' ? st.key : `to:${st.to}`
    const gate = st.kind === 'advance' && !deviationCovers(st.to) ? gateHolding(st.to) : undefined
    return st.kind === 'action' ? null : needs(key) ?? (gate ? gateWhy(gate) : null)
  }
  /** One next-step button; the same in the cockpit and the compact bar. */
  const stepButton = (st: Exclude<NextStep, { kind: 'wait' }>, primary: boolean, size: ButtonSize = 'md') => {
    const key = st.kind === 'go' || st.kind === 'action' ? st.key : `to:${st.to}`
    const denied = deniedFor(st)
    const blockedHint = demoted && st.kind === 'advance'
      ? plural(t('next.blockedStepHint'), hardBlockers.length) : undefined
    return (
      <button key={key} type="button" data-testid={`next-${key.replace(':', '-')}`}
        className={stepCls(primary, size)}
        disabled={!!denied || (st.kind === 'advance' && advancing)}
        title={denied ?? blockedHint ?? (st.kind === 'advance' || st.kind === 'action' ? st.hint : undefined) ?? undefined}
        onClick={() => (st.kind === 'go' ? (onGo ?? onAction)?.(st.tab)
          : st.kind === 'action' ? onStepAction?.(st.key) : onAdvance(st.to))}>
        {st.kind === 'go' || st.kind === 'action' ? st.label : (st.label ?? transitionLabel(st.to, change.status))}
      </button>
    )
  }
  const resolveButton = (size: ButtonSize = 'md') => (
    <button type="button" data-testid="next-resolve-blockers" className={stepCls(true, size)}
      disabled={!lead?.go} onClick={() => lead?.go?.()}
      title={lead ? t('next.resolveFirst').replace('{x}', lead.text) : undefined}>
      {plural(t('next.resolveBlockers'), hardBlockers.length)}
    </button>
  )
  const statusPill = (small = false) => (
    <span data-testid="status-pill" className={`whitespace-nowrap rounded-full font-semibold ${
      small ? 'px-2 py-0.5 text-xs' : 'px-2.5 py-1 text-sm'} ${
      endLabel(change) ? 'bg-red-900 text-red-100' : STATUS_PILL[change.status]}`}>
      {endLabel(change) ?? STATUS_LABELS[change.status]}
    </span>
  )

  const waitRow = (w: WaitState) => {
    const Icon = w.info ? Info : Hourglass
    const body = (
      <>
        <Icon aria-hidden="true" size={14} className="mt-0.5 shrink-0" />
        <span>{w.text}{w.tab && onGo ? <Where to={tabName(w.tab)} /> : null}</span>
      </>
    )
    return (
      <li key={w.key} data-testid={`wait-${w.key}`}
        className={w.level === 3 && !w.info ? 'text-rose-300 font-medium' : w.info ? 'text-slate-300' : 'text-amber-300'}>
        {w.tab && onGo ? (
          <button type="button" className={linkRow}
            onClick={() => (w.issueId != null ? onGo(w.tab!, w.issueId) : onGo(w.tab!))}>
            {body}
          </button>
        ) : <span className="inline-flex items-start gap-1.5">{body}</span>}
      </li>
    )
  }

  if (variant === 'compact') {
    const primaryStep = !demoted && buttons[0] && steps[0] === buttons[0] ? buttons[0] : null
    const firstWait = steps.find((st) => st.kind === 'wait')
    return (
      <div data-testid="cockpit-compact" className="flex min-w-0 flex-1 items-center gap-2">
        {statusPill(true)}
        {hardBlockers.length > 0 ? (
          <button type="button" data-testid="compact-blockers" onClick={onShowOverview}
            className="inline-flex shrink-0 items-center gap-1 whitespace-nowrap rounded-full border border-amber-700/60 bg-amber-950/40 px-2 py-0.5 text-xs text-amber-200 hover:bg-amber-900/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400">
            <AlertTriangle aria-hidden="true" size={12} />
            {plural(t('cockpit.blockersCount'), hardBlockers.length)}
          </button>
        ) : !ended && (
          <span className="hidden shrink-0 items-center gap-1 text-xs text-emerald-400 sm:inline-flex">
            <Check aria-hidden="true" size={12} />{t('cockpit.nothingBlocking')}
          </span>
        )}
        {mainActions.length > 0 && (
          <button type="button" data-testid="compact-actions" onClick={onShowOverview}
            className="inline-flex shrink-0 items-center whitespace-nowrap rounded-full border border-sky-700 bg-sky-900/40 px-2 py-0.5 text-xs text-sky-100 hover:bg-sky-800/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400">
            {plural(t('cockpit.actionsCount'), mainActions.length)}
          </button>
        )}
        <div className="ml-auto flex min-w-0 items-center gap-2">
          {meetingDecides ? (
            <button type="button" className={btnSm.secondary} onClick={() => onAction?.('scoping')}>
              {canRecordMeeting ? t('cockpit.decideInMeeting') : t('cockpit.meetingDecides')}
            </button>
          ) : demoted ? resolveButton('sm')
            : primaryStep ? (
              <>
                {/* A held step says why right beside it, not only in a tooltip. */}
                {deniedFor(primaryStep) && (
                  <span data-testid="compact-held" className="min-w-0 truncate text-xs text-amber-200"
                    title={deniedFor(primaryStep) ?? undefined}>
                    {deniedFor(primaryStep)}
                  </span>
                )}
                {!deniedFor(primaryStep) && primaryStep.kind === 'advance' && warns(`to:${primaryStep.to}`) && (
                  <span data-testid="compact-warn" className="min-w-0 truncate text-xs text-amber-200"
                    title={warns(`to:${primaryStep.to}`) ?? undefined}>
                    {warns(`to:${primaryStep.to}`)}
                  </span>
                )}
                {stepButton(primaryStep, true, 'sm')}
              </>
            )
            : firstWait && firstWait.kind === 'wait' ? (
              <span className="inline-flex min-w-0 items-center gap-1 text-xs text-slate-400">
                <Hourglass aria-hidden="true" size={12} className="shrink-0" />
                <span className="truncate">{firstWait.text}</span>
              </span>
            ) : null}
        </div>
      </div>
    )
  }

  const backupGroup = (
    <div data-testid="backup-actions">
      <h3 className="text-xs uppercase tracking-wide text-slate-400 mb-2">{t('actions.asBackup')}</h3>
      <div className="flex flex-wrap gap-2">
        {backupActions.map((a, i) => (
          <button
            key={actionKey(a, i)}
            type="button"
            title={a.hint ? `${a.hint} · ${t('team.backupHint')}` : t('team.backupHint')}
            className={`${btnBase} ${btnSizes.md} h-auto min-h-9 whitespace-normal flex-col items-start py-1.5 text-left border border-slate-600 text-slate-300 hover:bg-slate-700`}
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
      {takeOff && takeOff.department_id != null && (
        <TakeOffRoutingDialog changeId={change.id} departmentId={takeOff.department_id}
          departmentName={takeOff.department_name ?? String(takeOff.department_id)}
          stageOrder={takeOff.stage_order ?? undefined}
          onClose={() => setTakeOff(null)} />
      )}
      {mainActions.length > 0 && (
        <div data-testid="your-actions" className="bg-sky-950 border border-sky-700 rounded-lg p-4 mb-3">
          <h3 className="text-xs uppercase tracking-wide text-sky-300 mb-2">{t('actions.title')}</h3>
          <div className="flex flex-wrap gap-2">
            {mainActions.map((a, i) => {
              const chase = (
                <button
                  key={actionKey(a, i)}
                  type="button"
                  data-testid={a.issue_id != null ? `action-${a.kind}-${a.issue_id}` : `action-${a.kind}`}
                  title={a.hint ?? undefined}
                  className={actionCls}
                  onClick={() => runAction(a)}>
                  {pluralizeLabel(a.label)}
                </button>
              )
              // The lead's late flag has two ways out: chase the department,
              // or take it off the routing (a remove deviation, with a reason).
              if (a.kind !== 'late_assessment' || a.department_id == null) return chase
              return (
                <span key={actionKey(a, i)} className="inline-flex flex-wrap items-stretch gap-1">
                  {chase}
                  {removalPending(a) ? (
                    <span className="inline-flex items-center">
                      <PendingRemovalChip testId={`action-late-removal-${a.assessment_id ?? a.department_id}`} />
                    </span>
                  ) : (
                    <button type="button" data-testid={`action-late-takeoff-${a.assessment_id ?? a.department_id}`}
                      title={t('lateAssess.takeOffHint')}
                      className={`${btnSm.secondary} h-auto min-h-9`}
                      onClick={() => setTakeOff(a)}>
                      {t('lateAssess.takeOff')}
                    </button>
                  )}
                </span>
              )
            })}
          </div>
          {backupActions.length > 0 && <div className="mt-3 pt-3 border-t border-sky-900">{backupGroup}</div>}
        </div>
      )}
      {mainActions.length === 0 && backupActions.length > 0 && (
        <div className="bg-slate-800/60 border border-slate-700 rounded-lg p-4 mb-3">{backupGroup}</div>
      )}
      <div className="grid md:grid-cols-3 gap-3">
      <div className="bg-slate-800 rounded-lg border border-slate-700 p-4">
        <h3 className="text-xs uppercase tracking-wide text-slate-400 mb-2">{t('cockpit.where')}</h3>
        {statusPill()}
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
            {plantText('mp.sop', change.mother_plant_name)} {formatCalendarDate(change.mother_plant_sop)}
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
        <p data-testid="status-dates" className="mt-1 text-xs text-slate-400">
          {t('cockpit.created')} {formatDate(change.created_at)} · {t('cockpit.updated')} {formatDate(change.updated_at)}
        </p>
      </div>

      <div className="bg-slate-800 rounded-lg border border-slate-700 p-4">
        <h3 className="text-xs uppercase tracking-wide text-slate-400 mb-2">{t('cockpit.blocking')}</h3>
        {hardBlockers.length === 0 ? (
          <>
            <p className="inline-flex items-center gap-1.5 text-sm text-emerald-400">
              <Check aria-hidden="true" size={14} />{t('cockpit.nothingBlocking')}
            </p>
            {laterGates.length > 0 && (
              <ul className="space-y-1.5 text-sm mt-2">
                {laterGates.map((g) => gateRow(g, false))}
              </ul>
            )}
          </>
        ) : (
          <ul className="space-y-1.5 text-sm">
            {waits.filter((w) => !w.info).map(waitRow)}
            {blockingGates.map((g) => gateRow(g, true))}
            {pendingDeviations > 0 && (
              <li data-testid="blocked-pending-deviations" className="text-amber-300">
                {onDecideDeviation ? (
                  <button type="button" className={linkRow} onClick={() => onDecideDeviation()}>
                    <AlertTriangle aria-hidden="true" size={14} className="mt-0.5 shrink-0" />
                    <span>{t('cockpit.pendingDeviations')}: {pendingDeviations}<Where to={tabName('overview')} /></span>
                  </button>
                ) : (
                  <span className="inline-flex items-start gap-1.5">
                    <AlertTriangle aria-hidden="true" size={14} className="mt-0.5 shrink-0" />
                    {t('cockpit.pendingDeviations')}: {pendingDeviations}
                  </span>
                )}
              </li>
            )}
            {overdue > 0 && (
              <li className="flex items-start gap-1.5 text-red-400">
                <AlertTriangle aria-hidden="true" size={14} className="mt-0.5 shrink-0" />
                {t('cockpit.overdueAssessments')}: {overdue}
              </li>
            )}
            {impactUnconfirmed && (
              <li className="text-amber-300">
                {onShowImpact ? (
                  <button type="button" className={linkRow} onClick={onShowImpact}>
                    <AlertTriangle aria-hidden="true" size={14} className="mt-0.5 shrink-0" />
                    <span>{t('impact.pending')}<Where to={t('impact.title')} /></span>
                  </button>
                ) : (
                  <span className="inline-flex items-start gap-1.5">
                    <AlertTriangle aria-hidden="true" size={14} className="mt-0.5 shrink-0" />{t('impact.pending')}
                  </span>
                )}
              </li>
            )}
            {laterGates.map((g) => gateRow(g, false))}
          </ul>
        )}
        {infoWaits.length > 0 && (
          // Worth knowing, holding nothing: listed apart and not counted, so
          // the blocker count and this card always agree.
          <div data-testid="cockpit-worth-knowing" className="mt-3">
            <h4 className="text-[11px] uppercase tracking-wide text-slate-500 mb-1">{t('cockpit.worthKnowing')}</h4>
            <ul className="space-y-1.5 text-sm">{infoWaits.map(waitRow)}</ul>
          </div>
        )}
      </div>

      <div className="bg-slate-800 rounded-lg border border-slate-700 p-4">
        <h3 className="text-xs uppercase tracking-wide text-slate-400 mb-2">{t('cockpit.next')}</h3>
        {impl?.ready_to_go && (
          <span className="mb-2 inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-semibold bg-emerald-900 text-emerald-200">
            <Check aria-hidden="true" size={12} />{t('impl.readyToGo')}
          </span>
        )}
        {kickoffMissing.length > 0 && (
          <div data-testid="kickoff-hint"
            className="mb-2 rounded-lg border border-amber-700/60 bg-amber-950/30 p-2 text-xs">
            <p className="inline-flex items-center gap-1.5 text-amber-200">
              <AlertTriangle aria-hidden="true" size={12} />{t('kickoff.title')}
            </p>
            <ul className="mt-1 list-disc list-inside text-amber-100/80">
              {kickoffMissing.map((m) => <li key={m}>{m}</li>)}
            </ul>
            <p className="mt-1 text-slate-400">{t(motherPlant ? 'kickoff.hard' : 'kickoff.soft')}</p>
          </div>
        )}
        {change.status === 'captured' && kickoffMissing.length === 0 && (
          <p data-testid="kickoff-ready" className="mb-2 inline-flex items-center gap-1.5 text-xs text-emerald-400">
            <Check aria-hidden="true" size={12} />{t('kickoff.ready')}
          </p>
        )}
        {meetingDecides ? (
          // The decision lives in the meeting record, not on a button here.
          <button type="button"
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
                className="flex items-start gap-1.5 rounded-lg border border-slate-700 bg-slate-900/40 px-3 py-2 text-sm text-slate-300">
                <Hourglass aria-hidden="true" size={14} className="mt-0.5 shrink-0 text-slate-400" />
                <span>{st.kind === 'wait' ? st.text : ''}</span>
              </p>
            ))}
            {demoted && (
              <>
                {resolveButton()}
                {lead && (
                  <p data-testid="next-resolve-first" className="-mt-1 text-xs text-slate-400">
                    {t('next.resolveFirst').replace('{x}', lead.text)}
                  </p>
                )}
              </>
            )}
            {/* While the step waits there is no primary button at all. */}
            {buttons.map((st) => stepButton(st, !demoted && steps[0] === st))}
            {/* A warning beside a live step: read it, the step still goes. */}
            {buttons.flatMap((st) => {
              if (st.kind !== 'advance' || deniedFor(st)) return []
              const w = warns(`to:${st.to}`)
              return w ? [(
                <p key={`warn-${st.to}`} data-testid={`next-warn-${st.to}`}
                  className="flex items-start gap-1.5 text-xs text-amber-200">
                  <AlertTriangle aria-hidden="true" size={12} className="mt-0.5 shrink-0" /><span>{w}</span>
                </p>
              )] : []
            })}
            {/* The gate that holds a step, with the way to where it is decided. */}
            {[...new Map(buttons.flatMap((st) => {
              const g = st.kind === 'advance' ? gateHolding(st.to) : undefined
              return g && st.kind === 'advance' ? [[g.gate_key, { g, to: st.to }] as const] : []
            })).values()].map(({ g, to }) => {
              if (deviationCovers(to)) {
                return (
                  <p key={g.gate_key} data-testid={`next-gate-${g.gate_key}`}
                    className="flex items-start gap-1.5 text-xs text-emerald-300">
                    <Check aria-hidden="true" size={12} className="mt-0.5 shrink-0" />
                    <span>{t('cockpit.gateDeviationApproved').replace('{gate}', t('gate.' + g.gate_key))
                      .replace('{state}', gateState(g))}</span>
                  </p>
                )
              }
              const canJump = !!onResolveGate && canSeeGovernance
              return (
                <div key={g.gate_key} data-testid={`next-gate-${g.gate_key}`} className="text-xs text-amber-300">
                  {canJump ? (
                    <button type="button" className={linkRow}
                      onClick={() => onResolveGate!(g.gate_key)} title={t('cockpit.resolveGate')}>
                      <Ban aria-hidden="true" size={12} className="mt-0.5 shrink-0" />
                      <span>{gateWhy(g)}<Where to="D1" /></span>
                    </button>
                  ) : (
                    <p className="flex items-start gap-1.5">
                      <Ban aria-hidden="true" size={12} className="mt-0.5 shrink-0" /><span>{gateWhy(g, false)}</span>
                    </p>
                  )}
                  {deviationAsked(to) ? (
                    <p className="mt-1 flex items-start gap-1.5 text-slate-400">
                      <Hourglass aria-hidden="true" size={12} className="mt-0.5 shrink-0" />
                      <span>{t('cockpit.gateDeviationPending')}</span>
                    </p>
                  ) : onAskDeviation ? (
                    <button type="button" data-testid={`next-ask-deviation-${to}`}
                      className={`mt-1 block text-amber-200 ${linkRow}`}
                      title={t('cockpit.askDeviationHint')}
                      onClick={() => onAskDeviation(to, g.gate_key)}>
                      {t('cockpit.askDeviation')}
                    </button>
                  ) : null}
                </div>
              )
            })}
            {(() => {
              const why = buttons.map((st) => (st.kind === 'go' ? needs(st.key)
                : st.kind === 'advance' ? needs(`to:${st.to}`) : null)).find(Boolean)
                ?? (hiddenSteps > 0 && buttons.length === 0 ? mayNotText ?? t('next.notYours') : null)
              return why ? <p data-testid="next-needs" className="text-xs text-slate-400">{why}</p> : null
            })()}
          </div>
        )}
      </div>
      </div>
    </div>
  )
}

const fieldCls =
  'mt-1 w-full rounded-lg border border-slate-600 bg-slate-900 p-2 text-sm text-slate-100 focus:border-sky-500 focus:outline-none'

/** "Take off routing" on the lead's late flag: a routing deviation that
 *  removes the department's row (op remove), with the reason on record. */
function TakeOffRoutingDialog({ changeId, departmentId, departmentName, stageOrder, onClose }: {
  changeId: number
  departmentId: number
  departmentName: string
  stageOrder?: number
  onClose: () => void
}) {
  const qc = useQueryClient()
  const [reason, setReason] = useState('')
  const reasonId = useId()
  const reasonRef = useRef<HTMLTextAreaElement>(null)
  const remove = useMutation({
    mutationFn: () => changesApi.postDeviation(changeId, {
      op: 'remove', department_id: departmentId, stage_order: stageOrder, reason: reason.trim(),
    }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['change-routing', changeId] })
      qc.invalidateQueries({ queryKey: ['change', changeId] })
      qc.invalidateQueries({ queryKey: ['change-my-actions', changeId] })
      toast.success(t('lateAssess.done'))
      onClose()
    },
    onError: (e: unknown) => { toastError(e, t('routingDev.failed')) },
  })
  return (
    <Dialog open onClose={onClose} busy={remove.isPending} closeOnBackdrop={false}
      title={t('lateAssess.title').replace('{x}', departmentName)}
      data-testid="take-off-routing-dialog"
      initialFocus={reasonRef as React.RefObject<HTMLElement>}
      footer={(
        <>
          <Button onClick={onClose} disabled={remove.isPending}>{t('common.cancel')}</Button>
          <Button variant="danger" data-testid="take-off-routing-submit"
            disabled={!reason.trim()} loading={remove.isPending}
            onClick={() => remove.mutate()}>{t('lateAssess.submit')}</Button>
        </>
      )}>
      <div className="space-y-3">
        <p className="flex items-start gap-2 rounded-lg border border-amber-700/60 bg-amber-950/40 px-3 py-2 text-xs text-amber-200">
          <TriangleAlert aria-hidden="true" size={14} className="mt-0.5 shrink-0 text-amber-300" />
          <span>{t('lateAssess.effect')}</span>
        </p>
        <div>
          <label htmlFor={reasonId} className="block text-sm text-slate-300">{t('lateAssess.reason')}</label>
          <textarea id={reasonId} ref={reasonRef} data-testid="take-off-routing-reason"
            className={`${fieldCls} min-h-[70px]`}
            value={reason} onChange={(e) => setReason(e.target.value)} />
        </div>
      </div>
    </Dialog>
  )
}
