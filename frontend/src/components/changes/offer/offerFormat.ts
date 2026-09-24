/** Number, date and chip helpers shared by the offer workspace. */

const moneyFmt = new Map<string, Intl.NumberFormat>()

/** 2 decimals + currency code, de-DE grouping: "12.345,50 EUR". */
export function fmtMoney(v: number | null | undefined, currency = 'EUR'): string {
  if (v === null || v === undefined || Number.isNaN(v)) return '-'
  let f = moneyFmt.get('m')
  if (!f) {
    f = new Intl.NumberFormat('de-DE', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
    moneyFmt.set('m', f)
  }
  return `${f.format(v)} ${currency}`
}

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
export function fmtDate(iso: string | null | undefined): string {
  if (!iso) return '-'
  const [y, m, d] = iso.slice(0, 10).split('-')
  if (!y || !m || !d) return iso
  return `${d}.${m}.${y}`
}

/** Today as YYYY-MM-DD in local time. */
export function todayIso(): string {
  const n = new Date()
  const p = (x: number) => String(x).padStart(2, '0')
  return `${n.getFullYear()}-${p(n.getMonth() + 1)}-${p(n.getDate())}`
}

/** ISO day plus n calendar days. */
export function addDaysIso(iso: string, n: number): string {
  const [y, m, d] = iso.split('-').map(Number)
  const dt = new Date(Date.UTC(y, m - 1, d + n))
  return dt.toISOString().slice(0, 10)
}

/** green > 10 days, amber <= 10, red when expired. */
export function daysLeftTone(daysLeft: number | null | undefined, expired?: boolean): string {
  if (expired || (daysLeft != null && daysLeft < 0)) return 'bg-rose-950/60 text-rose-200 border-rose-800'
  if (daysLeft != null && daysLeft <= 10) return 'bg-amber-950/60 text-amber-200 border-amber-800'
  return 'bg-emerald-950/60 text-emerald-200 border-emerald-800'
}

/** Parse a user-typed number, accepting a comma decimal separator. */
export function parseNum(s: string): number | null {
  const t = s.trim().replace(/\s/g, '')
  if (t === '') return null
  const norm = t.includes(',') ? t.replace(/\./g, '').replace(',', '.') : t
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
