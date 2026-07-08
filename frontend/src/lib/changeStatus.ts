import { CHANGE_STATUS_ORDER, type ChangeStatus, type GateKey } from '../types/change'

export const STATUS_LABELS: Record<ChangeStatus, string> = {
  captured: 'Captured', scoping: 'Scoping', in_assessment: 'In Assessment', costing: 'Costing',
  quoted: 'Quoted', approved: 'Approved', in_implementation: 'Implementing',
  in_validation: 'Validation', released: 'Released', closed: 'Closed',
  on_hold: 'On Hold', rejected: 'Rejected', cancelled: 'Cancelled',
}

export const NEXT_STATUS: Partial<Record<ChangeStatus, ChangeStatus[]>> = {
  captured: ['scoping'], scoping: ['in_assessment', 'rejected'],
  in_assessment: ['costing', 'rejected'],
  costing: ['quoted', 'approved'], quoted: ['approved', 'rejected'],
  approved: ['in_implementation'], in_implementation: ['in_validation'],
  in_validation: ['released'], released: ['closed'],
}

/** pill classes per status, dark-slate theme */
export const STATUS_PILL: Record<ChangeStatus, string> = {
  captured: 'bg-slate-700 text-slate-200',
  scoping: 'bg-violet-900 text-violet-200',
  in_assessment: 'bg-sky-900 text-sky-200',
  costing: 'bg-sky-900 text-sky-200',
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

/** Plain-language sublabels for on-path statuses, shown as tooltip + current-step hint. */
export const STATUS_HINTS: Partial<Record<ChangeStatus, string>> = {
  captured: 'Describe what should change',
  scoping: 'Meet, decide, pick departments',
  in_assessment: 'Departments check feasibility & cost',
  costing: 'Sum up costs',
  quoted: 'Offer sent to customer',
  approved: 'Go decision made',
  in_implementation: 'Doing the work',
  in_validation: 'Checking results',
  released: 'Change is live',
  closed: 'Wrapped up',
}

/** On-path step order for a given branch: customer-relevant changes keep `quoted`,
 * non-customer-relevant (internal) changes skip it. Mirrors the backend, which treats
 * any falsy customer_relevant (false OR null/undefined — e.g. a legacy change captured
 * before the flag existed) as internal, so `undefined` is treated as internal too. */
export function branchStepOrder(customerRelevant?: boolean): ChangeStatus[] {
  return !customerRelevant
    ? CHANGE_STATUS_ORDER.filter((s) => s !== 'quoted')
    : CHANGE_STATUS_ORDER
}

/** 0-based index + total on-path steps for `status` given the change's branch, or null
 * if `status` is off-path (on_hold/rejected/cancelled). */
export function stepPosition(
  status: ChangeStatus,
  customerRelevant?: boolean
): { index: number; total: number } | null {
  if (OFF_PATH_STATUSES.includes(status)) return null
  const order = branchStepOrder(customerRelevant)
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
