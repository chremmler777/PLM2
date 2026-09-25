/**
 * Critical path scheduling (spec 2026-09-25 §11). The backend service
 * implements the same rules; both are checked against the shared vectors in
 * `backend/tests/data/gantt_vectors.json`.
 *
 * Rules
 * - Units: durations, lags and slack count days in calendar mode, working
 *   days in working mode (see calendar.ts). Ends are exclusive.
 * - Links P -> S with lag L (negative = lead), X = shift(date, L):
 *     FS: S.start >= shift(P.end, L)    SS: S.start >= shift(P.start, L)
 *     FF: S.end   >= shift(P.end, L)    SF: S.end   >= shift(P.start, L)
 * - Forward pass, early start ES of a leaf = max of: its anchor (its own start
 *   in the default "push" mode, the project start in "pull" mode or when pull
 *   is on and the task has no predecessor), every link bound, inherited
 *   summary bounds, `snet` date, `mfo`/`mso` override (a hard constraint wins
 *   over links, a conflict is reported). The start is then moved to a working
 *   day (non-milestones, working mode). EF = shift(ES, duration).
 * - Summary tasks: a link or constraint on a summary applies to every leaf
 *   below it (start bounds as start bounds, finish bounds per leaf duration).
 *   Their dates roll up: start = min child start, end = max child end,
 *   progress = duration weighted mean of the leaves.
 * - Idea tasks are scheduled forward like any task but are left out of the
 *   project finish, the backward pass, slack and the critical path.
 * - Backward pass over non-idea tasks: LF starts at the project finish
 *   (max EF of non-idea leaves) and is lowered by every successor link
 *   (mirror of the rules above) and by `fnlt`/`mfo` dates (and `mso` via its
 *   start). LS = startFor(LF, duration).
 * - Total slack = diff(ES, LS) (may be negative: a constraint cannot be met).
 *   Free slack = min over outgoing links of the gap to the successor's bound,
 *   or diff(EF, project finish) without successors; never above total slack.
 *   Critical = not an idea and total slack <= 0. A summary is critical when a
 *   leaf below it is; its slack is the minimum of its leaves.
 * - A cycle (links, including a link between a task and its own summary)
 *   stops the pass: every task keeps its own dates, slack is null and the
 *   cycle is reported.
 */
import {
  diff, endOf, makeCal, normStart, shift, startFor, toDay, toIso, type Cal,
} from './calendar'
import { buildTree, key, leaves, type Tree } from './tree'
import type {
  GanttCalendar, GanttId, GanttLink, GanttTask, Issue, ScheduleOptions, ScheduleResult, ScheduledTask,
} from './types'

interface Node {
  t: GanttTask
  k: string
  dur: number
  start: number
}

/** Lower bound on the successor's start (FS/SS) or end (FF/SF). */
function forwardBound(cal: Cal, type: GanttLink['type'], lag: number, pStart: number, pEnd: number) {
  switch (type) {
    case 'SS': return { side: 'start' as const, day: shift(cal, pStart, lag) }
    case 'FF': return { side: 'end' as const, day: shift(cal, pEnd, lag) }
    case 'SF': return { side: 'end' as const, day: shift(cal, pStart, lag) }
    default: return { side: 'start' as const, day: shift(cal, pEnd, lag) }
  }
}

/**
 * Topological order over "events": in(X) (bounds known) and out(X) (dates
 * known). Leaves have in == out. Returns null and the cycle members on a loop.
 */
