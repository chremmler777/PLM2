/* eslint-disable @typescript-eslint/no-explicit-any, @typescript-eslint/no-non-null-assertion */
/**
 * Undo/redo against a fake server (port of the review simulator fuzz2/sim.ts):
 * the real History, remap and ECR adapter; separate, overlapping task / link
 * id sequences; legacy predecessor links; injected refusals. The client
 * mirrors Gantt.tsx commit / undo / redo and useSaveQueue (tags with entry,
 * direction and sequence; a refused original change drops its queued saves).
 */
import { describe, expect, it } from 'vitest'
import { History, type SaveDirection } from '../../gantt/engine/history'
import { applyAll, isEmptyChangeSet, remapChangeSet, removeTasksChangeSet, unlinkChangeSet } from '../../gantt/engine/changes'
import { planToModel, toPlanChangeSet, translateIdMap } from './ecrAdapter'
import { serverMoves } from '../../gantt/useSaveQueue'

const dayN = (iso: string) => Math.round(Date.UTC(+iso.slice(0, 4), +iso.slice(5, 7) - 1, +iso.slice(8, 10)) / 86400000)
const isoN = (n: number) => new Date(n * 86400000).toISOString().slice(0, 10)

// ---------------- fake server: separate, overlapping id sequences; legacy predecessors
function makeServer(nTasks: number, linkPairs: [number, number][], legacyPairs: [number, number][] = [], linkSeqStart = 0, opts: { push?: boolean } = {}) {
  let taskSeq = 0, linkSeq = linkSeqStart
  const tasks: any[] = [], links: any[] = []
  for (let i = 0; i < nTasks; i++) { const id = ++taskSeq; tasks.push({ id, name: `T${id}`, start_date: '2026-10-01', duration_days: 2, kind: 'work', lane: null, department_id: null, is_idea: false, progress_pct: 0, sort_order: id, predecessors: [], parent_id: null, constraint_type: null, constraint_date: null, notes: null }) }
  for (const [f, t] of linkPairs) links.push({ id: ++linkSeq, from_task_id: f, to_task_id: t, type: 'FS', lag_days: 0 })
  for (const [f, t] of legacyPairs) tasks.find((x) => x.id === t).predecessors.push(f)
  let failNext = 0
  const plan = () => {
    const ids = new Set(tasks.map((t) => t.id))
    const linked = new Set(links.map((l) => [l.from_task_id, l.to_task_id].sort().join('-')))
    const legacy: any[] = []
    for (const t of tasks) for (const p of t.predecessors) {
      const pair = [p, t.id].sort().join('-')
      if (!ids.has(p) || linked.has(pair)) continue
      linked.add(pair); legacy.push({ id: null, from_task_id: p, to_task_id: t.id, type: 'FS', lag_days: 0, legacy: true })
    }
    const parents = new Set(tasks.map((t) => t.parent_id).filter((x) => x != null))
    return { tasks: tasks.map((t) => ({ ...t, is_summary: parents.has(t.id) })), links: [...links.map((l) => ({ ...l })), ...legacy] } as any
  }
  // Like the backend: push successors of what changed (later only), roll up summaries.
  const everSummary = new Set<number>()
  const isSummary = (id: number) => tasks.some((t) => t.parent_id === id)
  const allLinks = () => [...links.map((l) => [l.from_task_id, l.to_task_id]), ...tasks.flatMap((t) => t.predecessors.map((p: number) => [p, t.id]))]
    .filter(([f, t]) => tasks.some((x) => x.id === f) && tasks.some((x) => x.id === t) && !isSummary(f) && !isSummary(t)) as [number, number][]
  function pushFrom(sources: number[]): number[] {
    const L = allLinks()
    const was = new Map(tasks.map((t) => [t.id, t.start_date]))
    const down = new Set(sources); const st = [...sources]
    while (st.length) { const x = st.pop()!; for (const [f, t] of L) if (f === x && !down.has(t)) { down.add(t); st.push(t) } }
    for (let guard = 0; guard < 100; guard++) {
      let changed = false
      for (const [f, t] of L) {
        if (!down.has(t)) continue
        const pf = tasks.find((x) => x.id === f), pt = tasks.find((x) => x.id === t)
        const end = dayN(pf.start_date) + pf.duration_days
        if (dayN(pt.start_date) < end) { pt.start_date = isoN(end); changed = true }
      }
      if (!changed) break
    }
    return tasks.filter((t) => was.has(t.id) && was.get(t.id) !== t.start_date).map((t) => t.id)
  }
  function rollup() {
    for (let pass = 0; pass < 5; pass++) for (const t of tasks) {
      const kids = tasks.filter((k) => k.parent_id === t.id)
      if (!kids.length) continue
      everSummary.add(t.id)
      const s0 = Math.min(...kids.map((k) => dayN(k.start_date))), e0 = Math.max(...kids.map((k) => dayN(k.start_date) + k.duration_days))
      t.start_date = isoN(s0); t.duration_days = e0 - s0
    }
  }
  if (opts.push) { pushFrom(tasks.map((t) => t.id)); rollup() }
  function apply(pcs: any) {
    if (failNext > 0) { failNext--; throw new Error('409 refused (injected)') }
    const snapT = JSON.stringify(tasks), snapL = JSON.stringify(links)
    try {
      const id_map: Record<string, number> = {}, link_id_map: Record<string, number> = {}
      const tref = (v: any) => (typeof v === 'number' ? (tasks.some((t) => t.id === v) ? v : (() => { throw new Error(`404 task ${v}`) })()) : id_map[String(v)] ?? (() => { throw new Error(`unknown task ref ${v}`) })())
      for (const lid of pcs.links_delete) { const i = links.findIndex((l) => l.id === lid); if (i < 0) throw new Error(`404 link ${lid}`); links.splice(i, 1) }
      for (const d of pcs.tasks_delete) { const i = tasks.findIndex((t) => t.id === d); if (i < 0) throw new Error(`404 task ${d}`); tasks.splice(i, 1); for (let j = links.length - 1; j >= 0; j--) if (links[j].from_task_id === d || links[j].to_task_id === d) links.splice(j, 1) }
      for (const u of pcs.tasks_upsert) {
        if (typeof u.id === 'number') { const t = tasks.find((x) => x.id === u.id); if (!t) throw new Error(`404 task ${u.id}`); Object.assign(t, { ...u, id: t.id }); continue }
        const t = { ...tasks[0], sort_order: 999, ...u, id: ++taskSeq, predecessors: [] }; tasks.push(t); id_map[String(u.id)] = t.id
      }
      for (const u of pcs.tasks_upsert) { const t = tasks.find((x) => x.id === (typeof u.id === 'number' ? u.id : id_map[String(u.id)])); if (t.parent_id != null && typeof t.parent_id !== 'number') t.parent_id = tref(t.parent_id) }
      for (const u of pcs.tasks_upsert) {
        const id = typeof u.id === 'number' ? u.id : id_map[String(u.id)]
        if (opts.push && isSummary(id) && ('start_date' in u || 'duration_days' in u)) throw new Error(`400 dates of summary ${id}`)
      }
      for (const l of pcs.links_upsert) {
        if (typeof l.id === 'number') { const x = links.find((y) => y.id === l.id); if (!x) throw new Error(`404 link ${l.id}`); Object.assign(x, { ...l, ...(l.from_task_id != null ? { from_task_id: tref(l.from_task_id) } : {}), ...(l.to_task_id != null ? { to_task_id: tref(l.to_task_id) } : {}) }); continue }
        const nl = { id: ++linkSeq, from_task_id: tref(l.from_task_id), to_task_id: tref(l.to_task_id), type: l.type, lag_days: l.lag_days }
        if (links.some((y) => [y.from_task_id, y.to_task_id].sort().join() === [nl.from_task_id, nl.to_task_id].sort().join())) throw new Error('already linked')
        links.push(nl); link_id_map[String(l.id)] = nl.id
      }
      if (opts.push) {
        const src = [...pcs.tasks_upsert.map((u: any) => (typeof u.id === 'number' ? u.id : id_map[String(u.id)])),
          ...pcs.links_upsert.map((l: any) => tref(l.to_task_id ?? links.find((y) => y.id === l.id)?.to_task_id))]
        const own = src.filter((x: any) => typeof x === 'number')
        // moved_ids: what the server moved by itself (not what the request set).
        const moved_ids = pushFrom(own).filter((id) => !pcs.tasks_upsert.some((u: any) => u.id === id && 'start_date' in u))
        rollup()
        return { ...plan(), id_map, link_id_map, moved_ids }
      }
      return { ...plan(), id_map, link_id_map }
    } catch (e) { tasks.splice(0, tasks.length, ...JSON.parse(snapT)); links.splice(0, links.length, ...JSON.parse(snapL)); throw e }
  }
  const nameOf = (id: number) => tasks.find((t) => t.id === id)?.name ?? `?${id}`
  const state = () => {
    const p = plan()
    return {
      tasks: p.tasks.map((t: any) => t.name).sort().join(' '),
      links: p.links.map((l: any) => `${nameOf(l.from_task_id)}>${nameOf(l.to_task_id)}${l.legacy ? '(L)' : ''}`).sort().join(' '),
      // Leaf dates (a task that once was a summary keeps its rolled-up dates, as on the real server).
      ...(opts.push ? { dates: p.tasks.filter((t: any) => !everSummary.has(t.id)).map((t: any) => `${t.name}@${t.start_date}+${t.duration_days}`).sort().join(' ') } : {}),
    }
  }
  /** Re-run the initial push and roll-up (after a test set parents by hand). */
  const init = () => { pushFrom(tasks.map((t) => t.id)); rollup() }
  return { plan, apply, state, fail: (n = 1) => { failNext = n }, tasks, links, everSummary, init }
}


