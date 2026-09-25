/**
 * Change-plan specific edits as generic ChangeSets: the buffer and bank build
 * presets and the alignment actions of the selection. Pure, unit tested.
 */
import {
  endOf, makeCal, nextWork, normStart, shift, startFor, toDay, toIso, todayDay, type Cal,
} from '../../gantt/engine/calendar'
import { tempId } from '../../gantt/engine/notation'
import { applyChangeSet } from '../../gantt/engine/changes'
import { cascade } from '../../gantt/engine/schedule'
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

/**
 * The successor moves the backend makes when `from` move (its `cascade`):
 * everything downstream along links, links out of their summaries and into
 * summaries (to the leaves below), later only, pinned tasks stay.
 */
function pushSuccessors(ctx: Ctx, cs: ChangeSet, from: GanttId[]): ChangeSet {
  const after = applyChangeSet({ tasks: ctx.tasks, links: ctx.links }, cs)
  const moves = cascade(after.tasks, after.links, ctx.calendar, from)
  if (!moves.length) return cs
  const upd = [...(cs.updateTasks ?? [])]
  const added = [...(cs.addTasks ?? [])]
  for (const m of moves) {
    const ai = added.findIndex((t) => key(t.id) === key(m.id))
    if (ai >= 0) { added[ai] = { ...added[ai], ...m.patch }; continue }
    const i = upd.findIndex((u) => key(u.id) === key(m.id))
    if (i >= 0) upd[i] = { id: upd[i].id, patch: { ...upd[i].patch, ...m.patch } }
    else upd.push({ id: m.id, patch: m.patch })
  }
  return { ...cs, ...(cs.addTasks ? { addTasks: added } : {}), updateTasks: upd }
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
    const start = last ? nextWork(cal, span(cal, last).e) : nextWork(cal, todayDay())
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
  const firstStart = ctx.tasks.length ? Math.min(...ctx.tasks.map((t) => span(cal, t).s)) : nextWork(cal, todayDay())
  const end = anchor ? span(cal, anchor).s : firstStart + days
  const start = startFor(cal, end, days)
  // Linked finish-to-start into its anchor: the idea follows it when it moves.
  const twin = anchor && ctx.tasks.some((t) => t.kind === 'bank_build' && ctx.links.some((l) => key(l.from) === key(t.id) && key(l.to) === key(anchor.id)))
  return {
    label: 'Add bank build idea',
    addTasks: [{
      id, name: 'Bank build (idea)', start: toIso(start), duration: days, kind: 'bank_build', isIdea: true,
      lane: scheduling.lane, meta: { department_id: scheduling.departmentId },
    }],
    ...(anchor ? { addLinks: [{ id: (ctx.newId ?? (() => tempId('link')))(), from: id, to: anchor.id, type: 'FS' as const, lagDays: 0 }] } : {}),
    order: orderWith(ctx.tasks, id, anchor?.id ?? null, 'before'),
    ...(twin ? { meta: { warning: `'${anchor!.name}' already has a bank build idea: this adds a second one` } } : {}),
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
      // In the plan calendar's units (working days in working mode).
      const days = cal.idx(toDay(u.patch.start!)) - cal.idx(span(cal, t).s)
      return { id: u.id, name: t.name, from: t.start, to: u.patch.start!, days }
    })
  return { cs: out, moved }
}

/**
 * Idea blocks linked finish-to-start into a task follow it: when the task
 * moves, the idea keeps ending where the task starts (the server does not
 * move ideas; these moves are the user's, sent as such).
 */
export function ideasFollow(ctx: Ctx, cs: ChangeSet): ChangeSet {
  const moved = new Map((cs.updateTasks ?? []).filter((u) => 'start' in u.patch).map((u) => [key(u.id), u.patch.start!]))
  if (!moved.size) return cs
  const cal = makeCal(ctx.calendar)
  const upd = [...(cs.updateTasks ?? [])]
  for (const l of ctx.links) {
    if (l.type !== 'FS' || !moved.has(key(l.to))) continue
    const idea = ctx.tasks.find((t) => key(t.id) === key(l.from) && t.isIdea)
    if (!idea || upd.some((u) => key(u.id) === key(idea.id))) continue
    const anchorStart = cal.idx(normStart(cal, toDay(moved.get(key(l.to))!)))
    const start = toIso(cal.dateAt(anchorStart - l.lagDays - Math.max(0, idea.duration)))
    if (start !== idea.start) upd.push({ id: idea.id, patch: { start } })
  }
  return upd.length === (cs.updateTasks ?? []).length ? cs : { ...cs, updateTasks: upd }
}
