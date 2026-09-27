/**
 * Critical path scheduling (spec 2026-09-25 §11). A port of the backend's
 * `plan_engine.compute` so both engines give the same answers; both are
 * checked against `backend/tests/data/gantt_vectors.json`.
 *
 * Everything runs in index space: `cal.idx(day)` counts days (calendar
 * mode) or working days (working mode). A task starting at index s with
 * duration d ends at index s + d; dates come back through `cal.dateAt`.
 *
 * Rules
 * - Links P -> S with lag L (negative = lead):
 *     FS: S.es >= P.ef + L    SS: S.es >= P.es + L
 *     FF: S.ef >= P.ef + L    SF: S.ef >= P.es + L
 * - Summary task rule (spec §11): a link INTO a summary (FS, SS) bounds the
 *   start of every leaf below it; FF/SF into a summary are refused and not
 *   scheduled. A link FROM a summary reads its rolled-up dates (SS/SF the
 *   earliest start, FS/FF the latest end). A link between a summary and its
 *   own descendant is ignored (warning `summary_link`, not a cycle).
 *   Constraints: snet and fnlt on a summary apply to every leaf below it;
 *   mso / mfo on a summary are refused and not scheduled.
 * - Forward pass, leaf ES = its own start ("push", default) or the project
 *   start (pull), raised by snet dates (own and summaries'), the start gate
 *   of its summaries and every incoming link. mso / mfo pin the start and
 *   win over everything.
 * - Idea tasks are scheduled forward but left out of the project finish, the
 *   backward pass, slack and the critical path.
 * - Backward pass over non-idea leaves from the project finish (max EF of
 *   non-idea leaves). A summary's finish bound caps every leaf below it; its
 *   start bound caps only the leaves that define its start. fnlt dates cap
 *   the late finish; a pinned task's late finish is its early finish.
 * - Total slack = LF - EF (may be negative); critical = total slack <= 0.
 *   Free slack = the smallest gap to the successors' bounds (links out of
 *   the task and out of its summaries), else project finish - EF; never
 *   above total slack.
 * - Summaries roll up: start / end from their children, total and free
 *   slack = min of the children, critical when a child is, progress weighted
 *   by the children's spans (plain mean when every span is 0).
 * - A cycle stops the pass: tasks keep their own dates, slack is null.
 */
import { endFromIdx, makeCal, toDay, toIso, type Cal } from './calendar'
import { applyChangeSet } from './changes'
import { buildTree, key, type Tree } from './tree'
import type {
  ChangeSet, GanttCalendar, GanttId, GanttLink, GanttTask, Issue, ScheduleOptions, ScheduleResult, ScheduledTask,
} from './types'

export const PIN_CONSTRAINTS = ['mso', 'mfo'] as const
export const FINISH_TARGET_LINKS = ['FF', 'SF'] as const

/**
 * Graph nodes: L a leaf; for a summary G its start gate (the start bound
 * every leaf below it gets), PS its start point (the earliest child start,
 * read by SS/SF out of it) and PF its finish point (the latest child end,
 * read by FS/FF out of it).
 */
type NodeKind = 'G' | 'L' | 'PS' | 'PF'
type NodeKey = string
const nk = (kind: NodeKind, k: string): NodeKey => `${kind}|${k}`
const parse = (n: NodeKey): [NodeKind, string] => {
  const i = n.indexOf('|')
  return [n.slice(0, i) as NodeKind, n.slice(i + 1)]
}

interface ULink { from: string; to: string; type: GanttLink['type']; lag: number; id: GanttId }

export interface Graph {
  tree: Tree
  summaries: Set<string>
  anc: Map<string, string[]>
  leaves: string[]
  links: ULink[]
  /** Topological order of the nodes, null on a cycle. */
  order: [NodeKind, string][] | null
  /** Task keys stuck in a cycle (empty without one). */
  stuck: string[]
  /** Node successors ("L|k", "G|k", "PS|k", "PF|k"): links and structure edges. */
  succ: Map<string, string[]>
  /** Summary key -> the children its start point rolls up. */
  startKids: Map<string, string[]>
  /**
   * Summary key -> the children its dates roll up: those with committed
   * (non-idea) work below them; all children when there is none (an idea
   * does not stretch a summary).
   */
  realKids: Map<string, string[]>
}