function makeClient(srv: ReturnType<typeof makeServer>, opts: { movedIds?: boolean } = {}) {
  const h = new History()
  let idMapRef: Record<string, any> = {}, linkMapRef: Record<string, any> = {}
  const tempOnly = (m: Record<string, any>) => Object.fromEntries(Object.entries(m).filter(([k]) => !/^-?\d+$/.test(k)))
  const remapKnown = (cs: any) => (Object.keys(idMapRef).length || Object.keys(linkMapRef).length ? remapChangeSet(cs, idMapRef, linkMapRef) : cs)
  type Item = { seq: number; cs: any; status: string; tag?: { entry: number; dir: SaveDirection } }
  let items: Item[] = [], seq = 0
  const log: string[] = []
  // Like GanttPlanner: the client knows the server's answers to its own saves
  // (a refetch after a refusal); another window's edit is not seen until then.
  let known = srv.plan()
  const base = () => { const m = planToModel(known); return { tasks: m.tasks, links: m.links } }
  const display = () => applyAll(base(), items.filter((i) => i.status !== 'settled').map((i) => i.cs))
  const onChange = (cs: any) => {
    const before = base()
    const body = toPlanChangeSet(cs, before)
    log.push(JSON.stringify(body))
    if (!body.tasks_upsert.length && !body.tasks_delete.length && !body.links_upsert.length && !body.links_delete.length) return {}
    let out: any
    try { out = srv.apply(body) } catch (e) { known = srv.plan(); throw e }
    known = out
    const m = planToModel(out)
    return {
      idMap: translateIdMap(out.id_map), linkIdMap: translateIdMap(out.link_id_map), server: { tasks: m.tasks, links: m.links }, serverBefore: before,
      ...(opts.movedIds !== false && out.moved_ids ? { serverMoved: out.moved_ids } : {}),
    }
  }
  const pumpOne = () => {
    const next = items.find((i) => i.status === 'queued'); if (!next) return false
    const cs = remapKnown(next.cs)
    if (isEmptyChangeSet(cs)) {
      items = items.filter((i) => i.seq !== next.seq)
      if (next.tag) h.settled(next.tag.entry, next.seq)
      return true
    }
    try {
      const res: any = onChange(cs)
      const idMap = res?.idMap ?? {}, linkIdMap = res?.linkIdMap ?? {}
      const any = Object.keys(idMap).length > 0 || Object.keys(linkIdMap).length > 0
      if (any) { idMapRef = { ...idMapRef, ...tempOnly(idMap) }; linkMapRef = { ...linkMapRef, ...tempOnly(linkIdMap) }; h.remap(idMap, linkIdMap) }
      // As useSaveQueue + Gantt: what the server moved on its own joins the step.
      if (res?.server && next.tag?.dir === 'do') {
        const moves = serverMoves(res.serverBefore, any ? remapChangeSet(cs, idMap, linkIdMap) : cs, res.server, res.serverMoved)
        if (moves.length) {
          h.extend(next.tag.entry,
            { updateTasks: moves.map((mv) => ({ id: mv.id, patch: { ...mv.to } })) },
            { updateTasks: moves.map((mv) => ({ id: mv.id, patch: { ...mv.from } })) })
        }
      }
      items = items.map((i) => (i.seq === next.seq ? { ...i, status: 'settled' } : any && i.status === 'queued' ? { ...i, cs: remapChangeSet(i.cs, idMap, linkIdMap) } : i))
      if (next.tag) h.settled(next.tag.entry, next.seq)
    } catch (e: any) {
      log.push('ERR ' + e.message)
      items = items.filter((i) => i.seq !== next.seq)
      if (next.tag && h.refused(next.tag.entry, next.seq, next.tag.dir)) {
        const gone = next.tag.entry
        items = items.filter((i) => i.status !== 'queued' || i.tag?.entry !== gone)
      }
    }
    items = items.filter((i) => i.status !== 'settled')
    return true
  }
  const drain = () => { while (pumpOne()); }
  const enqueue = (cs: any, tag?: Item['tag']) => { const s = ++seq; items.push({ seq: s, cs: remapKnown(cs), status: 'queued', tag }); return s }
  const commit = (cs: any) => { const entry = h.push(display(), cs); const s = enqueue(cs, entry ? { entry, dir: 'do' } : undefined); if (entry) h.sent(entry, s); return entry }
  // As Gantt: undo / redo wait until the step's own save answered.
  const settle = (peek: { id: number } | null) => { while (peek && h.isPending(peek.id) && pumpOne()); }
  const undo = () => { settle(h.peekUndo()); const e = h.peekUndo(); if (!e) return null; const s = enqueue(e.cs, { entry: e.id, dir: 'undo' }); h.confirmUndo(e.id, s); return e.id }
  const redo = () => { settle(h.peekRedo()); const e = h.peekRedo(); if (!e) return null; const s = enqueue(e.cs, { entry: e.id, dir: 'redo' }); h.confirmRedo(e.id, s); return e.id }
  const key = (x: any) => String(x)
  return {
    h, commit, undo, redo, drain, display, log,
    byName: (n: string) => display().tasks.find((t: any) => t.name === n)!.id,
    linkBy: (a: string, b: string) => { const d = display(); const id = (n: string) => key(d.tasks.find((t: any) => t.name === n)?.id); return d.links.find((l: any) => key(l.from) === id(a) && key(l.to) === id(b)) },
  }
}
const expectState = (srv: any, tasks: string, links: string) => { const s = srv.state(); expect(s.tasks).toBe(tasks); expect(s.links).toBe(links) }
const ren = (ids: any[], names: string[]) => ({ label: 'rename', updateTasks: ids.map((id, i) => ({ id, patch: { name: names[i] } })) })
const errors = (c: any) => c.log.filter((x: string) => x.startsWith('ERR') && !x.includes('injected'))

