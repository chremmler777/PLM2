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
  ROUTE_EXPLAIN, ROUTE_LABELS, suggestionReason, type Intake, type IntakeRoute,
} from '../../api/intakes'
import { STATUS_LABELS } from '../../lib/changeStatus'
import type { ChangeStatus } from '../../types/change'

const ROUTES: IntakeRoute[] = ['engineering_review', 'full_ecr', 'attach_ecr', 'administrative']
// A change past implementation cannot take a new index (the backend refuses).
const ATTACH_REFUSED = ['in_validation', 'released', 'closed', 'cancelled', 'rejected']

export interface RouteDialogProps {
  intake: Intake
  pending?: boolean
  onClose: () => void
  onSubmit: (body: { route: IntakeRoute; reason?: string; change_id?: number }) => void
}

export default function RouteDialog({ intake, pending = false, onClose, onSubmit }: RouteDialogProps) {
  const [route, setRoute] = useState<IntakeRoute>(intake.suggested_route ?? 'engineering_review')
  const [reason, setReason] = useState('')
  const [changeId, setChangeId] = useState<number | ''>('')
  const { data: changes = [] } = useQuery({
    queryKey: ['changes', { project_id: intake.project_id }],
    queryFn: () => changesApi.list({ project_id: intake.project_id }),
    enabled: route === 'attach_ecr',
  })
  const open = useMemo(
    () => (Array.isArray(changes) ? changes : []).filter((c) => !ATTACH_REFUSED.includes(c.status)),
    [changes],
  )
  const reasonNeeded = route === 'administrative' || route !== intake.suggested_route
  const blocked = pending || (reasonNeeded && !reason.trim()) || (route === 'attach_ecr' && changeId === '')

  const reasonId = useId()
  const changeSelectId = useId()
  const reasonHint = route === 'administrative' ? 'For example: title block only, no content change'
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
            })}>
            {route === 'administrative' ? 'Activate now' : `Decide: ${ROUTE_LABELS[route]}`}
          </Button>
        </>
      )}>
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
                {c.change_number} {c.title} ({STATUS_LABELS[c.status as ChangeStatus] ?? c.status})
              </option>
            ))}
          </select>
          {open.length === 0 && (
            <span className="mt-1 block text-xs text-slate-400">No open change up to implementation in this project.</span>
          )}
        </div>
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
