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
