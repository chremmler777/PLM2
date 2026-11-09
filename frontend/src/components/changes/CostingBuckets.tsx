/**
 * The costing phase, one bucket per participating department — the same shape as
 * the assessment accordion, so the two phases read alike.
 *
 * A department opens its own bucket and works in it: cost positions, cost lines
 * and the lead time it needs. Other people's figures are not theirs to see — an
 * ordinary member gets their own bucket and nothing else, the same way the
 * assessment board works. PM, Sales, the lead and admins see every bucket and
 * the money in the summation below, which is where the whole picture belongs.
 *
 * Per-department pipeline (2026-10-14): a department costs and FINALIZES its
 * part as soon as it has submitted its assessment as feasible (and owes a cost
 * input), while the change is still in assessment. A finalized part is
 * read-only for the department until it reopens it; PM and admin may still fix
 * it. While in assessment the board lists only the departments already costing.
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
import {
  NoCostButton, SupplierWaitDecisions, SupplierWaitPanel, noCostWords,
} from './costing/NoCostAndWaits'
import PlantNotInUseNote from '../common/PlantNotInUseNote'
import PmCostingOverview from './costing/PmCostingOverview'
import { t } from '../../i18n/cmLabels'
import { formatDate, formatDays, formatMoney, formatNumber } from '../../lib/format'
import type { ChangeDetail, DeptRollup, Summation } from '../../types/change'

/** Finalize / reopen the department's own costing (the backend refuses a
 *  finalize with nothing entered: a zero line is an answer, nothing is not).
 *
 *  Christoph 2026-11-08: Finalize is THE step that tells the PM a department
 *  is done. It sits at the end of the department's lines, large; while
 *  something is missing it is disabled with the list from finalize-check; once
 *  nothing is missing it is also pinned at the top. Pressing it asks inline
 *  (no modal), and afterwards the bar says who finalized, what happens next
 *  and who may reopen. */
