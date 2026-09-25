/**
 * Step 3 of the offer: the technical risks the departments raised. Sales
 * decides which ones the customer reads and prices a surcharge where the risk
 * is real money. A severity-3 risk kept out of the offer is a decision worth a
 * second look, so it is flagged.
 */
import type { OfferData, OfferRisk } from '../../../types/changeOffer'
import { CircleAlert } from 'lucide-react'
import { fmtMoney, inputCls } from './offerFormat'
import { NumField, Segmented, Toggle } from './ui'

const SEV_CHIP: Record<number, string> = {
  1: 'bg-slate-800 text-slate-300 border-slate-600',
  2: 'bg-amber-950/70 text-amber-200 border-amber-800',
  3: 'bg-rose-950/70 text-rose-200 border-rose-800',
}

export default function OfferRisksSection({
  data, update, editable, currency, risksTotal,
}: {
  data: OfferData
  update: <K extends keyof OfferData>(key: K, value: OfferData[K]) => void
  editable: boolean
  currency: string
  risksTotal: number
}) {
  const risks = data.risks ?? []
  const setRisk = (i: number, patch: Partial<OfferRisk>) =>
    update('risks', risks.map((r, j) => (j === i ? { ...r, ...patch } : r)))
  const hiddenSevere = risks.filter((r) => r.severity === 3 && !r.show)

  if (risks.length === 0) {
    return (
      <p className="rounded-lg border border-dashed border-slate-700 px-3 py-4 text-center text-xs text-slate-500">
        No open risks on this change. Nothing to state or price here.
      </p>
    )
  }
  return (
    <div className="space-y-3">
      <p data-testid="risk-opt-in" className="text-[11px] text-slate-500">
        Risks stay off the offer until you switch them on: the customer reads only the ones shown.
      </p>
      {hiddenSevere.length > 0 && (
        <p data-testid="risk-severe-hidden" role="alert"
          className="flex items-start gap-1.5 rounded-lg border border-amber-800/70 bg-amber-950/30 px-3 py-2 text-xs text-amber-200">
          <CircleAlert aria-hidden="true" size={14} className="mt-px shrink-0" />
          <span>{hiddenSevere.length === 1 ? '1 severity-3 risk is' : `${hiddenSevere.length} severity-3 risks are`} not shown
          in the offer. The customer will not read about {hiddenSevere.length === 1 ? 'it' : 'them'}.</span>
        </p>
      )}
      <ul className="space-y-2">
        {risks.map((r, i) => (
          <li key={r.concern_id} data-testid={`risk-${r.concern_id}`}
            className={`rounded-lg border px-3 py-2 ${r.show ? 'border-slate-600 bg-slate-900/60' : 'border-slate-800 bg-slate-900/20'}`}>
            <div className="flex flex-wrap items-center gap-2">
              <span className={`rounded border px-1.5 py-0 text-[11px] font-semibold ${SEV_CHIP[r.severity ?? 1] ?? SEV_CHIP[1]}`}>
                S{r.severity ?? '-'}
              </span>
              {r.department && <span className="text-[11px] text-slate-500">{r.department}</span>}
              <span className="min-w-0 flex-1 text-sm text-slate-100">{r.label}</span>
              <label className="flex items-center gap-2 text-xs text-slate-400">
                Show in offer
                <Toggle checked={r.show} disabled={!editable} label={`Show ${r.label} in offer`}
                  testId={`risk-show-${r.concern_id}`} onChange={(v) => setRisk(i, { show: v })} />
              </label>
            </div>
            <div className="mt-2 grid grid-cols-[auto_8rem_minmax(0,1fr)] items-center gap-2">
              <Segmented value={r.type} disabled={!editable}
                options={[{ value: 'pct', label: '%' }, { value: 'amount', label: currency }]}
                onChange={(v) => setRisk(i, { type: v })} />
              <NumField value={r.value} disabled={!editable} ariaLabel={`Surcharge ${r.label}`}
                testId={`risk-value-${r.concern_id}`} onChange={(v) => setRisk(i, { value: v ?? 0 })} />
              <input className={inputCls} placeholder="Note for the customer" value={r.note ?? ''}
                disabled={!editable} aria-label={`Note ${r.label}`}
                onChange={(e) => setRisk(i, { note: e.target.value })} />
            </div>
          </li>
        ))}
      </ul>
      <div className="flex flex-wrap items-center justify-between gap-3 text-xs text-slate-400">
        <label className="flex items-center gap-2"
          title="Hidden amounts are spread over the cost lines; the total stays the same.">
          <Toggle checked={!!data.show_risk_surcharge} disabled={!editable} label="Show risk surcharges as a line on the offer"
            testId="risk-surcharge-show" onChange={(v) => update('show_risk_surcharge', v)} />
          <span>
            Show risk surcharges as a line on the offer
            <span className="block text-[11px] text-slate-500">Hidden amounts are spread over the cost lines; the total stays the same.</span>
          </span>
        </label>
        <span>
          Risk surcharge total
          <span data-testid="risk-total" className="ml-2 tabular-nums text-slate-100">{fmtMoney(risksTotal, currency)}</span>
        </span>
      </div>
    </div>
  )
}
