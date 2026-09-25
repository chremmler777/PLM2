/**
 * Words, colors and the pure rules of a validation issue card: the stepper,
 * the viewer's acts, the check key to category map and working-day slips.
 * Kept free of React so the rules are tested on their own.
 */
import type {
  CostBearer, CustomerDecision, EscalationLevel, IssueAct, IssueCategory, IssueEscalationOut,
  IssueOut, IssueRoute, IssueSeverity,
} from '../../../types/validationIssue'
import { isIssueOpen } from '../../../types/validationIssue'

export const CATEGORY_LABEL: Record<IssueCategory, string> = {
  tool: 'Tool',
  equipment_assembly: 'Equipment / assembly',
  dimensional: 'Dimensional',
  material_weight: 'Material / weight',
  cycle_time: 'Cycle time',
  cosmetic: 'Cosmetic',
  packaging: 'Packaging',
  documentation: 'Documentation',
  other: 'Other',
}

export const SEVERITY: Record<IssueSeverity, { label: string; chip: string }> = {
  1: { label: 'Low', chip: 'border-slate-600 bg-slate-800 text-slate-300' },
  2: { label: 'Medium', chip: 'border-amber-800 bg-amber-950/50 text-amber-200' },
  3: { label: 'Blocks production', chip: 'border-rose-800 bg-rose-950/60 text-rose-200' },
}

export const LEVEL: Record<EscalationLevel, { label: string; who: string; chip: string; dot: string }> = {
  1: { label: 'L1', who: 'Department', chip: 'border-slate-600 bg-slate-800 text-slate-300', dot: 'bg-slate-400' },
  2: { label: 'L2', who: 'Project', chip: 'border-amber-700 bg-amber-950/60 text-amber-200', dot: 'bg-amber-400' },
  3: { label: 'L3', who: 'Management and customer', chip: 'border-rose-700 bg-rose-950/60 text-rose-200', dot: 'bg-rose-400' },
}

/** One line per route, and what deciding it sets in motion. */
export const ROUTE: Record<IssueRoute, { label: string; line: string }> = {
  internal_rework: { label: 'Internal rework', line: 'Our own shop fixes the tool, equipment or part.' },
  supplier_rework: { label: 'Supplier rework', line: 'The supplier fixes it, optionally at their cost.' },
  design_change: { label: 'Design change', line: 'The design itself changes; the customer is told by default.' },
  customer_concession: { label: 'Customer concession', line: 'The customer accepts the part as it is, for now or for good.' },
  follow_up_change: { label: 'Follow-up change', line: 'A new change carries the fix; this one can release without it.' },
}

export const FIX_ROUTES: IssueRoute[] = ['internal_rework', 'supplier_rework', 'design_change']

export const DECISION_LABEL: Record<CustomerDecision, string> = {
  accept_deviation: 'Accepts the deviation',
  require_fix: 'Requires a fix',
  new_timing: 'New timing',
  pending: 'Pending',
}

export const DECISION_CHIP: Record<CustomerDecision, string> = {
  accept_deviation: 'border-emerald-800 bg-emerald-950/50 text-emerald-200',
  require_fix: 'border-rose-800 bg-rose-950/50 text-rose-200',
  new_timing: 'border-amber-800 bg-amber-950/50 text-amber-200',
  pending: 'border-slate-600 bg-slate-800 text-slate-300',
}

export const BEARER_LABEL: Record<CostBearer, string> = {
  internal: 'We pay',
  supplier: 'Supplier pays',
  customer: 'Customer pays',
}

export const STATUS_LABEL: Record<IssueOut['status'], string> = {
  open: 'Open',
  contained: 'Contained',
  route_decided: 'Route decided',
  fixing: 'Fixing',
  revalidation: 'Re-validation',
  closed: 'Closed',
  accepted: 'Accepted by customer',
  transferred: 'Transferred',
}

/**
 * The status chip in the card header. The backend keeps an issue "open"
 * until the route is decided, so the chip names the furthest step reached
 * before that: a recorded root cause reads "Root cause found".
 */
export function statusChipLabel(i: Pick<IssueOut, 'status' | 'contained_at' | 'root_cause_at' | 'step'>): string {
  if (i.status === 'open' || i.status === 'contained') {
    if (i.root_cause_at || i.step === 'root_cause') return 'Root cause found'
    if (i.contained_at || i.step === 'contained') return 'Contained'
  }
  return STATUS_LABEL[i.status]
}

