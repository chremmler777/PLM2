import { describe, expect, it } from 'vitest'
import { planWeeks } from '../offer/offerFormat'

describe('planWeeks (G2)', () => {
  it('counts calendar weeks of the span, not working days / 7', () => {
    // 78 working days Mon 5 Oct 2026 .. Fri 22 Jan 2027: 110 calendar days = 16 weeks.
    expect(planWeeks({ start: '2026-10-05', finish: '2027-01-22' })).toBe(16)
    expect(planWeeks({ start: '2026-10-05', finish: '2026-10-05' })).toBe(1)
    expect(planWeeks({ start: null, finish: '2026-10-05' })).toBeNull()
  })
  it('still reads a bare number as calendar days', () => {
    expect(planWeeks(22)).toBe(4)
    expect(planWeeks(0)).toBeNull()
    expect(planWeeks(null)).toBeNull()
  })
})
