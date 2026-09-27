/**
 * The strip above the costing buckets (spec §15 phase 2): which cost sheet
 * prices this change (the version valid on the day the change was created,
 * plant, currency), a banner when Sales owes
 * a review of the sheet, the change's machine class (machine time and
 * sampling lines are priced on it; default from the tonnage of the change's
 * tools, MachineDB first, TWOS second, said with its source, and a refresh
 * that asks both again),
 * and the totals per currency when the costing mixes currencies. The
 * summation's warnings (lines without a rate, mixed currencies) are shown
 * once, on the P&L card above.
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { changesApi } from '../../api/changes'
import { toastError } from '../../lib/apiError'
import { t } from '../../i18n/cmLabels'
import { formatCalendarDate, formatMoney } from '../../lib/format'
import type { Summation } from '../../types/change'
import { machineClassOriginDetail, machineClassOriginText } from './machineClassOrigin'

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
    onError: (e: unknown) => toastError(e, 'Could not set the machine class'),
  })
  const refresh = useMutation({
    mutationFn: () => changesApi.refreshToolTonnage(changeId),
    onSuccess: (data) => {
      qc.setQueryData(['costing-context', changeId], data)
      // a line not priced yet may price now; priced lines keep their class
      qc.invalidateQueries({ queryKey: ['costing-positions', changeId] })
      qc.invalidateQueries({ queryKey: ['change-summation', changeId] })
      const r = data.tool_tonnage_refresh
      // the backend's error text is safe to show (no token, no body): it
      // tells "not deployed yet" apart from "not reachable"
      const failed = r ? ([['costing.tonnageSource.machinedb', r.machinedb],
        ['costing.tonnageSource.twos', r.twos]] as const)
        .filter(([, s]) => s.status === 'failed')
        .map(([key, s]) => ({ source: t(key), error: s.error })) : []
      if (failed.length) {
        toast.warning(failed.every((f) => f.error)
          ? t('costing.refreshTonnageFailedWhy')
            .replace('{why}', failed.map((f) => `${f.source}: ${f.error}`).join('; '))
          : t('costing.refreshTonnageFailed')
            .replace('{source}', failed.map((f) => f.source).join(', ')))
      } else {
        toast.success(t('costing.refreshTonnageDone'))
      }
    },
    onError: (e: unknown) => toastError(e, 'Could not refresh the tool tonnage'),
  })
  if (!ctx) return null

  const vars = (s: string) => s
    .split('{v}').join(String(ctx.current_version?.version ?? ctx.latest_version ?? '-'))
    .replace('{plant}', ctx.plant_name ?? '-')
    .replace('{cur}', ctx.currency)
    .replace('{date}', ctx.pricing_date ? formatCalendarDate(ctx.pricing_date) : '-')
  const source = ctx.rate_source === 'department_rate'
    ? vars(t('costing.sheetLegacy'))
    : ctx.current_version
      // older than the first version: priced with it, and said so
      ? vars(t(ctx.pricing_note ? 'costing.sheetEarliest' : 'costing.sheetInfo'))
      : vars(t('costing.sheetNone'))
  const stale = ctx.stale?.stale ? ctx.stale : null
  const defaultClass = ctx.machine_classes.find((c) => c.id === ctx.default_machine_class_id)
  const origin = ctx.tool_class_origin ?? null
  const originText = machineClassOriginText(origin)
  // who may set the class, or sync the machines (Sales, Finance, admins);
  // a refresh writes tool data, not the costing, so not tied to editable
  const canRefresh = !!(ctx.can_refresh_tonnage ?? ctx.can_set_machine_class)
    && !!(ctx.tonnage_sources?.machinedb || ctx.tonnage_sources?.twos)
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
              .replace('{due}', formatCalendarDate(stale.due_on))}
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
                ? (origin?.kind === 'tool' && originText
                  ? `${defaultClass.name}, ${originText}`
                  : `${defaultClass.name} (${t('costing.machineClassDefault').replace('{t}', String(ctx.tonnage))})`)
                : t('costing.machineClassNone')}
            </option>
            {ctx.machine_classes.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
        </span>
        {ctx.machine_class_id == null && originText && (!defaultClass || origin?.kind !== 'tool') && (
          <span data-testid="costing-class-origin" className="text-amber-300"
            title={machineClassOriginDetail(origin) ?? undefined}>
            {originText}
          </span>
        )}
        {canRefresh && (
          <button type="button" data-testid="costing-refresh-tonnage"
            onClick={() => refresh.mutate()} disabled={refresh.isPending}
            className="rounded border border-slate-600 px-2 py-0.5 text-xs text-slate-200 hover:bg-slate-700 disabled:opacity-60">
            {t('costing.refreshTonnage')}
          </button>
        )}
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