/** Is this link used by the math? (backend `usable_link`): not out of an idea, not within a summary's own tree, not FF/SF into a summary. */
export function usableLink(
  from: string, to: string, type: GanttLink['type'], tree: Tree, anc: Map<string, string[]>, summaries: Set<string>,
  ideas: Set<string> = ideaKeys(tree, summaries),
): boolean {
  if (!tree.byId.has(from) || !tree.byId.has(to) || from === to) return false
  // An idea never drives committed work (it follows): the link stays stored and
  // shown, validation warns when the idea overlaps its successor.
  if (ideas.has(from)) return false
  if ((anc.get(to) ?? []).includes(from) || (anc.get(from) ?? []).includes(to)) return false
  if (summaries.has(to) && (type === 'FF' || type === 'SF')) return false
  return true
}

/**
 * Tasks that count as ideas for link driving (spec §11 Idea blocks): a leaf
 * by its flag; a summary exactly when no committed (non-idea) work lies
 * below it, whatever its own flag says.
 */
export function ideaKeys(tree: Tree, summaries: Set<string>): Set<string> {
  const real = new Map<string, boolean>()
  for (const t of [...tree.order].reverse()) {
    const k = key(t.id)
    if (!summaries.has(k)) { real.set(k, !t.isIdea); continue }
    real.set(k, (tree.children.get(k) ?? []).some((c) => real.get(key(c.id))))
  }
  return new Set([...real].filter(([, r]) => !r).map(([k]) => k))
}

