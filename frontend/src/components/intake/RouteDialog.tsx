/**
 * The triage of a new index (spec 2026-09-25 §17): Development picks one of
 * four routes, with a reason. The route suggested by the phase is marked;
 * picking another one (and administrative always) needs a reason.
 */
import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { changesApi } from '../../api/changes'
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

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" role="dialog"
      aria-modal="true" aria-labelledby="route-dialog-title" data-testid="route-dialog">
      <div className="w-full max-w-2xl rounded-xl border border-slate-700 bg-slate-900 p-5 shadow-xl">
        <h2 id="route-dialog-title" className="text-lg font-semibold text-slate-100">
          Triage index {intake.revision_name} of {intake.part_number}
        </h2>
        <p className="mt-1 text-sm text-slate-400">
          {intake.source_label}
          {intake.customer_index ? `, customer index ${intake.customer_index}` : ''}
          {intake.active_revision_name ? `. Active today: ${intake.active_revision_name}` : '. No active index yet'}
        </p>

        <fieldset className="mt-4 space-y-2">
          <legend className="sr-only">Route</legend>
          {ROUTES.map((r) => {
            const suggested = r === intake.suggested_route
            return (
              <label key={r} data-testid={`route-${r}`}
                className={`flex cursor-pointer gap-3 rounded-lg border p-3 ${
                  route === r ? 'border-sky-500 bg-sky-950/40' : 'border-slate-700 hover:border-slate-500'}`}>
                <input type="radio" name="route" className="mt-1" checked={route === r}
                  onChange={() => setRoute(r)} />
                <span>
                  <span className="flex items-center gap-2 text-sm font-medium text-slate-100">
                    {ROUTE_LABELS[r]}
                    {suggested && (
                      <span className="rounded-full bg-emerald-900/60 px-2 py-0.5 text-[11px] font-normal text-emerald-200">
                        Suggested: {suggestionReason(intake)}
                      </span>
                    )}
                  </span>
                  <span className="mt-0.5 block text-xs text-slate-400">{ROUTE_EXPLAIN[r]}</span>
                </span>
              </label>
            )
          })}
        </fieldset>

        {route === 'attach_ecr' && (
          <label className="mt-3 block text-sm text-slate-300">
            Open change in {intake.project_name ?? 'this project'}
            <select value={changeId} onChange={(e) => setChangeId(e.target.value ? Number(e.target.value) : '')}
              data-testid="attach-change" aria-label="Open change"
              className="mt-1 w-full rounded-md border border-slate-600 bg-slate-800 px-2 py-1.5 text-sm text-slate-100">
              <option value="">Choose a change</option>
              {open.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.change_number} {c.title} ({STATUS_LABELS[c.status as ChangeStatus] ?? c.status})
                </option>
              ))}
            </select>
            {open.length === 0 && (
              <span className="mt-1 block text-xs text-slate-500">No open change up to implementation in this project.</span>
            )}
          </label>
        )}

        <label className="mt-3 block text-sm text-slate-300">
          Reason {reasonNeeded ? <span className="text-amber-300">(required)</span> : <span className="text-slate-500">(optional)</span>}
          <textarea value={reason} onChange={(e) => setReason(e.target.value)} rows={2}
            data-testid="route-reason"
            placeholder={route === 'administrative' ? 'e.g. title block only, no content change'
              : reasonNeeded ? 'Why not the suggested route?' : 'Anything the team should know'}
            className="mt-1 w-full rounded-md border border-slate-600 bg-slate-800 px-2 py-1.5 text-sm text-slate-100" />
        </label>

        <div className="mt-4 flex justify-end gap-2">
          <button onClick={onClose}
            className="rounded-lg border border-slate-600 px-3 py-1.5 text-sm text-slate-200 hover:bg-slate-800">Cancel</button>
          <button disabled={blocked} data-testid="route-submit"
            onClick={() => onSubmit({
              route, reason: reason.trim() || undefined,
              change_id: route === 'attach_ecr' && changeId !== '' ? changeId : undefined,
            })}
            className="rounded-lg bg-sky-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-sky-500 disabled:cursor-not-allowed disabled:opacity-40">
            {route === 'administrative' ? 'Activate now' : `Decide: ${ROUTE_LABELS[route]}`}
          </button>
        </div>
      </div>
    </div>
  )
}