function eventOrder(tree: Tree, links: GanttLink[]): { order: string[] | null; cycle: string[] } {
  const inN = (k: string) => (tree.children.get(k)?.length ? `in:${k}` : `n:${k}`)
  const outN = (k: string) => (tree.children.get(k)?.length ? `out:${k}` : `n:${k}`)
  const nodes = new Set<string>()
  const edges = new Map<string, string[]>()
  const add = (a: string, b: string) => {
    nodes.add(a); nodes.add(b)
    if (!edges.has(a)) edges.set(a, [])
    edges.get(a)!.push(b)
  }
  for (const t of tree.order) {
    const k = key(t.id)
    nodes.add(inN(k)); nodes.add(outN(k))
    for (const c of tree.children.get(k) ?? []) {
      add(inN(k), inN(key(c.id)))
      add(outN(key(c.id)), outN(k))
    }
  }
  for (const l of links) {
    const f = key(l.from), t = key(l.to)
    if (!tree.byId.has(f) || !tree.byId.has(t)) continue
    if (f === t) return { order: null, cycle: [f] }
    add(outN(f), inN(t))
  }
  const indeg = new Map<string, number>([...nodes].map((n) => [n, 0]))
  edges.forEach((bs) => bs.forEach((b) => indeg.set(b, (indeg.get(b) ?? 0) + 1)))
  // Stable: seed in display order.
  const rank = new Map<string, number>()
  tree.order.forEach((t, i) => { const k = key(t.id); rank.set(inN(k), i * 2); rank.set(outN(k), i * 2 + 1) })
  const ready = [...nodes].filter((n) => indeg.get(n) === 0).sort((a, b) => (rank.get(a) ?? 0) - (rank.get(b) ?? 0))
  const out: string[] = []
  while (ready.length) {
    const n = ready.shift()!
    out.push(n)
    for (const b of edges.get(n) ?? []) {
      indeg.set(b, indeg.get(b)! - 1)
      if (indeg.get(b) === 0) {
        // insert keeping rank order
        const r = rank.get(b) ?? 0
        let i = 0
        while (i < ready.length && (rank.get(ready[i]) ?? 0) <= r) i++
        ready.splice(i, 0, b)
      }
    }
  }
  if (out.length === nodes.size) return { order: out, cycle: [] }
  const stuck = new Set<string>()
  for (const n of nodes) if ((indeg.get(n) ?? 0) > 0) stuck.add(n.replace(/^(in|out|n):/, ''))
  return { order: null, cycle: [...stuck] }
}

const issue = (level: Issue['level'], code: string, message: string, taskId: GanttId | null): Issue =>
  ({ level, code, message, taskId })

/** Find a cycle among the links (task ids), or [] when there is none. */
export function findCycle(tasks: GanttTask[], links: GanttLink[]): GanttId[] {
  const tree = buildTree(tasks)
  const { cycle } = eventOrder(tree, links)
  return cycle.map((k) => tree.byId.get(k)?.id ?? k)
}

/** Would adding from -> to close a loop? */
export function wouldCycle(tasks: GanttTask[], links: GanttLink[], from: GanttId, to: GanttId): boolean {
  if (key(from) === key(to)) return true
  return findCycle(tasks, [...links, { id: '__probe', from, to, type: 'FS', lagDays: 0 }]).length > 0
}

