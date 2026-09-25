/**
 * What is this change waiting on?
 *
 * Every blocking wait in the flow answers to one resolver, so the change detail
 * can state them all in one place, in one voice, to every viewer regardless of
 * role. A new wait state is one entry here — the banner never changes.
 *
 * Derived purely from data the detail page already holds; nothing is fetched.
 */
import { t } from '../i18n/cmLabels'
import type {
  Assessment, ChangeConcern, ChangeRequest, ImplDepartmentState, ValidationState,
} from '../types/change'
import type { IssueOut } from '../types/validationIssue'
import { isIssueOpen, issueCode } from '../types/validationIssue'
import { formatDate } from './format'

/** The slice of GET /plan/feedback the waits need. */
export interface PlanFeedbackLite {
  required: { department_name: string; verdict: string | null; stale: boolean }[]
  all_confirmed?: boolean
  validated_at?: string | null
}

export interface WaitState {
  /** Stable key, also the test id suffix. */
  key: string
  text: string
  /** Where the work happens, for the "take me there" affordance. */
  tab?: 'overview' | 'scoping' | 'impacted' | 'assessments' | 'costing' | 'offer' | 'timing' | 'release'
  /** Worth knowing, not holding anything up yet (shown muted). */
  info?: boolean
  /** An escalation line: 2 amber, 3 rose. */
  level?: 1 | 2 | 3
}

/** The slice of a validation issue the waits need. */
export type IssueLite = Pick<IssueOut, 'id' | 'number' | 'title' | 'status' | 'severity'
  | 'escalation_level' | 'escalations' | 'customer_inform' | 'customer_decision' | 'customer_decided_at'
  | 'attachments' | 'department_name'>

const STATUS_WORDS: Record<IssueOut['status'], string> = {
  open: 'open', contained: 'contained', route_decided: 'route decided', fixing: 'fixing',
  revalidation: 're-validation', closed: 'closed', accepted: 'accepted', transferred: 'transferred',
}

const dayMonth = (iso?: string | null) => (iso ? formatDate(iso).slice(0, 5) : '')

/**
 * Open validation issues as waits: the highest escalation level first
 * ("Escalation L3: VI-2 Tool cannot run, customer informed 25.09"), then one
 * line per open issue (more than three fold into one line).
 */
export function issueWaits(issues: IssueLite[]): WaitState[] {
  const open = issues.filter(isIssueOpen)
  if (open.length === 0) return []
  const waits: WaitState[] = []
  const level = (i: IssueLite) => i.escalation_level ?? 1
  const top = [...open].sort((a, b) => level(b) - level(a) || b.severity - a.severity || a.number - b.number)[0]
  if (level(top) >= 2) {
    const mails = (top.attachments ?? []).filter((a) => a.kind === 'customer_email')
      .map((a) => a.created_at).sort()
    const lastEsc = [...(top.escalations ?? [])].filter((e) => e.level === level(top))
      .sort((a, b) => b.created_at.localeCompare(a.created_at))[0]
    const tail = top.customer_decided_at ? `customer decided ${dayMonth(top.customer_decided_at)}`
      : mails.length ? `customer informed ${dayMonth(mails[mails.length - 1])}`
        : lastEsc ? `since ${dayMonth(lastEsc.created_at)}${lastEsc.acknowledged_at ? '' : ', not acknowledged'}`
          : ''
    waits.push({
      key: 'issue-escalation',
      text: `Escalation L${level(top)}: ${issueCode(top)} ${top.title}${tail ? `, ${tail}` : ''}`,
      tab: 'release',
      level: level(top) as 2 | 3,
    })
  }
  if (open.length > 3) {
    waits.push({
      key: 'validation-issues',
      text: `${open.length} validation issues open: ${open.map(issueCode).join(', ')}`,
      tab: 'release',
    })
  } else {
    for (const i of open) {
      waits.push({
        key: `validation-issue-${i.id}`,
        text: `${issueCode(i)} open: ${excerpt(i.title, 60)} (${STATUS_WORDS[i.status]})`,
        tab: 'release',
      })
    }
  }
  return waits
}

