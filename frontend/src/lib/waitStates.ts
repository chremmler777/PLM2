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

export interface WaitState {
  /** Stable key, also the test id suffix. */
  key: string
  text: string
  /** Where the work happens, for the "take me there" affordance. */
  tab?: 'overview' | 'scoping' | 'impacted' | 'assessments' | 'commercial' | 'implementation'
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
    | 'bank_build_mode' | 'plan_published_at'>,
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
): WaitState[] {
  const waits: WaitState[] = []

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
      tab: 'commercial',
    })
  }

  // An approved change is not moving until Scheduling has said how it reaches
  // the line, and — when the customer is the cost carrier — until Sales has put
  // the resulting plan in front of them. Two waits, one after the other.
  if (change.status === 'approved') {
    if (!change.bank_build_mode) {
      waits.push({ key: 'bank-build', text: t('wait.onBankBuild'), tab: 'implementation' })
    } else if (change.customer_relevant && !change.plan_published_at) {
      waits.push({ key: 'plan-publish', text: t('wait.onPlanPublish'), tab: 'implementation' })
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
        tab: 'implementation',
      })
    }
    // An escalation is a change-level act, so the pairing is change-level too:
    // any at-risk department while nothing is open means Sales still owes one.
    const openEscalation = (impl.escalations ?? []).some((e) => !e.resolved_at)
    if (state.some((s) => s.at_risk_open) && !openEscalation) {
      waits.push({
        key: 'implementation-escalation',
        text: t('wait.onRiskEscalation'),
        tab: 'implementation',
      })
    }
  }

  // While the results are being checked: the departments that have not answered
  // their checks, and — separately, because it is a different desk and a
  // different consequence — a validated weight the quote has not caught up with.
  if (change.status === 'in_validation' && validation) {
    const owing = (validation.departments ?? [])
      .filter((d) => d.checks.some((c) => c.status !== 'passed')).length
    if (owing > 0) {
      waits.push({
        key: 'validation-checks',
        text: t('wait.onValidationChecks').replace('{n}', String(owing)),
        tab: 'implementation',
      })
    }
    if ((validation.weight_delta_g ?? 0) !== 0 && !validation.weight_ack_at) {
      waits.push({
        key: 'validation-weight-ack',
        text: t('wait.onWeightAck'),
        tab: 'implementation',
      })
    }
  }

  // A rejected customer change is not finished until the customer has been told.
  if (change.status === 'rejected' && change.customer_relevant && !change.rejection_sent_at) {
    waits.push({ key: 'rejection-letter', text: t('wait.onRejectionLetter'), tab: 'scoping' })
  }

  return waits
}