export function schedule(
  tasks: GanttTask[], links: GanttLink[], calendar?: Partial<GanttCalendar> | null, opts: ScheduleOptions = {},
): ScheduleResult {
  const cal = makeCal(calendar)
  const tree = buildTree(tasks)
  const issues: Issue[] = []
  const byId = new Map<GanttId, ScheduledTask>()
  const validLinks = links.filter((l) => tree.byId.has(key(l.from)) && tree.byId.has(key(l.to)))
  const isSum = (k: string) => (tree.children.get(k)?.length ?? 0) > 0

  const nodes = new Map<string, Node>()
  for (const t of tasks) {
    const k = key(t.id)
    nodes.set(k, { t, k, dur: Math.max(0, Math.round(t.duration || 0)), start: toDay(t.start) })
  }

  const { order, cycle } = eventOrder(tree, validLinks)
  const ES = new Map<string, number>()
  const EF = new Map<string, number>()

  const rollup = () => {
    // Summaries: bottom-up over pre-order reversed.
    for (const t of [...tree.order].reverse()) {
      const k = key(t.id)
      const kids = tree.children.get(k) ?? []
      if (!kids.length) continue
      ES.set(k, Math.min(...kids.map((c) => ES.get(key(c.id))!)))
      EF.set(k, Math.max(...kids.map((c) => EF.get(key(c.id))!)))
    }
  }

  const progressOf = (k: string): number => {
    const ls = leaves(tree, k)
    const weights = ls.map((l) => Math.max(1, nodes.get(key(l.id))!.dur))
    const total = weights.reduce((a, b) => a + b, 0)
    if (!total) return 0
    const sum = ls.reduce((acc, l, i) => acc + (Math.max(0, Math.min(100, l.progress ?? 0)) * weights[i]), 0)
    return Math.round(sum / total)
  }

  if (!order) {
    // Cycle: keep the dates as planned.
    for (const n of nodes.values()) {
      const s = normStart(cal, n.start)
      ES.set(n.k, s)
      EF.set(n.k, endOf(cal, s, n.dur))
    }
    rollup()
    issues.push(issue('error', 'cycle', 'The dependencies form a loop', null))
    for (const t of tasks) {
      const k = key(t.id)
      byId.set(t.id, {
        id: t.id, start: toIso(ES.get(k)!), end: toIso(EF.get(k)!), lateStart: null, lateEnd: null,
        totalSlack: null, freeSlack: null, critical: false, isSummary: isSum(k),
        progress: isSum(k) ? progressOf(k) : Math.max(0, Math.min(100, t.progress ?? 0)),
      })
    }
    return {
      byId, cycle: cycle.map((k) => tree.byId.get(k)?.id ?? k), criticalIds: [],
      start: ES.size ? toIso(Math.min(...ES.values())) : null,
      finish: finishOf(tasks, tree, EF), issues,
    }
  }

  // ------------------------------------------------------------ forward pass
  const incoming = new Map<string, GanttLink[]>()
  const outgoing = new Map<string, GanttLink[]>()
  for (const l of validLinks) {
    const f = key(l.from), t = key(l.to)
    if (!incoming.has(t)) incoming.set(t, [])
    incoming.get(t)!.push(l)
    if (!outgoing.has(f)) outgoing.set(f, [])
    outgoing.get(f)!.push(l)
  }
  const projectStart = opts.projectStart ? toDay(opts.projectStart)
    : Math.min(...[...nodes.values()].filter((n) => !isSum(n.k)).map((n) => n.start), Infinity)

  /** Start bounds and end bounds collected for a node (incl. inherited from summaries). */
  const startBound = new Map<string, number>()
  const endBound = new Map<string, number>()
  const hasPred = new Set<string>()
  const bump = (m: Map<string, number>, k: string, d: number) => m.set(k, Math.max(m.get(k) ?? -Infinity, d))

  const collect = (k: string) => {
    for (const l of incoming.get(k) ?? []) {
      const p = key(l.from)
      const b = forwardBound(cal, l.type, Math.round(l.lagDays || 0), ES.get(p)!, EF.get(p)!)
      bump(b.side === 'start' ? startBound : endBound, k, b.day)
      hasPred.add(k)
    }
    const c = nodes.get(k)!.t.constraint
    if (c && c.type === 'snet' && c.date) bump(startBound, k, toDay(c.date))
    const parent = tree.parentOf.get(k)
    if (parent != null) {
      if (startBound.has(parent)) bump(startBound, k, startBound.get(parent)!)
      if (endBound.has(parent)) bump(endBound, k, endBound.get(parent)!)
      if (hasPred.has(parent)) hasPred.add(k)
    }
  }

  for (const ev of order) {
    const [kind, k] = ev.split(/:(.*)/s) as [string, string]
    if (kind === 'out') {
      // Summary: all children are scheduled, roll its dates up now so links out of it see them.
      const kids = tree.children.get(k) ?? []
      ES.set(k, Math.min(...kids.map((c) => ES.get(key(c.id))!)))
      EF.set(k, Math.max(...kids.map((c) => EF.get(key(c.id))!)))
      continue
    }
    collect(k)
    if (kind === 'in') {
      // Summary: hard constraints on a summary act as bounds for its leaves.
      const c = nodes.get(k)!.t.constraint
      if (c?.date && (c.type === 'mso')) bump(startBound, k, toDay(c.date))
      if (c?.date && (c.type === 'mfo')) bump(endBound, k, toDay(c.date))
      continue
    }
    const n = nodes.get(k)!
    const anchor = opts.pull ? (hasPred.has(k) ? -Infinity : projectStart) : n.start
    let es = Math.max(anchor, startBound.get(k) ?? -Infinity)
    if (endBound.has(k)) es = Math.max(es, startFor(cal, endBound.get(k)!, n.dur))
    if (!Number.isFinite(es)) es = n.start
    const c = n.t.constraint
    const linkEs = es
    if (c?.date && (c.type === 'mso' || c.type === 'mfo')) {
      const fixed = c.type === 'mso' ? toDay(c.date) : startFor(cal, toDay(c.date), n.dur)
      if (hasPred.has(k) && normStart(cal, linkEs) > normStart(cal, fixed)) {
        issues.push(issue('warning', 'constraint_conflict',
          `'${n.t.name}' must ${c.type === 'mso' ? 'start' : 'finish'} on ${c.date} but its predecessors push it later`, n.t.id))
      }
      es = fixed
    }
    es = normStart(cal, es)
    ES.set(k, es)
    EF.set(k, endOf(cal, es, n.dur))
    if (c?.type === 'fnlt' && c.date && EF.get(k)! > toDay(c.date)) {
      issues.push(issue('warning', 'constraint_conflict',
        `'${n.t.name}' cannot finish by ${c.date}`, n.t.id))
    }
  }
  rollup()

  // ------------------------------------------------------------ backward pass
  const real = (k: string) => !nodes.get(k)!.t.isIdea && !ancestorsIdea(tree, k)
  const realLeaves = [...nodes.keys()].filter((k) => !isSum(k) && real(k))
  const finish = realLeaves.length ? Math.max(...realLeaves.map((k) => EF.get(k)!)) : null
  const LF = new Map<string, number>()
  const LS = new Map<string, number>()

  if (finish != null) {
    const finishBound = new Map<string, number>()
    const startCap = new Map<string, number>()
    const lower = (m: Map<string, number>, k: string, d: number) => m.set(k, Math.min(m.get(k) ?? Infinity, d))
    const collectBack = (k: string) => {
      for (const l of outgoing.get(k) ?? []) {
        const s = key(l.to)
        if (!real(s) || !LS.has(s)) continue
        const lag = Math.round(l.lagDays || 0)
        // Mirror of forwardBound: the successor's late start/finish less the lag.
        switch (l.type) {
          case 'SS': lower(startCap, k, shift(cal, LS.get(s)!, -lag)); break
          case 'FF': lower(finishBound, k, shift(cal, LF.get(s)!, -lag)); break
          case 'SF': lower(startCap, k, shift(cal, LF.get(s)!, -lag)); break
          default: lower(finishBound, k, shift(cal, LS.get(s)!, -lag))
        }
      }
      const c = nodes.get(k)!.t.constraint
      if (c?.date && (c.type === 'fnlt' || c.type === 'mfo')) lower(finishBound, k, toDay(c.date))
      if (c?.date && c.type === 'mso') lower(startCap, k, toDay(c.date))
      const parent = tree.parentOf.get(k)
      if (parent != null) {
        if (finishBound.has(parent)) lower(finishBound, k, finishBound.get(parent)!)
        if (startCap.has(parent)) lower(startCap, k, startCap.get(parent)!)
      }
    }
    // Reverse event order: out(X) of a summary collects its outgoing bounds
    // before its children (which inherit), leaves compute LS/LF.
    for (const ev of [...order].reverse()) {
      const [kind, k] = ev.split(/:(.*)/s) as [string, string]
      if (!real(k)) continue
      if (kind === 'in') {
        // Summary late dates from its leaves.
        const ls = leaves(tree, k).map((l) => key(l.id)).filter((x) => LS.has(x))
        if (ls.length) {
          LS.set(k, Math.min(...ls.map((x) => LS.get(x)!)))
          LF.set(k, Math.max(...ls.map((x) => LF.get(x)!)))
        }
        continue
      }
      // Summary: its outgoing links and finish constraints bind all its leaves.
      if (kind === 'out') { collectBack(k); continue }
      collectBack(k)
      const n = nodes.get(k)!
      let lf = Math.min(finish, finishBound.get(k) ?? Infinity)
      if (startCap.has(k)) lf = Math.min(lf, endOf(cal, startCap.get(k)!, n.dur))
      LF.set(k, lf)
      LS.set(k, startFor(cal, lf, n.dur))
    }
  }

  // ------------------------------------------------------------ slack
  const critical: GanttId[] = []
  const total = new Map<string, number | null>()
  const free = new Map<string, number | null>()
  for (const k of nodes.keys()) {
    if (isSum(k) || !real(k) || !LS.has(k)) { total.set(k, null); free.set(k, null); continue }
    const ts = diff(cal, ES.get(k)!, LS.get(k)!)
    total.set(k, ts)
    let fs = Infinity
    const succ = (outgoing.get(k) ?? []).filter((l) => real(key(l.to)))
    // Links out of an ancestor summary also count for its leaves.
    for (const a of ancestorsList(tree, k)) succ.push(...(outgoing.get(a) ?? []).filter((l) => real(key(l.to))))
    for (const l of succ) {
      const s = key(l.to)
      const lag = Math.round(l.lagDays || 0)
      const b = forwardBound(cal, l.type, lag, ES.get(k)!, EF.get(k)!)
      const target = b.side === 'start' ? ES.get(s)! : EF.get(s)!
      fs = Math.min(fs, diff(cal, b.day, target))
    }
    if (!succ.length) fs = diff(cal, EF.get(k)!, finish!)
    free.set(k, Math.min(fs, ts))
  }
  for (const t of tree.order) {
    const k = key(t.id)
    if (!isSum(k) || !real(k)) continue
    const vals = leaves(tree, k).map((l) => total.get(key(l.id))).filter((v): v is number => v != null)
    total.set(k, vals.length ? Math.min(...vals) : null)
  }
  for (const t of tree.order) {
    const k = key(t.id)
    const ts = total.get(k)
    const crit = ts != null && ts <= 0 && real(k)
    if (crit) critical.push(t.id)
    byId.set(t.id, {
      id: t.id,
      start: toIso(ES.get(k)!),
      end: toIso(EF.get(k)!),
      lateStart: LS.has(k) ? toIso(LS.get(k)!) : null,
      lateEnd: LF.has(k) ? toIso(LF.get(k)!) : null,
      totalSlack: ts ?? null,
      freeSlack: free.get(k) ?? null,
      critical: crit,
      isSummary: isSum(k),
      progress: isSum(k) ? progressOf(k) : Math.max(0, Math.min(100, t.progress ?? 0)),
    })
  }
  const starts = [...nodes.keys()].filter((k) => !isSum(k) && real(k)).map((k) => ES.get(k)!)
  return {
    byId, cycle: [], criticalIds: critical,
    start: starts.length ? toIso(Math.min(...starts)) : null,
    finish: finish != null ? toIso(finish) : null,
    issues,
  }
}

