/**
 * The costing phase, one bucket per participating department — the same shape as
 * the assessment accordion, so the two phases read alike.
 *
 * A department opens its own bucket and works in it: cost positions, cost lines
 * and the lead time it needs. Other people's figures are not theirs to see — an
 * ordinary member gets their own bucket and nothing else, the same way the
 * assessment board works. PM, Sales, the lead and admins see every bucket and
 * the money in the summation below, which is where the whole picture belongs.
 */
import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { ChevronDown, ChevronRight, CircleAlert } from 'lucide-react'
import { changesApi } from '../../api/changes'
import { toastError } from '../../lib/apiError'
import { btnSm } from '../common/buttonStyles'
import CostLineGrid from './CostLineGrid'
import CostPositions from './CostPositions'
import CostingSheetBar from './CostingSheetBar'
import PlantNotInUseNote from '../common/PlantNotInUseNote'
import { t } from '../../i18n/cmLabels'
import { formatDays, formatMoney, formatNumber } from '../../lib/format'
import type { ChangeDetail, DeptRollup, Summation } from '../../types/change'

function LeadTimeField({ changeId, departmentId, initial }: {
  changeId: number; departmentId: number; initial: number | null | undefined
}) {
  const qc = useQueryClient()
  const [days, setDays] = useState(initial != null ? String(initial) : '')
  const save = useMutation({
    mutationFn: () => changesApi.setCostLeadTime(changeId, departmentId, Number(days)),
    onSuccess: () => {
      toast.success(t('costing.leadTimeSaved'))
      qc.invalidateQueries({ queryKey: ['change', changeId] })
      qc.invalidateQueries({ queryKey: ['change-summation', changeId] })
    },
    onError: (e: unknown) => toastError(e, 'Could not save the lead time'),
  })
  const dirty = days.trim() !== '' && Number(days) !== (initial ?? null)
  return (
    <div className="flex items-end gap-2">
      <div>
        <label htmlFor={`lead-${departmentId}`} className="block text-xs text-slate-500 mb-1">
          {t('costing.leadTime')}
        </label>
        <input id={`lead-${departmentId}`} type="number" min={0} step={1}
          data-testid={`lead-time-${departmentId}`}
          value={days} onChange={(e) => setDays(e.target.value)}
          className="w-24 bg-slate-900 border border-slate-600 rounded px-2 py-1 text-sm text-slate-100" />
      </div>
      <button type="button" data-testid={`lead-time-save-${departmentId}`}
        disabled={!dirty || save.isPending}
        onClick={() => save.mutate()}
        className={btnSm.secondary}>
        {t('common.save')}
      </button>
    </div>
  )
}

