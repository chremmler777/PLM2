/**
 * After "Timing validated" every date move is a deviation with a reason.
 * PM/Sales either lock it (accepted internally) or escalate it to the
 * customer, which opens a customer escalation.
 *
 * One move usually pushes its successors along, and the server records a
 * deviation per task. They are shown as one group (the move, then what it
 * pushed) with one Lock / Escalate on the group: the pushed rows follow the
 * move's decision. Until the server keeps groups itself, the group decision
 * is sent as one call per open row.
 */
import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { CornerDownRight } from 'lucide-react'
import { planApi } from '../../../api/changePlan'
import type { DeviationStatus, PlanDeviation } from '../../../types/changePlan'
import ReasonDialog from '../ReasonDialog'
import { toDay } from '../plan/ganttMath'
import { formatDateShort } from '../../../lib/format'
import { toastError } from '../../../lib/apiError'
import { btnSm } from '../../common/buttonStyles'

/** "25 Sep 26" from a day number (days since 1970-01-01, UTC). */
const fmtDay = (day: number) => formatDateShort(day)

interface Props {
  changeId: number
  deviations: PlanDeviation[]
  canDecide: boolean
  /** The change status: deviations are decided only while the work runs. */
  status?: string
}

/** Lock / escalate exist while the plan is live: approved to validation. */
const DECIDING: string[] = ['approved', 'in_implementation', 'in_validation']

/** Inclusive last day of an exclusive [start, end) span; a milestone sits on its start. */
const lastDay = (start: number, end: number) => (end > start ? end - 1 : end)

const STATUS: Record<DeviationStatus, { label: string; cls: string }> = {
  open: { label: 'Open', cls: 'border-amber-700 bg-amber-950/40 text-amber-200' },
  locked: { label: 'Locked', cls: 'border-slate-600 bg-slate-800 text-slate-300' },
  escalated: { label: 'Escalated', cls: 'border-rose-700 bg-rose-950/50 text-rose-200' },
}

const signed = (n: number) => (n > 0 ? `+${n}` : String(n))

export interface DeviationGroup { root: PlanDeviation; pushed: PlanDeviation[] }

/**
 * The user's own moves first, each followed by the successors it pushed
 * (`caused_by_task_id`): a pushed row sits under the latest own move of its
 * cause recorded before it. Rows whose cause is not listed stand alone.
 */
export function groupDeviations(list: PlanDeviation[]): DeviationGroup[] {
  const byId = [...list].sort((a, b) => a.id - b.id)
  const own = (d: PlanDeviation) => d.caused_by_task_id == null || d.caused_by_task_id === d.task_id
  const parent = new Map<number, PlanDeviation>()
  for (const d of byId) {
    if (own(d)) continue
    const root = byId.filter((r) => own(r) && r.task_id === d.caused_by_task_id && r.id < d.id).pop()
    if (root) parent.set(d.id, root)
  }
  // Newest moves first; pushed rows follow their move in the order recorded.
  return list.filter((d) => !parent.has(d.id))
    .map((root) => ({ root, pushed: byId.filter((c) => parent.get(c.id)?.id === root.id) }))
}

