/**
 * Spec §4 / §5 (ASSESSMENT_V2), the honest answers of a department's costing:
 *
 * - "<Dept> has no cost" (C18): one button instead of an invented zero. No
 *   work / absorbed (the hours, an estimate) / the supplier does it. Toolshop
 *   reads it as "Will toolmakers spend time on this?". The backend refuses it
 *   while the department has a position, priced lines or a supplier wait and
 *   says whose.
 * - Waiting on a supplier: vendor, asked on, expected by, "day 9 of 21". It
 *   holds the department's finalize and pauses its late clock. The department
 *   closes it when the quote is in (or it is not needed); at close costing the
 *   lead picks "Wait for FZ (3 Nov)" or "Price on estimate".
 * - SupplierWaitLine: the header's "Waiting on FZ since 7 Oct".
 */
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { btnSm } from '../../common/buttonStyles'
import { toastError } from '../../../lib/apiError'
import { changesApi } from '../../../api/changes'
import { formatDate } from '../../../lib/format'
import { t } from '../../../i18n/cmLabels'
import type { ChangeRequest, NoCostReason, SupplierWait } from '../../../types/change'

const input = 'bg-slate-900 border border-slate-600 rounded px-2 py-1 text-xs text-slate-100'
const today = () => new Date().toISOString().slice(0, 10)

function useRefresh(changeId: number) {
  const qc = useQueryClient()
  return () => {
    qc.invalidateQueries({ queryKey: ['change', changeId] })
    qc.invalidateQueries({ queryKey: ['change-my-actions', changeId] })
    qc.invalidateQueries({ queryKey: ['change-summation', changeId] })
    qc.invalidateQueries({ queryKey: ['change-my-tasks'] })
    qc.invalidateQueries({ queryKey: ['change', changeId, 'supplier-waits'] })
    qc.invalidateQueries({ queryKey: ['change', changeId, 'impl-state'] })
  }
}

/** "No cost: absorbed (6 h)" in words. */
export function noCostWords(nc: { reason: NoCostReason; hours?: number } | undefined): string | null {
  if (!nc) return null
  return nc.reason === 'absorbed'
    ? t('nocost.word.absorbed').replace('{h}', String(nc.hours ?? 0))
    : t(`nocost.word.${nc.reason}`)
}

export function NoCostButton({ changeId, departmentId, departmentName }: {
  changeId: number; departmentId: number; departmentName: string
}) {
  const refresh = useRefresh(changeId)
  const [open, setOpen] = useState(false)
  const [reason, setReason] = useState<NoCostReason | ''>('')
  const [hours, setHours] = useState('')
  const toolshop = departmentName === 'Toolshop'
  const save = useMutation({
    mutationFn: () => changesApi.departmentNoCost(changeId, departmentId, {
      reason: reason as NoCostReason,
      ...(reason === 'absorbed' ? { hours: Number(hours) } : {}) }),
    onSuccess: () => { setOpen(false); refresh() },
    onError: (e: unknown) => { toastError(e, t('nocost.failed')) },
  })
  if (!open) {
    return (
      <button type="button" className={btnSm.secondary} data-testid={`nocost-open-${departmentId}`}
        onClick={() => setOpen(true)}>
        {toolshop ? t('nocost.toolshopAsk') : t('nocost.button').replace('{d}', departmentName)}
      </button>
    )
  }
  const ready = reason !== '' && (reason !== 'absorbed' || Number(hours) > 0)
  return (
    <div className="w-full space-y-1.5 rounded border border-slate-700 p-2" data-testid={`nocost-form-${departmentId}`}>
      <p className="text-xs text-slate-200">
        {toolshop ? t('nocost.toolshopAsk') : t('nocost.why').replace('{d}', departmentName)}
      </p>
      <div role="radiogroup" className="flex flex-wrap gap-3 text-xs">
        {(['no_work', 'absorbed', 'supplier'] as const).map((r) => (
          <label key={r} className="inline-flex items-center gap-1 text-slate-200">
            <input type="radio" name={`nocost-${departmentId}`} checked={reason === r}
              data-testid={`nocost-${departmentId}-${r}`} onChange={() => setReason(r)} />
            {t(toolshop ? `nocost.toolshop.${r}` : `nocost.reason.${r}`)}
          </label>
        ))}
      </div>
      {reason === 'absorbed' && (
        <input type="number" min={0} step={0.5} className={`${input} w-24`} value={hours}
          aria-label={t('nocost.hours')} placeholder={t('nocost.hours')}
          data-testid={`nocost-hours-${departmentId}`} onChange={(e) => setHours(e.target.value)} />
      )}
      <div className="flex gap-2">
        <button type="button" className={btnSm.primary} disabled={!ready || save.isPending}
          data-testid={`nocost-save-${departmentId}`} onClick={() => save.mutate()}>
          {t('nocost.save')}
        </button>
        <button type="button" className={btnSm.secondary} onClick={() => setOpen(false)}>
          {t('achk.cancel')}
        </button>
      </div>
    </div>
  )
}