/**
 * An escalation still owed an acknowledgement: level 2 or 3, not a lowering.
 * The backend's `needs_ack` wins when sent.
 */
export const needsAck = (e: Pick<IssueEscalationOut, 'needs_ack' | 'acknowledged_at' | 'level' | 'trigger'>): boolean =>
  e.needs_ack ?? (!e.acknowledged_at && e.level >= 2 && e.trigger !== 'deescalate')

/** Whether the issue waits on an acknowledgement (drives the badge's pulse). */
export const issueNeedsAck = (i: Pick<IssueOut, 'escalation' | 'escalations'>): boolean =>
  i.escalation?.unacknowledged ?? (i.escalations ?? []).some(needsAck)

/** A failed check proposes its category (spec §12 Raise). */
export const CATEGORY_FROM_CHECK: Record<string, IssueCategory> = {
  cycle_time: 'cycle_time',
  weight: 'material_weight',
  measured: 'dimensional',
  sampled: 'tool',
  packaging_validated: 'packaging',
  revision_bump: 'documentation',
}
export const categoryForCheck = (key?: string | null): IssueCategory =>
  (key && CATEGORY_FROM_CHECK[key]) || 'other'

// ---------------------------------------------------------------- stepper

export type StepState = 'done' | 'current' | 'todo' | 'skipped'
export interface Step { key: string; label: string; state: StepState; note?: string }

/**
 * Raised, Contained, Root cause, Route, Fixing, Re-validation, Closed. A step
 * the route does without (no fix on a concession, no containment on a low
 * severity decided without it) is shown skipped, not owed.
 */
export function issueSteps(i: IssueOut): Step[] {
  const decided = !!i.route_decided_at || !!i.route
  const fixRoute = !!i.route && FIX_ROUTES.includes(i.route)
  const ended = !isIssueOpen(i)
  const actionsDone = i.actions.length > 0 && i.actions.every((a) => a.status === 'done')
  const raw: [string, string, StepState, string?][] = [
    ['raised', 'Raised', 'done'],
    ['contained', 'Contained',
      i.contained_at ? 'done' : (decided || ended) ? 'skipped' : 'todo',
      !i.contained_at && i.severity === 3 ? 'required before the route' : undefined],
    ['root_cause', 'Root cause', i.root_cause_at ? 'done' : (decided || ended) ? 'skipped' : 'todo'],
    ['route', 'Route', decided ? 'done' : ended ? 'skipped' : 'todo'],
    ['fixing', 'Fixing',
      decided && !fixRoute ? 'skipped'
        : ['revalidation'].includes(i.status) || (ended && fixRoute) || (fixRoute && actionsDone) ? 'done' : 'todo'],
    ['revalidation', 'Re-validation',
      decided && !fixRoute ? 'skipped' : ended ? (i.status === 'closed' ? 'done' : 'skipped') : 'todo'],
    ['closed', i.status === 'accepted' ? 'Accepted' : i.status === 'transferred' ? 'Transferred' : 'Closed',
      ended ? 'done' : 'todo'],
  ]
  const steps: Step[] = raw.map(([key, label, state, note]) => ({ key, label, state, note }))
  if (!ended) {
    const cur = steps.find((s) => s.state === 'todo')
    if (cur) cur.state = 'current'
  }
  return steps
}

// ---------------------------------------------------------------- acts

export interface IssueViewer {
  id?: number | null
  isAdmin?: boolean
  /** PM, the change lead, admin. */
  canManage?: boolean
  isSales?: boolean
  /** admin, lead, Sales, PM: may see money. */
  canSeeCosts?: boolean
  myDepartmentIds?: number[]
}

export const ACT_LABEL: Record<IssueAct, string> = {
  contain: 'Record containment',
  root_cause: 'Record root cause',
  route: 'Decide the route',
  customer: 'Record customer decision',
  cost: 'Set the cost',
  add_action: 'Add fix action',
  action_done: 'Tick my fix action',
  recheck: 'Re-check the validation',
  close: 'Close issue',
  acknowledge: 'Acknowledge escalation',
  escalate: 'Escalate',
  edit: 'Edit',
  attach: 'Attach',
}

