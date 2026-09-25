/**
 * The currency each plant's rows are priced in. The migration set it from the
 * plant's location only, so until Finance confirms it the chip says so.
 */
import { useState } from 'react'
import type { PlantCurrency } from '../../types/costSheet'

interface Props {
  plants: PlantCurrency[]
  currencies: string[]
  canEdit: boolean
  onSet: (plantId: number, currency: string) => void
}

export default function PlantCurrencies({ plants, currencies, canEdit, onSet }: Props) {
  const [editing, setEditing] = useState<number | null>(null)
  const shown = plants.filter((p) => p.is_active)
  const open = shown.filter((p) => !p.currency_confirmed).length
  return (
    <div className="flex flex-wrap items-center gap-2 text-sm">
      <span className="text-xs uppercase tracking-wide text-slate-500">Plant currencies</span>
      {shown.map((p) => (
        <span key={p.id}
              className={`inline-flex items-center gap-1.5 rounded-md border px-2 py-0.5 ${
                p.currency_confirmed ? 'border-slate-700 bg-slate-800 text-slate-200' : 'border-amber-500/40 bg-amber-500/10 text-amber-200'}`}
              title={p.currency_confirmed ? 'Confirmed by Finance' : 'Currency set by location, Finance to confirm'}>
          {p.name}
          {editing === p.id ? (
            <select autoFocus aria-label={`Currency of ${p.name}`} defaultValue={p.currency}
                    onChange={(e) => { onSet(p.id, e.target.value); setEditing(null) }}
                    onBlur={() => setEditing(null)}
                    className="rounded border border-slate-600 bg-slate-900 px-1 py-0 text-xs text-slate-100">
              {currencies.map((c) => <option key={c} value={c}>{c}</option>)}
            </select>
          ) : (
            <span className="font-medium tabular-nums">{p.currency}</span>
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
          {open === 1 ? 'One currency was' : `${open} currencies were`} set by location; Finance to confirm.
        </span>
      )}
    </div>
  )
}
