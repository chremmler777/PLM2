/**
 * Change-plan specific edits as generic ChangeSets: the buffer and bank build
 * presets and the alignment actions of the selection. Pure, unit tested.
 */
import {
  endOf, makeCal, nextWork, normStart, shift, startFor, toDay, toIso, type Cal,
} from '../../gantt/engine/calendar'
import { tempId } from '../../gantt/engine/notation'
import { autoSchedulePatches } from '../../gantt/engine/schedule'
import { key } from '../../gantt/engine/tree'
import type { ChangeSet, GanttCalendar, GanttId, GanttLink, GanttTask } from '../../gantt/engine/types'

interface Ctx {
  tasks: GanttTask[]
  links: GanttLink[]
  calendar?: Partial<GanttCalendar> | null
  newId?: () => GanttId
}

const span = (cal: Cal, t: GanttTask) => {
  const s = normStart(cal, toDay(t.start))
  return { s, e: endOf(cal, s, t.duration) }
}
const isMilestone = (t: GanttTask) => t.duration === 0 || t.kind === 'milestone'

/** Push-mode moves of the tasks reachable from `from` after the ChangeSet (successors only). */
function pushSuccessors(ctx: Ctx, cs: ChangeSet, from: GanttId[]): ChangeSet {
  const tasks = [...ctx.tasks.filter((t) => !(cs.removeTasks ?? []).some((r) => key(r) === key(t.id))), ...(cs.addTasks ?? [])]
    .map((t) => {
      const u = (cs.updateTasks ?? []).find((x) => key(x.id) === key(t.id))
      return u ? { ...t, ...u.patch } : t
    })
  const removed = new Set((cs.removeLinks ?? []).map(key))
  const links = [...ctx.links.filter((l) => !removed.has(key(l.id))), ...(cs.addLinks ?? [])]
  const reach = new Set<string>()
  const stack = from.map(key)
  while (stack.length) {
    const k = stack.pop()!
    for (const l of links) if (key(l.from) === k && !reach.has(key(l.to))) { reach.add(key(l.to)); stack.push(key(l.to)) }
  }
  const moves = autoSchedulePatches(tasks, links, ctx.calendar).filter((m) => reach.has(key(m.id)))
  if (!moves.length) return cs
  const upd = [...(cs.updateTasks ?? [])]
  for (const m of moves) {
    const i = upd.findIndex((u) => key(u.id) === key(m.id))
    if (i >= 0) upd[i] = { id: upd[i].id, patch: { ...upd[i].patch, ...m.patch } }
    else if (!(cs.addTasks ?? []).some((t) => key(t.id) === key(m.id))) upd.push(m)
  }
  const added = (cs.addTasks ?? []).map((t) => {
    const m = moves.find((x) => key(x.id) === key(t.id))
    return m ? { ...t, ...m.patch } : t
  })
  return { ...cs, addTasks: cs.addTasks ? added : undefined, updateTasks: upd }
}

/** Insert `id` into an order before or after `anchor` (end when no anchor). */
function orderWith(tasks: GanttTask[], id: GanttId, anchor: GanttId | null, where: 'before' | 'after'): GanttId[] {
  const order = tasks.map((t) => t.id)
  const i = anchor == null ? -1 : order.findIndex((x) => key(x) === key(anchor))
  if (i < 0) return [...order, id]
  order.splice(where === 'before' ? i : i + 1, 0, id)
  return order
}

/**
 * Safety buffer. With a selection: after the selected task that ends last,
 * taking over its outgoing finish-to-start links. Without one: in front of the
 * last milestone (SOP): the milestone's predecessors now lead to the buffer,
 * the buffer leads to the milestone. Successors are pushed as needed.
 */