export function buildGraph(tasks: GanttTask[], links: GanttLink[]): Graph {
  const tree = buildTree(tasks)
  const summaries = new Set([...tree.children.entries()].filter(([, c]) => c.length).map(([k]) => k))
  const anc = new Map<string, string[]>()
  for (const t of tasks) {
    const chain: string[] = []
    let p = tree.parentOf.get(key(t.id)) ?? null
    while (p != null) { chain.push(p); p = tree.parentOf.get(p) ?? null }
    anc.set(key(t.id), chain)
  }
  const leaves = tasks.map((t) => key(t.id)).filter((k) => !summaries.has(k))
  // One link per (from, to, type); a duplicate keeps the larger lag.
  const use = new Map<string, ULink>()
  const ideas = ideaKeys(tree, summaries)
  for (const l of links) {
    const type = (['FS', 'SS', 'FF', 'SF'] as const).includes(l.type) ? l.type : 'FS'
    const f = key(l.from), t = key(l.to)
    if (!usableLink(f, t, type, tree, anc, summaries, ideas)) continue
    const lag = Math.round(l.lagDays || 0)
    const k = `${f}>${t}>${type}`
    const cur = use.get(k)
    if (!cur || lag > cur.lag) use.set(k, { from: f, to: t, type, lag, id: l.id })
  }
  const ulinks = [...use.values()]
  const src = (k: string, type: GanttLink['type']): NodeKey =>
    nk(!summaries.has(k) ? 'L' : type === 'SS' || type === 'SF' ? 'PS' : 'PF', k)
  const dst = (k: string): NodeKey => nk(summaries.has(k) ? 'G' : 'L', k)
  const startNode = (k: string): NodeKey => nk(summaries.has(k) ? 'PS' : 'L', k)
  const pos = new Map(tasks.map((t, i) => [key(t.id), i]))
  const rank: Record<NodeKind, number> = { G: 0, L: 1, PS: 2, PF: 3 }
  const nodes: [NodeKind, string][] = []
  for (const t of tasks) {
    const k = key(t.id)
    if (summaries.has(k)) nodes.push(['G', k], ['PS', k], ['PF', k])
    else nodes.push(['L', k])
  }
  const succ = new Map<NodeKey, NodeKey[]>()
  const edge = (a: NodeKey, b: NodeKey) => {
    if (!succ.has(a)) succ.set(a, [])
    succ.get(a)!.push(b)
  }
  for (const [p, cs] of tree.children) {
    for (const c of cs) {
      const ck = key(c.id)
      if (summaries.has(ck)) { edge(nk('G', p), nk('G', ck)); edge(nk('PF', ck), nk('PF', p)) }
      else { edge(nk('G', p), nk('L', ck)); edge(nk('L', ck), nk('PF', p)) }
    }
  }
  for (const l of ulinks) edge(src(l.from, l.type), dst(l.to))
  const reach = (start: NodeKey): Set<NodeKey> => {
    const seen = new Set([start])
    const stack = [start]
    while (stack.length) {
      for (const m of succ.get(stack.pop()!) ?? []) if (!seen.has(m)) { seen.add(m); stack.push(m) }
    }
    return seen
  }
  // Start points roll up their children, deepest summary first, leaving out a
  // child the start point itself drives (it starts after it, so it cannot be
  // the earliest; leaving it out avoids a false cycle).
  const hasReal = new Map<string, boolean>()
  const realKids = new Map<string, string[]>()
  for (const t of [...tree.order].reverse()) {
    const k = key(t.id)
    if (!summaries.has(k)) { hasReal.set(k, !t.isIdea); continue }
    const ks = (tree.children.get(k) ?? []).map((c) => key(c.id))
    const real = ks.filter((c) => hasReal.get(c))
    hasReal.set(k, real.length > 0)
    realKids.set(k, real.length ? real : ks)
  }
  const startKids = new Map<string, string[]>()
  for (const t of [...tree.order].reverse()) {
    const sid = key(t.id)
    if (!summaries.has(sid)) continue
    const ks = realKids.get(sid)!
    const driven = succ.get(nk('PS', sid))?.length ? reach(nk('PS', sid)) : new Set<NodeKey>()
    const keep = ks.filter((c) => !driven.has(startNode(c)))
    const use = keep.length ? keep : ks
    startKids.set(sid, use)
    for (const c of use) edge(startNode(c), nk('PS', sid))
  }
  const indeg = new Map<NodeKey, number>(nodes.map(([kd, k]) => [nk(kd, k), 0]))
  succ.forEach((ms) => ms.forEach((m) => indeg.set(m, (indeg.get(m) ?? 0) + 1)))
  const byNode = new Map(nodes.map((n) => [nk(n[0], n[1]), n]))
  const cmp = (a: NodeKey, b: NodeKey) => {
    const na = byNode.get(a)!, nb = byNode.get(b)!
    return (pos.get(na[1])! - pos.get(nb[1])!) || (rank[na[0]] - rank[nb[0]])
  }
  const ready = [...indeg].filter(([, d]) => d === 0).map(([n]) => n).sort(cmp)
  const order: [NodeKind, string][] = []
  while (ready.length) {
    const n = ready.shift()!
    order.push(byNode.get(n)!)
    for (const m of succ.get(n) ?? []) {
      indeg.set(m, indeg.get(m)! - 1)
      if (indeg.get(m) === 0) {
        let i = 0
        while (i < ready.length && cmp(ready[i], m) <= 0) i++
        ready.splice(i, 0, m)
      }
    }
  }
  const ok = order.length === nodes.length
  const stuck = ok ? [] : [...new Set([...indeg].filter(([, d]) => d > 0).map(([n]) => byNode.get(n)![1]))]
  return { tree, summaries, anc, leaves, links: ulinks, order: ok ? order : null, stuck, succ, startKids, realKids }
}

/** Constraints per leaf: its own first, then snet / fnlt of its summaries (nearest first). */
export function leafConstraints(tasks: GanttTask[], g: Graph): Map<string, { type: string; date: number }[]> {
  const out = new Map<string, { type: string; date: number }[]>()
  for (const t of tasks) {
    const k = key(t.id)
    const cs: { type: string; date: number }[] = []
    ;[k, ...(g.anc.get(k) ?? [])].forEach((x, n) => {
      const c = g.tree.byId.get(x)?.constraint
      if (!c || c.type === 'asap' || !c.date) return
      if (n > 0 && (c.type === 'mso' || c.type === 'mfo')) return
      cs.push({ type: c.type, date: toDay(c.date) })
    })
    out.set(k, cs)
  }
  return out
}

/** A summary source has only the point this link reads (start or finish). */
function reqStart(l: ULink, pEs: number | undefined, pEf: number | undefined, dur: number): number {
  if (l.type === 'SS') return pEs! + l.lag
  if (l.type === 'FF') return pEf! + l.lag - dur
  if (l.type === 'SF') return pEs! + l.lag - dur
  return pEf! + l.lag
}

