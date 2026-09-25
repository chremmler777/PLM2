/**
 * After "Timing validated" every date move is a deviation with a reason.
 * PM/Sales either lock it (accepted internally) or escalate it to the
 * customer, which opens a customer escalation.
 *
 * One move usually pushes its successors along, and the server records a
 * deviation per task. They are shown as one group (the move, then what it
 * pushed) with one Lock / Escalate on the group: the pushed rows follow the
 * move's decision. Until the server decides a group in one call, the group
 * decision is sent as one call per open row by `decideGroup`, the one place
 * to swap for a group endpoint.
 */
import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { CornerDownRight } from 'lucide-react'
import { planApi } from '../../../api/changePlan'
import type { DeviationStatus, PlanDeviation } from '../../../types/changePlan'
import ReasonDialog from '../ReasonDialog'
import { toDay } from '../plan/ganttMath'
import { formatDateShort } from '../../../lib/format'
import { apiErrorMessage, toastError } from '../../../lib/apiError'
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

/** Rows of a group still waiting for a decision, the move first. */
const openOf = (g: DeviationGroup) => [g.root, ...g.pushed].filter((d) => d.status === 'open')

/** Lock note of a row pushed by an escalated move: says where the decision went. */
export const pushedEscalatedNote = (root: PlanDeviation, escalationId?: number | null) =>
  `Pushed by the move of ${root.task_name}, which was escalated to the customer${
    escalationId != null ? ` (escalation #${escalationId})` : ''}`

export type GroupAction = 'lock' | 'escalate'

/** What a group decision did, so the message can say exactly that. */
export interface GroupOutcome {
  action: GroupAction
  /** The move itself went to the customer in this call. */
  escalated: boolean
  /** Rows locked in this call, out of `toLock` open rows asked for. */
  locked: number
  toLock: number
  /** Why the rest stayed open, when a row was refused. */
  error?: unknown
}

/**
 * Decides one deviation group. `escalate` sends the move (which must be open)
 * to the customer, then locks the rows it pushed with a note naming the
 * escalation. `lock` locks every open row; rows pushed by an already
 * escalated move get that same note. One call per row, the move first; a
 * refused row stops the rest and is reported, not thrown, so the caller can
 * tell what did happen. A failed escalation is thrown: nothing changed.
 *
 * The one place a server-side group endpoint would plug in.
 */
export async function decideGroup(
  changeId: number, group: DeviationGroup, action: GroupAction, note?: string,
): Promise<GroupOutcome> {
  const { root } = group
  const openPushed = group.pushed.filter((d) => d.status === 'open')
  let escalationId = root.escalation_id ?? null
  let escalated = false
  let rows: PlanDeviation[]
  if (action === 'escalate') {
    if (root.status !== 'open') throw new Error('This move is already decided')
    const res = await planApi.escalateDeviation(changeId, root.id, note ?? '') as Partial<PlanDeviation> | undefined
    escalated = true
    escalationId = res?.escalation_id ?? null
    rows = openPushed
  } else {
    rows = openOf(group)
  }
  const afterEscalation = escalated || root.status === 'escalated'
  const noteFor = (d: PlanDeviation) => {
    if (d.id === root.id || !afterEscalation) return note
    const auto = pushedEscalatedNote(root, escalationId)
    return action === 'lock' && note ? `${auto}. ${note}` : auto
  }
  let locked = 0
  for (const d of rows) {
    try {
      await planApi.lockDeviation(changeId, d.id, noteFor(d))
      locked += 1
    } catch (error) {
      return { action, escalated, locked, toLock: rows.length, error }
    }
  }
  return { action, escalated, locked, toLock: rows.length }
}

const plural = (n: number, one: string, many = `${one}s`) => `${n} ${n === 1 ? one : many}`

/** The toast for a group decision: what happened, and what is left to retry. */
export function outcomeMessage(o: GroupOutcome): { ok: boolean; text: string } {
  const all = o.locked === o.toLock
  if (o.action === 'escalate') {
    if (o.toLock === 0) return { ok: true, text: 'Escalated to the customer' }
    if (all) return { ok: true, text: `Escalated to the customer; ${plural(o.locked, 'pushed row')} locked` }
    return { ok: false, text: `Escalated; ${o.locked} of ${plural(o.toLock, 'pushed row')} locked, retry to lock the rest` }
  }
  if (all) return { ok: true, text: `Locked ${plural(o.locked, 'deviation')}` }
  return { ok: false, text: `Locked ${o.locked} of ${plural(o.toLock, 'deviation')}, retry to lock the rest` }
}

function report(o: GroupOutcome) {
  const m = outcomeMessage(o)
  if (m.ok) toast.success(m.text)
  else toast.error(`${m.text}. ${apiErrorMessage(o.error, 'The server refused a row')}`)
}

export default function DeviationsPanel({ changeId, deviations, canDecide: mayDecide, status }: Props) {
  const canDecide = mayDecide && (status == null || DECIDING.includes(status))
  const qc = useQueryClient()
  const [lockFor, setLockFor] = useState<number | null>(null)
  const [lockNote, setLockNote] = useState('')
  /** Only the move's id: the group is rebuilt from the current rows each render. */
  const [escalateRoot, setEscalateRoot] = useState<number | null>(null)

  const done = () => {
    qc.invalidateQueries({ queryKey: ['change', changeId, 'plan-deviations'] })
    qc.invalidateQueries({ queryKey: ['change', changeId, 'impl-escalations'] })
    qc.invalidateQueries({ queryKey: ['change-my-actions', changeId] })
    qc.invalidateQueries({ queryKey: ['change', changeId] })
  }
  const lock = useMutation({
    mutationFn: (v: { group: DeviationGroup; note?: string }) => decideGroup(changeId, v.group, 'lock', v.note),
    onSuccess: (o) => { report(o); if (o.locked === o.toLock) { setLockFor(null); setLockNote('') } },
    onError: (e: unknown) => toastError(e, 'Could not lock the deviation'),
    onSettled: done,
  })
  const escalate = useMutation({
    // The move goes to the customer; what it pushed is part of that story
    // and is locked with a note pointing at it, not escalated a second time.
    mutationFn: (v: { group: DeviationGroup; note: string }) => decideGroup(changeId, v.group, 'escalate', v.note),
    onSuccess: report,
    onError: (e: unknown) => toastError(e, 'Could not escalate the deviation'),
    onSettled: () => { setEscalateRoot(null); done() },
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
    // Once the move is decided, only its leftover pushed rows can be locked;
    // escalating is offered only while the move itself is open.
    const rootOpen = g.root.status === 'open'
    const lockLabel = rootOpen ? (n > 1 ? `Lock all ${n}` : 'Lock') : 'Lock remaining'
    const submitLock = () => { if (!busy) lock.mutate({ group: g, note: lockNote.trim() || undefined }) }
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
                  aria-label={rootOpen
                    ? (n > 1 ? `Lock the ${n} open deviations of the move on ${d.task_name}` : `Lock deviation on ${d.task_name}`)
                    : `Lock the ${n} remaining pushed deviation${n === 1 ? '' : 's'} of the move on ${d.task_name}`}
                  className={btnSm.secondary}
                  onClick={() => { setLockFor(d.id); setLockNote('') }}>{lockLabel}</button>
                {rootOpen && (
                  <button type="button" data-testid={`deviation-escalate-${d.id}`} disabled={busy}
                    aria-label={`Escalate deviation on ${d.task_name} to the customer`}
                    className={`${btnSm.secondary} border-rose-800 text-rose-200 hover:border-rose-700 hover:bg-rose-950/50`}
                    onClick={() => setEscalateRoot(g.root.id)}>Escalate to customer</button>
                )}
              </div>
            )}
            {isRoot && lockFor === d.id && (
              <div className="flex items-center justify-end gap-1.5">
                <input value={lockNote} onChange={(e) => setLockNote(e.target.value)} autoFocus
                  placeholder="Note (optional)" aria-label="Lock note"
                  onKeyDown={(e) => {
                    if (e.key === 'Escape') setLockFor(null)
                    if (e.key === 'Enter') submitLock()
                  }}
                  className="w-40 rounded-md border border-slate-600 bg-slate-900 px-2 py-1 text-xs text-slate-100 placeholder-slate-500" />
                <button type="button" className={btnSm.ghost} onClick={() => setLockFor(null)}>Cancel</button>
                <button type="button" disabled={busy} data-testid={`deviation-lock-confirm-${d.id}`}
                  className={btnSm.primary} onClick={submitLock}>
                  {lockLabel}
                </button>
              </div>
            )}
          </td>
        )}
      </tr>
    )
  }

  // Rebuilt from the current rows: a refetch that decided the move elsewhere
  // closes the dialog instead of escalating a stale group.
  const escalateGroup = groups.find((g) => g.root.id === escalateRoot && g.root.status === 'open') ?? null
  const pushedOpen = escalateGroup ? escalateGroup.pushed.filter((d) => d.status === 'open').length : 0

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
      <ReasonDialog open={escalateGroup != null} title="Escalate to the customer"
        label="What does Sales tell the customer?"
        warning={`This opens a customer escalation for the implementation and marks the move escalated.${pushedOpen > 0
          ? ` The ${pushedOpen} task${pushedOpen === 1 ? '' : 's'} it pushed ${pushedOpen === 1 ? 'is' : 'are'} locked with it, noting the escalation.` : ''}`}
        submitLabel="Escalate" danger
        onSubmit={(note) => { if (escalateGroup != null && !busy) escalate.mutate({ group: escalateGroup, note }) }}
        onClose={() => setEscalateRoot(null)} />
    </section>
  )
}
