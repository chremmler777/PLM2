/**
 * The exchange rates of a cost sheet version (106): "1 USD = 17.30 MXN" for
 * each two-currency plant's pair. Sales or Finance type them on the draft;
 * publishing freezes them with the rates, so an old change keeps the rate
 * of its version. The number is sent as typed (17.30 stays 17.30).
 */
import { useEffect, useId, useState } from 'react'
import { NUMBER_INPUT_INVALID } from '../../lib/format'
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

/** "17.30" and "17,30" read as 17.30; anything else is refused. The text
 * goes to the server as typed (dot decimals), never re-formatted. */
export function readFxInput(raw: string): { value: string | null } | { refused: true } {
  const t = raw.trim()
  if (!t) return { value: null }
  if (!/^\d+([.,]\d+)?$/.test(t)) return { refused: true }
  const value = t.replace(',', '.')
  return Number(value) > 0 ? { value } : { refused: true }
}

function FxInput({ p, current, busy, onSet }: {
  p: Pair; current: string | null; busy?: boolean
  onSet: (base: string, quote: string, rate: string | null) => void
}) {
  const [draft, setDraft] = useState(current ?? '')
  const [refused, setRefused] = useState(false)
  const msgId = useId()
  useEffect(() => { setDraft(current ?? ''); setRefused(false) }, [current])
  const commit = () => {
    const r = readFxInput(draft)
    if ('refused' in r) { setRefused(true); return }
    setRefused(false)
    if (r.value !== current) onSet(p.base, p.quote, r.value)
  }
  return (
    <span className="inline-flex flex-col">
      <input aria-label={`${p.quote} per ${p.base}`} data-testid={`fx-input-${p.pair}`}
        inputMode="decimal" value={draft} disabled={busy} placeholder="Not set"
        aria-invalid={refused || undefined} aria-describedby={refused ? msgId : undefined}
        onChange={(e) => { setDraft(e.target.value); setRefused(false) }}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === 'Enter') (e.target as HTMLInputElement).blur()
          if (e.key === 'Escape') { setDraft(current ?? ''); setRefused(false) }
        }}
        className={`w-24 rounded border bg-slate-900/60 px-2 py-1 text-right text-sm tabular-nums text-slate-100 placeholder:text-amber-400/70 focus:border-sky-500 focus:outline-none focus:ring-1 focus:ring-sky-500/40 ${
          refused ? 'border-rose-500' : 'border-slate-700'}`} />
      {refused && (
        <span id={msgId} role="alert" className="mt-0.5 text-[11px] text-rose-300">
          {NUMBER_INPUT_INVALID}
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
      {pairs.map((p) => {
        const current = byPair.get(p.pair)?.rate ?? null
        return (
          <span key={p.pair} className="inline-flex items-center gap-1.5 text-slate-300">
            <span className="tabular-nums">1 {p.base} =</span>
            {editable ? (
              <FxInput p={p} current={current} busy={busy} onSet={onSet} />
            ) : (
              <span data-testid={`fx-value-${p.pair}`}
                className={`font-medium tabular-nums ${current ? 'text-slate-100' : 'text-amber-300'}`}>
                {current ?? 'not set'}
              </span>
            )}
            <span>{p.quote}</span>
            {!current && (
              <span className="text-xs text-amber-300/90">
                Rates typed in {p.quote} cannot be priced until it is set.
              </span>
            )}
          </span>
        )
      })}
      <span className="text-xs text-slate-500">
        {editable
          ? 'Frozen with the rates when the version is published.'
          : `Frozen with version ${version}: changes priced with it convert at this rate.`}
      </span>
    </div>
  )
}