function pinOf(cons: { type: string; date: number }[], cal: Cal, dur: number): number | null {
  for (const c of cons) {
    if (c.type === 'mso') return cal.idx(c.date)
    if (c.type === 'mfo') return cal.idx(c.date) - dur
  }
  return null
}

const minN = (a: number | null, b: number | null) => (a == null ? b : b == null ? a : Math.min(a, b))
const issue = (level: Issue['level'], code: string, message: string, taskId: GanttId | null): Issue =>
  ({ level, code, message, taskId })

/** Task ids in a dependency loop (links used for scheduling), or []. */
export function findCycle(tasks: GanttTask[], links: GanttLink[]): GanttId[] {
  const self = links.find((l) => key(l.from) === key(l.to) && tasks.some((t) => key(t.id) === key(l.from)))
  if (self) return [self.from]
  const g = buildGraph(tasks, links)
  return g.stuck.map((k) => g.tree.byId.get(k)?.id ?? k)
}

/** Would adding from -> to (FS) close a loop? A self link counts as one. */
export function wouldCycle(tasks: GanttTask[], links: GanttLink[], from: GanttId, to: GanttId): boolean {
  if (key(from) === key(to)) return true
  return findCycle(tasks, [...links, { id: '__probe', from, to, type: 'FS', lagDays: 0 }]).length > 0
}

export interface ComputeOptions extends ScheduleOptions {
  /** false: keep every task at its own dates (analyse). Default true. */
  move?: boolean
  /** Only these leaf keys may move; every other task keeps its dates. */
  only?: Set<string>
}

