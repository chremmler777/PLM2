/**
 * The part page's intake banner and panel (spec 2026-09-25 §17): a new
 * customer index waits for Development's triage. Development picks the route
 * (RouteDialog); everyone else sees the state and who decides.
 */
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { intakesApi, ROUTE_LABELS, suggestionReason, type Intake } from '../../api/intakes'
import { usePartIntakes } from '../../hooks/queries/useIntakes'
import { formatDate } from '../../lib/format'
import { STATUS_LABELS } from '../../lib/changeStatus'
import type { ChangeStatus } from '../../types/change'
import RouteDialog from './RouteDialog'

const errDetail = (e: unknown): string | undefined =>
  (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail

export default function IntakePanel({ partId, onDecided }: { partId: number; onDecided?: () => void }) {
  const qc = useQueryClient()
  const { data } = usePartIntakes(partId)
  const [deciding, setDeciding] = useState<Intake | null>(null)
  const decide = useMutation({
    mutationFn: ({ id, body }: { id: number; body: Parameters<typeof intakesApi.decide>[1] }) =>
      intakesApi.decide(id, body),
    onSuccess: (out) => {
      toast.success(out.route === 'administrative'
        ? `Index ${out.revision_name} is active`
        : `Index ${out.revision_name}: ${out.route_label}${out.change_number ? ` (${out.change_number})` : ''}`)
      setDeciding(null)
      qc.invalidateQueries({ queryKey: ['intakes'] })
      qc.invalidateQueries({ queryKey: ['changes'] })
      onDecided?.()
    },
    onError: (e) => toast.error(errDetail(e) ?? 'Could not decide the route'),
  })
  const intakes = data?.intakes ?? []
  if (intakes.length === 0) return null
  const triage = intakes.filter((i) => i.needs_triage)
  const linked = intakes.filter((i) => !i.needs_triage)

  return (
    <section data-testid="intake-panel" className="mb-8 rounded-lg border border-amber-700/60 bg-amber-950/20 p-4">
      {triage.map((i) => (
        <div key={i.id} className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <p data-testid="intake-banner" className="font-semibold text-amber-100">
              Index {i.revision_name}{i.customer_index ? ` (customer ${i.customer_index})` : ''} pending triage
            </p>
            <p className="mt-0.5 text-sm text-amber-100/70">
              {i.source_label}, received {formatDate(i.received_at)}{i.received_by_name ? ` by ${i.received_by_name}` : ''}
              {`. ${i.file_count} file${i.file_count === 1 ? '' : 's'}`}
              {i.active_revision_name ? `. Active until decided: ${i.active_revision_name}` : '. Nothing is active until decided'}
            </p>
            <p className="mt-1 text-xs text-slate-400">
              Suggested: <span className="text-slate-200">{i.suggested_route ? ROUTE_LABELS[i.suggested_route] : '-'}</span>
              {i.suggested_route ? ` (${suggestionReason(i)})` : ''}
            </p>
          </div>
          {i.can_decide ? (
            <button data-testid={`triage-${i.id}`} onClick={() => setDeciding(i)}
              className="rounded-lg bg-amber-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-amber-500">
              Decide the route
            </button>
          ) : (
            <p className="max-w-xs text-xs text-slate-400" data-testid="intake-readonly">
              Development decides the route of a new index. Files and BOM of the pending index can still be completed.
            </p>
          )}
        </div>
      ))}
      {linked.map((i) => (
        <div key={i.id} className={`text-sm text-amber-100/90 ${triage.length ? 'mt-3 border-t border-amber-800/40 pt-3' : ''}`}
          data-testid="intake-linked">
          Index {i.revision_name} is pending: {i.route_label}
          {i.change_id ? (
            <> in <Link className="text-sky-300 hover:underline" to={`/changes/${i.change_id}`}>{i.change_number}</Link>
              {i.change_status ? ` (${STATUS_LABELS[i.change_status as ChangeStatus] ?? i.change_status})` : ''}</>
          ) : null}
          {i.decided_by_name ? `, decided by ${i.decided_by_name} ${formatDate(i.decided_at)}` : ''}.
          <span className="text-amber-100/60">{i.route === 'engineering_review' && !i.escalated_at
            ? ' It becomes active when every asked department answers "no impact".'
            : ' It becomes active when that change releases it.'}</span>
        </div>
      ))}
      {deciding && (
        <RouteDialog intake={deciding} pending={decide.isPending} onClose={() => setDeciding(null)}
          onSubmit={(body) => decide.mutate({ id: deciding.id, body })} />
      )}
    </section>
  )
}