export function bufferChangeSet(ctx: Ctx, selection: GanttId[], days = 5, extra: Partial<GanttTask> = {}): ChangeSet {
  const cal = makeCal(ctx.calendar)
  const newId = ctx.newId ?? (() => tempId('task'))
  const id = newId()
  const sel = ctx.tasks.filter((t) => selection.some((s) => key(s) === key(t.id)) && !t.isIdea)
  const real = ctx.tasks.filter((t) => !t.isIdea)
  const base: Omit<GanttTask, 'start' | 'lane'> = { id, name: 'Safety buffer', duration: days, kind: 'buffer', ...extra }
  if (sel.length) {
    const anchor = sel.reduce((a, b) => (span(cal, b).e > span(cal, a).e ? b : a))
    const outs = ctx.links.filter((l) => key(l.from) === key(anchor.id) && l.type === 'FS')
    const cs: ChangeSet = {
      label: 'Add buffer',
      addTasks: [{ ...base, start: toIso(nextWork(cal, span(cal, anchor).e)), lane: anchor.lane ?? null, meta: { department_id: anchor.meta?.department_id ?? null } }],
      addLinks: [
        { id: newId(), from: anchor.id, to: id, type: 'FS', lagDays: 0 },
        ...outs.map((l) => ({ ...l, id: newId(), from: id })),
      ],
      removeLinks: outs.map((l) => l.id),
      order: orderWith(ctx.tasks, id, anchor.id, 'after'),
    }
    return pushSuccessors(ctx, cs, [id])
  }
  const sop = [...real].filter(isMilestone).sort((a, b) => span(cal, b).s - span(cal, a).s)[0]
  if (!sop) {
    const last = real.length ? real.reduce((a, b) => (span(cal, b).e > span(cal, a).e ? b : a)) : undefined
    const start = last ? nextWork(cal, span(cal, last).e) : nextWork(cal, toDay(new Date().toISOString().slice(0, 10)))
    return {
      label: 'Add buffer',
      addTasks: [{ ...base, start: toIso(start), lane: last?.lane ?? null, meta: { department_id: last?.meta?.department_id ?? null } }],
      ...(last ? { addLinks: [{ id: newId(), from: last.id, to: id, type: 'FS' as const, lagDays: 0 }] } : {}),
      order: orderWith(ctx.tasks, id, last?.id ?? null, 'after'),
    }
  }
  const ins = ctx.links.filter((l) => key(l.to) === key(sop.id))
  const preds = ins.map((l) => ctx.tasks.find((t) => key(t.id) === key(l.from))).filter((t): t is GanttTask => !!t)
  const lead = preds.length ? preds.reduce((a, b) => (span(cal, b).e > span(cal, a).e ? b : a)) : undefined
  const start = lead ? Math.max(nextWork(cal, span(cal, lead).e), span(cal, sop).s) : span(cal, sop).s
  const cs: ChangeSet = {
    label: 'Add buffer',
    addTasks: [{ ...base, start: toIso(nextWork(cal, start)), lane: lead?.lane ?? sop.lane ?? null, meta: { department_id: lead?.meta?.department_id ?? null } }],
    removeLinks: ins.map((l) => l.id),
    addLinks: [
      ...ins.map((l) => ({ ...l, id: newId(), to: id })),
      { id: newId(), from: id, to: sop.id, type: 'FS', lagDays: 0 },
    ],
    order: orderWith(ctx.tasks, id, sop.id, 'before'),
  }
  return pushSuccessors(ctx, cs, [id])
}

/**
 * Bank build idea: 10 days in the Scheduling lane, ending where the first
 * tool downtime starts (or where the selection starts). Not linked: it is a
 * proposal until the team decides.
 */
export function bankBuildChangeSet(ctx: Ctx, selection: GanttId[], scheduling: { lane: string; departmentId: number | null }, days = 10): ChangeSet {
  const cal = makeCal(ctx.calendar)
  const id = (ctx.newId ?? (() => tempId('task')))()
  const sel = ctx.tasks.filter((t) => selection.some((s) => key(s) === key(t.id)))
  const downtime = ctx.tasks.filter((t) => t.kind === 'downtime' && !t.isIdea).sort((a, b) => span(cal, a).s - span(cal, b).s)[0]
  const anchor = sel.length ? sel.reduce((a, b) => (span(cal, b).s < span(cal, a).s ? b : a)) : downtime
  const firstStart = ctx.tasks.length ? Math.min(...ctx.tasks.map((t) => span(cal, t).s)) : nextWork(cal, toDay(new Date().toISOString().slice(0, 10)))
  const end = anchor ? span(cal, anchor).s : firstStart + days
  const start = startFor(cal, end, days)
  return {
    label: 'Add bank build idea',
    addTasks: [{
      id, name: 'Bank build (idea)', start: toIso(start), duration: days, kind: 'bank_build', isIdea: true,
      lane: scheduling.lane, meta: { department_id: scheduling.departmentId },
    }],
    order: orderWith(ctx.tasks, id, anchor?.id ?? null, 'before'),
  }
}

// ------------------------------------------------------------------ alignment

