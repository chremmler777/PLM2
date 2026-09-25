/**
 * The one number, money and date format of the app (en-US, see the UI polish
 * plan 2.1). Every screen formats through these helpers; nothing else calls
 * Intl, toLocale* or toFixed for display.
 *
 *   number     12,345.5            money        12,345.50 USD (ISO code, never summed across currencies)
 *   delta      +4,626.50 USD        piece price  0.4125 EUR (2 to 4 decimals)
 *   percent    27.2%                hours, days  13.5 h, 7 d, +7 d
 *   date       25 Sep 2026          compact      25 Sep 26 (tables, Gantt grid, chips)
 *   date+time  25 Sep 2026, 14:05   missing      -
 *   calendar day (due / target dates): formatCalendarDate, never shifted
 *   typed numbers: parseNumberInput ("." decimals, "," only in 3-digit groups)
 *
 * The customer offer PDF keeps its own per-currency locale (backend).
 */

export const LOCALE = 'en-US'

/** English month abbreviations, fixed (Intl en-GB would say "Sept"). */
export const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

/** Narrow no-break space between a number and its unit ("13.5 h"). */
const UNIT_SP = '\u202F'

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

const MS_DAY = 86_400_000

/** Year, month (0-11) and day of an ISO date or datetime; null when unreadable. */
function partsOf(iso: string): { y: number; m: number; d: number; dt: Date | null } | null {
  if (DATE_ONLY.test(iso)) {
    const [y, m, d] = iso.split('-').map(Number)
    return { y, m: m - 1, d, dt: null }
  }
  const dt = parseApiDateTime(iso)
  if (Number.isNaN(dt.getTime())) return null
  return { y: dt.getFullYear(), m: dt.getMonth(), d: dt.getDate(), dt }
}

/**
 * "25 Sep 2026" from an ISO date or datetime. A plain date ("2026-10-05") is
 * formatted from its text and never shifted by the time zone; a datetime is
 * read as UTC when naive and shown as the local calendar day. Unreadable
 * text passes through.
 */
export function formatDate(iso: string | null | undefined): string {
  if (!iso) return '-'
  const p = partsOf(iso)
  return p ? `${p.d} ${MONTHS[p.m]} ${p.y}` : iso
}

/**
 * "25 Sep 26" for tables, the Gantt grid and chips. Takes an ISO date or
 * datetime, or a Gantt day number (days since 1970-01-01, UTC).
 */
export function formatDateShort(v: string | number | null | undefined): string {
  if (v === null || v === undefined || v === '') return '-'
  if (typeof v === 'number') {
    if (Number.isNaN(v)) return '-'
    const dt = new Date(v * MS_DAY)
    return `${dt.getUTCDate()} ${MONTHS[dt.getUTCMonth()]} ${String(dt.getUTCFullYear()).slice(-2)}`
  }
  const p = partsOf(v)
  return p ? `${p.d} ${MONTHS[p.m]} ${String(p.y).slice(-2)}` : v
}

/**
 * The calendar day of a "date" field ("2026-10-05" or the midnight datetime
 * "2026-10-05T00:00:00" many date columns send), read from its first ten
 * characters with no time zone shift: a due date is the same day in Detroit
 * and in Berlin. Use formatDate for real timestamps (created_at, signed_at).
 */
function calendarParts(iso: string): { y: number; m: number; d: number } | null {
  const day = iso.slice(0, 10)
  if (!DATE_ONLY.test(day) || (iso.length > 10 && !/^[T ]/.test(iso.slice(10)))) return null
  const [y, m, d] = day.split('-').map(Number)
  if (m < 1 || m > 12 || d < 1 || d > 31) return null
  return { y, m: m - 1, d }
}

/** "25 Sep 2026" from a calendar-day field (date or midnight datetime), never shifted. */
export function formatCalendarDate(iso: string | null | undefined): string {
  if (!iso) return '-'
  const p = calendarParts(iso)
  return p ? `${p.d} ${MONTHS[p.m]} ${p.y}` : iso
}

/** "25 Sep 26": the compact form of formatCalendarDate. */
export function formatCalendarDateShort(iso: string | null | undefined): string {
  if (!iso) return '-'
  const p = calendarParts(iso)
  return p ? `${p.d} ${MONTHS[p.m]} ${String(p.y).slice(-2)}` : iso
}

/** "14 Nov": day and month only, for a sentence where the year is plain. */
export function formatDayMonth(iso: string | null | undefined): string {
  if (!iso) return '-'
  const p = partsOf(iso)
  return p ? `${p.d} ${MONTHS[p.m]}` : iso
}

/** "25 Sep 2026, 14:05" in local time (24 h); a naive backend datetime is read as UTC. */
export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return '-'
  const p = partsOf(iso)
  if (!p) return iso
  if (!p.dt) return formatDate(iso)
  return `${p.d} ${MONTHS[p.m]} ${p.y}, ${pad(p.dt.getHours())}:${pad(p.dt.getMinutes())}`
}

