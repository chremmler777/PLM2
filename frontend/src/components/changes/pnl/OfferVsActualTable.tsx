import { formatDate, formatMoney } from '../../../lib/format'
import type { OfferVsActual, OvaLine } from '../../../types/pnl'
import { TONE_CLASS, varianceTone } from './variance'
import { plantText } from '../../../lib/plantName'

const money = (v: number | null | undefined, cur?: string) =>
  v === null || v === undefined || !Number.isFinite(v) ? '-' : formatMoney(v, cur)

const pct = (v: number | null | undefined) =>
  v === null || v === undefined ? '' : ` (${v.toFixed(1)} %)`

const BASIS_LABEL: Record<string, string> = {
  accepted_offer: 'accepted offer',
  sent_offer: 'sent offer, not accepted',
  internal_approval: 'internal approval',
  costing: 'current costing',
}

function Chip({ line, currency }: { line: OvaLine; currency: string }) {
  if (line.kind === 'info' || line.variance === null) {
    return <span className="text-slate-500">-</span>
  }
  const tone = varianceTone(line.variance, line.planned, line.kind === 'revenue' ? 1 : -1)
  return (
    <span data-testid={`ova-chip-${line.key}`} data-tone={tone}
      className={`rounded px-1.5 py-0.5 text-[11px] tabular-nums ${TONE_CLASS[tone]}`}>
      {line.variance > 0 ? '+' : ''}{money(line.variance, currency)}
    </span>
  )
}

/**
 * Offer versus doing: the plan frozen at acceptance against what the change
 * really cost, line by line, then both margins, the slip and the piece price
 * effect. The server computes every number; this only lays them out.
 *
 * While the change still runs, "Actual" is what is booked so far and a
 * separate "Forecast" column carries the expected end (cost lines below plan
 * count at plan until release). The variance is always forecast against plan.
 * Once released the forecast is the actual, and the column goes.
 */
