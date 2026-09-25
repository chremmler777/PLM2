/**
 * Step 2 of the offer: what the customer pays. Cost lines come from costing
 * (Sales may adjust or drop a line, the source stays visible), optional
 * factors sit on top, then the changeover, the piece-price effect and any free
 * items. The sum card on the right shows the server's arithmetic.
 */
import {
  factorShown,
  type OfferCostLine, type OfferData, type OfferFactor, type OfferFreeField, type OfferPiecePrice,
  type OfferChangeover,
} from '../../../types/changeOffer'
import { X } from 'lucide-react'
import { fmtMoney, inputCls } from './offerFormat'
import { Field, NumField, Segmented, SubLabel, Toggle } from './ui'

const CATEGORY_CHIP: Record<string, string> = {
  internal: 'bg-sky-950 text-sky-300 border-sky-900',
  external: 'bg-violet-950 text-violet-300 border-violet-900',
  other: 'bg-slate-800 text-slate-300 border-slate-700',
}

type Update = <K extends keyof OfferData>(key: K, value: OfferData[K]) => void

/** Warnings that belong to the price itself (spec §15 phase 2): the costing
    in another currency than the offer, currencies the costing could not
    add, lines without a rate, a newer cost sheet than costing used. */
export const PRICE_WARNING_CODES = [
  'currency_mismatch', 'mixed_currency', 'no_rate', 'cost_sheet_outdated',
  // a hand-set amount the refresh reduced by the split-out machine-time and
  // sampling lines (so they are not counted twice): Sales re-checks it
  'override_split',
]