/** Start each selected task where its incoming links allow (earlier or later). */
export function snapToLinks(ctx: Ctx, selection: GanttId[]): ChangeSet | null {
  const cal = makeCal(ctx.calendar)
  const byKey = new Map(ctx.tasks.map((t) => [key(t.id), t]))
  const sel = new Set(selection.map(key))
  const next = new Map<string, number>()
  const startOf = (k: string) => next.get(k) ?? span(cal, byKey.get(k)!).s
  // Walk in dependency order so a selected predecessor's new position counts.
  const done = new Set<string>()
  const visit = (k: string, depth = 0) => {
    if (done.has(k) || depth > 500) return
    done.add(k)
    const ins = ctx.links.filter((l) => key(l.to) === k && byKey.has(key(l.from)))
    ins.forEach((l) => { if (sel.has(key(l.from))) visit(key(l.from), depth + 1) })
    if (!sel.has(k) || !ins.length) return
    const t = byKey.get(k)!
    let req = -Infinity
    for (const l of ins) {
      const p = byKey.get(key(l.from))!
      const ps = startOf(key(p.id))
      const pe = endOf(cal, ps, p.duration)
      const b = l.type === 'SS' ? shift(cal, ps, l.lagDays) : l.type === 'FF' ? startFor(cal, shift(cal, pe, l.lagDays), t.duration)
        : l.type === 'SF' ? startFor(cal, shift(cal, ps, l.lagDays), t.duration) : shift(cal, pe, l.lagDays)
      req = Math.max(req, b)
    }
    next.set(k, nextWork(cal, req))
  }
  sel.forEach((k) => visit(k))
  const updateTasks = [...next].filter(([k, d]) => d !== span(cal, byKey.get(k)!).s)
    .map(([k, d]) => ({ id: byKey.get(k)!.id, patch: { start: toIso(d) } }))
  return updateTasks.length ? { label: 'Snap to predecessors', updateTasks } : null
}

/** Give the selection the start (or end) of the first selected task. */
export function matchSelection(ctx: Ctx, selection: GanttId[], edge: 'start' | 'end'): ChangeSet | null {
  const cal = makeCal(ctx.calendar)
  const byKey = new Map(ctx.tasks.map((t) => [key(t.id), t]))
  const anchor = byKey.get(key(selection[0] ?? ''))
  if (!anchor) return null
  const a = span(cal, anchor)
  const updateTasks = selection.slice(1).map((id) => byKey.get(key(id))).filter((t): t is GanttTask => !!t)
    .map((t) => ({ t, s: edge === 'start' ? a.s : startFor(cal, a.e, t.duration) }))
    .filter(({ t, s }) => s !== span(cal, t).s)
    .map(({ t, s }) => ({ id: t.id, patch: { start: toIso(s) } }))
  return updateTasks.length ? { label: edge === 'start' ? 'Match start' : 'Match end', updateTasks } : null
}

/** Drop the links among the selection and start all of it together. */
export function runParallel(ctx: Ctx, selection: GanttId[]): ChangeSet | null {
  const cal = makeCal(ctx.calendar)
  const sel = new Set(selection.map(key))
  const tasks = ctx.tasks.filter((t) => sel.has(key(t.id)))
  if (tasks.length < 2) return null
  const start = Math.min(...tasks.map((t) => span(cal, t).s))
  const removeLinks = ctx.links.filter((l) => sel.has(key(l.from)) && sel.has(key(l.to))).map((l) => l.id)
  const updateTasks = tasks.filter((t) => span(cal, t).s !== start).map((t) => ({ id: t.id, patch: { start: toIso(start) } }))
  if (!removeLinks.length && !updateTasks.length) return null
  return { label: 'Run in parallel', ...(removeLinks.length ? { removeLinks } : {}), ...(updateTasks.length ? { updateTasks } : {}) }
}

/**
 * After the baseline a date move carries its successors along (the server
 * records each as a deviation). The ChangeSet with those moves added, and
 * the list for the reason dialog.
 */
export function withSuccessorMoves(ctx: Ctx, cs: ChangeSet): { cs: ChangeSet; moved: { id: GanttId; name: string; from: string; to: string; days: number }[] } {
  const changed = (cs.updateTasks ?? []).filter((u) => 'start' in u.patch || 'duration' in u.patch).map((u) => u.id)
  if (!changed.length) return { cs, moved: [] }
  const out = pushSuccessors(ctx, cs, changed)
  const cal = makeCal(ctx.calendar)
  const byKey = new Map(ctx.tasks.map((t) => [key(t.id), t]))
  const moved = (out.updateTasks ?? [])
    .filter((u) => !changed.some((c) => key(c) === key(u.id)) && 'start' in u.patch)
    .map((u) => {
      const t = byKey.get(key(u.id))!
      const from = span(cal, t).s, to = toDay(u.patch.start!)
      return { id: u.id, name: t.name, from: t.start, to: u.patch.start!, days: to - from }
    })
  return { cs: out, moved }
}