function FinalizeBar({ changeId, departmentId, finalized, v2 = false, departmentName = '',
  noCost, placement = 'end', finalizedBy, finalizedAt, pmName }: {
  changeId: number; departmentId: number; finalized: boolean
  /** ASSESSMENT_V2: "<Dept> has no cost" beside Finalize (C18). */
  v2?: boolean
  departmentName?: string
  /** The department's "no cost" answer, when that is how it finalized. */
  noCost?: string | null
  /** 'top': only the finalized state, or the call once nothing is missing;
   *  'end': the full call with what is missing (under the lines). */
  placement?: 'top' | 'end'
  finalizedBy?: string | null
  finalizedAt?: string | null
  /** The project's PM, named in "what happens next". */
  pmName?: string | null
}) {
  const qc = useQueryClient()
  const [confirming, setConfirming] = useState(false)
  const [keptWorking, setKeptWorking] = useState(false)
  // Christoph 2026-11-08: "has no cost" only while the department has no cost
  // line (anything beyond the booked assessment/costing hours)
  const { data: allPositions } = useQuery({
    queryKey: ['costing-positions', changeId],
    queryFn: () => changesApi.listCostPositions(changeId),
    enabled: v2,
  })
  const hasCostLines = (allPositions ?? []).some((p) => p.department_id === departmentId
    && (p.kind === 'external' || (p.kind !== 'internal_effort' && p.notes !== 'From the bookings'
      && ((p.hours ?? 0) > 0 || (p.est_cost ?? 0) > 0))))
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ['change', changeId] })
    qc.invalidateQueries({ queryKey: ['change-my-actions', changeId] })
    qc.invalidateQueries({ queryKey: ['change-summation', changeId] })
  }
  const finalize = useMutation({
    mutationFn: () => changesApi.finalizeDepartmentCosting(changeId, departmentId),
    onSuccess: () => { toast.success(t('costing.finalizedSaved')); setConfirming(false); refresh() },
    onError: (e: unknown) => toastError(e, 'Could not finalize the costing'),
  })
  const { data: check, isFetched } = useQuery({
    queryKey: ['change', changeId, 'finalize-check', departmentId],
    queryFn: () => changesApi.finalizeCheck(changeId, departmentId),
    enabled: !finalized,
  })
  const reasons = finalized ? [] : (check?.reasons ?? [])
  const reopen = useMutation({
    mutationFn: () => changesApi.reopenDepartmentCosting(changeId, departmentId),
    onSuccess: () => { toast.success(t('costing.reopenInputSaved')); setKeptWorking(false); refresh() },
    onError: (e: unknown) => toastError(e, 'Could not reopen the costing'),
  })
  const TAG_STYLE: Record<string, string> = {
    waiting: 'bg-sky-700 text-white', compare: 'bg-amber-600 text-white', favourite: 'bg-amber-600 text-white',
    quote_missing: 'bg-red-700 text-white', price_missing: 'bg-red-700 text-white',
    basis_missing: 'bg-red-700 text-white', hours_missing: 'bg-red-700 text-white',
    empty: 'bg-slate-600 text-white', other: 'bg-slate-600 text-white',
    received: 'bg-emerald-700 text-white', waiting_info: 'bg-sky-800 text-sky-100',
    book_hours: 'bg-red-700 text-white',
  }
  const items: { tag: string; text: string; info?: boolean }[] = check?.items ?? reasons.map((r) => ({ tag: 'other', text: r }))
  const blocking = items.filter((i) => !i.info)
  const infoItems = items.filter((i) => i.info)
  const ready = !finalized && isFetched && reasons.length === 0
  const dept = departmentName || 'this department'

  if (finalized) {
    // the finalized state lives at the top of the bucket, once
    if (placement !== 'top') return null
    return (
      <div data-testid={`costing-finalize-bar-${departmentId}`}
        className="rounded border border-emerald-800/70 bg-emerald-950/20 px-3 py-2 text-xs text-slate-300">
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div className="space-y-0.5">
            <p className="text-sm font-medium text-emerald-200" data-testid={`costing-finalized-by-${departmentId}`}>
              {noCost ? t('nocost.finalized').replace('{x}', noCost) : t('costing.finalized')}
              {finalizedBy ? ` by ${finalizedBy}` : ''}{finalizedAt ? `, ${formatDate(finalizedAt)}` : ''}
            </p>
            {/* Christoph 2026-11-08: after finalizing, the department is done until implementation */}
            <p data-testid={`costing-allset-${departmentId}`} className="text-base font-semibold text-emerald-200">
              All set for now.
            </p>
            <p data-testid={`costing-next-${departmentId}`}>
              Nothing more to do for {dept} until implementation: {pmName ? `the PM (${pmName})` : 'the PM'} and
              Sales take it from here (offer to the customer). You will be asked again when the change goes into implementation.
            </p>
            <p className="text-slate-400">
              To change a line, reopen: a member of {dept}, Project Management or an admin can, while costing is open.
            </p>
          </div>
          <button type="button" data-testid={`costing-reopen-${departmentId}`}
            disabled={reopen.isPending} onClick={() => reopen.mutate()}
            className={btnSm.secondary}>
            {t('costing.reopenInput')}
          </button>
        </div>
      </div>
    )
  }
  // at the top only once nothing is missing: the call, pinned
  if (placement === 'top') return null  // one Finalize button, at the end of the department (Christoph 2026-11-08)

  const confirmPanel = confirming && (
    <div role="group" aria-label="Confirm finalize" data-testid={`costing-finalize-confirm-${departmentId}`}
      className="mx-3 mb-3 rounded border border-slate-500 bg-slate-800 px-3 py-2 text-sm text-slate-100">
      <p>Finalize costing for {dept}? You can&apos;t change your lines afterwards; the PM takes over (offer).</p>
      <div className="mt-2 flex gap-2">
        <button type="button" data-testid={`costing-finalize-now-${departmentId}`}
          disabled={finalize.isPending} onClick={() => finalize.mutate()} className={btnSm.primary}>
          Finalize now
        </button>
        <button type="button" data-testid={`costing-keep-working-${departmentId}`}
          onClick={() => { setConfirming(false); setKeptWorking(true) }} className={btnSm.secondary}>
          Keep working
        </button>
      </div>
    </div>
  )

  return (
    <div data-testid={`costing-finalize-bar-${departmentId}`}
      className="rounded border border-slate-600 bg-slate-900/60 text-xs text-slate-300">
      {/* Christoph 2026-11-08: one container of line items, a coloured banner each */}
      {/* Christoph 2026-11-08: same look as the assessment's open points */}
      {placement === 'end' && blocking.length > 0 && (
        <div className="m-2 rounded border border-red-700/60 bg-red-950/20 px-2 py-1.5"
          data-testid={`costing-why-not-${departmentId}`}>
          <p className="text-[11px] font-semibold uppercase tracking-wide text-red-300">
            {t('bucket.openPoints').replace('{n}', String(blocking.length))}</p>
          <ul className="mt-0.5 space-y-0.5 text-xs text-red-100">
            {blocking.map((r, n) => (
              <li key={n}>• <span className="mr-1 rounded bg-red-800/80 px-1 text-[10px] font-semibold text-red-50">
                {t(`costing.tag.${r.tag}`)}</span>{r.text}</li>
            ))}
          </ul>
        </div>
      )}
      {placement === 'end' && infoItems.length > 0 && (
        <div className="mx-2 mb-2 rounded border border-slate-700 bg-slate-900/40 px-2 py-1.5">
          <p className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">{t('costing.quoteStatus')}</p>
          <ul className="mt-0.5 space-y-0.5 text-xs text-slate-300">
            {infoItems.map((r, n) => (
              <li key={n}>• <span className={`mr-1 rounded px-1 text-[10px] font-semibold ${TAG_STYLE[r.tag] ?? TAG_STYLE.other}`}>
                {t(`costing.tag.${r.tag}`)}</span>{r.text}</li>
            ))}
          </ul>
        </div>
      )}
      <div className="flex flex-wrap items-center justify-between gap-3 px-3 py-3">
        <div className="space-y-0.5">
          <p className="text-sm text-slate-100">
            {ready
              ? 'Everything is entered: finalize, the PM then knows your department is done.'
              : 'When everything is entered, finalize: the PM then knows your department is done.'}
          </p>
          {keptWorking && (
            <p className="text-amber-300" data-testid={`costing-kept-working-${departmentId}`}>
              Not finalized: the PM sees your department as open.
            </p>
          )}
          {v2 && placement === 'end' && !hasCostLines && (
            <NoCostButton changeId={changeId} departmentId={departmentId} departmentName={departmentName} />
          )}
        </div>
        {!confirming && (
          <button type="button" data-testid={`costing-finalize-${departmentId}`}
            disabled={finalize.isPending || !ready} onClick={() => setConfirming(true)}
            title={ready ? undefined : `${blocking.length || reasons.length} open point(s) first`}
            className="rounded-md bg-sky-600 px-5 py-2 text-sm font-semibold text-white hover:bg-sky-500 disabled:cursor-not-allowed disabled:bg-slate-700 disabled:text-slate-400">
            {t('costing.finalize')}
          </button>
        )}
      </div>
      {confirmPanel}
    </div>
  )
}

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