function ancestorsList(tree: Tree, k: string): string[] {
  const out: string[] = []
  let cur = tree.parentOf.get(k) ?? null
  while (cur != null) { out.push(cur); cur = tree.parentOf.get(cur) ?? null }
  return out
}

function ancestorsIdea(tree: Tree, k: string): boolean {
  return ancestorsList(tree, k).some((a) => !!tree.byId.get(a)?.isIdea)
}

function finishOf(tasks: GanttTask[], tree: Tree, EF: Map<string, number>): string | null {
  const ends = tasks.filter((t) => !t.isIdea && !(tree.children.get(key(t.id))?.length)).map((t) => EF.get(key(t.id))!)
  return ends.length ? toIso(Math.max(...ends)) : null
}

/**
 * Auto-schedule: the date patches that move tasks to their early start
 * (only tasks whose start actually changes; summaries are never patched).
 */
export function autoSchedulePatches(
  tasks: GanttTask[], links: GanttLink[], calendar?: Partial<GanttCalendar> | null, opts: ScheduleOptions = {},
): { id: GanttId; patch: { start: string } }[] {
  const r = schedule(tasks, links, calendar, opts)
  if (r.cycle.length) return []
  return tasks
    .filter((t) => { const s = r.byId.get(t.id); return s && !s.isSummary && s.start !== t.start })
    .map((t) => ({ id: t.id, patch: { start: r.byId.get(t.id)!.start } }))
}
