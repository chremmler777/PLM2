/**
 * The cost breakdown as the customer reads it on the offer PDF, rebuilt the
 * way backend/app/services/offer_pdf.py builds it (customer_cbd_lines and
 * spread_cbd), so the preview and the PDF say the same rows and amounts.
 *
 * Included lines are summed per customer category in print order; a line
 * without one (typed in by Sales, or an offer from before categories) keeps
 * its own label after them. Hidden factors (overhead and margin by default)
 * and, unless shown, the risk surcharges are folded into the positive rows in
 * proportion, so the rows add up with the printed rows below them to the total.
 */
import type { OfferData, OfferTotals } from '../../../types/changeOffer'

/** offer_pdf.CBD_ORDER */
export const CBD_ORDER = ['Engineering', 'Tooling', 'Sampling and trials', 'Machine time',
  'Supplier parts', 'Other']

/** offer_pdf.EXTRA_CBD_LABEL: the row a hidden amount goes on when no line can carry it. */
export const EXTRA_CBD_LABEL = 'Engineering and handling'

export interface CbdRow { label: string; amount: number }

const num = (v: unknown): number => {
  const n = typeof v === 'number' ? v : Number(v)
  return Number.isFinite(n) ? n : 0
}
/**
 * Python's round(v, 2) on a float: the exact binary value of `v`, rounded to
 * the cent with ties to even (round(0.125, 2) == 0.12, round(2.675, 2) ==
 * 2.67 because 2.675 is stored as 2.67499...). Decided on the exact value
 * (the double as mantissa x 2^exp, in BigInt), not on v * 100, which already
 * carries a rounding error. The PDF is rendered with Python, so the preview
 * has to round the same way to print the same cents.
 */
export function r2(v: number): number {
  if (!Number.isFinite(v) || v === 0) return v
  const view = new DataView(new ArrayBuffer(8))
  view.setFloat64(0, Math.abs(v))
  const hi = view.getUint32(0)
  const lo = view.getUint32(4)
  const expBits = (hi >>> 20) & 0x7ff
  const frac = (BigInt(hi & 0xfffff) << 32n) | BigInt(lo)
  const mant = expBits === 0 ? frac : frac | (1n << 52n)
  const exp = (expBits === 0 ? 1 : expBits) - 1075
  // An integer already: nothing after the point to round.
  if (exp >= 0) return v
  const scaled = mant * 100n
  const den = 1n << BigInt(-exp)
  let q = scaled / den
  const twice = (scaled % den) * 2n
  if (twice > den || (twice === den && q % 2n === 1n)) q += 1n
  const out = Number(q) / 100
  return v < 0 ? -out : out
}

/** Python's d.get(k, True): absent means true, a null that was sent means false. */
const flag = (v: boolean | null | undefined): boolean => (v === undefined ? true : !!v)

/** offer_pdf.customer_cbd_lines */
export function customerCbdLines(lines: { label?: string | null; amount?: number | null;
  customer_category?: string | null }[]): CbdRow[] {
  const sums = new Map<string, number>()
  const own: CbdRow[] = []
  for (const l of lines) {
    const cat = l.customer_category?.trim()
    if (cat) sums.set(cat, (sums.get(cat) ?? 0) + num(l.amount))
    else own.push({ label: l.label ?? '', amount: num(l.amount) })
  }
  const order = [...CBD_ORDER.filter((c) => sums.has(c)),
    ...[...sums.keys()].filter((c) => !CBD_ORDER.includes(c)).sort()]
  return [...order.map((c) => ({ label: c, amount: r2(sums.get(c)!) })), ...own]
}

/** offer_pdf.spread_cbd */
export function spreadCbd(lines: CbdRow[], hidden: number, target?: number): CbdRow[] {
  const amounts = lines.map((l) => r2(num(l.amount)))
  const t = r2(target ?? amounts.reduce((a, b) => a + b, 0) + hidden)
  const pos = amounts.flatMap((a, i) => (a > 0 ? [i] : []))
  const out = [...amounts]
  if (pos.length) {
    const base = pos.reduce((s, i) => s + amounts[i], 0)
    if (Math.abs(hidden) >= 0.005) for (const i of pos) out[i] = r2(amounts[i] + hidden * amounts[i] / base)
    const last = pos[pos.length - 1]
    out[last] = r2(t - (out.reduce((a, b) => a + b, 0) - out[last]))
    return lines.map((l, i) => ({ label: l.label, amount: out[i] }))
  }
  const rows = lines.map((l, i) => ({ label: l.label, amount: out[i] }))
  const rest = r2(t - out.reduce((a, b) => a + b, 0))
  if (Math.abs(rest) >= 0.005) rows.push({ label: EXTRA_CBD_LABEL, amount: rest })
  return rows
}

/** The detailed CBD rows the PDF prints for this offer (section 2, before
 *  the shown factors, risk, scrap and free rows). */
export function customerCbd(data: OfferData, totals: Partial<OfferTotals> | null | undefined): CbdRow[] {
  const factors = (totals?.factors ?? []) as { amount: number; show?: boolean | null }[]
  const shown = factors.filter((f) => flag(f.show))
  const showRisk = !!data.show_risk_surcharge
  const risks = num(totals?.risks_total)
  let hidden = factors.filter((f) => !flag(f.show)).reduce((s, f) => s + num(f.amount), 0)
  if (!showRisk) hidden += risks
  const included = customerCbdLines((data.cost_lines ?? []).filter((l) => flag(l.include)))
  const risksRow = showRisk && risks ? r2(risks) : 0
  const freeRows = (data.free_fields ?? []).filter((f) => num(f.amount)).map((f) => r2(num(f.amount)))
  const target = r2(num(totals?.total_one_time))
    - shown.reduce((s, f) => s + r2(num(f.amount)), 0)
    - risksRow - r2(num(totals?.scrap)) - freeRows.reduce((a, b) => a + b, 0)
  return spreadCbd(included, hidden, target)
}