/** Long reasons are a banner, not an essay. */
const excerpt = (s: string, max = 90) =>
  s.length > max ? `${s.slice(0, max - 1).trimEnd()}…` : s

/**
 * How far the assessment round has got, over the rows that actually owe an
 * answer: R and A. S/C/I are consulted, not on the hook, so counting them would
 * make the board look permanently unfinished.
 *
 * Deliberately takes normalised rows rather than raw assessments: the buckets
 * derive theirs from routing plus assessments, the banner from assessments
 * alone, and both must produce the same "3/5" for the same change.
 */
export interface ProgressRow {
  departmentId: number
  rasic: string | null
  submitted: boolean
  /** Waived and not-yet-started rows owe nothing right now. */
  dormant: boolean
}

export function assessmentProgress(rows: ProgressRow[]): {
  done: number; total: number; waiting: number[]
} {
  // One entry per department: a department that has answered anywhere counts as
  // answered, whatever leftover rows an earlier routing version left behind.
  const owed = rows.filter((r) => r.rasic === 'R' || r.rasic === 'A')
  const byDept = new Map<number, boolean>()
  for (const r of owed) {
    if (r.submitted) byDept.set(r.departmentId, true)
    else if (!r.dormant && !byDept.get(r.departmentId)) byDept.set(r.departmentId, false)
  }
  const entries = [...byDept.entries()]
  return {
    done: entries.filter(([, ok]) => ok).length,
    total: entries.length,
    waiting: entries.filter(([, ok]) => !ok).map(([id]) => id),
  }
}

const isSubmitted = (a: Pick<Assessment, 'submitted_at' | 'verdict'>) =>
  !!a.submitted_at || (!!a.verdict && a.verdict !== 'pending')

