import { CHANGE_STATUS_ORDER, type ChangeStatus, type GateKey } from '../types/change'

export const STATUS_LABELS: Record<ChangeStatus, string> = {
  captured: 'Captured', scoping: 'Scoping', in_assessment: 'In Assessment', costing: 'Costing',
  quoting: 'Quote creation', quoted: 'Quoted', approved: 'Approved', in_implementation: 'Implementing',
  in_validation: 'Validation', released: 'Released', closed: 'Closed',
  on_hold: 'On Hold', rejected: 'Rejected', cancelled: 'Cancelled',
}

/**
 * Statuses reachable from each status. Used both for the advance buttons and to
 * decide which gates are currently blocking, so it must stay a statement about
 * reachability — not about which buttons happen to be shown. See
 * DECIDED_BY_MEETING for the statuses whose buttons are deliberately withheld.
 */
export const NEXT_STATUS: Partial<Record<ChangeStatus, ChangeStatus[]>> = {
  captured: ['scoping'], scoping: ['in_assessment', 'rejected'],
  in_assessment: ['costing', 'rejected'],
  costing: ['quoting', 'quoted', 'approved'],
  quoting: ['quoted', 'approved', 'rejected'],
  quoted: ['approved', 'rejected'],
  approved: ['in_implementation'], in_implementation: ['in_validation'],
  in_validation: ['released'], released: ['closed'],
}

/** pill classes per status, dark-slate theme */
export const STATUS_PILL: Record<ChangeStatus, string> = {
  captured: 'bg-slate-700 text-slate-200',
  scoping: 'bg-violet-900 text-violet-200',
  in_assessment: 'bg-sky-900 text-sky-200',
  costing: 'bg-sky-900 text-sky-200',
  quoting: 'bg-indigo-900 text-indigo-200',
  quoted: 'bg-indigo-900 text-indigo-200',
  approved: 'bg-emerald-900 text-emerald-200',
  in_implementation: 'bg-amber-900 text-amber-200',
  in_validation: 'bg-amber-900 text-amber-200',
  released: 'bg-emerald-900 text-emerald-200',
  closed: 'bg-slate-700 text-slate-300',
  on_hold: 'bg-amber-900 text-amber-200',
  rejected: 'bg-red-900 text-red-200',
  cancelled: 'bg-red-900 text-red-200',
}

export const OFF_PATH_STATUSES: ChangeStatus[] = ['on_hold', 'rejected', 'cancelled']

/**
 * Statuses whose onward move is the scoping meeting's call, not a button's.
 * Proceeding and rejecting both require a recorded decision (meeting, chat or
 * email) — and since migrations 037/038 a reason as well. A plain advance
 * button would bypass both, so it is withheld and the cockpit points at the
 * scoping tab instead. These transitions remain reachable, which is why
 * NEXT_STATUS still lists them: gate relevance is computed from it.
 */
export const DECIDED_BY_MEETING: ChangeStatus[] = ['scoping']

/** Plain-language sublabels for on-path statuses, shown as tooltip + current-step hint. */
export const STATUS_HINTS: Partial<Record<ChangeStatus, string>> = {
  captured: 'Describe what should change',
  scoping: 'Meet, decide, pick departments',
  in_assessment: 'Departments check feasibility & cost',
  costing: 'Sum up costs',
  quoting: 'Sales builds the offer from the costing wrap-up',
  quoted: 'Offer sent to customer',
  approved: 'Go decision made',
  in_implementation: 'Doing the work',
  in_validation: 'Checking results',
  released: 'Change is live',
  closed: 'Wrapped up',
}

/**
 * Mother-plant side track (spec §14): no assessment, costing or quote. The
 * mother plant engineered and sold the change; scoping informs the team and
 * goes straight to approved (the backend refuses everything else).
 */
export const MOTHER_PLANT_STEP_ORDER: ChangeStatus[] = [
  'captured', 'scoping', 'approved', 'in_implementation', 'in_validation', 'released', 'closed',
]

/** NEXT_STATUS for one change: the mother-plant side track leaves scoping for approved. */
export function nextStatusesFor(status: ChangeStatus, origin?: string | null): ChangeStatus[] {
  if (origin === 'mother_plant' && status === 'scoping') return ['approved', 'rejected']
  return NEXT_STATUS[status] ?? []
}

/** On-path step order for a given branch: customer-relevant changes keep `quoted`,
 * non-customer-relevant (internal) changes skip it. Mirrors the backend, which treats
 * any falsy customer_relevant (false OR null/undefined — e.g. a legacy change captured
 * before the flag existed) as internal, so `undefined` is treated as internal too. */
export function branchStepOrder(customerRelevant?: boolean, origin?: string | null): ChangeStatus[] {
  // The mother-plant side track (spec §14) shows only the stages it uses.
  if (origin === 'mother_plant') return MOTHER_PLANT_STEP_ORDER
  return !customerRelevant
    // An internal change is never offered, so neither quoting step applies.
    ? CHANGE_STATUS_ORDER.filter((s) => s !== 'quoting' && s !== 'quoted')
    : CHANGE_STATUS_ORDER
}

/** 0-based index + total on-path steps for `status` given the change's branch, or null
 * if `status` is off-path (on_hold/rejected/cancelled). */
export function stepPosition(
  status: ChangeStatus,
  customerRelevant?: boolean,
  origin?: string | null,
): { index: number; total: number } | null {
  if (OFF_PATH_STATUSES.includes(status)) return null
  const order = branchStepOrder(customerRelevant, origin)
  const index = order.indexOf(status)
  if (index === -1) return null
  return { index, total: order.length }
}

/** Which transition each gate guards. Mirrors GATE_TARGET_STATUS in
 * backend/app/models/change_cost.py — keep values in sync. */
