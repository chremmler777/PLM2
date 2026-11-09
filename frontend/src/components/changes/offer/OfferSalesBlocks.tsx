/**
 * Christoph 2026-11-09: Sales picks the cost blocks and puts his markup on
 * top. Three pieces of the Price step:
 *
 * - QuotePicker: a supplier line with several quotes; the department's
 *   favourite is preselected, another pick writes Sales' vendor decision
 *   (costing shows "Sales chose X, against recommendation"; a reason is
 *   required then, as the costing asks).
 * - SalesMarkupCard: a multiplier (1.15) and/or an overhead in % or a fixed
 *   amount on the cost basis. Never its own row in the customer CBD: folded
 *   into the rows like the hidden overhead and margin.
 * - OfferInternalBreakdown: who is doing what (cost per department), the
 *   cost basis, the markup, the price and the margin. Internal only: the
 *   offer tab is Sales, PM and admin; the PDF never prints it.
 */
import { useState } from 'react'
import {
  SALES_MARKUP_FACTORS, SALES_MARKUP_KEYS,
  type CostBlock, type OfferData, type OfferFactor, type OfferOut, type OfferQuote,
} from '../../../types/changeOffer'
import { fmtMoney, fmtPct, inputCls, resultTone } from './offerFormat'
import { NumField, SubLabel } from './ui'

export const BLOCK_LABEL: Record<CostBlock, string> = {
  time: 'Our time',
  machine_time: 'Machine time',
  sampling: 'Sampling and trials',
  external: 'External change',
  supplier: 'Supplier quote',
  spare_part: 'Spare part',
}

/** A cost line's block name: its block, else its category. */
export const blockLabel = (l: { block?: CostBlock | null; category: string }): string =>
  (l.block && BLOCK_LABEL[l.block])
  || (l.category === 'internal' ? 'Internal change' : l.category === 'external' ? 'External change' : 'Other')

export function QuotePicker({
  lineKey, quotes, selected, currency, disabled, onChoose, busy,
}: {
  lineKey: string
  quotes: OfferQuote[]
  selected?: number | null
  currency: string
  disabled?: boolean
  busy?: boolean
  /** Sales' vendor decision; `reason` set when it goes against the favourite. */
  onChoose: (offerId: number, reason?: string) => void
}) {
  const [pending, setPending] = useState<number | null>(null)
  const [reason, setReason] = useState('')
  const current = selected ?? quotes.find((q) => q.chosen)?.offer_id ?? quotes.find((q) => q.recommended)?.offer_id
  const pick = (id: number) => {
    const q = quotes.find((x) => x.offer_id === id)
    if (!q || id === current) return
    if (q.recommended) { setPending(null); onChoose(id) } else { setPending(id); setReason('') }
  }
  const against = pending != null ? quotes.find((q) => q.offer_id === pending) : undefined
  return (
    <div className="mt-1 space-y-1">
      <select data-testid={`quote-pick-${lineKey}`} aria-label="Supplier quote"
        value={pending ?? current ?? ''} disabled={disabled || busy}
        onChange={(e) => pick(Number(e.target.value))}
        className={`${inputCls} w-full max-w-xs py-0.5 text-xs`}>
        {quotes.map((q) => (
          <option key={q.offer_id} value={q.offer_id}>
            {q.vendor} · {fmtMoney(q.total, currency)}{q.recommended ? ' (department favourite)' : ''}
          </option>
        ))}
      </select>
      {against && (
        <div data-testid={`quote-reason-${lineKey}`} className="flex flex-wrap items-center gap-1.5">
          <input className={`${inputCls} min-w-0 flex-1 text-xs`} value={reason}
            placeholder={`Why ${against.vendor}, against the department's favourite?`}
            aria-label="Reason for choosing against the recommendation"
            onChange={(e) => setReason(e.target.value)} />
          <button type="button" data-testid={`quote-confirm-${lineKey}`}
            disabled={!reason.trim() || busy}
            onClick={() => { onChoose(against.offer_id, reason.trim()); setPending(null) }}
            className="rounded border border-sky-700 px-2 py-0.5 text-xs text-sky-200 hover:bg-sky-900/40 disabled:opacity-50">
            Choose
          </button>
          <button type="button" onClick={() => setPending(null)}
            className="px-1 text-xs text-slate-400 hover:text-slate-200">Cancel</button>
        </div>
      )}
    </div>
  )
}

type Update = <K extends keyof OfferData>(key: K, value: OfferData[K]) => void

/** The markup factor of `key`, or its default when the offer does not carry it yet. */
const markupFactor = (factors: OfferFactor[], key: string): OfferFactor => {
  const found = factors.find((f) => f.key === key)
  if (found) return found
  const d = SALES_MARKUP_FACTORS.find((f) => f.key === key)!
  return { key, label: d.label, type: d.type, value: d.type === 'multiplier' ? 1 : 0, sign: 1, enabled: false, show: false }
}

