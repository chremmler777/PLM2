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
import type { ChangeConcern, ChangeRequest } from '../types/change'

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

export function resolveWaitStates(
  change: Pick<ChangeRequest, 'status' | 'customer_relevant' | 'blocked_department_ids'
    | 'rejection_sent_at' | 'costing_pending_department_ids'>,
  concerns: ChangeConcern[] = [],
  departmentName: (id: number) => string = (id) => `#${id}`,
): WaitState[] {
  const waits: WaitState[] = []

  // Customer questions: first nobody has answered, then nobody has closed it.
  const teamQuestions = concerns.filter(
    (c) => c.is_open && c.kind === 'needs_info' && c.department_id == null)
  for (const c of teamQuestions) {
    waits.push(c.answer_note
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
