import { describe, it, expect } from 'vitest'
import {
  addDaysIso, daysUntil, formatCalendarDate, formatCalendarDateShort, formatDate, formatDateShort, formatDateTime, formatDayMonth, formatDays, formatHours, formatMoney,
  formatMoneyDelta, formatNumber, formatPercent, formatPiecePrice, formatTime, parseApiDateTime, todayIso,
} from './format'

// vitest pins TZ=Europe/Berlin (see vitest.config).
describe('formatDate / formatDateTime', () => {
  it('formats a date-only value from its text, never shifted by the time zone', () => {
    expect(formatDate('2026-01-01')).toBe('1 Jan 2026')
    expect(formatDateTime('2026-01-01')).toBe('1 Jan 2026')
  })

  it('reads a naive backend datetime as UTC and shows local time', () => {
    // 23:30 UTC on 31 Dec is already 1 Jan 00:30 in Berlin (CET, +1).
    expect(formatDate('2025-12-31T23:30:00')).toBe('1 Jan 2026')
    expect(formatDateTime('2025-12-31T23:30:00')).toBe('1 Jan 2026, 00:30')
    expect(formatDateTime('2026-07-01T10:00:00.123456')).toBe('1 Jul 2026, 12:00')
  })

  it('keeps an explicit offset or Z as given', () => {
    expect(formatDateTime('2026-07-01T10:00:00Z')).toBe('1 Jul 2026, 12:00')
    expect(formatDateTime('2026-07-01T10:00:00+02:00')).toBe('1 Jul 2026, 10:00')
    expect(parseApiDateTime('2026-07-01T10:00:00').toISOString()).toBe('2026-07-01T10:00:00.000Z')
  })

  it('renders missing values as "-" and passes unparseable text through', () => {
    expect(formatDate(undefined)).toBe('-')
    expect(formatDateTime(null)).toBe('-')
    expect(formatDateTime('soon')).toBe('soon')
  })
})

describe('formatDateShort / formatTime', () => {
  it('writes d MMM yy from an ISO date, a datetime or a Gantt day number', () => {
    expect(formatDateShort('2026-09-25')).toBe('25 Sep 26')
    expect(formatDateShort('2025-12-31T23:30:00')).toBe('1 Jan 26')
    expect(formatDateShort(Date.UTC(2026, 9, 5) / 86_400_000)).toBe('5 Oct 26')
    expect(formatDateShort(null)).toBe('-')
    expect(formatDateShort(NaN)).toBe('-')
    expect(formatDayMonth('2026-11-14')).toBe('14 Nov')
  })

  it('writes 24 h local time', () => {
    expect(formatTime('2026-07-01T12:05:00')).toBe('14:05')
    expect(formatTime('2026-07-01')).toBe('-')
  })
})

describe('numbers, money, percent, units (en-US)', () => {
  it('groups with commas and uses a decimal point', () => {
    expect(formatNumber(12345.5)).toBe('12,345.5')
    expect(formatNumber(2, { min: 2 })).toBe('2.00')
    expect(formatNumber(7, { sign: true })).toBe('+7')
    expect(formatNumber(undefined)).toBe('-')
  })

  it('writes money with 2 decimals and the ISO code', () => {
    expect(formatMoney(12345.5, 'USD')).toBe('12,345.50 USD')
    expect(formatMoney(-0.001, 'EUR')).toBe('0.00 EUR')
    expect(formatMoney(null)).toBe('-')
    expect(formatMoneyDelta(4626.5, 'USD')).toBe('+4,626.50 USD')
    expect(formatMoneyDelta(-2826.5, 'USD')).toBe('-2,826.50 USD')
    expect(formatMoneyDelta(0, 'USD')).toBe('0.00 USD')
  })

  it('writes piece prices with 2 to 4 decimals', () => {
    expect(formatPiecePrice(0.4125, 'EUR')).toBe('0.4125 EUR')
    expect(formatPiecePrice(1.5, 'EUR')).toBe('1.50 EUR')
    expect(formatPiecePrice(0.02, 'USD', { sign: true })).toBe('+0.02 USD')
  })

  it('writes percent with one decimal and no space', () => {
    expect(formatPercent(27.24)).toBe('27.2%')
    expect(formatPercent(0)).toBe('0.0%')
    expect(formatPercent(3, 0, { sign: true })).toBe('+3%')
  })

  it('writes hours and days with a narrow space', () => {
    expect(formatHours(13.5)).toBe('13.5\u202Fh')
    expect(formatDays(7)).toBe('7\u202Fd')
    expect(formatDays(7, { sign: true })).toBe('+7\u202Fd')
    expect(formatDays(-3, { sign: true })).toBe('-3\u202Fd')
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

// Also run under TZ=America/New_York (a scratch vitest config that overrides
// the pinned Europe/Berlin): the stored day must show in every zone.
describe('formatCalendarDate (due and target days, never shifted)', () => {
  it('shows the stored day of a date or a midnight datetime', () => {
    expect(formatCalendarDate('2026-10-05T00:00:00')).toBe('5 Oct 2026')
    expect(formatCalendarDate('2026-10-05')).toBe('5 Oct 2026')
    expect(formatCalendarDate('2026-01-01 00:00:00')).toBe('1 Jan 2026')
    expect(formatCalendarDate('2026-12-31T23:59:59.999')).toBe('31 Dec 2026')
    expect(formatCalendarDateShort('2026-09-25T00:00:00')).toBe('25 Sep 26')
  })

  it('differs from formatDate exactly where a zone west of UTC shifted the day', () => {
    const west = new Date(Date.UTC(2026, 9, 5)).getDate() !== 5
    expect(formatDate('2026-10-05T00:00:00')).toBe(west ? '4 Oct 2026' : '5 Oct 2026')
    expect(formatCalendarDate('2026-10-05T00:00:00')).toBe('5 Oct 2026')
  })

  it('renders missing as "-" and passes unreadable text through', () => {
    expect(formatCalendarDate(null)).toBe('-')
    expect(formatCalendarDate('')).toBe('-')
    expect(formatCalendarDateShort(undefined)).toBe('-')
    expect(formatCalendarDate('soon')).toBe('soon')
    expect(formatCalendarDate('2026-13-01')).toBe('2026-13-01')
    expect(formatCalendarDate('2026-10-05x')).toBe('2026-10-05x')
  })
})