describe('undo / redo against a server (review simulator)', () => {
  it('S0 delete, undo, redo, undo, rename by old ids', () => {
    const s = makeServer(6, [[4, 5], [5, 6]]); const c = makeClient(s)
    c.commit(removeTasksChangeSet(c.display(), [5])!); c.drain(); expectState(s, 'T1 T2 T3 T4 T6', '')
    c.undo(); c.drain(); expectState(s, 'T1 T2 T3 T4 T5 T6', 'T4>T5 T5>T6')
    c.redo(); c.drain(); expectState(s, 'T1 T2 T3 T4 T6', '')
    c.undo(); c.drain(); expectState(s, 'T1 T2 T3 T4 T5 T6', 'T4>T5 T5>T6')
    c.commit(ren([1, 2], ['R1', 'R2'])); c.drain(); expectState(s, 'R1 R2 T3 T4 T5 T6', 'T4>T5 T5>T6')
    expect(errors(c)).toEqual([])
  })

  it('S1 temp ids with colliding task / link numbers', () => {
    const s = makeServer(4, [[1, 2], [2, 3], [3, 4]]); const c = makeClient(s)
    c.commit({ label: 'add', addTasks: [{ id: 'tmp-a', name: 'NA', start: '2026-10-01', duration: 2 }], addLinks: [{ id: 'tmp-l1', from: 4, to: 'tmp-a', type: 'FS', lagDays: 0 }] })
    c.commit({ label: 'rename new', updateTasks: [{ id: 'tmp-a', patch: { name: 'NA2' } }], updateLinks: [{ id: 'tmp-l1', patch: { lagDays: 0, type: 'SS' } }] })
    c.drain(); expectState(s, 'NA2 T1 T2 T3 T4', 'T1>T2 T2>T3 T3>T4 T4>NA2')
    expect(s.links.find((l: any) => l.id === 4)?.type).toBe('SS')
    c.undo(); c.drain(); expectState(s, 'NA T1 T2 T3 T4', 'T1>T2 T2>T3 T3>T4 T4>NA')
    c.undo(); c.drain(); expectState(s, 'T1 T2 T3 T4', 'T1>T2 T2>T3 T3>T4')
    c.redo(); c.drain(); c.redo(); c.drain(); expectState(s, 'NA2 T1 T2 T3 T4', 'T1>T2 T2>T3 T3>T4 T4>NA2')
    c.commit({ label: 'unlink', removeLinks: [c.linkBy('T3', 'T4')!.id] }); c.drain(); expectState(s, 'NA2 T1 T2 T3 T4', 'T1>T2 T2>T3 T4>NA2')
    c.undo(); c.drain(); c.redo(); c.drain(); c.undo(); c.drain(); c.undo(); c.drain(); c.undo(); c.drain()
    expectState(s, 'T1 T2 T3 T4', 'T1>T2 T2>T3 T3>T4')
    c.commit(ren([1, 2, 3, 4], ['A', 'B', 'C', 'D'])); c.drain(); expectState(s, 'A B C D', 'A>B B>C C>D')
    expect(errors(c)).toEqual([])
  })

  it('S2 refused middle change and a refused undo that is retried', () => {
    const s = makeServer(5, [[1, 2], [2, 3]]); const c = makeClient(s)
    c.commit({ label: 'add', addTasks: [{ id: 'tmp-x', name: 'X', start: '2026-10-01', duration: 2 }], addLinks: [{ id: 'tmp-lx', from: 3, to: 'tmp-x', type: 'FS', lagDays: 0 }] })
    c.drain()
    s.fail(1)
    c.commit(ren([4], ['R4']))
    c.commit(removeTasksChangeSet(c.display(), [2])!)
    c.drain(); expectState(s, 'T1 T3 T4 T5 X', 'T3>X')
    s.fail(1); c.undo(); c.drain(); expectState(s, 'T1 T3 T4 T5 X', 'T3>X')
    c.undo(); c.drain(); expectState(s, 'T1 T2 T3 T4 T5 X', 'T1>T2 T2>T3 T3>X')
    c.undo(); c.drain(); expectState(s, 'T1 T2 T3 T4 T5', 'T1>T2 T2>T3')
    c.redo(); c.drain(); c.redo(); c.drain(); expectState(s, 'T1 T3 T4 T5 X', 'T3>X')
    c.undo(); c.drain(); expectState(s, 'T1 T2 T3 T4 T5 X', 'T1>T2 T2>T3 T3>X')
    c.commit(ren(['T1', 'T2', 'T3', 'T4', 'T5'].map(c.byName), ['A', 'B', 'C', 'D', 'E'])); c.drain()
    expectState(s, 'A B C D E X', 'A>B B>C C>X')
    expect(errors(c)).toEqual([])
  })

  it('S3 legacy links: delete, undo, redo, unlink', () => {
    const s = makeServer(4, [[1, 2]], [[3, 4], [2, 3]]); const c = makeClient(s)
    expectState(s, 'T1 T2 T3 T4', 'T1>T2 T2>T3(L) T3>T4(L)')
    expect(c.display().links.filter((l: any) => l.readOnly)).toHaveLength(2)
    expect(unlinkChangeSet(c.display(), [3])).toBeNull()
    c.commit(removeTasksChangeSet(c.display(), [3])!); c.drain(); expectState(s, 'T1 T2 T4', 'T1>T2')
    c.undo(); c.drain(); expectState(s, 'T1 T2 T3 T4', 'T1>T2 T2>T3 T3>T4')
    c.redo(); c.drain(); expectState(s, 'T1 T2 T4', 'T1>T2')
    c.undo(); c.drain(); expectState(s, 'T1 T2 T3 T4', 'T1>T2 T2>T3 T3>T4')
    c.commit({ label: 'unlink', removeLinks: [c.linkBy('T3', 'T4')!.id] }); c.drain(); expectState(s, 'T1 T2 T3 T4', 'T1>T2 T2>T3')
    c.undo(); c.drain(); expectState(s, 'T1 T2 T3 T4', 'T1>T2 T2>T3 T3>T4')
    expect(errors(c)).toEqual([])
  })

  it('S4 an undo refused while its redo is queued leaves the change applied and undoable', () => {
    const s = makeServer(3, []); const c = makeClient(s)
    c.commit(ren([1], ['R1'])); c.drain()
    s.fail(1); c.undo(); c.redo()
    c.drain(); expectState(s, 'R1 T2 T3', '')
    expect(c.h.stacks).toEqual({ past: [1], future: [], limbo: [] })
  })

  it('S5 a new change undone before its refusal arrives is forgotten', () => {
    const s = makeServer(3, []); const c = makeClient(s)
    s.fail(1); c.commit({ label: 'add', addTasks: [{ id: 'tmp-z', name: 'Z', start: '2026-10-01', duration: 2 }] }); c.undo()
    c.drain(); expectState(s, 'T1 T2 T3', '')
    expect(c.h.canUndo || c.h.canRedo).toBe(false)
  })

  it('S6 an undo refused after a new change cleared the redo stack returns to its place on the undo stack', () => {
    const s = makeServer(3, []); const c = makeClient(s)
    c.commit(ren([1], ['A'])); c.drain()
    c.commit(ren([2], ['B'])); c.drain()
    s.fail(1); c.undo()                // undo of B, will be refused
    c.commit(ren([3], ['C']))          // a new change clears the redo stack meanwhile
    c.drain(); expectState(s, 'A B C', '')
    expect(c.h.stacks.past).toEqual([1, 2, 3])
    c.undo(); c.drain(); c.undo(); c.drain(); c.undo(); c.drain()
    expectState(s, 'T1 T2 T3', '')
  })

  it('fuzz: 3000 traces; undo-all restores the plan without refusals, no stray errors with refusals', () => {
    let seed = 7; const rnd = (n: number) => { seed = (seed * 1103515245 + 12345) & 0x7fffffff; return seed % n }
    const bad: string[] = []
    let clean = 0
    for (let run = 0; run < 3000; run++) {
      const s = makeServer(6, [[1, 2], [2, 3], [4, 5]], [[5, 6], [3, 4]]); const c = makeClient(s)
      const start = JSON.stringify(s.state()).replace(/\(L\)/g, ''); let tmp = 0
      for (let step = 0; step < 12; step++) {
        const d = c.display(); const op = rnd(6)
        if (rnd(5) === 0) s.fail(1)
        if (op === 0 && d.tasks.length > 2) c.commit(removeTasksChangeSet(d, [d.tasks[rnd(d.tasks.length)].id])!)
        else if (op === 1) { const L = d.links.filter((l: any) => !l.readOnly); if (L.length) c.commit({ label: 'unlink', removeLinks: [L[rnd(L.length)].id] }) }
        else if (op === 2) { const f = d.tasks[rnd(d.tasks.length)]; const id = `tmp-t${++tmp}`; c.commit({ label: 'add', addTasks: [{ id, name: `N${run}_${tmp}`, start: '2026-10-01', duration: 1 }], addLinks: [{ id: `tmp-l${tmp}`, from: f.id, to: id, type: 'FS', lagDays: 0 }] }) }
        else if (op === 3) { const t = d.tasks[rnd(d.tasks.length)]; c.commit(ren([t.id], [`${t.name}'`])) }
        else if (op === 4) c.undo()
        else c.redo()
        if (rnd(3) === 0) c.drain()
      }
      c.drain()
      let u = 0
      while (c.h.canUndo && u < 50) { c.undo(); c.drain(); u++ }
      const back = JSON.stringify(s.state()).replace(/\(L\)/g, '')
      const injected = c.log.some((x) => x.includes('injected'))
      if (!injected) clean++
      if (errors(c).length || (!injected && back !== start)) bad.push(`run ${run}: ${errors(c).join('; ')} ${back !== start ? 'not restored' : ''}`)
    }
    expect(bad.slice(0, 5)).toEqual([])
    expect(clean).toBeGreaterThan(200)
  })

  it('S7 a move inside an outline: the server pushes a successor and rolls up the summary; undo / redo never patch the summary', () => {
    const s = makeServer(4, [[2, 3]], [], 0, { push: true }); const c = makeClient(s)
    s.tasks.find((t: any) => t.id === 2).parent_id = 1; s.tasks.find((t: any) => t.id === 3).parent_id = 1; s.init()
    const start = JSON.stringify(s.state())
    c.commit({ label: 'longer', updateTasks: [{ id: 2, patch: { duration: 5 } }] }); c.drain()
    expect(s.tasks.find((t: any) => t.id === 3).start_date).toBe('2026-10-06')
    c.undo(); c.drain()
    expect(JSON.stringify(s.state())).toBe(start)
    c.redo(); c.drain()
    expect(s.tasks.find((t: any) => t.id === 3).start_date).toBe('2026-10-06')
    c.undo(); c.drain()
    expect(JSON.stringify(s.state())).toBe(start)
    expect(errors(c)).toEqual([])
    expect(c.log.some((x) => /"id":1,"start_date"/.test(x))).toBe(false)
  })

  for (const movedIds of [true, false]) {
    it(`S9 undo never reverts another window's edit (${movedIds ? 'moved_ids' : 'fallback: reachable, start only'})`, () => {
      const s = makeServer(4, [[1, 2], [2, 3], [3, 4]], [], 0, { push: true }); const c = makeClient(s, { movedIds })
      // another window lengthens D (T3); the server pushes E (T4); this client has not seen it
      s.apply({ tasks_upsert: [{ id: 3, duration_days: 5 }], tasks_delete: [], links_upsert: [], links_delete: [] })
      const other = JSON.stringify(s.state())
      c.commit({ label: 'longer B', updateTasks: [{ id: 2, patch: { duration: 4 } }] }); c.drain()
      c.undo(); c.drain()
      expect(JSON.stringify(s.state())).toBe(other)
      expect(s.tasks.find((t: any) => t.id === 3).duration_days).toBe(5)
      expect(errors(c)).toEqual([])
    })
  }

  it('S8 undo pressed before the step answered still undoes the server push', () => {
    const s = makeServer(3, [[1, 2], [2, 3]], [], 0, { push: true }); const c = makeClient(s)
    const start = JSON.stringify(s.state())
    c.commit({ label: 'later', updateTasks: [{ id: 1, patch: { start: '2026-10-04' } }] })
    c.undo(); c.drain()
    expect(JSON.stringify(s.state())).toBe(start)
    expect(errors(c)).toEqual([])
  })

  it('fuzz with a pushing, rolling-up server: 1500 traces, undo-all restores leaf dates, no summary patches', () => {
    // High bits: the low bits of this generator repeat quickly.
    let seed = 11; const rnd = (n: number) => { seed = (seed * 1103515245 + 12345) & 0x7fffffff; return (seed >>> 12) % n }
    const bad: string[] = []
    let clean = 0
    for (let run = 0; run < 1500; run++) {
      const s = makeServer(7, [[1, 2], [2, 3], [4, 5]], [[5, 6]], 0, { push: true }); const c = makeClient(s, { movedIds: run % 2 === 0 })
      s.tasks.find((t: any) => t.id === 3).parent_id = 7; s.tasks.find((t: any) => t.id === 4).parent_id = 7; s.init()
      const start = JSON.stringify(s.state()).replace(/\(L\)/g, ''); let tmp = 0
      for (let step = 0; step < 12; step++) {
        const d = c.display(); const op = rnd(7)
        const parents = new Set(d.tasks.map((t: any) => String(t.parentId ?? '')))
        // Leaves here and on the server (a refused delete can leave a summary the optimistic view shows as a leaf).
        const leaves = d.tasks.filter((t: any) => !parents.has(String(t.id)) && !s.tasks.some((x: any) => String(x.parent_id) === String(t.id)))
        if (rnd(24) === 0) s.fail(1)
        if (op === 0 && leaves.length > 3) c.commit(removeTasksChangeSet(d, [leaves[rnd(leaves.length)].id])!)
        else if (op === 1) { const t = leaves[rnd(leaves.length)]; c.commit({ label: 'move', updateTasks: [{ id: t.id, patch: { start: isoN(dayN(t.start) + 1 + rnd(4)) } }] }) }
        else if (op === 2) { const t = leaves[rnd(leaves.length)]; c.commit({ label: 'dur', updateTasks: [{ id: t.id, patch: { duration: 1 + rnd(5) } }] }) }
        else if (op === 3) { const f = leaves[rnd(leaves.length)]; const id = `tmp-t${++tmp}`; c.commit({ label: 'add', addTasks: [{ id, name: `N${run}_${tmp}`, start: '2026-10-01', duration: 1 }], addLinks: [{ id: `tmp-l${tmp}`, from: f.id, to: id, type: 'FS', lagDays: 0 }] }) }
        else if (op === 4) c.undo()
        else if (op === 5) c.redo()
        else { const t = d.tasks[rnd(d.tasks.length)]; c.commit(ren([t.id], [`${t.name}'`])) }
        if (rnd(3) === 0) c.drain()
      }
      c.drain()
      let u = 0
      while (c.h.canUndo && u < 50) { c.undo(); c.drain(); u++ }
      const back = JSON.stringify(s.state()).replace(/\(L\)/g, '')
      const injected = c.log.some((x) => x.includes('injected'))
      if (!injected) clean++
      if (errors(c).length || (!injected && back !== start)) bad.push(`run ${run}: ${errors(c).join('; ')} ${back !== start ? `not restored ${start} -> ${back}` : ''}`)
    }
    expect(bad.length + ' ' + bad.slice(0, 3).join('\n')).toBe('0 ')
    expect(clean).toBeGreaterThan(500)
    expect(clean).toBeLessThan(1500)
  })
})
