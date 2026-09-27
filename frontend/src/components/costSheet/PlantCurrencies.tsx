/**
 * The currency each plant's rows are priced in (the quote currency, which
 * costing and offers use) and, for a plant that works in two, its local
 * currency (Silao: USD and MXN). The migration set the quote currency from
 * the plant's location only, so until Sales or Finance confirms it the chip
 * says so.
 */
import { useState } from 'react'
import type { PlantCurrency } from '../../types/costSheet'

interface Props {
  plants: PlantCurrency[]
  currencies: string[]
  canEdit: boolean
  /** local: undefined = unchanged, null = one currency only. */
  onSet: (plantId: number, currency: string, local?: string | null) => void
}

const SELECT = 'rounded border border-slate-600 bg-slate-900 px-1 py-0 text-xs text-slate-100 focus:border-sky-500 focus:outline-none'

export default function PlantCurrencies({ plants, currencies, canEdit, onSet }: Props) {
  const [editing, setEditing] = useState<number | null>(null)
  const shown = plants.filter((p) => p.is_active)
  const open = shown.filter((p) => !p.currency_confirmed).length
  return (
    <div className="flex flex-wrap items-center gap-2 text-sm">
      <span className="text-xs uppercase tracking-wide text-slate-500">Plant currencies</span>
      {shown.map((p) => (
        <span key={p.id} data-testid={`plant-currency-${p.id}`}
              className={`inline-flex items-center gap-1.5 rounded-md border px-2 py-0.5 ${
                p.currency_confirmed ? 'border-slate-700 bg-slate-800 text-slate-200' : 'border-amber-500/40 bg-amber-500/10 text-amber-200'}`}
              title={p.currency_confirmed ? 'Confirmed' : 'Currency set by location, Sales or Finance to confirm'}>
          {p.name}
          {editing === p.id ? (
            <span className="inline-flex items-center gap-1"
              onBlur={(e) => { if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setEditing(null) }}>
              <select autoFocus aria-label={`Quote currency of ${p.name}`} defaultValue={p.currency}
                      onChange={(e) => onSet(p.id, e.target.value)} className={SELECT}>
                {currencies.map((c) => <option key={c} value={c}>{c}</option>)}
              </select>
              <span className="text-xs text-slate-400">local</span>
              <select aria-label={`Local currency of ${p.name}`} defaultValue={p.local_currency ?? ''}
                      onChange={(e) => onSet(p.id, p.currency, e.target.value || null)} className={SELECT}>
                <option value="">None</option>
                {currencies.filter((c) => c !== p.currency).map((c) => <option key={c} value={c}>{c}</option>)}
              </select>
              <button type="button" onClick={() => setEditing(null)}
                      className="rounded px-1 text-xs text-slate-400 hover:text-slate-100">Done</button>
            </span>
          ) : (
            <span className="font-medium tabular-nums">
              {p.currency}
              {p.local_currency && (
                <span className="font-normal text-slate-400" title={`Quotes in ${p.currency}, local currency ${p.local_currency}`}>
                  {' '}+ {p.local_currency}
                </span>
              )}
            </span>
          )}
          {canEdit && editing !== p.id && (
            <>
              {!p.currency_confirmed && (
                <button type="button" onClick={() => onSet(p.id, p.currency)}
                        className="rounded px-1 text-xs text-amber-100 underline decoration-dotted hover:text-white">
                  Confirm
                </button>
              )}
              <button type="button" onClick={() => setEditing(p.id)} aria-label={`Change currency of ${p.name}`}
                      className="rounded px-1 text-xs text-slate-400 hover:text-slate-100">Change</button>
            </>
          )}
        </span>
      ))}
      {open > 0 && (
        <span className="text-xs text-amber-300/80">
          {open === 1 ? 'One currency was' : `${open} currencies were`} set by location; Sales or Finance to confirm.
        </span>
      )}
    </div>
  )
}