export default function OfferPriceSection({
  data, update, editable, currency, annualEffect, onRefresh, refreshing, warnings = [],
}: {
  data: OfferData
  update: Update
  editable: boolean
  currency: string
  annualEffect?: number | null
  onRefresh?: () => void
  refreshing?: boolean
  warnings?: { code: string; message: string }[]
}) {
  const priceWarnings = warnings.filter((w) => PRICE_WARNING_CODES.includes(w.code))
  const lines = data.cost_lines ?? []
  // The customer's CBD groups lines by its own categories, not by our
  // departments: shown once the backend names them.
  const customerView = lines.some((l) => !!l.customer_category)
  const factors = data.factors ?? []
  const changeover: OfferChangeover = data.changeover ?? { mode: 'running_change' }
  const piece: OfferPiecePrice = data.piece_price ?? { enabled: false, rows: [] }
  const free = data.free_fields ?? []

  const setLine = (i: number, patch: Partial<OfferCostLine>) =>
    update('cost_lines', lines.map((l, j) => (j === i ? { ...l, ...patch } : l)))
  const setFactor = (i: number, patch: Partial<OfferFactor>) =>
    update('factors', factors.map((f, j) => (j === i ? { ...f, ...patch } : f)))
  const setFree = (i: number, patch: Partial<OfferFreeField>) =>
    update('free_fields', free.map((f, j) => (j === i ? { ...f, ...patch } : f)))
  const setPiece = (patch: Partial<OfferPiecePrice>) => update('piece_price', { ...piece, ...patch })
  const setChangeover = (patch: Partial<OfferChangeover>) => update('changeover', { ...changeover, ...patch })

  const scrapPreview = (changeover.scrap_qty ?? 0) * (changeover.scrap_unit_price ?? 0)

  return (
    <div className="space-y-6">
      {priceWarnings.length > 0 && (
        <ul role="status" data-testid="offer-price-warnings"
          className="rounded-md border border-amber-700/70 bg-amber-950/40 px-3 py-2 text-xs text-amber-100 space-y-1">
          {priceWarnings.map((w) => <li key={w.code} data-code={w.code}>{w.message}</li>)}
        </ul>
      )}
      {/* Cost lines */}
      <div>
        <div className="flex items-center justify-between">
          <SubLabel>Cost lines from costing</SubLabel>
          {editable && onRefresh && (
            <button type="button" data-testid="offer-refresh" onClick={onRefresh} disabled={refreshing}
              className="text-xs text-sky-300 hover:text-sky-200 disabled:opacity-50">
              {refreshing ? 'Refreshing' : '↻ Refresh from costing'}
            </button>
          )}
        </div>
        {lines.length === 0 ? (
          <p className="rounded-lg border border-dashed border-slate-700 px-3 py-4 text-center text-xs text-slate-500">
            No cost lines yet. Refresh from costing once departments have priced their work.
          </p>
        ) : (
          <div className="overflow-x-auto rounded-lg border border-slate-700">
            <table className="w-full text-sm">
              <thead className="bg-slate-900/60 text-[11px] uppercase tracking-wider text-slate-500">
                <tr>
                  <th className="w-8 px-2 py-2" />
                  <th className="px-2 py-2 text-left font-medium">Line</th>
                  <th className="px-2 py-2 text-left font-medium">Department</th>
                  <th className="px-2 py-2 text-left font-medium">Type</th>
                  {customerView && <th className="px-2 py-2 text-left font-medium">Customer reads</th>}
                  <th className="whitespace-nowrap px-2 py-2 text-right font-medium">Source</th>
                  <th className="w-40 px-2 py-2 text-right font-medium">Offer amount</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-700/60">
                {lines.map((l, i) => {
                  const changed = l.source_amount != null && Math.abs(l.amount - l.source_amount) > 0.004
                  return (
                    <tr key={l.key} data-testid={`cost-line-${l.key}`}
                      className={l.include ? '' : 'opacity-50'}>
                      <td className="px-2 py-1.5 text-center">
                        <input type="checkbox" aria-label={`Include ${l.label}`} checked={l.include}
                          disabled={!editable} data-testid={`cost-line-include-${l.key}`}
                          onChange={(e) => setLine(i, { include: e.target.checked })}
                          className="accent-sky-500" />
                      </td>
                      <td className="px-2 py-1.5 text-slate-100">{l.label}</td>
                      <td className="px-2 py-1.5 text-slate-400">{l.department ?? '-'}</td>
                      <td className="px-2 py-1.5">
                        <span className={`rounded border px-1.5 py-0 text-[11px] ${CATEGORY_CHIP[l.category] ?? CATEGORY_CHIP.other}`}>
                          {l.category}
                        </span>
                      </td>
                      {customerView && (
                        <td data-testid={`cost-line-customer-${l.key}`} className="px-2 py-1.5 text-slate-300">
                          {/* As the PDF prints it: a line without a category keeps its own label. */}
                          {l.customer_category?.trim() || l.label}
                        </td>
                      )}
                      <td className="whitespace-nowrap px-2 py-1.5 text-right tabular-nums text-slate-500">
                        {changed ? <s data-testid={`cost-line-source-${l.key}`}>{fmtMoney(l.source_amount, currency)}</s>
                          : fmtMoney(l.source_amount, currency)}
                      </td>
                      <td className="px-2 py-1.5">
                        <NumField value={l.amount} disabled={!editable} ariaLabel={`Amount ${l.label}`}
                          testId={`cost-line-amount-${l.key}`}
                          onChange={(v) => setLine(i, { amount: v ?? 0 })} className="w-full" />
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Factors */}
      <div>
        <SubLabel>Factors</SubLabel>
        <p className="mb-1.5 text-[11px] text-slate-500">
          Show on offer prints a factor as its own line. Hidden amounts are spread over the cost lines; the total stays the same.
        </p>
        <div className="space-y-1.5">
          {factors.map((f, i) => (
            <div key={f.key} data-testid={`factor-${f.key}`}
              className={`grid grid-cols-[auto_minmax(0,1.4fr)_auto_7rem_auto_minmax(0,1fr)_auto_auto] items-center gap-2 rounded-lg border px-2 py-1.5 ${
                f.enabled ? 'border-slate-600 bg-slate-900/60' : 'border-slate-800 bg-slate-900/20'}`}>
              <Toggle checked={f.enabled} disabled={!editable} label={`Enable ${f.label}`}
                testId={`factor-toggle-${f.key}`} onChange={(v) => setFactor(i, { enabled: v })} />
              {f.key.startsWith('custom') ? (
                <input className={inputCls} value={f.label} disabled={!editable} aria-label="Factor label"
                  onChange={(e) => setFactor(i, { label: e.target.value })} />
              ) : <span className={`text-sm ${f.enabled ? 'text-slate-100' : 'text-slate-400'}`}>{f.label}</span>}
              <Segmented value={f.type} disabled={!editable}
                options={[{ value: 'pct', label: '%' }, { value: 'amount', label: currency }]}
                onChange={(v) => setFactor(i, { type: v })} />
              <NumField value={f.value} disabled={!editable} ariaLabel={`Value ${f.label}`}
                testId={`factor-value-${f.key}`} onChange={(v) => setFactor(i, { value: v ?? 0 })} />
              <Segmented value={f.sign === -1 ? 'minus' : 'plus'} disabled={!editable}
                options={[{ value: 'plus', label: '+' }, { value: 'minus', label: '−' }]}
                onChange={(v) => setFactor(i, { sign: v === 'minus' ? -1 : 1 })} />
              <input className={inputCls} placeholder="Note" value={f.note ?? ''} disabled={!editable}
                aria-label={`Note ${f.label}`} onChange={(e) => setFactor(i, { note: e.target.value })} />
              <label className="flex items-center gap-1.5 whitespace-nowrap text-[11px] text-slate-400"
                title="Shown: its own line on the offer. Hidden: spread over the cost lines in the PDF; the total stays the same.">
                <Toggle checked={factorShown(f)} disabled={!editable} label={`Show ${f.label} on offer`}
                  testId={`factor-show-${f.key}`} onChange={(v) => setFactor(i, { show: v })} />
                Show on offer
              </label>
              {editable && f.key.startsWith('custom') ? (
                <button type="button" aria-label={`Remove ${f.label}`}
                  className="inline-flex h-6 w-6 items-center justify-center rounded text-slate-500 hover:bg-slate-800 hover:text-rose-300"
                  onClick={() => update('factors', factors.filter((_, j) => j !== i))}><X aria-hidden="true" size={13} /></button>
              ) : <span className="w-4" />}
            </div>
          ))}
        </div>
        {editable && (
          <button type="button" data-testid="factor-add"
            className="mt-2 text-xs text-sky-300 hover:text-sky-200"
            onClick={() => update('factors', [...factors, {
              key: `custom_${Date.now().toString(36)}`, label: 'Custom factor', type: 'amount',
              value: 0, sign: 1, enabled: true, note: '', show: true,
            }])}>
            + Add factor
          </button>
        )}
      </div>

      {/* Changeover */}
      <div>
        <SubLabel>Changeover</SubLabel>
        <div className="flex flex-wrap items-end gap-3">
          <Segmented testId="changeover-mode" value={changeover.mode} disabled={!editable}
            options={[
              { value: 'running_change', label: 'Running change' },
              { value: 'customer_pays_scrap', label: 'Customer pays scrap' },
            ]}
            onChange={(v) => setChangeover({ mode: v })} />
          {changeover.mode === 'customer_pays_scrap' && (
            <>
              <Field label="Scrap quantity">
                <NumField value={changeover.scrap_qty} disabled={!editable} ariaLabel="Scrap quantity"
                  testId="scrap-qty" className="w-28" onChange={(v) => setChangeover({ scrap_qty: v })} />
              </Field>
              <span className="pb-1.5 text-slate-500">×</span>
              <Field label={`Unit price (${currency})`}>
                <NumField value={changeover.scrap_unit_price} disabled={!editable} ariaLabel="Scrap unit price"
                  testId="scrap-price" className="w-28" onChange={(v) => setChangeover({ scrap_unit_price: v })} />
              </Field>
              <span className="pb-1.5 text-slate-500">=</span>
              <span className="pb-1.5 text-sm tabular-nums text-slate-100">{fmtMoney(scrapPreview, currency)}</span>
            </>
          )}
        </div>
        <input className={`${inputCls} mt-2 w-full`} placeholder="Changeover note (shown in the offer)"
          value={changeover.note ?? ''} disabled={!editable} aria-label="Changeover note"
          onChange={(e) => setChangeover({ note: e.target.value })} />
      </div>

      {/* Piece price */}
      <div>
        <div className="flex items-center gap-2">
          <Toggle checked={piece.enabled} disabled={!editable} label="Piece-price effect"
            testId="piece-toggle" onChange={(v) => setPiece({ enabled: v })} />
          <SubLabel>Piece-price effect</SubLabel>
        </div>
        {piece.enabled && (
          <div className="mt-2 space-y-2">
            <Field label="Annual volume (pieces)" className="w-48">
              <NumField value={piece.annual_volume} disabled={!editable} ariaLabel="Annual volume"
                testId="piece-volume" onChange={(v) => setPiece({ annual_volume: v })} />
            </Field>
            {(piece.rows ?? []).map((r, i) => (
              <div key={i} className="grid grid-cols-[minmax(0,1fr)_minmax(0,1fr)_9rem_auto] items-center gap-2">
                <input className={inputCls} placeholder="Label, e.g. material" value={r.label} disabled={!editable}
                  aria-label="Piece row label"
                  onChange={(e) => setPiece({ rows: piece.rows.map((x, j) => (j === i ? { ...x, label: e.target.value } : x)) })} />
                <input className={inputCls} placeholder="Driver, e.g. +12 g PP" value={r.driver ?? ''} disabled={!editable}
                  aria-label="Piece row driver"
                  onChange={(e) => setPiece({ rows: piece.rows.map((x, j) => (j === i ? { ...x, driver: e.target.value } : x)) })} />
                <NumField value={r.delta_per_piece} disabled={!editable} ariaLabel="Delta per piece"
                  placeholder="Δ / piece"
                  onChange={(v) => setPiece({ rows: piece.rows.map((x, j) => (j === i ? { ...x, delta_per_piece: v ?? 0 } : x)) })} />
                {editable ? (
                  <button type="button" aria-label="Remove row" className="inline-flex h-6 w-6 items-center justify-center rounded text-slate-500 hover:bg-slate-800 hover:text-rose-300"
                    onClick={() => setPiece({ rows: piece.rows.filter((_, j) => j !== i) })}><X aria-hidden="true" size={13} /></button>
                ) : <span />}
              </div>
            ))}
            <div className="flex items-center justify-between">
              {editable ? (
                <button type="button" className="text-xs text-sky-300 hover:text-sky-200"
                  onClick={() => setPiece({ rows: [...(piece.rows ?? []), { label: '', driver: '', delta_per_piece: 0 }] })}>
                  + Add row
                </button>
              ) : <span />}
              <span className="text-xs text-slate-400">
                Annual effect <span className="ml-1 tabular-nums text-slate-100">{fmtMoney(annualEffect, currency)}</span>
              </span>
            </div>
          </div>
        )}
      </div>

      {/* Free fields */}
      <div>
        <SubLabel>Additional items</SubLabel>
        {free.length === 0 && (
          <p className="text-xs text-slate-500">Anything else the offer should state: a tooling transfer, a deadline surcharge, a note with or without an amount.</p>
        )}
        <div className="space-y-1.5">
          {free.map((f, i) => (
            <div key={i} className="grid grid-cols-[minmax(0,1fr)_minmax(0,1.5fr)_9rem_auto] items-center gap-2">
              <input className={inputCls} placeholder="Label" value={f.label} disabled={!editable}
                aria-label="Item label" onChange={(e) => setFree(i, { label: e.target.value })} />
              <input className={inputCls} placeholder="Value / text" value={f.value} disabled={!editable}
                aria-label="Item value" onChange={(e) => setFree(i, { value: e.target.value })} />
              <NumField value={f.amount} disabled={!editable} ariaLabel="Item amount" placeholder="Amount (optional)"
                onChange={(v) => setFree(i, { amount: v })} />
              {editable ? (
                <button type="button" aria-label="Remove item" className="inline-flex h-6 w-6 items-center justify-center rounded text-slate-500 hover:bg-slate-800 hover:text-rose-300"
                  onClick={() => update('free_fields', free.filter((_, j) => j !== i))}><X aria-hidden="true" size={13} /></button>
              ) : <span />}
            </div>
          ))}
        </div>
        {editable && (
          <button type="button" className="mt-2 text-xs text-sky-300 hover:text-sky-200"
            onClick={() => update('free_fields', [...free, { label: '', value: '', amount: null }])}>
            + Add item
          </button>
        )}
      </div>
    </div>
  )
}
