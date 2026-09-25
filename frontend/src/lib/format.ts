/**
 * One date and money format for the change screens: dd.mm.yyyy, dd.mm.yyyy
 * hh:mm and "12.345,50 EUR" (de-DE grouping, 2 decimals, currency code).
 * Missing values render as "-".
 */

const pad = (x: number) => String(x).padStart(2, '0')

const DATE_ONLY = /^\d{4}-\d{2}-\d{2}$/

/**
 * Parse a backend datetime. The backend sends naive UTC ("2026-10-05T08:07:00",
 * no offset); such a value is read as UTC so it shows in the viewer's local
 * time. Values with a "Z" or an explicit offset are parsed as given.
 */
export function parseApiDateTime(iso: string): Date {
  const naive = /^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2}(\.\d+)?)?$/.test(iso)
  return new Date(naive ? `${iso.replace(' ', 'T')}Z` : iso)
}

/**
 * dd.mm.yyyy from an ISO date or datetime. A plain date ("2026-10-05") is
 * formatted from its text and never shifted by the time zone; a datetime is
 * read as UTC when naive and shown as the local calendar day.
 */
export function formatDate(iso: string | null | undefined): string {
  if (!iso) return '-'
  if (DATE_ONLY.test(iso)) {
    const [y, m, d] = iso.split('-')
    return `${d}.${m}.${y}`
  }
  const dt = parseApiDateTime(iso)
  if (Number.isNaN(dt.getTime())) return iso
  return `${pad(dt.getDate())}.${pad(dt.getMonth() + 1)}.${dt.getFullYear()}`
}

/** dd.mm.yyyy hh:mm in local time; a naive backend datetime is read as UTC. */
export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return '-'
  if (DATE_ONLY.test(iso)) return formatDate(iso)
  const dt = parseApiDateTime(iso)
  if (Number.isNaN(dt.getTime())) return iso
  return `${pad(dt.getDate())}.${pad(dt.getMonth() + 1)}.${dt.getFullYear()} ${pad(dt.getHours())}:${pad(dt.getMinutes())}`
}

/** Today as YYYY-MM-DD in local time. */
export function todayIso(now: Date = new Date()): string {
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`
}

/** ISO day plus n calendar days (pure calendar math, no time zone). */
export function addDaysIso(iso: string, n: number): string {
  const [y, m, d] = iso.split('-').map(Number)
  return new Date(Date.UTC(y, m - 1, d + n)).toISOString().slice(0, 10)
}

/**
 * Days from now until a deadline. A plain date counts calendar days from
 * today (local), so "tomorrow" is 1 in every time zone; a datetime (naive
 * backend values read as UTC) counts started days, rounded up.
 */
export function daysUntil(iso: string, now: number = Date.now()): number {
  if (DATE_ONLY.test(iso)) {
    const [y, m, d] = iso.split('-').map(Number)
    const today = new Date(now)
    const from = Date.UTC(today.getFullYear(), today.getMonth(), today.getDate())
    return Math.round((Date.UTC(y, m - 1, d) - from) / 864e5)
  }
  const ms = parseApiDateTime(iso).getTime()
  if (Number.isNaN(ms)) return NaN
  return Math.ceil((ms - now) / 864e5) || 0 // no -0
}

const moneyFmt = new Intl.NumberFormat('de-DE', { minimumFractionDigits: 2, maximumFractionDigits: 2 })

/** "12.345,50 EUR". */
export function formatMoney(amount: number | null | undefined, currency: string | null | undefined = 'EUR'): string {
  if (amount === null || amount === undefined || Number.isNaN(amount)) return '-'
  return `${moneyFmt.format(amount)} ${currency || 'EUR'}`
}