export default function CostingBuckets({
  change, departments, myDepartmentIds, plants, projectPlantId, canSeeAll, editable,
  isPm = false,
}: {
  change: ChangeDetail
  departments: { id: number; name: string; is_active?: boolean }[]
  myDepartmentIds: number[]
  plants: { id: number; name: string; is_active?: boolean; code?: string | null; location?: string | null }[]
  projectPlantId?: number | null
  /** PM, Sales, the change lead and admins see every figure. */
  canSeeAll: boolean
  editable: boolean
  /** Project Management (and an admin not acting as a department) maintains
      any department's positions — the backend allows both. */
  isPm?: boolean
}) {
  const changeId = change.id
  const [openDept, setOpenDept] = useState<number | null>(null)

  // Only the privileged view may ask for the summation, so only it can tell a
  // filled bucket from an empty one for someone else's department.
  const { data: summation } = useQuery<Summation>({
    queryKey: ['change-summation', changeId],
    queryFn: () => changesApi.getSummation(changeId),
    enabled: canSeeAll,
  })

  const deptName = (id: number) => departments.find((d) => d.id === id)?.name ?? `#${id}`
  const deptTotal = (id: number) => {
    const row = summation?.by_department.find((d) => d.department_id === id)
    if (!row) return null
    return row.one_time_internal + row.one_time_external
      + row.lifecycle_internal + row.lifecycle_external
  }
  // Money in another currency than the costing's is booked only into
  // totals_by_currency (backend _book), never into by_department: look for it
  // in the department's plant cells and positions, which carry their currency.
  const deptForeignMoney = (id: number) => {
    if (!summation) return false
    const cur = summation.currency
    const cells = (summation as Summation & { by_department_plant?: (DeptRollup & { plant_id: number })[] })
      .by_department_plant ?? []
    return cells.some((c) => c.department_id === id && !!c.currency && c.currency !== cur
      && (c.one_time_internal || c.one_time_external || c.lifecycle_internal || c.lifecycle_external))
      || (summation.positions_by_department ?? []).some((d) => d.department_id === id
        && d.positions.some((p) => !!p.currency && p.currency !== cur && (!!p.cost || !!p.line_value)))
  }
  /** Costed at all, in any currency; null when the figures are not ours to read. */
  const deptCosted = (id: number): boolean | null => {
    const tot = deptTotal(id)
    if (tot == null) return deptForeignMoney(id) ? true : null
    return tot !== 0 || deptForeignMoney(id)
  }
  const leadTimeOf = (id: number) =>
    summation?.lead_time_by_department?.find((d) => d.department_id === id)?.lead_time_days
      ?? change.assessments.find((a) => a.department_id === id)?.lead_time_impact_days
      ?? null

  // One bucket per department: a department routed on several stages (or
  // re-routed) still has one costing table, bound to its earliest row.
  const rows = [...change.assessments]
    .sort((a, b) => a.stage_order - b.stage_order
      || deptName(a.department_id).localeCompare(deptName(b.department_id)))
    .filter((a, i, all) => all.findIndex((x) => x.department_id === a.department_id) === i)

  if (rows.length === 0) {
    return <p className="text-sm text-slate-400">{t('costing.none')}</p>
  }
  const sheetBar = (
    <CostingSheetBar changeId={changeId} summation={canSeeAll ? summation : undefined}
      editable={editable} />
  )
  // Costing-side truth for the step button in the cockpit: a costing with no
  // money in it is not a basis for a quote. Said here, where it can be fixed.
  const unbooked = canSeeAll && summation
    ? rows.filter((a) => {
      const priced = deptCosted(a.department_id) === true
      const unpriced = (summation.unpriced_lines ?? []).some((l) => l.department_id === a.department_id)
      return !priced && !unpriced
    }).map((a) => deptName(a.department_id))
    : []
  const nothingCosted = !!summation && canSeeAll && change.status === 'costing'
    && Math.abs(summation.totals?.grand_total ?? 0) < 0.005
    && Object.values(summation.totals_by_currency ?? {}).every((g) => Math.abs(g.grand_total ?? 0) < 0.005)
    && (summation.unpriced_lines ?? []).length === 0

  // An ordinary member gets their own bucket and nothing else — not even a
  // collapsed row for a department whose figures they may not read. The full
  // board belongs to PM, Sales, the lead and admins, exactly as in assessment.
  const visible = canSeeAll ? rows : rows.filter((r) => myDepartmentIds.includes(r.department_id))
  // Who is still costing: the backend's own list (costing_pending_department_ids),
  // the one the cockpit's "waiting on" reads, less the viewer's departments.
  const others = change.status !== 'costing' ? 0
    : (change.costing_pending_department_ids ?? [])
      .filter((id) => !myDepartmentIds.includes(id)).length

  return (
    <div className="space-y-2">
      {sheetBar}
      {/* Mexico (Silao) among the change's plants: not in use yet, said once. */}
      <PlantNotInUseNote plants={plants} />
      {change.status === 'costing' && canSeeAll && summation && (nothingCosted || unbooked.length > 0) && (
        <div role="status" data-testid="costing-readiness"
          className={`flex items-start gap-2 rounded-md border px-3 py-2 text-sm ${nothingCosted
            ? 'border-amber-700/70 bg-amber-950/40 text-amber-100'
            : 'border-slate-700 bg-slate-800/40 text-slate-300'}`}>
          <CircleAlert aria-hidden="true" size={16} className={`mt-0.5 shrink-0 ${nothingCosted ? 'text-amber-300' : 'text-slate-400'}`} />
          <span>
            {nothingCosted
              ? `Nothing is costed yet: the total is ${summation.currency ? formatMoney(0, summation.currency) : '0.00'}. `
                + 'Close costing once the departments have booked their lines, or Sales quotes from an empty basis.'
              : `${unbooked.length} of ${rows.length} department${rows.length === 1 ? '' : 's'} `
                + `ha${unbooked.length === 1 ? 's' : 've'} not costed yet: ${unbooked.join(', ')}.`}
          </span>
        </div>
      )}
      {visible.map((a) => {
        const id = a.department_id
        const isMine = myDepartmentIds.includes(id)
        const expanded = openDept === id
        const total = deptTotal(id)
        const filled = deptCosted(id)
        // Entered, but no cost sheet rate: not "Empty" (the department did
        // its part), and not a price either.
        const noRate = !filled && (summation?.unpriced_lines ?? []).some((l) => l.department_id === id)
        return (
          <section key={id} data-testid={`costing-bucket-${id}`}
            className={`rounded-lg border ${
              expanded ? 'border-slate-600 bg-slate-800' : 'border-slate-700 bg-slate-800/50'}`}>
            <button type="button" data-testid={`costing-toggle-${id}`}
              aria-expanded={expanded}
              onClick={() => setOpenDept(expanded ? null : id)}
              className="w-full flex items-center gap-3 px-3 py-2 text-left">
              <span aria-hidden="true" className="text-slate-500 w-3.5 flex-shrink-0">
                {expanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
              </span>
              <span className="text-slate-100 font-medium truncate">{deptName(id)}</span>
              {isMine && (
                <span className="rounded bg-sky-900/70 text-sky-200 px-1.5 py-0 text-[11px] leading-tight flex-shrink-0">
                  {t('costing.yourBucket')}
                </span>
              )}
              <span data-testid={`costing-state-${id}`}
                className={`rounded px-1.5 py-0 text-[11px] leading-tight font-medium flex-shrink-0 ${
                  noRate ? 'bg-amber-900/70 text-amber-200'
                  : filled === null ? 'bg-slate-700 text-slate-400'
                  : filled ? 'bg-emerald-900/70 text-emerald-200'
                  : 'bg-slate-700 text-slate-300'}`}
                title={noRate ? t('costing.noRateHint') : filled === null ? t('costing.hiddenHint') : undefined}>
                {noRate ? t('costing.noRate') : filled === null ? t('costing.hidden')
                  : filled ? t('costing.filled') : t('costing.empty')}
              </span>
              <span className="ml-auto flex items-center gap-3 flex-shrink-0 text-xs text-slate-400">
                {leadTimeOf(id) != null && (
                  <span data-testid={`costing-lead-${id}`}>
                    {formatDays(leadTimeOf(id))}
                  </span>
                )}
                {/* Figures ride along only for those allowed to see them. */}
                {canSeeAll && total != null && (
                  <span data-testid={`costing-total-${id}`} className="tabular-nums text-slate-300">
                    {summation?.currency ? formatMoney(total, summation.currency) : formatNumber(total, { min: 2, max: 2 })}
                  </span>
                )}
              </span>
            </button>

            {expanded && (
              <div className="border-t border-slate-700 px-3 py-3 space-y-3">
                {isMine ? (
                  <>
                    {/* What this department books against the change, above the
                        old grid — the grid keeps working, position by position
                        is how departments actually think about it. */}
                    <CostPositions changeId={changeId} departmentId={id}
                      departmentName={deptName(id)}
                      partWeightG={change.estimated_part_weight_g}
                      editable={editable && (isMine || isPm)} />
                    {/* The per-plant workbook matrix: lifecycle cycle-time
                        deltas and hours × rate per plant. Kept under the
                        table, one click away, for the departments that
                        still think in it. */}
                    <details open className="rounded border border-slate-700/70 bg-slate-900/30 px-2 py-1.5"
                      data-testid={`costing-plant-lines-${id}`}>
                      <summary className="cursor-pointer text-[11px] uppercase tracking-wide text-slate-500 select-none">
                        {t('costpos.plantLines')}
                      </summary>
                      <div className="pt-2">
                        <CostLineGrid changeId={changeId} assessmentId={a.id} departmentId={id}
                          plants={plants} projectPlantId={projectPlantId} />
                      </div>
                    </details>
                    {editable && (
                      <LeadTimeField changeId={changeId} departmentId={id}
                        initial={leadTimeOf(id)} />
                    )}
                  </>
                ) : (
                  <div className="text-sm space-y-3" data-testid={`costing-readonly-${id}`}>
                    <p className="text-slate-300">
                      {t('costing.deptTotal')}: <span className="tabular-nums">
                        {total != null
                          ? (summation?.currency ? formatMoney(total, summation.currency) : formatNumber(total, { min: 2, max: 2 }))
                          : '-'}
                      </span>
                    </p>
                    {leadTimeOf(id) != null && (
                      <p className="text-slate-400">
                        {t('costing.leadTime')}: {formatDays(leadTimeOf(id))}
                      </p>
                    )}
                    {/* PM may still fix another department's positions; Sales
                        and the lead only read them. */}
                    <CostPositions changeId={changeId} departmentId={id}
                      departmentName={deptName(id)}
                      partWeightG={change.estimated_part_weight_g}
                      editable={editable && isPm} />
                  </div>
                )}
              </div>
            )}
          </section>
        )
      })}

      {/* Everyone else, in one line: enough to know the change is not sitting on
          this department alone, without showing figures they may not read. */}
      {!canSeeAll && others > 0 && (
        <p data-testid="costing-others" className="text-xs text-slate-400 px-1 py-1">
          {t('costing.others').replace('{n}', String(others)).replace('{s}', others === 1 ? '' : 's')}
        </p>
      )}
    </div>
  )
}
