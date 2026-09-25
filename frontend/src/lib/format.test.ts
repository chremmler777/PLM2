import { describe, it, expect } from 'vitest'
import { addDaysIso, daysUntil, formatDate, formatDateTime, parseApiDateTime, todayIso } from './format'

// vitest pins TZ=Europe/Berlin (see vitest.config).
describe('formatDate / formatDateTime', () => {
  it('formats a date-only value from its text, never shifted by the time zone', () => {
    expect(formatDate('2026-01-01')).toBe('01.01.2026')
    expect(formatDateTime('2026-01-01')).toBe('01.01.2026')
  })

  it('reads a naive backend datetime as UTC and shows local time', () => {
    // 23:30 UTC on 31.12. is already 01.01. 00:30 in Berlin (CET, +1).
    expect(formatDate('2025-12-31T23:30:00')).toBe('01.01.2026')
    expect(formatDateTime('2025-12-31T23:30:00')).toBe('01.01.2026 00:30')
    expect(formatDateTime('2026-07-01T10:00:00.123456')).toBe('01.07.2026 12:00')
  })

  it('keeps an explicit offset or Z as given', () => {
    expect(formatDateTime('2026-07-01T10:00:00Z')).toBe('01.07.2026 12:00')
    expect(formatDateTime('2026-07-01T10:00:00+02:00')).toBe('01.07.2026 10:00')
    expect(parseApiDateTime('2026-07-01T10:00:00').toISOString()).toBe('2026-07-01T10:00:00.000Z')
  })

  it('renders missing values as "-" and passes unparseable text through', () => {
    expect(formatDate(undefined)).toBe('-')
    expect(formatDateTime(null)).toBe('-')
    expect(formatDateTime('soon')).toBe('soon')
  })
})

describe('daysUntil / todayIso / addDaysIso', () => {
  it('counts calendar days to a plain date from the local today, whatever the hour', () => {
    const late = new Date(2026, 9, 5, 23, 30).getTime()
    const early = new Date(2026, 9, 5, 0, 30).getTime()
    for (const now of [late, early]) {
      expect(daysUntil('2026-10-06', now)).toBe(1)
      expect(daysUntil('2026-10-05', now)).toBe(0)
      expect(daysUntil('2026-10-02', now)).toBe(-3)
    }
  })

  it('counts started days to a datetime, naive values read as UTC', () => {
    const now = Date.UTC(2026, 9, 5, 10, 0)
    expect(daysUntil('2026-10-05T22:00:00', now)).toBe(1)
    expect(daysUntil('2026-10-04T22:00:00Z', now)).toBe(0)
  })

  it('returns NaN for a garbage datetime instead of throwing or coercing to 0', () => {
    expect(Number.isNaN(daysUntil('not-a-date'))).toBe(true)
    expect(Number.isNaN(daysUntil(''))).toBe(true)
  })

  it('does calendar math without time-zone shifts', () => {
    expect(todayIso(new Date(2026, 0, 1, 0, 5))).toBe('2026-01-01')
    expect(addDaysIso('2026-03-28', 2)).toBe('2026-03-30')
    expect(addDaysIso('2026-12-30', 3)).toBe('2027-01-02')
  })
})
