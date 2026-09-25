import { describe, expect, it } from 'vitest'
import {
  addDaysIso, dayOf, diff, durationBetween, durationFromLastDay, endOf, fmtDay, fmtIso, isIsoDay,
  isOffDay, isoWeek, isoWeekday, lastDay, makeCal, mondayOf, nextWork, normStart, prevWork, shift,
  startFor, toDay, toIso, todayDay, ymd,
} from './calendar'

const W = makeCal({ mode: 'working', workdays: [1, 2, 3, 4, 5], holidays: [] })
const C = makeCal({ mode: 'calendar', workdays: [1, 2, 3, 4, 5], holidays: [] })
const d = toDay
const iso = toIso

describe('ISO day conversion (UTC, DST free)', () => {
  it('round-trips an ordinary day', () => expect(iso(d('2026-10-05'))).toBe('2026-10-05'))
  it('round-trips a leap day', () => expect(iso(d('2024-02-29'))).toBe('2024-02-29'))
  it('crosses the spring DST switch by exactly one day', () => {
    expect(d('2026-03-30') - d('2026-03-29')).toBe(1)
    expect(addDaysIso('2026-03-28', 2)).toBe('2026-03-30')
  })
  it('crosses the autumn DST switch by exactly one day', () => {
    expect(d('2026-10-26') - d('2026-10-25')).toBe(1)
    expect(addDaysIso('2026-10-24', 3)).toBe('2026-10-27')
  })
  it('crosses a year end', () => expect(addDaysIso('2026-12-30', 3)).toBe('2027-01-02'))
  it('goes backwards over a month end', () => expect(addDaysIso('2026-03-01', -1)).toBe('2026-02-28'))
  it('handles leap years in day arithmetic', () => {
    expect(addDaysIso('2028-02-28', 1)).toBe('2028-02-29')
    expect(addDaysIso('2027-02-28', 1)).toBe('2027-03-01')
  })
  it('is zero at the epoch', () => expect(d('1970-01-01')).toBe(0))
  it('ignores a time suffix', () => expect(d('2026-10-05T23:30:00')).toBe(d('2026-10-05')))
  it('builds a day from y/m/d (month 0-based)', () => expect(iso(dayOf(2026, 9, 5))).toBe('2026-10-05'))
  it('splits a day into y/m/d', () => expect(ymd(d('2026-10-05'))).toEqual({ y: 2026, m: 9, d: 5 }))
  it('reads today from the local calendar', () => {
    expect(iso(todayDay(new Date(2026, 9, 25, 23, 59)))).toBe('2026-10-25')
    expect(iso(todayDay(new Date(2026, 2, 29, 0, 30)))).toBe('2026-03-29')
  })
})

describe('isIsoDay', () => {
  it('accepts valid days', () => expect(isIsoDay('2024-02-29')).toBe(true))
  it('rejects an impossible day', () => expect(isIsoDay('2026-02-29')).toBe(false))
  it('rejects month 13', () => expect(isIsoDay('2026-13-01')).toBe(false))
  it('rejects other shapes', () => {
    expect(isIsoDay('2026-1-5')).toBe(false)
    expect(isIsoDay('')).toBe(false)
    expect(isIsoDay(null)).toBe(false)
    expect(isIsoDay(20261005)).toBe(false)
  })
})

describe('weekdays and weeks', () => {
  it('numbers Monday 1 to Sunday 7', () => {
    expect(isoWeekday(d('2026-10-05'))).toBe(1)
    expect(isoWeekday(d('2026-10-10'))).toBe(6)
    expect(isoWeekday(d('2026-10-11'))).toBe(7)
    expect(isoWeekday(d('1970-01-01'))).toBe(4)
  })
  it('works for days before the epoch', () => expect(isoWeekday(d('1969-12-29'))).toBe(1))
  it('finds the Monday of a week', () => {
    expect(iso(mondayOf(d('2026-10-11')))).toBe('2026-10-05')
    expect(iso(mondayOf(d('2026-10-05')))).toBe('2026-10-05')
  })
  it('computes ISO weeks around year ends', () => {
    expect(isoWeek(d('2026-01-01'))).toBe(1)
    expect(isoWeek(d('2026-09-24'))).toBe(39)
    expect(isoWeek(d('2027-01-01'))).toBe(53)
    expect(isoWeek(d('2027-01-04'))).toBe(1)
    expect(isoWeek(d('2024-12-30'))).toBe(1)
  })
  it('formats days compactly', () => {
    expect(fmtDay(d('2026-10-05'))).toBe('5 Oct 26')
    expect(fmtDay(null)).toBe('-')
    expect(fmtDay(NaN)).toBe('-')
    expect(fmtIso('2027-01-02')).toBe('2 Jan 27')
    expect(fmtIso(null)).toBe('-')
  })
})