/** The department answered Yes to a cycle-time change (the per-plant grid's job). */
function cycleTimeYes(a: { details?: unknown } | undefined): boolean {
  if (!a) return false
  let d: Record<string, unknown> = {}
  try { d = typeof a.details === 'string' ? JSON.parse(a.details) : ((a.details as Record<string, unknown>) ?? {}) } catch { d = {} }
  const imp = (d.impacts as { key?: string; answer?: string; impacted?: boolean }[] | undefined) ?? []
  return imp.some((i) => i.key === 'cycle_time_change' && (i.answer === 'yes' || i.impacted))
}

/** Departments whose costing row exists for the offer only (R37). */
const COMMERCIAL_DEPTS = ['Sales', 'Project Manager']

export default function CostingBuckets({
  change, departments, myDepartmentIds, plants, projectPlantId, canSeeAll, editable,
  isPm = false, canDecideWaits = false,
}: {
  /** The lead, PM or admin: §5 "Wait for <vendor>" / "Price on estimate". */
  canDecideWaits?: boolean
  change: ChangeDetail
  departments: { id: number; name: string; is_active?: boolean }[]
  myDepartmentIds: number[]
  plants: { id: number; name: string; is_active?: boolean; code?: string | null; location?: string | null }[]
  projectPlantId?: number | null
  /** PM, Sales, Management, the change lead and admins see every figure. */
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

  const early = change.status === 'in_assessment'
  const live = early || change.status === 'costing'
  const finalizedIds = change.costing_finalized_department_ids ?? []
  const isFinalized = (id: number) => finalizedIds.includes(id)
  // Finalize / reopen only for a department that owes a cost input: one whose
  // checklist marked nothing impacted has nothing to finalize (the backend
  // refuses it with a 400 in assessment and in costing alike).
  const owesInput = (id: number) => (change.costing_owed_department_ids ?? []).includes(id)
  // In assessment only the departments whose costing is open: submitted
  // feasible, owing a cost input (or already finalized).
  const earlyIds = new Set([...(change.costing_owed_department_ids ?? []), ...finalizedIds])
  // One bucket per department: a department routed on several stages (or
  // re-routed) still has one costing table, bound to its earliest row.
  const rows = [...change.assessments]
    .sort((a, b) => a.stage_order - b.stage_order
      || deptName(a.department_id).localeCompare(deptName(b.department_id)))
    .filter((a, i, all) => all.findIndex((x) => x.department_id === a.department_id) === i)
    .filter((a) => !early || earlyIds.has(a.department_id))
    // R37: an internal change has no offer and no customer, so Sales and
    // the PM row (summation / customer stages) cost nothing there; a row
    // that already holds money (in flight) still shows.
    .filter((a) => change.customer_relevant !== false
      || !COMMERCIAL_DEPTS.includes(deptName(a.department_id))
      || deptCosted(a.department_id) === true)

  if (rows.length === 0) {
    return <p data-testid="costing-none" className="text-sm text-slate-400">
      {t(early ? 'costing.earlyNone' : 'costing.none')}</p>
  }
  const sheetBar = (
    <CostingSheetBar changeId={changeId} summation={canSeeAll ? summation : undefined}
      editable={editable} />
  )
  // Who still owes a cost input: the backend's own list, the one the cockpit's
  // "Waiting on cost input" counts, so the two never disagree. A department
  // that is only consulted or informed owes nothing, and a zero line is an
  // answer (ChangeService.costing_pending_department_ids).
  const owing = live
    ? (change.costing_pending_department_ids ?? []).map(deptName)
    : []
  const owedTotal = change.costing_owed_department_ids?.length
  const finalizedOwed = finalizedIds.filter((d) =>
    (change.costing_owed_department_ids ?? finalizedIds).includes(d)).length
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
  const others = !live ? 0
    : (change.costing_pending_department_ids ?? [])
      .filter((id) => !myDepartmentIds.includes(id)).length

  // Christoph 2026-11-08: the PM's overview names every department that owes
  // costing (or already finalized it) and jumps to its bucket.
  const owedRows = rows.filter((r) => !change.costing_owed_department_ids
    || owesInput(r.department_id) || isFinalized(r.department_id))
    .map((r) => r.department_id)
  const jumpTo = (id: number) => {
    setOpenDept(id)
    requestAnimationFrame(() => document.getElementById(`costing-dept-${id}`)
      ?.scrollIntoView({ behavior: 'smooth', block: 'start' }))
  }

  // The project's PM, named in a finalized bar's "what happens next".
  const pmDeptId = departments.find((d) => d.name === 'Project Manager')?.id
  const pmRow = change.assessments.find((x) => x.department_id === pmDeptId)
  const pmName = pmRow?.owner_name ?? pmRow?.responsible_name ?? null
  const finalizeBar = (id: number, placement: 'top' | 'end') => {
    const info = change.costing_finalized_info?.[String(id)]
    return (
      <FinalizeBar changeId={changeId} departmentId={id} finalized={isFinalized(id)}
        v2={!!change.assessment_v2} departmentName={deptName(id)} placement={placement}
        noCost={noCostWords(change.costing_no_cost?.[String(id)])}
        finalizedBy={info?.by_name} finalizedAt={info?.at} pmName={pmName} />
    )
  }

  return (
    <div className="space-y-2">
      {canSeeAll && owedRows.length > 0 && (
        <PmCostingOverview change={change} departmentIds={owedRows} deptName={deptName}
          summation={summation} isPm={isPm} onJump={jumpTo} />
      )}
      {sheetBar}
      {/* Mexico (Silao) among the change's plants: not in use yet, said once. */}
      <PlantNotInUseNote plants={plants} />
      {live && change.assessment_v2 && (
        <SupplierWaitDecisions changeId={changeId} waits={change.open_supplier_waits ?? []}
          canDecide={canDecideWaits && editable} />
      )}
      {live && canSeeAll && (nothingCosted || owing.length > 0) && (
        <div role="status" data-testid="costing-readiness"
          className={`flex items-start gap-2 rounded-md border px-3 py-2 text-sm ${nothingCosted
            ? 'border-amber-700/70 bg-amber-950/40 text-amber-100'
            : 'border-slate-700 bg-slate-800/40 text-slate-300'}`}>
          <CircleAlert aria-hidden="true" size={16} className={`mt-0.5 shrink-0 ${nothingCosted ? 'text-amber-300' : 'text-slate-400'}`} />
          <span>
            {nothingCosted
              ? `Nothing is costed yet: the total is ${summation.currency ? formatMoney(0, summation.currency) : '0.00'}. `
                + 'Close costing once the departments have booked their lines, or Sales quotes from an empty basis.'
              : owedTotal != null
                ? t('wait.costingProgress').replace('{n}', String(finalizedOwed))
                  .replace('{m}', String(owedTotal)).replace('{x}', owing.join(', '))
                : `${t('next.waitingCostInput').replace('{n}', String(owing.length))
                  .replace('{s}', owing.length === 1 ? '' : 's')}: ${owing.join(', ')}.`}
          </span>
        </div>
      )}
      {visible.map((a) => {
        const id = a.department_id
        const isMine = myDepartmentIds.includes(id)
        // Christoph 2026-11-08: a department's own costing is always open for
        // its people (no fold); the overview roles fold as before
        const ownBucket = myDepartmentIds.includes(id)
        const expanded = ownBucket || openDept === id
        const total = deptTotal(id)
        const filled = deptCosted(id)
        // Entered, but no cost sheet rate: not "Empty" (the department did
        // its part), and not a price either.
        const noRate = !filled && (summation?.unpriced_lines ?? []).some((l) => l.department_id === id)
        const finalized = isFinalized(id)
        // The department's own figures close with its finalize; PM (and admin)
        // still fix them, as everywhere in costing.
        const writable = editable && (isPm || !finalized)
        return (
          <section key={id} id={`costing-dept-${id}`} data-testid={`costing-bucket-${id}`}
            // Christoph 2026-11-08: red goes on the sub-container that misses
            // something (a line, the finalize list), not on the whole bucket
            className={`rounded-lg border ${expanded ? 'border-slate-600' : 'border-slate-700'} ${
              expanded ? 'bg-slate-800' : 'bg-slate-800/50'}`}>
            <button type="button" data-testid={`costing-toggle-${id}`}
              aria-expanded={expanded}
              onClick={() => { if (!ownBucket) setOpenDept(expanded ? null : id) }}
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
                  finalized ? 'bg-emerald-900/70 text-emerald-200'
                  : noRate ? 'bg-amber-900/70 text-amber-200'
                  : filled === null ? 'bg-slate-700 text-slate-400'
                  // Christoph 2026-11-08: filled is not done until Finalize
                  : filled && live && owesInput(id) ? 'bg-red-900/70 text-red-100'
                  : filled ? 'bg-emerald-900/70 text-emerald-200'
                  : 'bg-slate-700 text-slate-300'}`}
                title={noRate ? t('costing.noRateHint') : filled === null ? t('costing.hiddenHint')
                  : filled && live && owesInput(id) ? 'Filled, not finalized: the PM sees the department as open' : undefined}>
                {finalized ? t('costing.finalized')
                  : noRate ? t('costing.noRate') : filled === null ? t('costing.hidden')
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
                    {editable && owesInput(id) && finalizeBar(id, 'top')}
                    {change.assessment_v2 && (
                      <SupplierWaitPanel changeId={changeId} departmentId={id}
                        waits={change.open_supplier_waits ?? []}
                        editable={editable && owesInput(id) && !finalized} />
                    )}
                    <CostPositions changeId={changeId} departmentId={id}
                      v2={!!change.assessment_v2}
                      basisParts={(change.impacted_items ?? []).map((i) => ({
                        id: i.part_id, number: i.part_number ?? `#${i.part_id}` }))}
                      departmentName={deptName(id)}
                      partWeightG={change.estimated_part_weight_g}
                      editable={writable} />
                    {/* The per-plant workbook matrix: lifecycle cycle-time
                        deltas and hours × rate per plant. Kept under the
                        table, one click away, for the departments that
                        still think in it. */}
                    {/* Christoph 2026-11-08: only where the cycle time changes (± min
                        per part); every other Yes row is a line in the table above */}
                    {(!change.assessment_v2 || cycleTimeYes(a)) && (
                    <details open className="rounded border border-slate-700/70 bg-slate-900/30 px-2 py-1.5"
                      data-testid={`costing-plant-lines-${id}`}>
                      <summary className="cursor-pointer text-[11px] uppercase tracking-wide text-slate-500 select-none">
                        {t('costpos.plantLines')}
                      </summary>
                      {/* A finalized part reads only: the grid has no read-only
                          mode of its own, the fieldset disables its controls. */}
                      <fieldset className="pt-2" disabled={!writable}>
                        <CostLineGrid changeId={changeId} assessmentId={a.id} departmentId={id}
                          plants={plants} projectPlantId={projectPlantId} />
                      </fieldset>
                    </details>
                    )}
                    {/* Christoph 2026-11-08: every line has its own days; the
                        department's lead time is the longest of them */}
                    {writable && !change.assessment_v2 && (
                      <LeadTimeField changeId={changeId} departmentId={id}
                        initial={leadTimeOf(id)} />
                    )}
                    {/* Christoph 2026-11-08: Finalize closes the department's
                        section, after its lines and total */}
                    {editable && owesInput(id) && finalizeBar(id, 'end')}
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
                    {/* A3-12 (R24): what the backend lets PM do for any
                        department: finalize, "no cost", supplier waits */}
                    {editable && isPm && owesInput(id) && finalizeBar(id, 'top')}
                    {change.assessment_v2 && isPm && (
                      <SupplierWaitPanel changeId={changeId} departmentId={id}
                        waits={change.open_supplier_waits ?? []}
                        editable={editable && owesInput(id) && !finalized} />
                    )}
                    <CostPositions changeId={changeId} departmentId={id}
                      v2={!!change.assessment_v2}
                      departmentName={deptName(id)}
                      partWeightG={change.estimated_part_weight_g}
                      editable={editable && isPm} />
                    {editable && isPm && owesInput(id) && finalizeBar(id, 'end')}
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