export default function DeviationsPanel({ changeId, deviations, canDecide: mayDecide, status }: Props) {
  const canDecide = mayDecide && (status == null || DECIDING.includes(status))
  const qc = useQueryClient()
  const [lockFor, setLockFor] = useState<number | null>(null)
  const [lockNote, setLockNote] = useState('')
  const [escalateFor, setEscalateFor] = useState<DeviationGroup | null>(null)

  const done = () => {
    qc.invalidateQueries({ queryKey: ['change', changeId, 'plan-deviations'] })
    qc.invalidateQueries({ queryKey: ['change', changeId, 'impl-escalations'] })
    qc.invalidateQueries({ queryKey: ['change-my-actions', changeId] })
    qc.invalidateQueries({ queryKey: ['change', changeId] })
  }
  const openOf = (g: DeviationGroup) => [g.root, ...g.pushed].filter((d) => d.status === 'open')
  const lock = useMutation({
    // One after the other, the move first: a refusal stops the rest.
    mutationFn: async (v: { ids: number[]; note?: string }) => {
      for (const id of v.ids) await planApi.lockDeviation(changeId, id, v.note)
    },
    onSuccess: () => { setLockFor(null); setLockNote('') },
    onError: (e: unknown) => toastError(e, 'Could not lock the deviation'),
    onSettled: done,
  })
  const escalate = useMutation({
    // The move goes to the customer; what it pushed is part of that story
    // and is locked with a note pointing at it, not escalated a second time.
    mutationFn: async (v: { group: DeviationGroup; note: string }) => {
      const { root } = v.group
      if (root.status === 'open') await planApi.escalateDeviation(changeId, root.id, v.note)
      for (const d of v.group.pushed.filter((x) => x.status === 'open')) {
        await planApi.lockDeviation(changeId, d.id, `Escalated to the customer with the move of ${root.task_name}`)
      }
    },
    onSuccess: () => setEscalateFor(null),
    onError: (e: unknown) => toastError(e, 'Could not escalate the deviation'),
    onSettled: done,
  })

  const groups = groupDeviations(deviations)
  const openGroups = groups.filter((g) => openOf(g).length > 0).length
  const busy = lock.isPending || escalate.isPending

  const row = (d: PlanDeviation, g: DeviationGroup, pushedBy: PlanDeviation | null) => {
    const ns = toDay(d.new_start)
    const ne = toDay(d.new_end)
    const baseEnd = ne - d.slip_days
    const span = ne - ns
    const open = openOf(g)
    const isRoot = pushedBy == null
    const n = open.length
    return (
      <tr key={d.id} className={`align-top ${pushedBy ? 'bg-slate-900/40' : ''}`} data-testid={`deviation-${d.id}`}
        data-pushed-by={pushedBy?.id}>
        <td className={`py-2 pr-2 text-slate-200 ${pushedBy ? 'pl-5' : ''}`}>
          <span className="inline-flex items-start gap-1">
            {pushedBy && <CornerDownRight aria-hidden="true" size={12} className="mt-0.5 shrink-0 text-slate-400" />}
            <span>{d.task_name}</span>
          </span>
          {pushedBy && (
            <p className="text-[11px] text-slate-400" data-testid={`deviation-cause-${d.id}`}>
              pushed by {d.caused_by_task_name ?? pushedBy.task_name}
            </p>
          )}
          {isRoot && g.pushed.length > 0 && (
            <p className="text-[11px] text-slate-400" data-testid={`deviation-group-${d.id}`}>
              moved {g.pushed.length} successor{g.pushed.length === 1 ? '' : 's'} along
            </p>
          )}
        </td>
        <td className="whitespace-nowrap py-2 pr-2 tabular-nums text-slate-300">
          {fmtDay(span > 0 ? baseEnd - 1 : baseEnd)} <span className="text-slate-400">to</span> {fmtDay(lastDay(ns, ne))}
        </td>
        <td className={`py-2 pr-2 text-right tabular-nums ${d.slip_days > 0 ? 'font-semibold text-red-300' : 'text-slate-300'}`}
          data-testid={`deviation-slip-${d.id}`}>
          {signed(d.slip_days)} d
        </td>
        <td className={`py-2 pr-2 text-right tabular-nums ${d.finish_impact_days > 0 ? 'text-red-300' : 'text-slate-400'}`}>
          {isRoot ? (d.finish_impact_days === 0 ? 'none' : `${signed(d.finish_impact_days)} d`) : ''}
        </td>
        <td className="max-w-[260px] py-2 pr-2 text-slate-300">
          {isRoot ? (
            <>
              <p>{d.reason}</p>
              {d.created_by_name && <p className="text-[11px] text-slate-400">{d.created_by_name}</p>}
            </>
          ) : <span className="sr-only">{d.reason}</span>}
          {d.decision_note && (isRoot || d.status !== 'locked' || !d.decision_note.startsWith('Escalated to the customer with')) && (
            <p className="mt-1 text-[11px] text-slate-400">
              {d.decided_by_name ? `${d.decided_by_name}: ` : ''}{d.decision_note}
            </p>
          )}
        </td>
        <td className="py-2 pr-2">
          <span className={`rounded-full border px-2 py-0.5 text-[11px] ${STATUS[d.status].cls}`}>
            {STATUS[d.status].label}
          </span>
        </td>
        {canDecide && (
          <td className="whitespace-nowrap py-2 text-right">
            {isRoot && n > 0 && lockFor !== d.id && (
              <div className="flex justify-end gap-1.5">
                <button type="button" data-testid={`deviation-lock-${d.id}`} disabled={busy}
                  aria-label={n > 1 ? `Lock the ${n} open deviations of the move on ${d.task_name}` : `Lock deviation on ${d.task_name}`}
                  className={btnSm.secondary}
                  onClick={() => { setLockFor(d.id); setLockNote('') }}>{n > 1 ? `Lock all ${n}` : 'Lock'}</button>
                <button type="button" data-testid={`deviation-escalate-${d.id}`} disabled={busy}
                  aria-label={`Escalate deviation on ${d.task_name} to the customer`}
                  className={`${btnSm.secondary} border-rose-800 text-rose-200 hover:border-rose-700 hover:bg-rose-950/50`}
                  onClick={() => setEscalateFor(g)}>Escalate to customer</button>
              </div>
            )}
            {isRoot && lockFor === d.id && (
              <div className="flex items-center justify-end gap-1.5">
                <input value={lockNote} onChange={(e) => setLockNote(e.target.value)} autoFocus
                  placeholder="Note (optional)" aria-label="Lock note"
                  onKeyDown={(e) => {
                    if (e.key === 'Escape') setLockFor(null)
                    if (e.key === 'Enter') lock.mutate({ ids: open.map((x) => x.id), note: lockNote.trim() || undefined })
                  }}
                  className="w-40 rounded-md border border-slate-600 bg-slate-900 px-2 py-1 text-xs text-slate-100 placeholder-slate-500" />
                <button type="button" className={btnSm.ghost} onClick={() => setLockFor(null)}>Cancel</button>
                <button type="button" disabled={busy} data-testid={`deviation-lock-confirm-${d.id}`}
                  className={btnSm.primary}
                  onClick={() => lock.mutate({ ids: open.map((x) => x.id), note: lockNote.trim() || undefined })}>
                  {n > 1 ? `Lock all ${n}` : 'Lock'}
                </button>
              </div>
            )}
          </td>
        )}
      </tr>
    )
  }

  const pushedOpen = escalateFor ? escalateFor.pushed.filter((d) => d.status === 'open').length : 0

  return (
    <section className="space-y-3 rounded-lg border border-slate-700 bg-slate-800 p-4" data-testid="deviations-panel">
      <div className="flex items-baseline justify-between gap-2">
        <h3 className="text-xs uppercase tracking-wide text-slate-400">Deviations from the baseline</h3>
        {openGroups > 0 && (
          <span className="text-xs text-amber-300">{openGroups} move{openGroups === 1 ? '' : 's'} to decide</span>
        )}
      </div>
      {deviations.length === 0 ? (
        <p className="text-sm text-slate-400">
          No deviations. Every date change after the timing was validated shows up here with its reason.
        </p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="text-left text-[11px] uppercase tracking-wide text-slate-400">
                <th scope="col" className="py-1 pr-2 font-medium">Task</th>
                <th scope="col" className="py-1 pr-2 font-medium">Baseline finish to new finish</th>
                <th scope="col" className="py-1 pr-2 text-right font-medium">Slip</th>
                <th scope="col" className="py-1 pr-2 text-right font-medium">Plan finish</th>
                <th scope="col" className="py-1 pr-2 font-medium">Reason</th>
                <th scope="col" className="py-1 pr-2 font-medium">Status</th>
                {canDecide && <th scope="col" className="py-1 font-medium"><span className="sr-only">Decision</span></th>}
              </tr>
            </thead>
            {groups.map((g) => (
              <tbody key={g.root.id} className="border-t border-slate-700/70" data-testid={`deviation-group-body-${g.root.id}`}>
                {row(g.root, g, null)}
                {g.pushed.map((d) => row(d, g, g.root))}
              </tbody>
            ))}
          </table>
        </div>
      )}
      <ReasonDialog open={escalateFor != null} title="Escalate to the customer"
        label="What does Sales tell the customer?"
        warning={`This opens a customer escalation for the implementation and marks the move escalated.${pushedOpen > 0
          ? ` The ${pushedOpen} task${pushedOpen === 1 ? '' : 's'} it pushed ${pushedOpen === 1 ? 'is' : 'are'} locked with it, noting the escalation.` : ''}`}
        submitLabel="Escalate" danger
        onSubmit={(note) => { if (escalateFor != null) escalate.mutate({ group: escalateFor, note }) }}
        onClose={() => setEscalateFor(null)} />
    </section>
  )
}
