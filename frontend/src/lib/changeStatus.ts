import type { ChangeStatus, GateKey } from '../types/change'

export const STATUS_LABELS: Record<ChangeStatus, string> = {
  captured: 'Captured', in_assessment: 'In Assessment', costing: 'Costing',
  quoted: 'Quoted', approved: 'Approved', in_implementation: 'Implementing',
  in_validation: 'Validation', released: 'Released', closed: 'Closed',
  on_hold: 'On Hold', rejected: 'Rejected', cancelled: 'Cancelled',
}

export const NEXT_STATUS: Partial<Record<ChangeStatus, ChangeStatus[]>> = {
  captured: ['in_assessment'], in_assessment: ['costing', 'rejected'],
  costing: ['quoted'], quoted: ['approved', 'rejected'],
  approved: ['in_implementation'], in_implementation: ['in_validation'],
  in_validation: ['released'], released: ['closed'],
}

/** pill classes per status, dark-slate theme */
export const STATUS_PILL: Record<ChangeStatus, string> = {
  captured: 'bg-slate-700 text-slate-200',
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

/** Which transition each gate guards. Mirrors GATE_TARGET_STATUS in
 * backend/app/models/change_cost.py — keep values in sync. */
export const GATE_TARGET_STATUS: Record<GateKey, ChangeStatus> = {
  feasibility: 'in_assessment',
  budget: 'costing',
  release: 'in_implementation',
}
