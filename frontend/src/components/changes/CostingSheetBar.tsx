/**
 * The strip above the costing buckets (spec §15 phase 2): which cost sheet
 * prices this change (version, plant, currency), a banner when Finance owes
 * a review of the sheet, the change's machine class (machine time and
 * sampling lines are priced on it; default from the impacted tool's tonnage),
 * and the totals per currency when the costing mixes currencies. The
 * summation's warnings (lines without a rate, mixed currencies) are shown
 * once, on the P&L card above.
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { changesApi } from '../../api/changes'
import { t } from '../../i18n/cmLabels'
import { formatDate, formatMoney } from '../../lib/format'
import type { Summation } from '../../types/change'

const errDetail = (e: unknown): string | undefined =>
  (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail

export default function CostingSheetBar({ changeId, summation, editable }: {
  changeId: number
  /** Only for those allowed to see the money. */
  summation?: Summation
  editable: boolean
}) {
  const qc = useQueryClient()
  const { data: ctx } = useQuery({
    queryKey: ['costing-context', changeId],
    queryFn: () => changesApi.costingContext(changeId),
    retry: false,
  })
  const setClass = useMutation({
    mutationFn: (id: number | null) => changesApi.setMachineClass(changeId, id),
    onSuccess: (data) => {
      qc.setQueryData(['costing-context', changeId], data)
      toast.success(t('costing.machineClassSaved'))
    },
    onError: (e: unknown) => toast.error(errDetail(e) ?? 'Could not set the machine class'),
  })
  if (!ctx) return null

  const vars = (s: string) => s
    .replace('{v}', String(ctx.current_version?.version ?? ctx.latest_version ?? '-'))
    .replace('{plant}', ctx.plant_name ?? '-')
    .replace('{cur}', ctx.currency)
  const source = ctx.rate_source === 'department_rate'
    ? vars(t('costing.sheetLegacy'))
    : ctx.current_version ? vars(t('costing.sheetInfo')) : t('costing.sheetNone')
  const stale = ctx.stale?.stale ? ctx.stale : null
  const defaultClass = ctx.machine_classes.find((c) => c.id === ctx.default_machine_class_id)
  const byCurrency = Object.entries(summation?.totals_by_currency ?? {})

  return (
    <div className="space-y-2" data-testid="costing-sheet-bar">
      {stale && (
        <div role="status" data-testid="costing-stale-banner"
          className="rounded-md border border-amber-700/70 bg-amber-950/40 px-3 py-2 text-sm text-amber-100">
          {stale.latest_version == null
            ? t('costing.staleNone')
            : t('costing.stale')
              .replace('{v}', String(stale.latest_version))
              .replace('{m}', String(stale.review_months))
              .replace('{due}', formatDate(stale.due_on))}
        </div>
      )}
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2 rounded-md border border-slate-700 bg-slate-800/40 px-3 py-2 text-xs text-slate-300">
        <span data-testid="costing-sheet-source"
          className={ctx.rate_source === 'cost_sheet' && ctx.current_version ? '' : 'text-amber-300'}>
          {source}
        </span>
        <span className="flex items-center gap-2">
          <label htmlFor={`machine-class-${changeId}`} className="text-slate-400">
            {t('costing.machineClass')}
          </label>
          <select id={`machine-class-${changeId}`} data-testid="costing-machine-class"
            disabled={!editable || !ctx.can_set_machine_class || setClass.isPending}
            value={ctx.machine_class_id ?? ''}
            onChange={(e) => setClass.mutate(e.target.value === '' ? null : Number(e.target.value))}
            className="bg-slate-900 border border-slate-600 rounded px-2 py-1 text-xs text-slate-100 disabled:opacity-60">
            <option value="">
              {t('costing.machineClassAuto')}: {defaultClass
                ? `${defaultClass.name} (${t('costing.machineClassDefault').replace('{t}', String(ctx.tonnage))})`
                : t('costing.machineClassNone')}
            </option>
            {ctx.machine_classes.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
        </span>
      </div>
      {summation?.mixed_currency && byCurrency.length > 1 && (
        <p data-testid="costing-totals-by-currency" className="text-xs text-slate-400">
          {t('costing.totalsByCurrency')}:{' '}
          {byCurrency.map(([cur, tot], i) => (
            <span key={cur} className="tabular-nums text-slate-200">
              {i > 0 && ' · '}{formatMoney(tot.grand_total, cur)}
            </span>
          ))}
        </p>
      )}
    </div>
  )
}