export function schedule(
  tasks: GanttTask[], links: GanttLink[], calendar?: Partial<GanttCalendar> | null, opts: ComputeOptions = {},
): ScheduleResult {
  const cal = makeCal(calendar)
  const move = opts.move !== false
  const g = buildGraph(tasks, links)
  const { tree, summaries } = g
  const byKey = tree.byId
  const cons = leafConstraints(tasks, g)
  const inLinks = new Map<NodeKey, ULink[]>()
  const outLinks = new Map<string, ULink[]>()
  const dstNode = (k: string) => nk(summaries.has(k) ? 'G' : 'L', k)
  for (const l of g.links) {
    const d = dstNode(l.to)
    if (!inLinks.has(d)) inLinks.set(d, [])
    inLinks.get(d)!.push(l)
    if (!outLinks.has(l.from)) outLinks.set(l.from, [])
    outLinks.get(l.from)!.push(l)
  }
  const dur = (k: string) => Math.max(0, Math.round(byKey.get(k)!.duration || 0))
  const own = (k: string) => cal.idx(toDay(byKey.get(k)!.start))
  const es = new Map<string, number>()
  const ef = new Map<string, number>()
  const gate = new Map<string, number | null>()
  const leafStarts = g.leaves.map(own)
  const projectStart = opts.projectStart ? cal.idx(toDay(opts.projectStart)) : (leafStarts.length ? Math.min(...leafStarts) : 0)
  const parentOf = (k: string) => tree.parentOf.get(k) ?? null
  const kids = (k: string) => (tree.children.get(k) ?? []).map((c) => key(c.id))
  const issues: Issue[] = []

  if (!g.order) {
    for (const k of g.leaves) { es.set(k, own(k)); ef.set(k, own(k) + dur(k)) }
    issues.push(issue('error', 'cycle', 'The dependencies form a loop', null))
  } else {
    for (const [kind, k] of g.order) {
      if (kind === 'G') {
        const p = parentOf(k)
        let b: number | null = p != null ? gate.get(p) ?? null : null
        for (const l of inLinks.get(nk('G', k)) ?? []) {
          const r = (l.type === 'SS' ? es.get(l.from)! : ef.get(l.from)!) + l.lag
          b = b == null ? r : Math.max(b, r)
        }
        gate.set(k, b)
      } else if (kind === 'L') {
        const d = dur(k)
        const o = own(k)
        const fixed = !move || (opts.only != null && !opts.only.has(k))
        const pin = fixed ? null : pinOf(cons.get(k)!, cal, d)
        let s: number
        if (fixed) s = o
        else if (pin != null) s = pin
        else {
          s = opts.pull ? projectStart : o
          for (const c of cons.get(k)!) if (c.type === 'snet') s = Math.max(s, cal.idx(c.date))
          const p = parentOf(k)
          const pg = p != null ? gate.get(p) ?? null : null
          if (pg != null) s = Math.max(s, pg)
          for (const l of inLinks.get(nk('L', k)) ?? []) s = Math.max(s, reqStart(l, es.get(l.from), ef.get(l.from), d))
        }
        es.set(k, s)
        ef.set(k, s + d)
      } else if (kind === 'PS') {
        es.set(k, Math.min(...g.startKids.get(k)!.map((c) => es.get(c)!)))
      } else {
        ef.set(k, Math.max(...g.realKids.get(k)!.map((c) => ef.get(c)!)))
      }
    }
  }

  const isIdea = (k: string) => !!byKey.get(k)!.isIdea
  const real = g.leaves.filter((k) => !isIdea(k))
  const total = new Map<string, number | null>()
  const free = new Map<string, number | null>()
  const crit = new Map<string, boolean>()
  const lfMap = new Map<string, number>()
  let projectEnd: number | null = null

  if (g.order && real.length) {
    const pe = Math.max(...real.map((k) => ef.get(k)!))
    projectEnd = pe
    const lg = new Map<string, number | null>()
    const lpf = new Map<string, number | null>()
    const lps = new Map<string, number | null>()
    // The two earliest non-idea starts under each summary: a start bound out
    // of a summary binds a leaf only when every OTHER leaf under it starts
    // after the bound (one of them keeps the summary start otherwise).
    const first2 = new Map<string, [number, string][]>()
    for (const k of real) {
      for (const a of g.anc.get(k) ?? []) {
        const cur = [...(first2.get(a) ?? []), [es.get(k)!, k] as [number, string]]
        cur.sort((x, y) => x[0] - y[0] || (x[1] < y[1] ? -1 : x[1] > y[1] ? 1 : 0))
        first2.set(a, cur.slice(0, 2))
      }
    }
    const othersStart = (a: string, k: string): number | null => {
      const rest = (first2.get(a) ?? []).filter((x) => x[1] !== k)
      return rest.length ? rest[0][0] : null
    }
    const late = (node: NodeKey, which: 'start' | 'finish'): number | null => {
      const [kind, x] = parse(node)
      if (kind === 'L') {
        if (!lfMap.has(x)) return null // an idea successor
        return which === 'start' ? lfMap.get(x)! - (ef.get(x)! - es.get(x)!) : lfMap.get(x)!
      }
      return which === 'start' ? lg.get(x) ?? null : null
    }
    const bounds = (src: string): [number | null, number | null] => {
      let fb: number | null = null, sb: number | null = null
      for (const l of outLinks.get(src) ?? []) {
        const vv = late(dstNode(l.to), l.type === 'FS' || l.type === 'SS' ? 'start' : 'finish')
        if (vv == null) continue
        if (l.type === 'FS' || l.type === 'FF') fb = minN(fb, vv - l.lag)
        else sb = minN(sb, vv - l.lag)
      }
      return [fb, sb]
    }
    for (const [kind, k] of [...g.order].reverse()) {
      if (kind === 'G') {
        let vv: number | null = null
        for (const c of kids(k)) vv = minN(vv, summaries.has(c) ? lg.get(c) ?? null : late(nk('L', c), 'start'))
        lg.set(k, vv)
      } else if (kind === 'PF') {
        const [fb] = bounds(k)
        const p = parentOf(k)
        lpf.set(k, p != null ? minN(fb, lpf.get(p) ?? null) : fb)
      } else if (kind === 'PS') {
        lps.set(k, bounds(k)[1])
      } else if (!isIdea(k)) {
        const d = ef.get(k)! - es.get(k)!
        let f = pe
        let [fb, sb] = bounds(k)
        const p = parentOf(k)
        if (p != null) fb = minN(fb, lpf.get(p) ?? null)
        for (const a of g.anc.get(k) ?? []) {
          const bnd = lps.get(a) ?? null
          const o = othersStart(a, k)
          if (bnd != null && (o == null || o > bnd)) sb = minN(sb, bnd)
        }
        if (fb != null) f = Math.min(f, fb)
        if (sb != null) f = Math.min(f, sb + d)
        for (const c of cons.get(k)!) if (c.type === 'fnlt') f = Math.min(f, cal.idx(c.date))
        if (pinOf(cons.get(k)!, cal, d) != null) f = Math.min(f, ef.get(k)!)
        lfMap.set(k, f)
      }
    }
    const early = (node: NodeKey, which: 'start' | 'finish'): number | null => {
      const [kind, x] = parse(node)
      if (kind === 'L') {
        if (isIdea(x)) return null
        return which === 'start' ? es.get(x)! : ef.get(x)!
      }
      return which === 'start' ? es.get(x)! : null
    }
    for (const k of real) {
      const tot = lfMap.get(k)! - ef.get(k)!
      const rooms: number[] = []
      for (const src of [k, ...(g.anc.get(k) ?? [])]) {
        const o = src === k ? null : othersStart(src, k)
        for (const l of outLinks.get(src) ?? []) {
          const vv = early(dstNode(l.to), l.type === 'FS' || l.type === 'SS' ? 'start' : 'finish')
          if (vv == null) continue
          if (l.type === 'FS' || l.type === 'FF') rooms.push(vv - l.lag - ef.get(k)!)
          else if (o == null || o > vv - l.lag) rooms.push(vv - l.lag - es.get(k)!)
        }
      }
      const fr = rooms.length ? Math.min(...rooms) : pe - ef.get(k)!
      total.set(k, tot)
      free.set(k, Math.min(fr, tot))
      crit.set(k, tot <= 0)
    }
  }

  const byId = new Map<GanttId, ScheduledTask>()
  const progress = new Map<string, number>()
  const out = new Map<string, ScheduledTask>()
  for (const k of g.leaves) {
    const t = byKey.get(k)!
    const s = es.get(k)!, e = ef.get(k)!
    const lf = lfMap.get(k)
    progress.set(k, Math.max(0, Math.min(100, Math.floor((t.progress ?? 0) + 0.5))))
    out.set(k, {
      id: t.id, start: toIso(cal.dateAt(s)), end: toIso(endFromIdx(cal, s, e)),
      lateStart: lf != null ? toIso(cal.dateAt(lf - (e - s))) : null,
      lateEnd: lf != null ? toIso(endFromIdx(cal, lf - (e - s), lf)) : null,
      totalSlack: total.get(k) ?? null, freeSlack: free.get(k) ?? null, critical: crit.get(k) ?? false,
      isSummary: false, progress: progress.get(k)!,
    })
  }
  // Summary rollup, children first. Spans come from the output rows (a
  // summary's rolled-up start/end index), never from the internal start
  // point; rounding is half-up (floor(x + 0.5)) like the backend.
  const rowIdx = new Map<string, [number, number]>()
  for (const k of g.leaves) rowIdx.set(k, [es.get(k)!, ef.get(k)!])
  const halfUp = (x: number) => Math.floor(x + 0.5)
  for (const t of [...tree.order].reverse()) {
    const k = key(t.id)
    if (!kids(k).length) continue
    const ks = g.realKids.get(k)!
    const rs = ks.map((c) => out.get(c)!)
    const idxs = ks.map((c) => rowIdx.get(c)!)
    rowIdx.set(k, [Math.min(...idxs.map((x) => x[0])), Math.max(...idxs.map((x) => x[1]))])
    const spans = idxs.map(([a, b]) => Math.max(b - a, 0))
    const weight = spans.reduce((a, b) => a + b, 0)
    const prog = weight > 0
      ? halfUp(rs.reduce((a, r, i) => a + r.progress * spans[i], 0) / weight)
      : halfUp(rs.reduce((a, r) => a + r.progress, 0) / rs.length)
    const slacks = rs.map((r) => r.totalSlack).filter((x): x is number => x != null)
    const frees = rs.map((r) => r.freeSlack).filter((x): x is number => x != null)
    out.set(k, {
      id: t.id, start: toIso(Math.min(...rs.map((r) => toDay(r.start)))), end: toIso(Math.max(...rs.map((r) => toDay(r.end)))),
      lateStart: null, lateEnd: null,
      totalSlack: slacks.length ? Math.min(...slacks) : null, freeSlack: frees.length ? Math.min(...frees) : null,
      critical: rs.some((r) => r.critical), isSummary: true, progress: prog,
    })
  }
  for (const t of tree.order) byId.set(t.id, out.get(key(t.id))!)
  const criticalIds = g.leaves.filter((k) => crit.get(k)).map((k) => byKey.get(k)!.id)
  const realStarts = real.map((k) => es.get(k)!)
  return {
    byId,
    cycle: g.order ? [] : g.stuck.map((k) => byKey.get(k)?.id ?? k),
    criticalIds,
    start: realStarts.length ? toIso(cal.dateAt(Math.min(...realStarts))) : null,
    finish: projectEnd != null ? toIso(endFromIdx(cal, Math.min(...realStarts), projectEnd))
      : (real.length ? toIso(Math.max(...real.map((k) => endFromIdx(cal, es.get(k)!, ef.get(k)!)))) : null),
    issues,
  }
}