/** The department's own supplier waits: start one, close it. */
export function SupplierWaitPanel({ changeId, departmentId, waits, editable }: {
  changeId: number; departmentId: number; waits: SupplierWait[]; editable: boolean
}) {
  const refresh = useRefresh(changeId)
  // all of the department's waits (closed ones too: who answered, when)
  const { data: all } = useQuery({
    queryKey: ['change', changeId, 'supplier-waits'],
    queryFn: () => changesApi.listSupplierWaits(changeId),
  })
  const mine = (all ?? waits).filter((w) => w.department_id === departmentId && w.is_open)
  const done = (all ?? []).filter((w) => w.department_id === departmentId && !w.is_open)
  // Christoph 2026-11-08: with two or more supplier lines (cases) the wait
  // names which one it is for
  const { data: positions } = useQuery({
    queryKey: ['costing-positions', changeId],
    queryFn: () => changesApi.listCostPositions(changeId),
  })
  const extLines = (positions ?? []).filter((p) => p.department_id === departmentId && p.kind === 'external')
  const [posId, setPosId] = useState<number | ''>('')
  const lineName = (id?: number | null) => extLines.find((p) => p.id === id)?.label
  const [open, setOpen] = useState(false)
  const [vendor, setVendor] = useState('')
  const [asked, setAsked] = useState(today())
  const [expected, setExpected] = useState('')
  const start = useMutation({
    mutationFn: () => changesApi.startSupplierWait(changeId, {
      department_id: departmentId, vendor_name: vendor.trim(), asked_on: asked, expected_by: expected,
      ...(posId !== '' ? { position_id: posId } : {}) }),
    onSuccess: () => { setOpen(false); setVendor(''); setExpected(''); setPosId(''); refresh() },
    onError: (e: unknown) => { toastError(e, t('wait.sup.failed')) },
  })
  const close = useMutation({
    mutationFn: ({ id, reason }: { id: number; reason: 'received' | 'not_needed' }) =>
      changesApi.closeSupplierWait(changeId, id, { reason }),
    onSuccess: refresh,
    onError: (e: unknown) => { toastError(e, t('wait.sup.failed')) },
  })
  return (
    <div className="space-y-1" data-testid={`supwait-panel-${departmentId}`}>
      {mine.map((w) => (
        <div key={w.id} className="flex flex-wrap items-center gap-2 rounded border border-sky-800/60 bg-sky-950/20 px-2 py-1 text-xs text-sky-100"
          data-testid={`supwait-${w.id}`}>
          <span>{t('wait.sup.line').replace('{v}', w.vendor_name)
            .replace('{a}', formatDate(w.asked_on)).replace('{e}', formatDate(w.expected_by))}</span>
          {lineName(w.position_id) && (
            <span className="rounded bg-amber-900/60 px-1 text-amber-100">{lineName(w.position_id)}</span>)}
          {w.created_by_name && <span className="text-sky-300/80">{t('wait.sup.by').replace('{x}', w.created_by_name)}</span>}
          <span className={`rounded px-1.5 ${w.overdue ? 'bg-red-900/70 text-red-100' : 'bg-slate-700 text-slate-200'}`}>
            {w.chip}</span>
          {editable && (
            <>
              <button type="button" className={btnSm.secondary} data-testid={`supwait-in-${w.id}`}
                onClick={() => close.mutate({ id: w.id, reason: 'received' })}>{t('wait.sup.received')}</button>
              <button type="button" className="underline text-slate-300"
                onClick={() => close.mutate({ id: w.id, reason: 'not_needed' })}>{t('wait.sup.notNeeded')}</button>
            </>
          )}
        </div>
      ))}
      {done.map((w) => (
        <div key={w.id} data-testid={`supwait-done-${w.id}`}
          className="rounded border border-slate-700 px-2 py-1 text-xs text-slate-400">
          {lineName(w.position_id) && (
            <span className="mr-1 rounded bg-slate-700 px-1 text-slate-200">{lineName(w.position_id)}</span>)}
          {t('wait.sup.doneLine').replace('{v}', w.vendor_name)
            .replace('{a}', formatDate(w.asked_on)).replace('{who}', w.created_by_name ?? '-')
            .replace('{r}', t(`wait.sup.reason.${w.close_reason ?? 'received'}`))
            .replace('{d}', w.closed_at ? formatDate(w.closed_at) : '-')
            .replace('{by}', w.closed_by_name ?? '-')}
        </div>
      ))}
      {editable && !open && (
        <button type="button" className="text-xs underline text-sky-300" data-testid={`supwait-open-${departmentId}`}
          onClick={() => setOpen(true)}>{t('wait.sup.start')}</button>
      )}
      {editable && open && (
        <div className="flex flex-wrap items-end gap-2 rounded border border-slate-700 p-2">
          {extLines.length > 0 && (
            <label className="text-[11px] text-slate-400">{t('wait.sup.forCase')}
              <select className={`${input} block`} value={posId} data-testid={`supwait-case-${departmentId}`}
                onChange={(e) => setPosId(e.target.value === '' ? '' : Number(e.target.value))}>
                <option value="">{extLines.length > 1 ? t('wait.sup.pickCase') : t('wait.sup.allCases')}</option>
                {extLines.map((p) => <option key={p.id} value={p.id}>{p.label}</option>)}
              </select></label>
          )}
          <label className="text-[11px] text-slate-400">{t('wait.sup.vendor')}
            <input className={`${input} block w-32`} value={vendor} data-testid={`supwait-vendor-${departmentId}`}
              onChange={(e) => setVendor(e.target.value)} /></label>
          <label className="text-[11px] text-slate-400">{t('wait.sup.askedOn')}
            <input type="date" className={`${input} block`} value={asked} max={today()}
              onChange={(e) => setAsked(e.target.value)} /></label>
          <label className="text-[11px] text-slate-400">{t('wait.sup.expectedBy')}
            <input type="date" className={`${input} block`} value={expected} min={today()}
              data-testid={`supwait-expected-${departmentId}`}
              onChange={(e) => setExpected(e.target.value)} /></label>
          <button type="button" className={btnSm.primary} data-testid={`supwait-save-${departmentId}`}
            disabled={vendor.trim().length < 2 || !asked || !expected || start.isPending
              || (extLines.length > 1 && posId === '')}
            onClick={() => start.mutate()}>{t('wait.sup.save')}</button>
          <button type="button" className={btnSm.secondary} onClick={() => setOpen(false)}>
            {t('achk.cancel')}</button>
        </div>
      )}
    </div>
  )
}

