/** Number, date and chip helpers shared by the offer workspace. */
import { daysUntil, formatDate, formatMoney } from '../../../lib/format'

/** 2 decimals + currency code, de-DE grouping: "12.345,50 EUR". */
export const fmtMoney = formatMoney

/** Piece-price deltas carry 4 decimals. */
export function fmtPiece(v: number | null | undefined, currency = 'EUR'): string {
  if (v === null || v === undefined || Number.isNaN(v)) return '-'
  const f = new Intl.NumberFormat('de-DE', { minimumFractionDigits: 2, maximumFractionDigits: 4 })
  return `${v > 0 ? '+' : ''}${f.format(v)} ${currency}`
}

export function fmtPct(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return '-'
  return `${new Intl.NumberFormat('de-DE', { maximumFractionDigits: 1 }).format(v)} %`
}

/** dd.mm.yyyy from an ISO date or datetime. */
export const fmtDate = formatDate

export { todayIso, addDaysIso } from '../../../lib/format'

/** A result: green above zero, red below, neutral at zero or unknown. */
export function resultTone(v: number | null | undefined): string {
  if (v == null || Number.isNaN(v) || Math.abs(v) < 0.005) return 'text-slate-400'
  return v > 0 ? 'text-emerald-400' : 'text-rose-400'
}

/**
 * How long a sent offer still holds, counted here from valid_until (local
 * calendar days), so a null days_left from the server never reads "null d".
 * Accepted and declined offers do not count down: null.
 */
export function offerDaysLeft(o: { status: string; valid_until?: string | null; days_left?: number | null }): number | null {
  if (o.status !== 'sent' || !o.valid_until) return null
  const d = daysUntil(o.valid_until.slice(0, 10))
  return Number.isNaN(d) ? (o.days_left ?? null) : d
}

/** The validity chip's words: "Accepted", "12 d left", "expired". */
export function validityText(o: { status: string; valid_until?: string | null; days_left?: number | null; expired?: boolean }): string {
  if (o.status === 'accepted') return 'accepted'
  if (o.status === 'declined') return 'declined'
  const d = offerDaysLeft(o)
  if (o.expired || (d != null && d < 0)) return 'expired'
  return d == null ? '' : `${d} d left`
}

/** green > 10 days, amber <= 10, red when expired. */
export function daysLeftTone(daysLeft: number | null | undefined, expired?: boolean): string {
  if (expired || (daysLeft != null && daysLeft < 0)) return 'bg-rose-950/60 text-rose-200 border-rose-800'
  if (daysLeft != null && daysLeft <= 10) return 'bg-amber-950/60 text-amber-200 border-amber-800'
  return 'bg-emerald-950/60 text-emerald-200 border-emerald-800'
}

/**
 * Parse a user-typed number the German way: comma is the decimal separator,
 * dot groups thousands. "1.234" is 1234 (a dot followed by exactly three
 * digits, no comma), "1.234,5" is 1234.5, "1,5" is 1.5. A lone dot that is
 * not a thousands group ("1.5", "0.125", "1.2345") is still read as a decimal
 * point: a group never starts with 0. en-US input with both separators
 * ("1,234.50": comma groups, the dot last) is 1234.5. Returns null for
 * anything else ("1.23.4", "1'234", "abc"). Same rule as the backend's
 * offer_service.read_number.
 */
export function parseNum(s: string): number | null {
  const t = s.trim().replace(/\s/g, '')
  if (t === '') return null
  let norm: string
  if (t.includes(',') && t.includes('.') && t.lastIndexOf('.') > t.lastIndexOf(',')) {
    const dot = t.lastIndexOf('.')
    const int = t.slice(0, dot)
    const frac = t.slice(dot + 1)
    if (!/^[+-]?[1-9]\d{0,2}(,\d{3})+$/.test(int) || !/^\d+$/.test(frac)) return null
    norm = `${int.replace(/,/g, '')}.${frac}`
  } else if (t.includes(',')) {
    // Dots before the comma must be thousands groups.
    const [int, ...rest] = t.split(',')
    if (rest.length !== 1) return null
    if (int.includes('.') && !/^[+-]?[1-9]\d{0,2}(\.\d{3})+$/.test(int)) return null
    norm = `${int.replace(/\./g, '')}.${rest[0]}`
  } else if (/^[+-]?[1-9]\d{0,2}(\.\d{3})+$/.test(t)) {
    norm = t.replace(/\./g, '')
  } else {
    norm = t
  }
  if (!/^[+-]?(\d+\.?\d*|\.\d+)$/.test(norm)) return null
  const n = Number(norm)
  return Number.isFinite(n) ? n : null
}