/**
 * Auto-schedule: the date patches that move leaves to their early start
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

/**
 * Leaf key -> the nearest source whose move can push it (backend
 * `downstream`): successors, successors of every summary above it, every
 * leaf under a summary it links into. A summary source walks from its start
 * gate (every leaf below it) as well as from its start and finish points.
 * With `stop` (default) the walk stops at another source, which answers for
 * what lies behind it, and sources are not in the result; without it a
 * source another source reaches is in the result, caused by that one.
 * Between two sources the first in the given order wins.
 */
export function downstream(
  tasks: GanttTask[], links: GanttLink[], sources: GanttId[], opts: { stop?: boolean } = {},
): Map<string, string> {
  const stop = opts.stop ?? true
  const g = buildGraph(tasks, links)
  const srcs = new Set(sources.map(key))
  const cause = new Map<string, string>()
  for (const src of sources.map(key)) {
    if (!g.tree.byId.has(src)) continue
    const starts = g.summaries.has(src) ? [nk('G', src), nk('PS', src), nk('PF', src)] : [nk('L', src)]
    const seen = new Set(starts)
    const stack = [...starts]
    while (stack.length) {
      const n = stack.pop()!
      for (const m of g.succ.get(n) ?? []) {
        const [kind, x] = parse(m)
        if (seen.has(m) || (stop && kind === 'L' && srcs.has(x))) continue
        seen.add(m)
        stack.push(m)
        if (kind === 'L' && x !== src && !cause.has(x)) cause.set(x, src)
      }
    }
  }
  return cause
}