/** Acts that are not a step of the issue: never the primary button. */
const QUIET: IssueAct[] = ['edit', 'attach', 'escalate', 'add_action']

/** The 4-eyes rule: the raiser does not decide the route alone (admins may). */
export const raiserBlocked = (i: IssueOut, v: IssueViewer) =>
  !v.isAdmin && v.id != null && i.created_by === v.id

/**
 * The viewer's acts. The backend's `next_acts` wins when sent; otherwise the
 * rights of spec §12 are mirrored here from the viewer's roles.
 */
export function issueActs(i: IssueOut, v: IssueViewer): IssueAct[] {
  if (i.next_acts) return i.next_acts
  if (!isIssueOpen(i)) return []
  const acts: IssueAct[] = []
  const ownerDept = i.department_id != null && (v.myDepartmentIds ?? []).includes(i.department_id)
  const manage = !!v.canManage || !!v.isAdmin
  const decided = !!i.route
  if ((i.escalations ?? []).some((e) => e.can_acknowledge && !e.acknowledged_at)) acts.push('acknowledge')
  if (!decided && !i.contained_at && (ownerDept || manage)) acts.push('contain')
  if (!decided && !i.root_cause_at && (ownerDept || manage)) acts.push('root_cause')
  if (!decided && manage && !raiserBlocked(i, v)) acts.push('route')
  if (v.isSales && i.customer_inform && (!i.customer_decision || i.customer_decision === 'pending')) acts.push('customer')
  if (i.actions.some((a) => a.status === 'open' && (a.can_done
    || (v.id != null && a.owner_id === v.id)
    || (a.department_id != null && (v.myDepartmentIds ?? []).includes(a.department_id)) || manage))) acts.push('action_done')
  if (manage && decided && !i.check_id && !i.check_key && i.status === 'revalidation') acts.push('close')
  if (v.canSeeCosts && !i.cost_set && i.extra_cost == null) acts.push('cost')
  if (manage && decided && FIX_ROUTES.includes(i.route!)) acts.push('add_action')
  if (manage || v.isSales) acts.push('escalate')
  return acts
}

export const primaryAct = (acts: IssueAct[]): IssueAct | null =>
  acts.find((a) => !QUIET.includes(a)) ?? null

/**
 * The card's one primary button. The backend's `primary_act` wins when the
 * key is sent (null included): after a failed re-validation with every fix
 * action done it names add_action, which the quiet rule would never pick.
 */
export const issuePrimaryAct = (i: Pick<IssueOut, 'primary_act'>, acts: IssueAct[]): IssueAct | null =>
  i.primary_act !== undefined
    ? (i.primary_act && acts.includes(i.primary_act) ? i.primary_act : null)
    : primaryAct(acts)

/** The linked check's row in the validation panel (ValidationPanel's test id). */
export const recheckTarget = (i: Pick<IssueOut, 'check' | 'check_key' | 'check_department_id' | 'department_id'>): string | null => {
  const key = i.check?.check_key ?? i.check_key
  const dept = i.check?.department_id ?? i.check_department_id ?? i.department_id
  return key && dept != null ? `validation-check-${dept}-${key}` : null
}

// ---------------------------------------------------------------- dates

const DAY = 86_400_000
const dayNum = (iso: string) => {
  const [y, m, d] = iso.slice(0, 10).split('-').map(Number)
  return Math.round(Date.UTC(y, m - 1, d) / DAY)
}

/**
 * Working days (Mon to Fri) from `from` to `to`: 0 on the same day, +n when
 * `to` is n working days later, -n when earlier. Holidays are the server's
 * business; this is the fallback when it sends no count.
 */
export function workingDaysBetween(from: string, to: string): number {
  const a = dayNum(from); const b = dayNum(to)
  if (a === b) return 0
  const sign = b > a ? 1 : -1
  let n = 0
  for (let d = Math.min(a, b) + 1; d <= Math.max(a, b); d++) {
    const wd = new Date(d * DAY).getUTCDay()
    if (wd !== 0 && wd !== 6) n++
  }
  return sign * n
}

export const signedWd = (n: number) => `${n > 0 ? '+' : ''}${n} wd`
