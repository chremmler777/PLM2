/**
 * What the quote is judged against: the costed total and the production-time
 * delta the change carries per part. Shown next to the price entry so Sales has
 * the basis in view — deliberately never summed into a suggested price, because
 * the piece-price effect is a commercial judgement, not arithmetic.
 */
import { useQuery } from '@tanstack/react-query'
import { changesApi } from '../../api/changes'
import { t } from '../../i18n/cmLabels'
import type { Summation } from '../../types/change'

export default function QuoteBasis({ changeId, plants = [] }: {
  changeId: number
  plants?: { id: number; name: string }[]
}) {
  const { data } = useQuery<Summation>({
    queryKey: ['change-summation', changeId],
    queryFn: () => changesApi.getSummation(changeId),
  })
  if (!data) return null
  const plantName = (id: number) => plants.find((p) => p.id === id)?.name ?? `Plant #${id}`
  const minutes = data.lifecycle_minutes_by_plant ?? []

  return (
    <div data-testid="quote-basis"
      className="rounded-lg border border-slate-700 bg-slate-800/60 p-3 space-y-1">
      <p className="text-xs uppercase tracking-wide text-slate-500">{t('quote.basis')}</p>
      <p className="flex items-baseline gap-2">
        <span className="text-slate-400">{t('total')}:</span>
        <span className="tabular-nums text-slate-100" data-testid="quote-basis-total">
          {data.totals.grand_total.toFixed(2)}
        </span>
      </p>
      {(minutes.length > 0 || data.total_minutes_per_part != null) && (
        <div className="text-xs" data-testid="quote-basis-minutes">
          <p className="text-slate-400">{t('costing.minutes')}</p>
          <ul className="mt-0.5 space-y-0.5">
            {minutes.map((m) => (
              <li key={m.plant_id} className="flex justify-between gap-3">
                <span className="text-slate-400">{plantName(m.plant_id)}</span>
                <span className="tabular-nums text-slate-200">
                  {m.minutes_per_part > 0 ? '+' : ''}{m.minutes_per_part} {t('summation.perPart')}
                </span>
              </li>
            ))}
            {data.total_minutes_per_part != null && (
              <li className="flex justify-between gap-3 font-semibold border-t border-slate-700 pt-0.5">
                <span className="text-slate-300">{t('total')}</span>
                <span className="tabular-nums text-slate-100">
                  {data.total_minutes_per_part > 0 ? '+' : ''}{data.total_minutes_per_part}
                </span>
              </li>
            )}
          </ul>
        </div>
      )}
      {data.max_lead_time_days != null && (
        <p className="text-xs text-slate-400">
          {t('summation.maxLeadTime')}: {data.max_lead_time_days} {t('summation.days')}
        </p>
      )}
      <p className="text-[11px] text-slate-500">{t('quote.basisHint')}</p>
    </div>
  )
}