/**
 * What moving `sources` pushes along (backend `cascade`): only their
 * downstream leaves move, later and never earlier; a pinned task keeps its
 * date, a task with an actual start keeps its dates. Returns the start
 * patches and, per moved task, the source behind it.
 */
export function cascade(
  tasks: GanttTask[], links: GanttLink[], calendar: Partial<GanttCalendar> | null | undefined, sources: GanttId[],
): { id: GanttId; patch: { start: string }; cause: GanttId }[] {
  return push(tasks, links, calendar, sources)
}

/**
 * cascade() plus `also`: tasks that may move themselves (a new link or lag
 * into them, a changed constraint on them), each its own cause. Automatic
 * scheduling before the baseline and the deviation cascade after it are this
 * one forward pass (backend `push`).
 */
export function push(
  tasks: GanttTask[], links: GanttLink[], calendar: Partial<GanttCalendar> | null | undefined,
  sources: GanttId[], also: GanttId[] = [],
): { id: GanttId; patch: { start: string }; cause: GanttId }[] {
  const { result: r, movable, cause, tree } = pushSchedule(tasks, links, calendar, sources, also)
  const out: { id: GanttId; patch: { start: string }; cause: GanttId }[] = []
  for (const t of tasks) {
    const k = key(t.id)
    const st = r.byId.get(t.id)
    if (!movable.has(k) || !st || st.start === t.start) continue
    out.push({ id: t.id, patch: { start: st.start }, cause: tree.byId.get(cause.get(k)!)?.id ?? t.id })
  }
  return out
}

