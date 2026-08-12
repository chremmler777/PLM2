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
import { changesApi } from '../../api/changes'
import CostLineGrid from './CostLineGrid'
import CostPositions from './CostPositions'
import { t } from '../../i18n/cmLabels'
import type { ChangeDetail, Summation } from '../../types/change'

const errDetail = (e: unknown): string | undefined =>
  (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail

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
    onError: (e: unknown) => toast.error(errDetail(e) ?? 'Could not save the lead time'),
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
        className="bg-sky-600 hover:bg-sky-500 text-white px-2.5 py-1 rounded text-xs disabled:opacity-50">
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
  plants: { id: number; name: string; is_active?: boolean }[]
  projectPlantId?: number | null
  /** PM, Sales, the change lead and admins see every figure. */
  canSeeAll: boolean
  editable: boolean
  /** Project Management maintains any department's positions. */
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
  const leadTimeOf = (id: number) =>
    summation?.lead_time_by_department?.find((d) => d.department_id === id)?.lead_time_days
      ?? change.assessments.find((a) => a.department_id === id)?.lead_time_impact_days
      ?? null

  const rows = [...change.assessments]
    .sort((a, b) => a.stage_order - b.stage_order
      || deptName(a.department_id).localeCompare(deptName(b.department_id)))

  if (rows.length === 0) {
    return <p className="text-sm text-slate-400">{t('costing.none')}</p>
  }

  // An ordinary member gets their own bucket and nothing else — not even a
  // collapsed row for a department whose figures they may not read. The full
  // board belongs to PM, Sales, the lead and admins, exactly as in assessment.
  const visible = canSeeAll ? rows : rows.filter((r) => myDepartmentIds.includes(r.department_id))
  const others = rows.length - visible.length

  return (
    <div className="space-y-2">
      {visible.map((a) => {
        const id = a.department_id
        const isMine = myDepartmentIds.includes(id)
        const expanded = openDept === id
        const total = deptTotal(id)
        const filled = total != null ? total !== 0 : null
        return (
          <section key={id} data-testid={`costing-bucket-${id}`}
            className={`rounded-lg border ${
              expanded ? 'border-slate-600 bg-slate-800' : 'border-slate-700 bg-slate-800/50'}`}>
            <button type="button" data-testid={`costing-toggle-${id}`}
              aria-expanded={expanded}
              onClick={() => setOpenDept(expanded ? null : id)}
              className="w-full flex items-center gap-3 px-3 py-2 text-left">
              <span aria-hidden className="text-slate-500 text-xs w-3 flex-shrink-0">
                {expanded ? '▾' : '▸'}
              </span>
              <span className="text-slate-100 font-medium truncate">{deptName(id)}</span>
              {isMine && (
                <span className="rounded bg-sky-900/70 text-sky-200 px-1.5 py-0 text-[10px] leading-tight flex-shrink-0">
                  {t('costing.yourBucket')}
                </span>
              )}
              <span data-testid={`costing-state-${id}`}
                className={`rounded px-1.5 py-0 text-[10px] leading-tight font-medium flex-shrink-0 ${
                  filled === null ? 'bg-slate-700 text-slate-400'
                  : filled ? 'bg-emerald-900/70 text-emerald-200'
                  : 'bg-slate-700 text-slate-300'}`}
                title={filled === null ? t('costing.hiddenHint') : undefined}>
                {filled === null ? t('costing.hidden')
                  : filled ? t('costing.filled') : t('costing.empty')}
              </span>
              <span className="ml-auto flex items-center gap-3 flex-shrink-0 text-xs text-slate-400">
                {leadTimeOf(id) != null && (
                  <span data-testid={`costing-lead-${id}`}>
                    {leadTimeOf(id)} {t('summation.days')}
                  </span>
                )}
                {/* Figures ride along only for those allowed to see them. */}
                {canSeeAll && total != null && (
                  <span data-testid={`costing-total-${id}`} className="tabular-nums text-slate-300">
                    {total.toFixed(2)}
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
                      editable={editable && (isMine || isPm)} />
                    <CostLineGrid changeId={changeId} assessmentId={a.id} departmentId={id}
                      plants={plants} projectPlantId={projectPlantId} />
                    {editable && (
                      <LeadTimeField changeId={changeId} departmentId={id}
                        initial={leadTimeOf(id)} />
                    )}
                  </>
                ) : (
                  <div className="text-sm space-y-3" data-testid={`costing-readonly-${id}`}>
                    <p className="text-slate-300">
                      {t('costing.deptTotal')}: <span className="tabular-nums">
                        {total != null ? total.toFixed(2) : '—'}
                      </span>
                    </p>
                    {leadTimeOf(id) != null && (
                      <p className="text-slate-400">
                        {t('costing.leadTime')}: {leadTimeOf(id)}
                      </p>
                    )}
                    {/* PM may still fix another department's positions; Sales
                        and the lead only read them. */}
                    <CostPositions changeId={changeId} departmentId={id}
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
          {t('costing.others').replace('{n}', String(others))}
        </p>
      )}
    </div>
  )
}
