/**
 * The exchange rates of a cost sheet version (106): "1 USD = 17.30 MXN" for
 * each two-currency plant's pair. Sales or Finance type them on the draft;
 * publishing freezes them with the rates, so an old change keeps the rate
 * of its version. The number is sent as typed (17.30 stays 17.30); "17,30"
 * is refused as ambiguous, like every number input.
 */
import { useEffect, useId, useState } from 'react'
import { NUMBER_INPUT_HINT, NUMBER_INPUT_INVALID, formatNumber, readNumberInput } from '../../lib/format'
import type { FxRate } from '../../types/costSheet'

interface Pair { pair: string; base: string; quote: string }

interface Props {
  rates: FxRate[]
  needed: Pair[]
  editable: boolean
  busy?: boolean
  version: number
  onSet: (base: string, quote: string, rate: string | null) => void
}

/**
 * A typed rate, read like every number input (lib/format readNumberInput):
 * "17.30" and "1,500" (= 1500) are read, "17,30" is refused as ambiguous
 * rather than guessed (re-check walk P3-4). The digits go to the server as
 * typed, only the thousands separators dropped ("17.30" stays "17.30").
 * A refusal carries the reason to show.
 */
export function readFxInput(raw: string): { value: string | null } | { refused: string } {
  const t = raw.trim()
  if (!t) return { value: null }
  const r = readNumberInput(t)
  if (r.error === 'ambiguous') return { refused: NUMBER_INPUT_HINT }
  if (r.error || r.value === null) return { refused: NUMBER_INPUT_INVALID }
  if (r.value <= 0) return { refused: 'An exchange rate is a number above 0' }
  return { value: t.replace(/[,\s\u00A0\u202F]/g, '').replace(/^\+/, '') }
}

/** 1 / rate with 4 decimals ("17.30" -> "0.0578"); null when not a number. */
export function inverse(rate: string): string | null {
  const n = Number(rate)
  if (!Number.isFinite(n) || n <= 0) return null
  return formatNumber(1 / n, { min: 4, max: 4 })
}

/** One pair: "1 USD = [17.30] MXN (1 MXN = 0.0578 USD)". Editable, the
 * reverse follows the field as it is typed; a refused rate puts the field
 * back on the saved one and says why next to it. */
function FxPair({ p, current, editable, busy, onSet }: {
  p: Pair; current: string | null; editable: boolean; busy?: boolean
  onSet: (base: string, quote: string, rate: string | null) => void
}) {
  const [draft, setDraft] = useState(current ?? '')
  const [refused, setRefused] = useState<string | null>(null)
  const msgId = useId()
  useEffect(() => { setDraft(current ?? '') }, [current])
  const commit = () => {
    if (draft === (current ?? '')) return
    const r = readFxInput(draft)
    if ('refused' in r) {
      setRefused(`"${draft.trim()}" not saved. ${r.refused}`)
      setDraft(current ?? '')
      return
    }
    setRefused(null)
    if (r.value !== current) onSet(p.base, p.quote, r.value)
  }
  // the reverse of what the field holds now; while the text is not a rate
  // (half typed), the saved rate's
  const typed = editable ? readFxInput(draft) : null
  const shownRate = typed && 'value' in typed ? typed.value : current
  const rev = shownRate ? inverse(shownRate) : null
  return (
    <span className="inline-flex items-center gap-1.5 text-slate-300">
      <span className="tabular-nums">1 {p.base} =</span>
      {editable ? (
        <span className="inline-flex flex-col">
          <input aria-label={`${p.quote} per ${p.base}`} data-testid={`fx-input-${p.pair}`}
            inputMode="decimal" value={draft} disabled={busy} placeholder="Not set"
            aria-describedby={refused ? msgId : undefined}
            onChange={(e) => { setDraft(e.target.value); setRefused(null) }}
            onBlur={commit}
            onKeyDown={(e) => {
              if (e.key === 'Enter') (e.target as HTMLInputElement).blur()
              if (e.key === 'Escape') { setDraft(current ?? ''); setRefused(null) }
            }}
            className={`w-24 rounded border bg-slate-900/60 px-2 py-1 text-right text-sm tabular-nums text-slate-100 placeholder:text-amber-400/70 focus:border-sky-500 focus:outline-none focus:ring-1 focus:ring-sky-500/40 ${
              refused ? 'border-rose-500' : 'border-slate-700'}`} />
          {refused && (
            <span id={msgId} role="alert" data-testid={`fx-refused-${p.pair}`}
              className="mt-0.5 max-w-[16rem] text-[11px] leading-tight text-rose-300">
              {refused}
            </span>
          )}
        </span>
      ) : (
        <span data-testid={`fx-value-${p.pair}`}
          className={`font-medium tabular-nums ${current ? 'text-slate-100' : 'text-amber-300'}`}>
          {current ?? 'not set'}
        </span>
      )}
      <span>{p.quote}</span>
      {rev && (
        // the other way round, so the direction is never in doubt
        <span data-testid={`fx-inverse-${p.pair}`} className="text-xs text-slate-500 tabular-nums">
          (1 {p.quote} = {rev} {p.base})
        </span>
      )}
      {!current && (
        <span className="text-xs text-amber-300/90">
          Rates typed in {p.quote} cannot be priced until it is set.
        </span>
      )}
    </span>
  )
}

export default function FxRates({ rates, needed, editable, busy, version, onSet }: Props) {
  const byPair = new Map(rates.map((r) => [r.pair, r]))
  const pairs: Pair[] = [...needed]
  for (const r of rates) if (!pairs.some((p) => p.pair === r.pair)) pairs.push(r)
  if (pairs.length === 0) return null
  return (
    <div data-testid="fx-rates"
      className="flex flex-wrap items-center gap-x-5 gap-y-2 rounded-lg border border-slate-700 bg-slate-800/40 px-4 py-2.5 text-sm">
      <span className="text-xs uppercase tracking-wide text-slate-500">Exchange rates</span>
      {pairs.map((p) => (
        <FxPair key={p.pair} p={p} current={byPair.get(p.pair)?.rate ?? null}
          editable={editable} busy={busy} onSet={onSet} />
      ))}
      <span className="text-xs text-slate-500">
        {editable
          ? 'Frozen with the rates when the version is published.'
          : `Frozen with version ${version}: changes priced with it convert at this rate.`}
      </span>
    </div>
  )
}