/** The schedule a push produces (backend `push` result), with what may move and why. */
export function pushSchedule(
  tasks: GanttTask[], links: GanttLink[], calendar: Partial<GanttCalendar> | null | undefined,
  sources: GanttId[], also: GanttId[] = [],
): { result: ScheduleResult; movable: Set<string>; cause: Map<string, string>; tree: Tree } {
  const srcKeys = new Set(sources.map(key))
  const g = buildGraph(tasks, links)
  const everyone = [...sources, ...also.filter((a) => !srcKeys.has(key(a)))]
  const cause = downstream(tasks, links, everyone)
  for (const a of also) if (!cause.has(key(a))) cause.set(key(a), key(a))
  // A moved block that another edited block (moved or `also`) drives moves
  // too when its link is broken: the user's date stands only as far as its
  // predecessors allow.
  for (const [s, by] of downstream(tasks, links, everyone, { stop: false })) {
    if (srcKeys.has(s) && !cause.has(s)) cause.set(s, by)
  }
  const alsoKeys = new Set(also.map(key))
  const cons = leafConstraints(tasks, g)
  // Pinned tasks (unless they move themselves) and tasks that already started stay; the walk goes on through them.
  const movable = new Set([...cause.keys()].filter((k) => !g.summaries.has(k) && !g.tree.byId.get(k)?.actualStart
    && (alsoKeys.has(k) || !(cons.get(k) ?? []).some((c) => c.type === 'mso' || c.type === 'mfo'))))
  return { result: schedule(tasks, links, calendar, { only: movable }), movable, cause, tree: g.tree }
}

/**
 * Automatic scheduling of one user action (MS Project "auto"): the successors
 * the changed tasks push along (later only; pinned and started tasks stay),
 * added to the ChangeSet so it stays one undoable step. The added moves are
 * listed in `meta.derived`: a server that pushes by itself gets only the
 * user's own changes (the adapter strips derived ones).
 */
export function autoPushChangeSet(
  model: { tasks: GanttTask[]; links: GanttLink[] }, cs: ChangeSet, calendar?: Partial<GanttCalendar> | null,
): { cs: ChangeSet; moved: { id: GanttId; from: string; to: string; cause: GanttId }[] } {
  const sources = new Set<string>()
  const also = new Set<string>()
  for (const u of cs.updateTasks ?? []) {
    if ('start' in u.patch || 'duration' in u.patch) sources.add(key(u.id))
    // A new parent or constraint may move the task itself (MS Project): under a
    // summary with a predecessor it jumps later.
    if ('constraint' in u.patch || 'parentId' in u.patch) also.add(key(u.id))
  }
  // A new task may move itself (its parent, constraint or links bind it).
  for (const t of cs.addTasks ?? []) also.add(key(t.id))
  for (const l of cs.addLinks ?? []) also.add(key(l.to))
  for (const u of cs.updateLinks ?? []) {
    const l = model.links.find((x) => key(x.id) === key(u.id))
    if (l) also.add(key(u.patch.to ?? l.to))
  }
  if (!sources.size && !also.size) return { cs, moved: [] }
  const after = applyChangeSet(model, cs)
  const known = new Set(after.tasks.map((t) => key(t.id)))
  const idOf = (k: string) => after.tasks.find((t) => key(t.id) === k)!.id
  const moves = push(after.tasks, after.links, calendar,
    [...sources].filter((k) => known.has(k)).map(idOf), [...also].filter((k) => known.has(k)).map(idOf))
  if (!moves.length) return { cs, moved: [] }
  const user = new Set((cs.updateTasks ?? []).filter((u) => 'start' in u.patch).map((u) => key(u.id)))
  const upd = [...(cs.updateTasks ?? [])]
  const added = [...(cs.addTasks ?? [])]
  const derived: GanttId[] = []
  const moved: { id: GanttId; from: string; to: string; cause: GanttId }[] = []
  const byKey = new Map(model.tasks.map((t) => [key(t.id), t]))
  for (const m of moves) {
    const k = key(m.id)
    const ai = added.findIndex((t) => key(t.id) === k)
    if (ai >= 0) { added[ai] = { ...added[ai], ...m.patch }; continue }
    const i = upd.findIndex((u) => key(u.id) === k)
    if (i >= 0) upd[i] = { id: upd[i].id, patch: { ...upd[i].patch, ...m.patch } }
    else upd.push({ id: m.id, patch: m.patch })
    if (!user.has(k)) {
      derived.push(m.id)
      moved.push({ id: m.id, from: byKey.get(k)?.start ?? m.patch.start, to: m.patch.start, cause: m.cause })
    }
  }
  return {
    cs: { ...cs, ...(cs.addTasks ? { addTasks: added } : {}), updateTasks: upd, meta: { ...(cs.meta ?? {}), derived } },
    moved,
  }
}
