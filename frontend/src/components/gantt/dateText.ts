/** Date text for inputs: dd.mm.yyyy out, dd.mm.yyyy / dd.mm.yy / ISO in. */
import { isIsoDay } from './engine/calendar'
import { LIMITS, inYearRange } from './engine/types'

/** "05.10.2026" from an ISO day ('' stays ''). */
export function formatDateInput(iso: string | null | undefined): string {
  if (!iso || !isIsoDay(iso)) return ''
  return `${iso.slice(8, 10)}.${iso.slice(5, 7)}.${iso.slice(0, 4)}`
}

/**
 * Two-digit years: 00-69 are 20xx, 70-99 are 19xx (a pivot like Excel's).
 * Slashes are refused: 01/02/2026 could be January or February.
 */
export function yearOf(two: string): number {
  if (two.length !== 2) return Number(two)
  const n = Number(two)
  return n < 70 ? 2000 + n : 1900 + n
}

/** ISO day from what a user typed: dd.mm.yyyy, dd.mm.yy, d.m.yyyy, dd-mm-yyyy, yyyy-mm-dd; null when not a date or out of range. */
export function parseDateInput(text: string): string | null {
  return readDateInput(text).iso
}

/**
 * The typed text read as a date, with the reason when it is not one:
 * { iso } or { iso: null, error } ('' has neither).
 */
export function readDateInput(text: string): { iso: string | null; error: string | null } {
  const s = text.trim()
  if (!s) return { iso: null, error: null }
  if (s.includes('/')) return { iso: null, error: 'Use dd.mm.yyyy: a date with slashes could be read either way' }
  let iso: string | null = null
  if (/^\d{4}-\d{2}-\d{2}$/.test(s)) iso = s
  else {
    const m = /^(\d{1,2})[.-](\d{1,2})[.-](\d{2}|\d{4})$/.exec(s)
    if (m) iso = `${String(yearOf(m[3])).padStart(4, '0')}-${m[2].padStart(2, '0')}-${m[1].padStart(2, '0')}`
  }
  if (!iso || !isIsoDay(iso)) return { iso: null, error: 'Not a date: use dd.mm.yyyy' }
  if (!inYearRange(iso)) return { iso: null, error: `The year must be between ${LIMITS.minYear} and ${LIMITS.maxYear}` }
  return { iso, error: null }
}
