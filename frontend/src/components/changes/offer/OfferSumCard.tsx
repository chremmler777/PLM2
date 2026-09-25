/**
 * The offer sum as the server computed it after the last save: every factor,
 * risk surcharge, scrap and free amount on its own line, then the total, the
 * piece-price effect and the margin against internal cost. Never recomputed
 * here: the business rule lives in one place.
 */
import type { OfferOut } from '../../../types/changeOffer'
import { fmtMoney, fmtPct, fmtPiece, sectionLabel } from './offerFormat'
import type { SaveState } from './useOfferDraft'

function Row({ label, value, muted, testId, strong }: {
  label: string; value: string; muted?: boolean; testId?: string; strong?: boolean
}) {
  return (
    <div className={`flex items-baseline justify-between gap-3 ${strong ? 'text-sm' : 'text-xs'}`}>
      <span className={muted ? 'text-slate-500' : 'text-slate-300'}>{label}</span>
      <span data-testid={testId}
        className={`tabular-nums text-right ${strong ? 'font-semibold text-slate-50' : muted ? 'text-slate-500' : 'text-slate-200'}`}>
        {value}
      </span>
    </div>
  )
}

export default function OfferSumCard({ offer, saveState, stale }: {
  offer: OfferOut
  saveState?: SaveState
  /** Local edits not saved yet: dim the figures until the server answers. */
  stale?: boolean
}) {
  const tot = offer.totals
  const cur = offer.currency || 'EUR'
  const margin = tot.margin_abs
  return (
    <aside data-testid="offer-sum" className="rounded-xl border border-slate-700 bg-slate-900/80 p-4 shadow-lg shadow-black/20">
      <div className="mb-3 flex items-center justify-between">
        <span className={sectionLabel}>Offer sum</span>
        <SaveBadge state={saveState} />
      </div>
      <div data-testid="offer-sum-figures" data-stale={stale ? 'true' : undefined}
        className={`transition-opacity ${stale ? 'opacity-50' : ''}`}>
      <div className="space-y-1.5">
        <Row label="Cost basis" value={fmtMoney(tot.base, cur)} testId="sum-base" />
        {(tot.factors ?? []).map((f) => (
          <Row key={f.key} label={f.label} value={fmtMoney(f.amount, cur)} testId={`sum-factor-${f.key}`} />
        ))}
        {tot.risks_total !== 0 && <Row label="Risk surcharges" value={fmtMoney(tot.risks_total, cur)} testId="sum-risks" />}
        {tot.scrap !== 0 && <Row label="Scrap (customer pays)" value={fmtMoney(tot.scrap, cur)} testId="sum-scrap" />}
        {tot.free !== 0 && <Row label="Additional items" value={fmtMoney(tot.free, cur)} testId="sum-free" />}
      </div>
      <div className="my-3 border-t border-slate-700" />
      <Row label="Total one-time" value={fmtMoney(tot.total_one_time, cur)} strong testId="sum-total" />
      {tot.piece_price_delta != null && (
        <div className="mt-2 space-y-1.5">
          <Row label="Piece price delta" value={fmtPiece(tot.piece_price_delta, cur)} testId="sum-piece" />
          {tot.annual_effect != null && (
            <Row label="Annual effect" value={fmtMoney(tot.annual_effect, cur)} testId="sum-annual" />
          )}
        </div>
      )}
      <div className="my-3 border-t border-slate-700" />
      <div className="space-y-1.5">
        <Row label="Internal cost" value={fmtMoney(tot.internal_cost, cur)} muted testId="sum-internal" />
        <div className="flex items-baseline justify-between text-xs">
          <span className="text-slate-500">Margin</span>
          <span data-testid="sum-margin"
            className={`tabular-nums ${margin == null ? 'text-slate-500' : margin >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
            {fmtMoney(margin, cur)}{tot.margin_pct != null && <span className="ml-1 text-slate-500">({fmtPct(tot.margin_pct)})</span>}
          </span>
        </div>
      </div>
      </div>
    </aside>
  )
}

export function SaveBadge({ state }: { state?: SaveState }) {
  if (!state || state === 'idle') return null
  const map: Record<Exclude<SaveState, 'idle'>, [string, string]> = {
    pending: ['Editing', 'text-slate-400'],
    saving: ['Saving', 'text-sky-300'],
    saved: ['Saved', 'text-emerald-400'],
    error: ['Not saved', 'text-rose-400'],
  }
  const [label, cls] = map[state]
  return <span data-testid="offer-save-state" className={`text-[11px] ${cls}`}>{state === 'saved' ? '✓ ' : ''}{label}</span>
}
