/**
 * Christoph 2026-11-08: "everything input in costing needs a live update".
 * One helper every costing write calls (hours bookings, effort rows, cost
 * lines, supplier quotes and waits, no cost, finalize), so the department
 * section, its total, the standing effort rows, the PM costing overview,
 * the finalize-check banners and the header chips all refetch together.
 */
import type { QueryClient } from '@tanstack/react-query'

/** Input by another person shows up within this time while the tab is
 *  visible (react-query pauses interval refetches in a hidden tab). */
export const COSTING_REFETCH_MS = 20_000

/** The change page, My Tasks and the change list poll at this pace while
 *  visible, so another department's input shows up without a reload
 *  (Christoph 2026-11-09 night). */
export const LIVE_REFETCH_MS = COSTING_REFETCH_MS

/** Every query of one change except the change itself: ['change', id, ...]
 *  and the per-change keys (['costing-positions', id], ['change-routing', id],
 *  ['change-summation', id], ['change-my-actions', id], ...), plus the task
 *  list. Called when a poll brought a changed change back. */
export function invalidateChangeDetails(qc: QueryClient, changeId: number): void {
  qc.invalidateQueries({
    predicate: (q) => {
      const k = q.queryKey
      if (k[1] !== changeId) return false
      return k[0] === 'change' ? k.length > 2 : typeof k[0] === 'string'
    },
  })
  qc.invalidateQueries({ queryKey: ['change-my-tasks'] })
}

export function invalidateCosting(qc: QueryClient, changeId: number): void {
  // the lines and their totals
  qc.invalidateQueries({ queryKey: ['costing-positions', changeId] })
  qc.invalidateQueries({ queryKey: ['costing-context', changeId] })
  qc.invalidateQueries({ queryKey: ['change-summation', changeId] })
  // the change and everything under it: header chips, costing_pending /
  // finalized ids, ['change', id, 'finalize-check', dept], 'supplier-waits',
  // 'hours', 'impl-state', 'impl-bookings'
  qc.invalidateQueries({ queryKey: ['change', changeId] })
  // "Your actions" and the task list
  qc.invalidateQueries({ queryKey: ['change-my-actions', changeId] })
  qc.invalidateQueries({ queryKey: ['change-my-tasks'] })
}