export function SalesMarkupCard({ data, update, editable, currency }: {
  data: OfferData; update: Update; editable: boolean; currency: string
}) {
  const factors = data.factors ?? []
  const set = (key: string, value: number | null) => {
    const f = markupFactor(factors, key)
    const v = value ?? (f.type === 'multiplier' ? 1 : 0)
    const enabled = f.type === 'multiplier' ? v > 0 && Math.abs(v - 1) > 1e-9 : Math.abs(v) > 1e-9
    const next = { ...f, value: v, enabled, show: false }
    update('factors', factors.some((x) => x.key === key)
      ? factors.map((x) => (x.key === key ? next : x)) : [...factors, next])
  }
  const val = (key: string) => markupFactor(factors, key).value
  return (
    <div data-testid="sales-markup" className="rounded-lg border border-slate-700 bg-slate-900/40 p-3">
      <SubLabel>Sales markup</SubLabel>
      <p className="mb-2 text-[11px] text-slate-500">
        On top of the chosen cost blocks. Never its own row on the offer: spread over the CBD rows, the total stays the same.
      </p>
      <div className="grid gap-3 sm:grid-cols-3">
        <label className="text-xs text-slate-400">Multiplier (e.g. 1.15)
          <NumField value={val('sales_multiplier')} disabled={!editable} ariaLabel="Sales multiplier"
            testId="markup-multiplier" className="mt-1 w-full" onChange={(v) => set('sales_multiplier', v)} />
        </label>
        <label className="text-xs text-slate-400">Overhead %
          <NumField value={val('sales_overhead')} disabled={!editable} ariaLabel="Sales overhead percent"
            testId="markup-overhead-pct" className="mt-1 w-full" onChange={(v) => set('sales_overhead', v)} />
        </label>
        <label className="text-xs text-slate-400">Overhead fixed ({currency})
          <NumField value={val('sales_overhead_fixed')} disabled={!editable} ariaLabel="Sales overhead fixed amount"
            testId="markup-overhead-fixed" className="mt-1 w-full" onChange={(v) => set('sales_overhead_fixed', v)} />
        </label>
      </div>
    </div>
  )
}

function Row({ label, value, testId, strong, muted, tone }: {
  label: string; value: string; testId?: string; strong?: boolean; muted?: boolean; tone?: string
}) {
  return (
    <div className={`flex items-baseline justify-between gap-3 ${strong ? 'text-sm font-semibold' : 'text-xs'}`}>
      <span className={muted ? 'text-slate-500' : 'text-slate-300'}>{label}</span>
      <span data-testid={testId} className={`tabular-nums ${tone ?? (strong ? 'text-slate-50' : 'text-slate-200')}`}>{value}</span>
    </div>
  )
}

export function OfferInternalBreakdown({ offer, stale }: { offer: OfferOut; stale?: boolean }) {
  const tot = offer.totals
  const cur = offer.currency || 'EUR'
  const others = (tot.factors ?? []).filter((f) => !SALES_MARKUP_KEYS.includes(f.key))
  const hasInternal = Math.abs(tot.internal_cost ?? 0) >= 0.005
  return (
    <section data-testid="offer-internal-breakdown" aria-label="Internal breakdown"
      className={`rounded-lg border border-slate-700 bg-slate-900/40 p-3 transition-opacity ${stale ? 'opacity-50' : ''}`}>
      <div className="flex items-baseline justify-between gap-2">
        <SubLabel>Internal breakdown: who is doing what</SubLabel>
        <span className="text-[11px] text-slate-500">Sales, PM and admin only. Never on the offer.</span>
      </div>
      <div className="space-y-1">
        {(tot.by_department ?? []).map((d) => (
          <Row key={d.department} label={d.department} value={fmtMoney(d.amount, cur)}
            testId={`breakdown-dept-${d.department}`} />
        ))}
      </div>
      <div className="my-2 border-t border-slate-700" />
      <div className="space-y-1">
        <Row label="Cost of the chosen blocks" value={fmtMoney(tot.base, cur)} testId="breakdown-base" />
        <Row label="Sales multiplier / overhead" value={fmtMoney(tot.sales_markup ?? 0, cur)} testId="breakdown-markup" />
        {others.map((f) => <Row key={f.key} label={f.label} value={fmtMoney(f.amount, cur)} muted />)}
        {tot.risks_total !== 0 && <Row label="Risk surcharges" value={fmtMoney(tot.risks_total, cur)} muted />}
        {tot.scrap !== 0 && <Row label="Old stock / scrap (customer pays)" value={fmtMoney(tot.scrap, cur)} muted />}
        {tot.free !== 0 && <Row label="Additional items" value={fmtMoney(tot.free, cur)} muted />}
      </div>
      <div className="my-2 border-t border-slate-700" />
      <Row label="Price (total one-time)" value={fmtMoney(tot.total_one_time, cur)} strong testId="breakdown-price" />
      <div className="mt-1 space-y-1">
        <Row label="Internal cost (all costing)" value={fmtMoney(tot.internal_cost, cur)} muted />
        <Row label="Margin" testId="breakdown-margin"
          value={hasInternal ? `${fmtMoney(tot.margin_abs, cur)}${tot.margin_pct != null ? ` (${fmtPct(tot.margin_pct)})` : ''}` : '- (no costing yet)'}
          tone={hasInternal ? resultTone(tot.margin_abs) : 'text-slate-500'} />
      </div>
    </section>
  )
}