export function resolveWaitStates(
  change: Pick<ChangeRequest, 'status' | 'customer_relevant' | 'blocked_department_ids'
    | 'rejection_sent_at' | 'costing_pending_department_ids'
    | 'bank_build_mode' | 'plan_published_at' | 'timing_validated_at'>,
  concerns: ChangeConcern[] = [],
  departmentName: (id: number) => string = (id) => `#${id}`,
  /** The change's assessment rows — the detail page already holds them. */
  assessments: Pick<Assessment,
    'department_id' | 'rasic_letter' | 'status' | 'submitted_at' | 'verdict'
    | 'stage_order'>[] = [],
  /**
   * Stage 8, while the work is being done: the per-department board and the
   * escalations raised against it. Both come from the implementation tab's own
   * queries — the resolver stays pure and is handed what the page already has.
   */
  impl: {
    state?: ImplDepartmentState[] | { departments?: ImplDepartmentState[] }
    escalations?: { resolved_at?: string | null }[]
  } = {},
  /**
   * Stage 9, the same way: the validation board as the panel already fetched
   * it. Two waits come out of it — the departments that still owe a check, and
   * the weight delta nobody has taken into the quote.
   */
  validation?: ValidationState | null,
  /**
   * At approved: the detailed plan's team confirmation, as the Timing tab's
   * query ['change', id, 'plan-feedback'] holds it.
   */
  planFeedback?: PlanFeedbackLite | null,
  /**
   * After the baseline: open plan deviations (a note while the work runs, a
   * blocker at release), and at validation the release guard's own reasons
   * (GET /release blockers) in its words.
   */
  more: {
    openPlanDeviations?: number; releaseBlockers?: string[] | null
    /** GET /validation/issues: open ones block the release (spec §12). */
    validationIssues?: IssueLite[] | null
  } = {},
): WaitState[] {
  const waits: WaitState[] = []
  const releaseBlockers = change.status === 'in_validation' ? more.releaseBlockers ?? null : null

  // Customer questions: first nobody has answered, then nobody has closed it.
  // Same predicate the backend uses for the Sales task — open and needs-info,
  // whatever it is attributed to and whichever meeting (if any) raised it. A
  // narrower rule here would put a task in someone's list that the change page
  // then denies is outstanding.
  const questions = concerns.filter((c) => c.is_open && c.kind === 'needs_info')
  for (const c of questions) {
    waits.push(c.answered_at
      ? {
        key: `review-${c.id}`,
        text: t('wait.onReview').replace('{x}', excerpt(c.note)),
        tab: 'scoping',
      }
      : {
        key: `sales-info-${c.id}`,
        text: t('wait.onSales.info').replace('{x}', excerpt(c.note)),
        tab: 'scoping',
      })
  }

  // Who the assessment round is still waiting on — stated for everyone, not just
  // the departments on the hook, so the change never looks idle without a reason.
  if (change.status === 'in_assessment') {
    // Only the assessment stage itself: later stages (summation, customer
    // activities) also live as rows, but Sales/PM are not assessing.
    const first = Math.min(...assessments.map((a) => a.stage_order))
    const p = assessmentProgress(assessments.filter(
      (a) => a.stage_order === first,
    ).map((a) => ({
      departmentId: a.department_id,
      rasic: a.rasic_letter,
      submitted: isSubmitted(a),
      dormant: a.status === 'waived' || a.status === 'pending',
    })))
    if (p.waiting.length > 0) {
      waits.push({
        key: 'assessment-round',
        text: t('wait.onAssessment')
          .replace('{x}', p.waiting.map(departmentName).join(', '))
          .replace('{n}', String(p.done)).replace('{m}', String(p.total)),
        tab: 'assessments',
      })
    }
  }

  // A department cannot submit while it holds its own open concern.
  const blocked = change.blocked_department_ids ?? []
  if (change.status === 'in_assessment' && blocked.length > 0) {
    waits.push({
      key: 'blocked-departments',
      text: t('wait.onDepartments').replace('{x}', blocked.map(departmentName).join(', ')),
      tab: 'assessments',
    })
  }

  // Costing waits on the departments that have not entered their numbers.
  if (change.status === 'costing' && (change.costing_pending_department_ids?.length ?? 0) > 0) {
    waits.push({
      key: 'costing-input',
      text: t('wait.onCosting').replace('{x}',
        change.costing_pending_department_ids!.map(departmentName).join(', ')),
      tab: 'costing',
    })
  }

  // An approved change is not moving until Scheduling has said how it reaches
  // the line and every responsible team has confirmed the detailed timing,
  // which is then validated. Only a validated timing goes to the customer, so
  // the publish wait (customer changes) comes after that.
  if (change.status === 'approved') {
    if (!change.bank_build_mode) {
      waits.push({ key: 'bank-build', text: t('wait.onBankBuild'), tab: 'timing' })
    }
    const validated = !!change.timing_validated_at || !!planFeedback?.validated_at
    if (!validated && planFeedback && Array.isArray(planFeedback.required)) {
      const waiting = planFeedback.required
        .filter((r) => !(r.verdict === 'confirmed' && !r.stale))
      if (waiting.length > 0) {
        waits.push({
          key: 'timing-confirm',
          text: t('wait.onTimingConfirm').replace('{x}', waiting.map((r) => r.department_name).join(', ')),
          tab: 'timing',
        })
      } else {
        waits.push({ key: 'timing-validate', text: t('wait.onTimingValidate'), tab: 'timing' })
      }
    }
    if (validated && change.bank_build_mode && change.customer_relevant && !change.plan_published_at) {
      waits.push({ key: 'plan-publish', text: t('wait.onPlanPublish'), tab: 'timing' })
    }
  }

  // While the work runs, two things stall it silently: a department that has
  // stopped saying how it is going, and a flagged risk nobody has taken
  // anywhere. Both are named for everyone, not only for the desk that owes it.
  if (change.status === 'in_implementation') {
    const raw = impl.state as unknown
    const state = Array.isArray(raw)
      ? raw as { owes_report?: boolean; at_risk_open?: boolean }[]
      : (raw as { departments?: { owes_report?: boolean; at_risk_open?: boolean }[] } | undefined)
          ?.departments ?? []
    const owing = state.filter((s) => s.owes_report).length
    if (owing > 0) {
      waits.push({
        key: 'implementation-reports',
        text: t('wait.onProgressReports').replace('{n}', String(owing)),
        tab: 'timing',
      })
    }
    // An escalation is a change-level act, so the pairing is change-level too:
    // any at-risk department while nothing is open means Sales still owes one.
    const openEscalation = (impl.escalations ?? []).some((e) => !e.resolved_at)
    if (state.some((s) => s.at_risk_open) && !openEscalation) {
      waits.push({
        key: 'implementation-escalation',
        text: t('wait.onRiskEscalation'),
        tab: 'timing',
      })
    }
  }

  // While the results are being checked: the departments that have not answered
  // their checks, and — separately, because it is a different desk and a
  // different consequence — a validated weight the quote has not caught up with.
  if (change.status === 'in_validation' && validation) {
    const owing = (validation.departments ?? [])
      .filter((d) => d.checks.some((c) => !c.retired && c.status !== 'passed')).length
    if (owing > 0) {
      waits.push({
        key: 'validation-checks',
        text: t('wait.onValidationChecks').replace('{n}', String(owing)),
        tab: 'release',
      })
    }
    if ((validation.weight_delta_g ?? 0) !== 0 && !validation.weight_ack_at) {
      waits.push({
        key: 'validation-weight-ack',
        text: t('wait.onWeightAck'),
        tab: 'release',
      })
    }
  }

  // Validation issues: open ones hold the release, and the loop back keeps
  // them alive while the fix is implemented.
  const issueLines = ['in_validation', 'in_implementation'].includes(change.status)
    ? issueWaits(more.validationIssues ?? []) : []
  waits.push(...issueLines)

  // Open plan deviations: PM/Sales lock or escalate them. Worth knowing while
  // the work runs; at validation the release guard names them itself.
  const devs = more.openPlanDeviations ?? 0
  if (devs > 0 && ['approved', 'in_implementation'].includes(change.status)) {
    waits.push({
      key: 'plan-deviations',
      text: `${devs} plan deviation${devs === 1 ? '' : 's'} open: lock or escalate`,
      tab: 'timing',
      info: true,
    })
  }
  if (devs > 0 && change.status === 'in_validation' && !releaseBlockers?.some((b) => /plan deviation/i.test(b))) {
    waits.push({
      key: 'plan-deviations',
      text: `${devs} plan deviation${devs === 1 ? '' : 's'} still open: lock or escalate them first`,
      tab: 'timing',
    })
  }
  // What the release guard would refuse on today. The validation checks are
  // already listed above (with their count), so the guard's version of that
  // one is left out.
  if (releaseBlockers) {
    releaseBlockers.forEach((b, i) => {
      if (/^validation (incomplete|failed)/i.test(b) && waits.some((w) => w.key === 'validation-checks')) return
      // The issues are listed one by one above.
      if (/validation issue|\bVI-\d+/i.test(b) && issueLines.length > 0) return
      waits.push({
        key: `release-${i}`,
        text: b,
        tab: /plan deviation/i.test(b) ? 'timing' : 'release',
      })
    })
  }

  // A rejected customer change is not finished until the customer has been told.
  if (change.status === 'rejected' && change.customer_relevant && !change.rejection_sent_at) {
    waits.push({ key: 'rejection-letter', text: t('wait.onRejectionLetter'), tab: 'scoping' })
  }

  return waits
}