describe('makeCal', () => {
  it('defaults to calendar mode Mon-Fri', () => {
    const c = makeCal()
    expect(c.mode).toBe('calendar')
    expect(c.source.workdays).toEqual([1, 2, 3, 4, 5])
  })
  it('knows weekends and holidays as off days', () => {
    const c = makeCal({ mode: 'working', holidays: ['2026-10-07'] })
    expect(c.isWork(d('2026-10-06'))).toBe(true)
    expect(c.isWork(d('2026-10-07'))).toBe(false)
    expect(isOffDay(c, d('2026-10-10'))).toBe(true)
  })
  it('drops invalid holiday strings', () => {
    const c = makeCal({ mode: 'working', holidays: ['2026-10-07', 'nope', '2026-02-30'] })
    expect(c.source.holidays).toEqual(['2026-10-07'])
  })
  it('falls back to Mon-Fri when workdays are empty', () => {
    expect(makeCal({ mode: 'working', workdays: [] }).source.workdays).toEqual([1, 2, 3, 4, 5])
  })
  it('treats a calendar without any valid working weekday as calendar mode', () => {
    const c = makeCal({ mode: 'working', workdays: [9] })
    expect(c.mode).toBe('calendar')
    expect(shift(c, d('2026-10-05'), 3)).toBe(d('2026-10-08'))
  })
  it('supports a Sunday to Thursday week', () => {
    const c = makeCal({ mode: 'working', workdays: [7, 1, 2, 3, 4] })
    expect(c.isWork(d('2026-10-11'))).toBe(true) // Sunday
    expect(c.isWork(d('2026-10-09'))).toBe(false) // Friday
    // Sun 11 + 5 working days = Sun..Thu, exclusive end Friday 16.
    expect(iso(endOf(c, d('2026-10-11'), 5))).toBe('2026-10-16')
  })
})

describe('next / previous working day', () => {
  it('keeps a working day', () => expect(nextWork(W, d('2026-10-05'))).toBe(d('2026-10-05')))
  it('moves Saturday to Monday', () => expect(iso(nextWork(W, d('2026-10-10')))).toBe('2026-10-12'))
  it('moves Saturday back to Friday', () => expect(iso(prevWork(W, d('2026-10-10')))).toBe('2026-10-09'))
  it('skips a holiday Monday', () => {
    const c = makeCal({ mode: 'working', holidays: ['2026-10-12'] })
    expect(iso(nextWork(c, d('2026-10-10')))).toBe('2026-10-13')
  })
  it('is the identity in calendar mode', () => {
    expect(nextWork(C, d('2026-10-10'))).toBe(d('2026-10-10'))
    expect(prevWork(C, d('2026-10-10'))).toBe(d('2026-10-10'))
  })
})

describe('shift', () => {
  it('adds plain days in calendar mode', () => expect(iso(shift(C, d('2026-10-09'), 3))).toBe('2026-10-12'))
  it('subtracts plain days in calendar mode', () => expect(iso(shift(C, d('2026-10-12'), -3))).toBe('2026-10-09'))
  it('is the identity for 0', () => expect(shift(W, d('2026-10-10'), 0)).toBe(d('2026-10-10')))
  it('counts working days forward from a Saturday end', () => {
    // Task ends Fri (exclusive Sat 10); +2 working days -> starts Wed 14.
    expect(iso(shift(W, d('2026-10-10'), 2))).toBe('2026-10-14')
  })
  it('counts working days backward (lead)', () => expect(iso(shift(W, d('2026-10-10'), -2))).toBe('2026-10-08'))
  it('skips holidays going forward', () => {
    const c = makeCal({ mode: 'working', holidays: ['2026-10-06'] })
    expect(iso(shift(c, d('2026-10-05'), 2))).toBe('2026-10-08')
  })
  it('skips holidays going backward', () => {
    const c = makeCal({ mode: 'working', holidays: ['2026-10-08'] })
    expect(iso(shift(c, d('2026-10-10'), -2))).toBe('2026-10-07')
  })
})