/** §5 close costing: each open costing wait, and the lead's pick. */
export function SupplierWaitDecisions({ changeId, waits, canDecide }: {
  changeId: number; waits: SupplierWait[]; canDecide: boolean
}) {
  const refresh = useRefresh(changeId)
  const [waiting, setWaiting] = useState<number[]>([])
  const estimate = useMutation({
    mutationFn: (id: number) => changesApi.closeSupplierWait(changeId, id, { reason: 'price_on_estimate' }),
    onSuccess: refresh,
    onError: (e: unknown) => { toastError(e, t('wait.sup.failed')) },
  })
  const open = waits.filter((w) => w.is_open && w.phase === 'costing')
  if (!open.length) return null
  return (
    <div className="space-y-1" data-testid="supwait-decisions">
      {open.map((w) => (
        <div key={w.id} className="flex flex-wrap items-center gap-2 rounded-md border border-sky-800/60 bg-sky-950/20 px-3 py-2 text-sm text-sky-100">
          <span>{t('wait.sup.decideLine').replace('{v}', w.vendor_name)
            .replace('{d}', w.department_name ?? '').replace('{e}', formatDate(w.expected_by))} ({w.chip})</span>
          {canDecide && !waiting.includes(w.id) && (
            <span className="ml-auto flex gap-2">
              <button type="button" className={btnSm.secondary} data-testid={`supwait-wait-${w.id}`}
                onClick={() => setWaiting((x) => [...x, w.id])}>
                {t('wait.sup.waitFor').replace('{v}', w.vendor_name).replace('{e}', formatDate(w.expected_by))}
              </button>
              <button type="button" className={btnSm.primary} data-testid={`supwait-estimate-${w.id}`}
                disabled={estimate.isPending} onClick={() => estimate.mutate(w.id)}>
                {t('wait.sup.priceOnEstimate')}
              </button>
            </span>
          )}
        </div>
      ))}
    </div>
  )
}

/** The header's "Waiting on FZ since 7 Oct (Toolshop, day 9 of 21)". */
export function SupplierWaitLine({ change }: { change: Pick<ChangeRequest, 'open_supplier_waits'> }) {
  const waits = change.open_supplier_waits ?? []
  if (!waits.length) return null
  return (
    <p data-testid="supwait-line" className="text-xs font-medium text-sky-200">
      {waits.map((w) => t('wait.sup.header').replace('{v}', w.vendor_name)
        .replace('{a}', formatDate(w.asked_on))
        .replace('{x}', [w.department_name, w.chip].filter(Boolean).join(', '))).join(' · ')}
    </p>
  )
}
