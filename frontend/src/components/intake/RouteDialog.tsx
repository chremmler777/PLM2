/**
 * The triage of a new index (spec 2026-09-25 §17): Development picks one of
 * four routes, with a reason. The route suggested by the phase is marked;
 * picking another one (and administrative always) needs a reason.
 */
import { useId, useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { changesApi } from '../../api/changes'
import Dialog from '../common/Dialog'
import Button from '../common/Button'
import FieldGroup from '../common/FieldGroup'
import {
  LIVE_CHANGE_REASONS, ROUTE_EXPLAIN, ROUTE_LABELS, WHAT_CHANGED_AREAS, suggestionReason,
  type DecideBody, type Intake, type IntakeRoute,
} from '../../api/intakes'
import { STATUS_LABELS } from '../../lib/changeStatus'
import { t } from '../../i18n/cmLabels'
import type { ChangeStatus } from '../../types/change'

const ROUTES: IntakeRoute[] = ['engineering_review', 'full_ecr', 'attach_ecr', 'administrative']
// A change past implementation cannot take a new index (the backend refuses).
const ATTACH_REFUSED = ['in_validation', 'released', 'closed', 'cancelled', 'rejected']
// In implementation the impacted set is frozen: the index can only be linked
// to a part the change already carries (the backend refuses any other).
const FROZEN_HINT = 'In implementation: only an index of a part already on this change can be linked. Start a full ECR instead.'

export interface RouteDialogProps {
  intake: Intake
  pending?: boolean
  onClose: () => void
  onSubmit: (body: DecideBody) => void
}

export default function RouteDialog({ intake, pending = false, onClose, onSubmit }: RouteDialogProps) {
  const [route, setRoute] = useState<IntakeRoute>(intake.suggested_route ?? 'engineering_review')
  const [reason, setReason] = useState('')
  // §1: a live change carrying the part is the suggestion, preselected
  const live = intake.live_change ?? null
  const [changeId, setChangeId] = useState<number | ''>(live?.attachable ? live.id : '')
  // §1 "What changed" (SCOPING_V2): areas + compare ref, or no visible change + reason
  const v2 = !!intake.scoping_v2
  const [areas, setAreas] = useState<string[]>([])
  const [noChange, setNoChange] = useState(false)
  const [compareRef, setCompareRef] = useState('')
  const [noChangeReason, setNoChangeReason] = useState('')
  const [liveReason, setLiveReason] = useState('')
  const [customerDriven, setCustomerDriven] = useState<'' | 'yes' | 'no'>('')
  const { data: changes = [] } = useQuery({
    queryKey: ['changes', { project_id: intake.project_id }],
    queryFn: () => changesApi.list({ project_id: intake.project_id }),
    enabled: route === 'attach_ecr',
  })
  const open = useMemo(
    () => (Array.isArray(changes) ? changes : []).filter((c) => !ATTACH_REFUSED.includes(c.status)),
    [changes],
  )
  const picked = open.find((c) => c.id === changeId)
  const frozen = route === 'attach_ecr' && picked?.status === 'in_implementation'
  // The list carries no parts: the picked change's detail says whether it
  // already has this part. Unknown (loading, failed): hint only, not blocked.
  const { data: pickedDetail } = useQuery({
    queryKey: ['change', changeId],
    queryFn: () => changesApi.get(changeId as number),
    enabled: frozen,
  })
  const carried = frozen && pickedDetail && pickedDetail.id === changeId
    ? (pickedDetail.impacted_items ?? []).some((i) => i.part_id === intake.part_id)
    : undefined
  const frozenRefused = frozen && carried === false
  // full_ecr although the live change could take it: a reason pick
  const liveReasonNeeded = v2 && route === 'full_ecr' && intake.suggested_route === 'attach_ecr' && !!live
  const reasonNeeded = route === 'administrative'
    || (liveReasonNeeded ? liveReason === 'other' : route !== intake.suggested_route)
  const whatNeeded = v2 && route !== 'administrative'
  const whatMissing = whatNeeded && (noChange ? noChangeReason.trim().length < 5
    : areas.length === 0 || compareRef.trim().length < 5)
  // attaching to an internal change: customer-driven? (yes flips it)
  const pickedInternal = route === 'attach_ecr' && !!picked && !picked.customer_relevant
    && picked.origin !== 'mother_plant' && picked.origin !== 'engineering_review'
  const driverMissing = v2 && pickedInternal && customerDriven === ''
  // R19: activating at once while a live change carries the part needs a
  // real reason (the backend refuses 'ok'); the live change's lead is told
  const adminOverLive = v2 && route === 'administrative' && !!live
  const blocked = pending || (reasonNeeded && !reason.trim()) || (route === 'attach_ecr' && changeId === '')
    || (adminOverLive && reason.trim().length < 5)
    || frozenRefused || whatMissing || (liveReasonNeeded && liveReason === '') || driverMissing
  const toggleArea = (a: string) => {
    setNoChange(false)
    setAreas((prev) => (prev.includes(a) ? prev.filter((x) => x !== a) : [...prev, a]))
  }

  const reasonId = useId()
  const changeSelectId = useId()
  const reasonHint = adminOverLive
    ? t('intake.adminOverLive').replace('{n}', live?.change_number ?? '')
    : route === 'administrative' ? 'For example: title block only, no content change'
    : reasonNeeded ? 'Why not the suggested route?' : 'Anything the team should know'

  return (
    <Dialog open onClose={onClose} busy={pending} size="lg" closeOnBackdrop={false}
      data-testid="route-dialog"
      title={`Triage index ${intake.revision_name} of ${intake.part_number}`}
      description={`${intake.source_label}${intake.customer_index ? `, customer index ${intake.customer_index}` : ''}${
        intake.active_revision_name ? `. Active today: ${intake.active_revision_name}` : '. No active index yet'}`}
      footer={(
        <>
          <Button onClick={onClose} disabled={pending}>Cancel</Button>
          <Button variant="primary" disabled={blocked} loading={pending} data-testid="route-submit"
            onClick={() => onSubmit({
              route, reason: reason.trim() || undefined,
              change_id: route === 'attach_ecr' && changeId !== '' ? changeId : undefined,
              ...(whatNeeded ? (noChange
                ? { what_changed: ['none'], no_change_reason: noChangeReason.trim(),
                  what_changed_ref: compareRef.trim() || undefined }
                : { what_changed: areas, what_changed_ref: compareRef.trim() }) : {}),
              ...(liveReasonNeeded ? { live_change_reason: liveReason } : {}),
              ...(v2 && pickedInternal ? { customer_driven: customerDriven === 'yes' } : {}),
            })}>
            {route === 'administrative' ? 'Activate now' : `Decide: ${ROUTE_LABELS[route]}`}
          </Button>
        </>
      )}>
      {live && (
        <p data-testid="live-change" role="note"
          className="mb-3 rounded-lg border border-sky-700/60 bg-sky-950/30 px-3 py-2 text-sm text-sky-100">
          {t('intake.liveChange')
            .replace('{n}', live.change_number)
            .replace('{s}', STATUS_LABELS[live.status as ChangeStatus] ?? live.status)
            .replace('{l}', live.lead_name ?? '-')
            .replace('{p}', intake.part_number ?? '')}
          {!live.attachable && ` ${t('intake.liveNotAttachable')}`}
        </p>
      )}
      {/* Every other live change carrying the part: named, their leads told */}
      {(intake.other_live_changes ?? []).length > 0 && (
        <p data-testid="other-live-changes" role="note"
          className="mb-3 rounded-lg border border-amber-700/60 bg-amber-950/30 px-3 py-2 text-sm text-amber-100">
          {t('intake.otherLive').replace('{x}', (intake.other_live_changes ?? []).map((c) =>
            `${c.change_number} (${STATUS_LABELS[c.status as ChangeStatus] ?? c.status}${
              c.lead_name ? `, ${c.lead_name}` : ''})`).join(', '))}
        </p>
      )}

      <FieldGroup legend="Route" legendHidden>
        <div className="space-y-2">
          {ROUTES.map((r) => {
            const suggested = r === intake.suggested_route
            return (
              <label key={r} data-testid={`route-${r}`}
                className={`flex cursor-pointer gap-3 rounded-lg border p-3 transition-colors has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-sky-400 ${
                  route === r ? 'border-sky-500 bg-sky-950/40' : 'border-slate-700 hover:border-slate-500'}`}>
                <input type="radio" name="route" className="mt-1 accent-sky-500" checked={route === r}
                  onChange={() => setRoute(r)} />
                <span>
                  <span className="flex flex-wrap items-center gap-2 text-sm font-medium text-slate-100">
                    {ROUTE_LABELS[r]}
                    {suggested && (
                      <span className="rounded-full bg-sky-900/60 px-2 py-0.5 text-[11px] font-normal text-sky-200">
                        Suggested: {suggestionReason(intake)}
                      </span>
                    )}
                  </span>
                  <span className="mt-0.5 block text-xs text-slate-400">{ROUTE_EXPLAIN[r]}</span>
                </span>
              </label>
            )
          })}
        </div>
      </FieldGroup>

      {route === 'attach_ecr' && (
        <div className="mt-3">
          <label htmlFor={changeSelectId} className="block text-sm text-slate-300">
            Open change in {intake.project_name ?? 'this project'}
          </label>
          <select id={changeSelectId} value={changeId}
            onChange={(e) => setChangeId(e.target.value ? Number(e.target.value) : '')}
            data-testid="attach-change"
            className="mt-1 w-full rounded-lg border border-slate-600 bg-slate-900 px-2 py-1.5 text-sm text-slate-100 focus:border-sky-500 focus:outline-none">
            <option value="">Choose a change</option>
            {open.map((c) => (
              <option key={c.id} value={c.id}>
                {c.change_number} {c.title} ({STATUS_LABELS[c.status as ChangeStatus] ?? c.status}
                {c.status === 'in_implementation' ? ', existing parts only' : ''})
              </option>
            ))}
          </select>
          {open.length === 0 && (
            <span className="mt-1 block text-xs text-slate-400">No open change up to implementation in this project.</span>
          )}
          {frozen && carried !== true && (
            <span data-testid="attach-frozen-hint" role={frozenRefused ? 'alert' : undefined}
              className={`mt-1 block text-xs ${frozenRefused ? 'text-amber-300' : 'text-slate-400'}`}>
              {frozenRefused ? `${intake.part_number ?? 'This part'} is not on ${picked?.change_number}. ` : ''}
              {FROZEN_HINT}
            </span>
          )}
        </div>
      )}

      {liveReasonNeeded && (
        <div className="mt-3">
          <label className="block text-sm text-slate-300" htmlFor={`${reasonId}-live`}>
            {t('intake.liveReason').replace('{n}', live?.change_number ?? '')}{' '}
            <span className="text-amber-300">(required)</span>
          </label>
          <select id={`${reasonId}-live`} value={liveReason} data-testid="live-reason"
            onChange={(e) => setLiveReason(e.target.value)}
            className="mt-1 w-full rounded-lg border border-slate-600 bg-slate-900 px-2 py-1.5 text-sm text-slate-100 focus:border-sky-500 focus:outline-none">
            <option value="">{t('intake.liveReasonPick')}</option>
            {LIVE_CHANGE_REASONS.map((r) => <option key={r} value={r}>{t(`intake.liveReason.${r}`)}</option>)}
          </select>
        </div>
      )}

      {v2 && pickedInternal && (
        <fieldset className="mt-3" data-testid="customer-driven">
          <legend className="text-sm text-slate-300">
            {t('intake.customerDriven').replace('{n}', picked?.change_number ?? '')}{' '}
            <span className="text-amber-300">(required)</span>
          </legend>
          <div className="mt-1 flex gap-4 text-sm">
            {(['yes', 'no'] as const).map((v) => (
              <label key={v} className="flex cursor-pointer items-center gap-1.5 text-slate-200">
                <input type="radio" name="customer-driven" checked={customerDriven === v}
                  data-testid={`customer-driven-${v}`} onChange={() => setCustomerDriven(v)} />
                {t(`intake.customerDriven.${v}`)}
              </label>
            ))}
          </div>
        </fieldset>
      )}

      {whatNeeded && (
        <fieldset className="mt-3" data-testid="what-changed">
          <legend className="text-sm text-slate-300">
            {t('intake.whatChanged')} <span className="text-amber-300">(required)</span>
          </legend>
          <div className="mt-1 flex flex-wrap gap-x-4 gap-y-1 text-sm">
            {WHAT_CHANGED_AREAS.map((a) => (
              <label key={a} className="flex cursor-pointer items-center gap-1.5 text-slate-200">
                <input type="checkbox" checked={areas.includes(a)} data-testid={`area-${a}`}
                  onChange={() => toggleArea(a)} />
                {t(`intake.area.${a}`)}
              </label>
            ))}
            <label className="flex cursor-pointer items-center gap-1.5 text-slate-200">
              <input type="checkbox" checked={noChange} data-testid="area-none"
                onChange={(e) => { setNoChange(e.target.checked); if (e.target.checked) setAreas([]) }} />
              {t('intake.area.none')}
            </label>
          </div>
          <input value={compareRef} onChange={(e) => setCompareRef(e.target.value)}
            data-testid="what-ref" aria-label={t('intake.compareRef')}
            placeholder={t('intake.compareRef') + (noChange ? ` (${t('intake.optional')})` : '')}
            className="mt-2 w-full rounded-lg border border-slate-600 bg-slate-900 px-2 py-1.5 text-sm text-slate-100 placeholder:text-slate-500 focus:border-sky-500 focus:outline-none" />
          {noChange && (
            <input value={noChangeReason} onChange={(e) => setNoChangeReason(e.target.value)}
              data-testid="no-change-reason" aria-label={t('intake.noChangeReason')}
              placeholder={t('intake.noChangeReason')}
              className="mt-2 w-full rounded-lg border border-slate-600 bg-slate-900 px-2 py-1.5 text-sm text-slate-100 placeholder:text-slate-500 focus:border-sky-500 focus:outline-none" />
          )}
          <span className="mt-1 block text-xs text-slate-400">{t('intake.whatChangedHint')}</span>
        </fieldset>
      )}

      <div className="mt-3">
        <label htmlFor={reasonId} className="block text-sm text-slate-300">
          Reason {reasonNeeded ? <span className="text-amber-300">(required)</span> : <span className="text-slate-400">(optional)</span>}
        </label>
        <textarea id={reasonId} value={reason} onChange={(e) => setReason(e.target.value)} rows={2}
          data-testid="route-reason" placeholder={reasonHint}
          className="mt-1 w-full rounded-lg border border-slate-600 bg-slate-900 px-2 py-1.5 text-sm text-slate-100 placeholder:text-slate-500 focus:border-sky-500 focus:outline-none" />
      </div>
    </Dialog>
  )
}