describe('task ends and durations', () => {
  it('calendar: end = start + duration', () => expect(iso(endOf(C, d('2026-10-05'), 5))).toBe('2026-10-10'))
  it('working: Mon + 5 ends Saturday (last day Friday)', () => {
    expect(iso(endOf(W, d('2026-10-05'), 5))).toBe('2026-10-10')
    expect(iso(lastDay(W, d('2026-10-05'), 5))).toBe('2026-10-09')
  })
  it('working: a task across the weekend', () => expect(iso(endOf(W, d('2026-10-08'), 3))).toBe('2026-10-13'))
  it('working: a holiday inside the task stretches it', () => {
    const c = makeCal({ mode: 'working', holidays: ['2026-10-07'] })
    expect(iso(endOf(c, d('2026-10-05'), 5))).toBe('2026-10-13')
  })
  it('working: a holiday on the start day moves the start', () => {
    const c = makeCal({ mode: 'working', holidays: ['2026-10-05'] })
    expect(iso(normStart(c, d('2026-10-05')))).toBe('2026-10-06')
    expect(iso(endOf(c, d('2026-10-05'), 1))).toBe('2026-10-07')
  })
  it('working: a weekend start snaps to Monday', () => expect(iso(endOf(W, d('2026-10-10'), 1))).toBe('2026-10-13'))
  it('milestone: ends on its (normalised) start', () => {
    expect(endOf(C, d('2026-10-10'), 0)).toBe(d('2026-10-10'))
    expect(iso(endOf(W, d('2026-10-10'), 0))).toBe('2026-10-12')
  })
  it('milestone: last day is the start', () => expect(lastDay(W, d('2026-10-07'), 0)).toBe(d('2026-10-07')))
  it('startFor inverts endOf', () => {
    expect(iso(startFor(W, d('2026-10-10'), 5))).toBe('2026-10-05')
    expect(iso(startFor(C, d('2026-10-10'), 5))).toBe('2026-10-05')
    expect(startFor(W, d('2026-10-10'), 0)).toBe(d('2026-10-10'))
  })
  it('startFor from a Monday end lands on Friday for one day', () => {
    expect(iso(startFor(W, d('2026-10-12'), 1))).toBe('2026-10-09')
  })
  it('diff counts working days in [a, b)', () => {
    expect(diff(W, d('2026-10-05'), d('2026-10-12'))).toBe(5)
    expect(diff(W, d('2026-10-12'), d('2026-10-05'))).toBe(-5)
    expect(diff(W, d('2026-10-10'), d('2026-10-12'))).toBe(0)
    expect(diff(C, d('2026-10-05'), d('2026-10-12'))).toBe(7)
  })
  it('durationBetween and durationFromLastDay', () => {
    expect(durationBetween(W, d('2026-10-05'), d('2026-10-10'))).toBe(5)
    expect(durationBetween(C, d('2026-10-05'), d('2026-10-03'))).toBe(0)
    expect(durationFromLastDay(W, d('2026-10-08'), d('2026-10-12'))).toBe(3)
    expect(durationFromLastDay(C, d('2026-10-05'), d('2026-10-09'))).toBe(5)
    expect(durationFromLastDay(C, d('2026-10-05'), d('2026-10-01'))).toBe(1)
  })
  it('long working durations stay exact over DST', () => {
    // 20 working days from Mon 12 Oct 2026 crosses the 25 Oct switch: ends Sat 7 Nov.
    expect(iso(endOf(W, d('2026-10-12'), 20))).toBe('2026-11-07')
  })
})
