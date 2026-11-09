import { describe, expect, it } from 'vitest'
import { QueryClient } from '@tanstack/react-query'
import { invalidateChangeDetails, LIVE_REFETCH_MS } from './invalidateCosting'

// Christoph 2026-11-09 night: another department's input shows up live.
describe('invalidateChangeDetails', () => {
  it('marks every query of the change stale except the change itself, plus the task list', () => {
    const qc = new QueryClient()
    const keys: unknown[][] = [
      ['change', 7], ['change', 7, 'stage-state'], ['change', 7, 'finalize-check', 3],
      ['costing-positions', 7], ['change-routing', 7], ['change-my-actions', 7],
      ['change-my-tasks'], ['change', 8, 'stage-state'], ['costing-positions', 8], ['projects'],
    ]
    for (const k of keys) qc.setQueryData(k, { v: 1 })
    invalidateChangeDetails(qc, 7)
    const stale = (k: unknown[]) => qc.getQueryState(k)?.isInvalidated
    expect(stale(['change', 7])).toBe(false)
    expect(stale(['change', 7, 'stage-state'])).toBe(true)
    expect(stale(['change', 7, 'finalize-check', 3])).toBe(true)
    expect(stale(['costing-positions', 7])).toBe(true)
    expect(stale(['change-routing', 7])).toBe(true)
    expect(stale(['change-my-actions', 7])).toBe(true)
    expect(stale(['change-my-tasks'])).toBe(true)
    expect(stale(['change', 8, 'stage-state'])).toBe(false)
    expect(stale(['costing-positions', 8])).toBe(false)
    expect(stale(['projects'])).toBe(false)
  })

  it('polls within 20 s', () => {
    expect(LIVE_REFETCH_MS).toBeLessThanOrEqual(20_000)
  })
})
