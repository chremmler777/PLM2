/**
 * Who may move a change where (spec §16 P1 4), and how a change that ended
 * reads (P1 7).
 *
 * The backend is the authority: when it sends `allowed_transitions` for the
 * viewer, that list decides. Until it does, this mirror hides the buttons the
 * backend would refuse, so nobody is offered a step that can only 403.
 */
import type { ChangeRequest, ChangeStatus } from '../types/change'

export interface Viewer {
  isAdmin: boolean
  isChangeLead: boolean
  isPm: boolean
  isSales: boolean
}

/**
 * The run team's moves (lead, PM, admin): stop, hold, recall, close the
 * assessment, and (ECR-solid C1) approve, start implementation and start
 * validation. Every move out of on_hold is theirs too (see below).
 */
const LEAD_PM_ADMIN_TARGETS = new Set<string>([
  'rejected', 'cancelled', 'on_hold', 'costing', 'approved', 'in_implementation', 'in_validation',
])

/**
 * Whether the viewer may move `change` to `to`. Only the transitions §16 names
 * are restricted here; every other step keeps its own gate (`needs`).
 */
export function mayTransition(
  change: Pick<ChangeRequest, 'status'>
    & Partial<Pick<ChangeRequest, 'allowed_transitions' | 'customer_relevant' | 'lead_id'>>,
  to: string,
  v: Viewer,
): boolean {
  if (Array.isArray(change.allowed_transitions)) return change.allowed_transitions.includes(to)
  const leadPmAdmin = v.isAdmin || v.isChangeLead || v.isPm
  const from = change.status
  // Resuming a hold (often "no PO yet") is the run team's (C1).
  if (from === 'on_hold') return leadPmAdmin
  // Sales captures customer changes; an internal change with a lead (P3: the
  // engineering raiser) is its run team's to hand over or reject.
  const salesCaptures = v.isSales && (change.customer_relevant !== false || change.lead_id == null)
  if (to === 'scoping') {
    // Kickoff from capture: Sales does the capture, so Sales may hand it over.
    if (from === 'captured') return leadPmAdmin || salesCaptures
    // Reopening a rejected change and recalling an assessment: lead/PM/admin.
    return leadPmAdmin
  }
  // Sales may reject at capture (the customer withdrew before scoping).
  if (to === 'rejected' && from === 'captured') return leadPmAdmin || salesCaptures
  // Costing back from quote creation is a reopen, gated elsewhere; from
  // assessment it closes the round: lead/PM/admin.
  if (to === 'costing' && from !== 'in_assessment') return true
  if (LEAD_PM_ADMIN_TARGETS.has(to)) return leadPmAdmin
  return true
}

export type EndState = 'rejected' | 'cancelled' | 'closed'

/** The end a change reached, or null while it is still running (on hold runs). */
export function endStateOf(
  change: Pick<ChangeRequest, 'status'> & Partial<Pick<ChangeRequest, 'rejected_at'>>,
): EndState | null {
  if (change.status === 'cancelled') return 'cancelled'
  if (change.status === 'rejected') return 'rejected'
  if (change.status === 'closed') return change.rejected_at ? 'rejected' : 'closed'
  return null
}

/** No live deadline on a change that has ended. */
export const hasEnded = (change: Pick<ChangeRequest, 'status'> & Partial<Pick<ChangeRequest, 'rejected_at'>>): boolean =>
  endStateOf(change) !== null

/** Human end label for lists: "Rejected", "Rejected, closed", "Cancelled". */
export function endLabel(change: Pick<ChangeRequest, 'status'> & Partial<Pick<ChangeRequest, 'rejected_at'>>): string | null {
  const e = endStateOf(change)
  if (e === 'cancelled') return 'Canceled'
  if (e === 'rejected') return change.status === 'closed' ? 'Rejected, closed' : 'Rejected'
  return null
}

/**
 * The stage a stopped change was in: the backend's `stopped_at`, else the last
 * status before the stop in the changelog (status rows, oldest first).
 */
export function stoppedAtFrom(
  change: Pick<ChangeRequest, 'status'> & Partial<Pick<ChangeRequest, 'stopped_at'>>,
  statusLog: { old_value?: string | null; new_value?: string | null }[] = [],
): ChangeStatus | null {
  if (change.stopped_at) return change.stopped_at
  const stops = statusLog.filter((e) => e.new_value === 'rejected' || e.new_value === 'cancelled')
  const last = stops[stops.length - 1]
  return (last?.old_value as ChangeStatus | undefined) ?? null
}