/** "14:05" in local time; a naive backend datetime is read as UTC. */
export function formatTime(iso: string | null | undefined): string {
  if (!iso || DATE_ONLY.test(iso)) return '-'
  const dt = parseApiDateTime(iso)
  if (Number.isNaN(dt.getTime())) return '-'
  return `${pad(dt.getHours())}:${pad(dt.getMinutes())}`
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

// ------------------------------------------------------------------ numbers

const fmtCache = new Map<string, Intl.NumberFormat>()
function nf(min: number, max: number): { format: (v: number) => string } {
  const key = `${min}-${max}`
  let f = fmtCache.get(key)
  if (!f) {
    f = new Intl.NumberFormat(LOCALE, { minimumFractionDigits: min, maximumFractionDigits: max })
    fmtCache.set(key, f)
  }
  const intl = f
  // A value that rounds to zero never shows as "-0.00".
  return { format: (v: number) => intl.format(Math.round(v * 10 ** max) === 0 ? 0 : v) }
}

const missing = (v: number | null | undefined): v is null | undefined =>
  v === null || v === undefined || Number.isNaN(v)

/** Sign prefix for an explicitly signed value: "+" only when it does not round to zero. */
function plus(v: number, max: number): string {
  return v > 0 && Math.round(v * 10 ** max) !== 0 ? '+' : ''
}

/** "12,345.5": en-US grouping, 0 to 2 decimals unless told otherwise. */
export function formatNumber(
  v: number | null | undefined,
  { min = 0, max = 2, sign = false }: { min?: number; max?: number; sign?: boolean } = {},
): string {
  if (missing(v)) return '-'
  return `${sign ? plus(v, max) : ''}${nf(min, Math.max(min, max)).format(v)}`
}

/** "12,345.50 USD": 2 decimals and the ISO code. Never add amounts of different currencies. */
export function formatMoney(amount: number | null | undefined, currency: string | null | undefined = 'EUR'): string {
  if (missing(amount)) return '-'
  return `${nf(2, 2).format(amount)} ${currency || 'EUR'}`
}

/** "+4,626.50 USD", "-2,826.50 USD", "0.00 USD". */
export function formatMoneyDelta(amount: number | null | undefined, currency: string | null | undefined = 'EUR'): string {
  if (missing(amount)) return '-'
  return `${plus(amount, 2)}${formatMoney(amount, currency)}`
}

/** "0.4125 EUR": piece prices carry 2 to 4 decimals; `sign` adds "+" to a rise. */
export function formatPiecePrice(
  v: number | null | undefined,
  currency: string | null | undefined = 'EUR',
  { sign = false }: { sign?: boolean } = {},
): string {
  if (missing(v)) return '-'
  return `${sign ? plus(v, 4) : ''}${nf(2, 4).format(v)} ${currency || 'EUR'}`
}

/** "27.2%" from a percent value (27.2, not 0.272); `sign` adds "+" to a rise. */
export function formatPercent(
  v: number | null | undefined,
  decimals = 1,
  { sign = false }: { sign?: boolean } = {},
): string {
  if (missing(v)) return '-'
  return `${sign ? plus(v, decimals) : ''}${nf(decimals, decimals).format(v)}%`
}

/** "13.5 h" (up to 2 decimals). */
export function formatHours(v: number | null | undefined): string {
  if (missing(v)) return '-'
  return `${nf(0, 2).format(v)}${UNIT_SP}h`
}

/** "7 d", or "+7 d" with `sign`. */
export function formatDays(v: number | null | undefined, { sign = false }: { sign?: boolean } = {}): string {
  if (missing(v)) return '-'
  return `${sign ? plus(v, 1) : ''}${nf(0, 1).format(v)}${UNIT_SP}d`
}

// ------------------------------------------------------------ number input

/** How a typed number was read: the value, or why it was not taken. */
export interface NumberInputRead {
  value: number | null
  /** 'invalid': not a number; 'ambiguous': a comma that is not a thousands group ("12,5"). */
  error: 'invalid' | 'ambiguous' | null
}

const COMMA_GROUPED = /^[+-]?[1-9]\d{0,2}(,\d{3})+$/
const PLAIN_NUMBER = /^[+-]?(\d+\.?\d*|\.\d+)$/

/**
 * A typed number, read en-US like it is shown: "." is the decimal point and
 * "," only groups thousands, every group exactly three digits ("12,500",
 * "1,234,567.5"). Any other comma ("12,5", "1,2345", "0,500", "1,") is
 * ambiguous: German for a decimal, so it is refused rather than guessed.
 * Spaces are dropped ("1 234.5"). Empty text is { value: null, error: null }.
 * Same rule as the backend's offer_service.read_number.
 */
export function readNumberInput(s: string): NumberInputRead {
  const t = s.trim().replace(/\s/g, '')
  if (t === '') return { value: null, error: null }
  let norm = t
  if (t.includes(',')) {
    const dot = t.indexOf('.')
    const int = dot < 0 ? t : t.slice(0, dot)
    if (!COMMA_GROUPED.test(int)) return { value: null, error: 'ambiguous' }
    norm = int.replace(/,/g, '') + (dot < 0 ? '' : t.slice(dot))
  }
  if (!PLAIN_NUMBER.test(norm)) return { value: null, error: 'invalid' }
  const n = Number(norm)
  return Number.isFinite(n) ? { value: n, error: null } : { value: null, error: 'invalid' }
}

/** The number a user typed (see readNumberInput); null when empty, not a number or ambiguous. */
export function parseNumberInput(s: string): number | null {
  return readNumberInput(s).value
}

/** The message for a refused number input. */
export const NUMBER_INPUT_HINT = 'Use a dot for decimals: 12.5, or 12,500 for twelve thousand five hundred'