export default function OfferVsActualTable({ data }: { data: OfferVsActual }) {
  const cur = data.currency
  const running = !!data.in_progress
  // The server's margin row wins; older payloads carry only the flat fields.
  const mr = data.margin_row ?? {
    planned: data.planned_margin, actual: data.actual_margin, forecast: data.forecast_margin,
    planned_pct: data.planned_margin_pct, actual_pct: data.actual_margin_pct,
    forecast_pct: data.forecast_margin_pct, variance: data.variance,
  }
  const marginTone = varianceTone(mr.variance, mr.planned, 1)
  const t = data.timing
  const slip = t.slip_days
  return (
    <div data-testid="pnl-offer-vs-actual" className="md:col-span-3 border-t border-slate-700 pt-3">
      <div className="flex items-baseline gap-2 flex-wrap mb-2">
        <span className="text-xs text-slate-400 uppercase tracking-wide">Offer vs actual</span>
        <span className="text-xs text-slate-500">
          {/* Mother plant (spec §14): no offer basis, actual local costs only. */}
          {data.basis === 'none' ? plantText('mp.pnlBasis', data.mother_plant_name) : <>
          Plan from the {BASIS_LABEL[data.basis] ?? data.basis}
          {data.offer_version
            ? (data.basis === 'costing' ? `, revenue from offer v${data.offer_version}` : ` v${data.offer_version}`)
            : ''}
          {data.frozen_at ? `, frozen ${formatDate(data.frozen_at)}` : ''}
          </>}
        </span>
        {/* Currencies are compared, never converted (spec §15 phase 2). */}
        {data.basis !== 'none' && data.costing_currency && data.costing_currency !== cur && (
          <span data-testid="ova-currency-mismatch"
            className="rounded bg-amber-950/60 border border-amber-800/60 px-1.5 py-0 text-[11px] text-amber-200">
            Offer {cur}, costing {data.costing_currency}: not converted
          </span>
        )}
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead className="text-slate-500 text-left">
            <tr>
              <th className="py-1 pr-2 font-medium" />
              <th className="py-1 px-2 font-medium text-right">Planned</th>
              <th className="py-1 px-2 font-medium text-right">{running ? 'Actual to date' : 'Actual'}</th>
              {running && <th className="py-1 px-2 font-medium text-right" data-testid="ova-forecast-head">Forecast</th>}
              <th className="py-1 pl-2 font-medium text-right">{running ? 'Variance (forecast)' : 'Variance'}</th>
            </tr>
          </thead>
          <tbody>
            {data.lines.map((l) => (
              <tr key={l.key} data-testid={`ova-line-${l.key}`}
                className={`border-t border-slate-700/60 ${l.kind === 'info' ? 'text-slate-500' : 'text-slate-200'}`}>
                <td className="py-1 pr-2">
                  {l.label}
                  {!l.in_margin && <span className="ml-1 text-[10px] text-slate-500">(not in margin)</span>}
                </td>
                <td className="py-1 px-2 text-right tabular-nums">{money(l.planned, cur)}</td>
                <td className="py-1 px-2 text-right tabular-nums">{money(l.actual, cur)}</td>
                {running && <td className="py-1 px-2 text-right tabular-nums text-slate-300">{money(l.forecast ?? l.actual, cur)}</td>}
                <td className="py-1 pl-2 text-right"><Chip line={l} currency={cur} /></td>
              </tr>
            ))}
            <tr className="border-t border-slate-600 font-semibold text-slate-100">
              <td className="py-1.5 pr-2">Margin</td>
              <td className="py-1.5 px-2 text-right tabular-nums" data-testid="ova-planned-margin">
                {money(mr.planned, cur)}
                <span className="font-normal text-slate-500">{pct(mr.planned_pct)}</span>
              </td>
              <td className="py-1.5 px-2 text-right tabular-nums" data-testid="ova-actual-margin">
                {money(mr.actual, cur)}
                <span className="font-normal text-slate-500">{pct(mr.actual_pct)}</span>
              </td>
              {running && (
                <td className="py-1.5 px-2 text-right tabular-nums" data-testid="ova-forecast-margin">
                  {money(mr.forecast ?? mr.actual, cur)}
                  <span className="font-normal text-slate-500">{pct(mr.forecast_pct ?? mr.actual_pct)}</span>
                </td>
              )}
              <td className="py-1.5 pl-2 text-right">
                {mr.variance !== null && mr.variance !== undefined && (
                  <span data-testid="ova-margin-variance" data-tone={marginTone}
                    className={`rounded px-1.5 py-0.5 text-[11px] tabular-nums ${TONE_CLASS[marginTone]}`}>
                    {mr.variance > 0 ? '+' : ''}{money(mr.variance, cur)}
                  </span>
                )}
              </td>
            </tr>
            {running && (
              <tr className="text-slate-500">
                <td colSpan={5} className="pt-0.5 text-[11px]" data-testid="ova-to-date">
                  Still running: actual to date is what is booked so far. The forecast counts cost lines below plan at
                  plan until release, so only overruns move it; the variance compares the forecast with the plan.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      <div className="mt-2 space-y-1 text-xs text-slate-400">
        <div data-testid="ova-timing">
          <span className="text-slate-500">Timing: </span>
          baseline {formatDate(t.baseline_finish)}
          {t.actual_finish ? `, finished ${formatDate(t.actual_finish)}` : `, forecast ${formatDate(t.forecast_finish)}`}
          {slip !== null && (
            <span className={`ml-2 rounded px-1.5 py-0.5 ${slip > 0 ? TONE_CLASS.rose : TONE_CLASS.green}`}>
              {slip > 0 ? `${slip} ${t.unit} late` : slip < 0 ? `${-slip} ${t.unit} early` : 'on time'}
            </span>
          )}
        </div>
        {data.piece_price && (
          <div data-testid="ova-piece-price">
            <span className="text-slate-500">Piece price: </span>
            {data.piece_price.delta_per_piece > 0 ? '+' : ''}
            {data.piece_price.delta_per_piece.toLocaleString('de-DE', { maximumFractionDigits: 4 })} {cur} per piece
            {data.piece_price.annual_volume ? ` x ${data.piece_price.annual_volume.toLocaleString('de-DE')} per year` : ''}
            {data.piece_price.annual_effect !== null ? ` = ${money(data.piece_price.annual_effect, cur)} per year` : ''}
          </div>
        )}
        <div className="text-slate-500">
          {data.booked_hours} h booked
          {data.issue_count ? `, ${data.issue_count} validation issue${data.issue_count === 1 ? '' : 's'} with cost` : ''}
        </div>
      </div>

      {data.warnings.length > 0 && (
        <ul data-testid="ova-warnings" className="mt-2 space-y-0.5">
          {data.warnings.map((w) => (
            <li key={w} className="text-[11px] text-amber-300"
              data-testid={w.startsWith('Costing used cost sheet') ? 'ova-sheet-outdated' : undefined}>{w}</li>
          ))}
        </ul>
      )}
    </div>
  )
}