export const inputCls =
  'bg-slate-900 border border-slate-700 rounded-md px-2 py-1 text-sm text-slate-100 '
  + 'placeholder:text-slate-600 focus:outline-none focus:border-sky-500 disabled:opacity-60'

export const sectionLabel = 'text-[11px] uppercase tracking-wider text-slate-500 font-medium'

export const DEFAULT_DISCLAIMER =
  'Draft timing. Final dates are confirmed after order according to shop, supplier and equipment availability.'

export const quotePlanKey = (changeId: number) => ['change', changeId, 'plan', 'quote'] as const

/** Weeks from the order milestone to the end of the plan, rounded up. */
export function planWeeks(durationDays: number | null | undefined): number | null {
  if (!durationDays || durationDays <= 0) return null
  return Math.ceil(durationDays / 7)
}

// ---------------------------------------------------------------- offer diff

const CHANGEOVER_LABEL: Record<string, string> = {
  running_change: 'Running change',
  customer_pays_scrap: 'Customer pays scrap',
}
const TERMS_LABEL: Record<string, string> = {
  payment: 'Payment terms', incoterms: 'Incoterms', delivery: 'Delivery', notes: 'Terms notes',
}

const RAW_LABEL: Record<string, string> = {
  total_one_time: 'Total one-time',
  piece_price_delta: 'Piece price delta',
  changeover: 'Changeover',
  scrap_qty: 'Scrap quantity',
  scrap_unit_price: 'Scrap unit price',
  weeks_from_order: 'Timing weeks from order',
}

/** The server names most rows already; raw keys get a readable name. */
export function diffLabel(field: string): string {
  if (RAW_LABEL[field]) return RAW_LABEL[field]
  const terms = /^Terms (\w+)$/.exec(field)
  if (terms) return TERMS_LABEL[terms[1]] ?? `Terms: ${terms[1].replace(/_/g, ' ')}`
  if (/^[a-z0-9_]+$/.test(field)) {
    const words = field.replace(/_/g, ' ')
    return words[0].toUpperCase() + words.slice(1)
  }
  return field
}

const numFmt = new Intl.NumberFormat('de-DE', { maximumFractionDigits: 4 })

/** A diff value in the words and units of its row. */
export function diffValue(rawField: string, v: unknown, currency = 'EUR'): string {
  const field = RAW_LABEL[rawField] ?? rawField
  if (v === null || v === undefined || v === '') return '-'
  if (typeof v === 'boolean') return v ? 'yes' : 'no'
  if (field === 'Changeover' && typeof v === 'string') return CHANGEOVER_LABEL[v] ?? v.replace(/_/g, ' ')
  if (typeof v === 'number') {
    if (field === 'Piece price delta') return fmtPiece(v, currency)
    if (field === 'Total one-time' || field === 'Scrap unit price' || field.startsWith('Cost line ')) {
      return fmtMoney(v, currency)
    }
    if (field === 'Timing weeks from order') return `${numFmt.format(v)} week${v === 1 ? '' : 's'}`
    if (field === 'Scrap quantity') return `${numFmt.format(v)} pcs`
    return numFmt.format(v)
  }
  if (Array.isArray(v)) return v.map((x) => diffValue(field, x, currency)).join(', ')
  if (typeof v === 'object') {
    return Object.entries(v as Record<string, unknown>)
      .filter(([, x]) => x !== null && x !== undefined && x !== '')
      .map(([k, x]) => `${k.replace(/_/g, ' ')}: ${diffValue(k, x, currency)}`).join(', ') || '-'
  }
  return String(v)
}
