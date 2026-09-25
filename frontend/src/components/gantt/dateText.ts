/**
 * Date text for inputs: "25 Sep 2026" out; in, "25 Sep 2026", "25 sep 26",
 * "25-Sep-2026", ISO "2026-09-25", "25.09.2026", "25.09.26" and "25-09-2026".
 * Slashes are refused: 01/02/2026 could be January or February.
 */
import { isIsoDay } from './engine/calendar'
import { LIMITS, inYearRange } from './engine/types'
import { formatDate } from '../../lib/format'

/** The example every hint and message shows. */
export const DATE_EXAMPLE = '25 Sep 2026'

/** Placeholder of an empty date field. */
export const DATE_PLACEHOLDER = `e.g. ${DATE_EXAMPLE}`

/** "5 Oct 2026" from an ISO day ('' stays ''). */
export function formatDateInput(iso: string | null | undefined): string {
  if (!iso || !isIsoDay(iso)) return ''
  return formatDate(iso)
}

/**
 * Two-digit years: 00-69 are 20xx, 70-99 are 19xx (a pivot like Excel's).
 */
export function yearOf(two: string): number {
  if (two.length !== 2) return Number(two)
  const n = Number(two)
  return n < 70 ? 2000 + n : 1900 + n
}

const MONTH_NAMES = ['january', 'february', 'march', 'april', 'may', 'june', 'july', 'august', 'september', 'october', 'november', 'december']

/** Month 1-12 from a name or its start ("sep", "Sept", "September"); null when unknown. */
function monthOf(word: string): number | null {
  const w = word.toLowerCase().replace(/\.$/, '')
  if (w.length < 3) return null
  const i = MONTH_NAMES.findIndex((n) => n.startsWith(w))
  return i < 0 ? null : i + 1
}

const iso = (y: number, m: number, d: number) =>
  `${String(y).padStart(4, '0')}-${String(m).padStart(2, '0')}-${String(d).padStart(2, '0')}`

/** ISO day from what a user typed (see the header); null when not a date or out of range. */
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
  if (s.includes('/')) {
    return { iso: null, error: `Use ${DATE_EXAMPLE} or 25.09.2026: a date with slashes could be read either way` }
  }
  let out: string | null = null
  if (/^\d{4}-\d{2}-\d{2}$/.test(s)) out = s
  else {
    const num = /^(\d{1,2})[.-](\d{1,2})[.-](\d{2}|\d{4})$/.exec(s)
    const named = /^(\d{1,2})[\s.-]*([A-Za-z]+\.?)[\s.,-]*(\d{2}|\d{4})$/.exec(s)
    if (num) out = iso(yearOf(num[3]), Number(num[2]), Number(num[1]))
    else if (named) {
      const m = monthOf(named[2])
      if (m) out = iso(yearOf(named[3]), m, Number(named[1]))
    }
  }
  if (!out || !isIsoDay(out)) return { iso: null, error: `Not a date: use ${DATE_EXAMPLE}` }
  if (!inYearRange(out)) return { iso: null, error: `The year must be between ${LIMITS.minYear} and ${LIMITS.maxYear}` }
  return { iso: out, error: null }
}
