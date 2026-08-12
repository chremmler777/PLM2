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
import type { Assessment, ChangeConcern, ChangeRequest } from '../types/change'

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
    | 'rejection_sent_at' | 'costing_pending_department_ids'>,
  concerns: ChangeConcern[] = [],
  departmentName: (id: number) => string = (id) => `#${id}`,
  /** The change's assessment rows — the detail page already holds them. */
  assessments: Pick<Assessment,
    'department_id' | 'rasic_letter' | 'status' | 'submitted_at' | 'verdict'>[] = [],
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
    const p = assessmentProgress(assessments.map((a) => ({
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

  // A rejected customer change is not finished until the customer has been told.
  if (change.status === 'rejected' && change.customer_relevant && !change.rejection_sent_at) {
    waits.push({ key: 'rejection-letter', text: t('wait.onRejectionLetter'), tab: 'scoping' })
  }

  return waits
}
