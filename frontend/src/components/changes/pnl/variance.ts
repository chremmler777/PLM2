/** Variance chip tone for a P&L line or margin: green on or better than plan,
 *  amber when worse by up to 10 %, rose beyond that. */
export type Tone = 'green' | 'amber' | 'rose' | 'neutral'

export const TONE_CLASS: Record<Tone, string> = {
  green: 'bg-emerald-900/60 text-emerald-200',
  amber: 'bg-amber-900/60 text-amber-200',
  rose: 'bg-rose-900/60 text-rose-200',
  neutral: 'bg-slate-700 text-slate-300',
}

/**
 * better = +1 when more is better (revenue, margin), -1 when less is better
 * (cost). planned is the base the 10 % band is taken from.
 */
export function varianceTone(
  variance: number | null | undefined, planned: number | null | undefined, better: 1 | -1,
): Tone {
  if (variance === null || variance === undefined || !Number.isFinite(variance)) return 'neutral'
  const worse = -better * variance
  if (worse <= 0.005) return 'green'
  const base = Math.abs(planned ?? 0)
  if (base > 0.005 && worse / base <= 0.1) return 'amber'
  return 'rose'
}