export const GATE_TARGET_STATUS: Record<GateKey, ChangeStatus> = {
  feasibility: 'in_assessment',
  budget: 'costing',
  release: 'in_implementation',
}

/**
 * Stepper names where the stage reads better by its work than by its status:
 * at `approved` the open job is the detailed timing, so the node says so. The
 * status itself (and every advance button) keeps its own label.
 */
export const STEPPER_LABELS: Partial<Record<ChangeStatus, string>> = {
  approved: 'Timing',
}
export const stepperLabel = (s: ChangeStatus): string => STEPPER_LABELS[s] ?? STATUS_LABELS[s]

/**
 * The change detail tabs (spec 2026-09-25 section 9). Governance tabs (d1,
 * audit) sit in their own group on the right.
 */
export type ChangeTab =
  | 'overview' | 'scoping' | 'impacted' | 'assessments'
  | 'costing' | 'offer' | 'mother' | 'timing' | 'release' | 'd1' | 'audit'

export const EVERYDAY_TABS: ChangeTab[] = [
  'overview', 'scoping', 'impacted', 'assessments', 'costing', 'offer', 'timing', 'release',
]
/** Mother plant (spec §14): Assessments, Costing and Offer become one "Mother plant" tab. */
export const MOTHER_PLANT_TABS: ChangeTab[] = [
  'overview', 'scoping', 'impacted', 'mother', 'timing', 'release',
]
export const everydayTabsFor = (origin?: string | null): ChangeTab[] =>
  origin === 'mother_plant' ? MOTHER_PLANT_TABS : EVERYDAY_TABS
export const GOVERNANCE_TABS: ChangeTab[] = ['d1', 'audit']
export const ALL_TABS: ChangeTab[] = [...EVERYDAY_TABS, 'mother', ...GOVERNANCE_TABS]

/** Each phase-bound tab opens when the change reaches its phase. */
export const TAB_UNLOCK_STATUS: Partial<Record<ChangeTab, ChangeStatus>> = {
  scoping: 'scoping',
  impacted: 'scoping',
  assessments: 'in_assessment',
  costing: 'costing',
  // The quote plan can be prepared while costing still runs.
  offer: 'costing',
  timing: 'approved',
  release: 'in_validation',
}

/** The tab where the change's current phase is worked. */
export const STATUS_ACTIVE_TAB: Partial<Record<ChangeStatus, ChangeTab>> = {
  captured: 'scoping', scoping: 'scoping',
  in_assessment: 'assessments',
  costing: 'costing',
  quoting: 'offer', quoted: 'offer',
  approved: 'timing', in_implementation: 'timing',
  in_validation: 'release', released: 'release',
}

/**
 * The tabs where the change's current phase is worked, given its branch. An
 * internal change at costing is approved by PM on the Approval (offer) tab
 * while the departments still enter lines on costing, so both are active.
 */
export function activeTabsFor(status: string, customerRelevant?: boolean | null,
  origin?: string | null): ChangeTab[] {
  // Mother plant: scoping is informing the team, worked on its own tab.
  if (origin === 'mother_plant' && status === 'scoping') return ['mother']
  const tab = STATUS_ACTIVE_TAB[status as ChangeStatus]
  if (!tab) return []
  if (status === 'costing' && !customerRelevant) return ['costing', 'offer']
  return [tab]
}

const RELEASE_STAGE: string[] = ['in_validation', 'released', 'closed']

/**
 * A tab name as links, actions and waits may still send it: the old
 * `commercial` and `implementation` tabs resolve to the new tab for the
 * change's stage. Unknown names come back as null.
 */
export function resolveChangeTab(raw: string | null | undefined, status: string,
  origin?: string | null): ChangeTab | null {
  if (!raw) return null
  // A mother-plant change has no assessment, costing or offer: those names
  // (and their aliases) land on its Mother plant tab.
  if (origin === 'mother_plant'
    && ['assessments', 'costing', 'offer', 'commercial', 'quote', 'quoting'].includes(raw)) return 'mother'
  if (origin !== 'mother_plant' && raw === 'mother') return null
  if (raw === 'commercial') return status === 'costing' ? 'costing' : 'offer'
  if (raw === 'implementation') return RELEASE_STAGE.includes(status) ? 'release' : 'timing'
  if (raw === 'quote' || raw === 'quoting') return 'offer'
  if (raw === 'validation') return 'release'
  return (ALL_TABS as string[]).includes(raw) ? raw as ChangeTab : null
}

/** Display name of a tab (also for the aliases). */
export function changeTabLabel(raw: string, customerRelevant?: boolean | null, status = ''): string {
  const tb = resolveChangeTab(raw, status) ?? raw
  switch (tb) {
    case 'overview': return 'Overview'
    case 'scoping': return 'Scoping'
    case 'impacted': return 'Impacted'
    case 'assessments': return 'Assessments'
    case 'costing': return 'Costing'
    case 'offer': return customerRelevant ? 'Offer' : 'Approval'
    case 'mother': return 'Mother plant'
    case 'timing': return 'Timing'
    case 'release': return 'Release'
    case 'd1': return 'D1'
    case 'audit': return 'Audit'
    default: return tb ? tb[0].toUpperCase() + tb.slice(1) : tb
  }
}

/** A changelog value as plain text. The API returns plain values, but the
 *  column stores JSON text ('"on_hold"'), so an older backend or a cached
 *  response may still carry the encoded form: decode a JSON string, keep
 *  anything else as it is. */
export function decodeLogValue(v: string | null | undefined): string | null {
  if (v == null) return null
  if (v.startsWith('"')) {
    try {
      const parsed: unknown = JSON.parse(v)
      if (typeof parsed === 'string') return parsed
    } catch {
      // not JSON: keep the text
    }
  }
  return v
}
