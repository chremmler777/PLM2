/**
 * Regression (review 83438dc4, fuzz/undo_sim): task and link ids are
 * separate id spaces. Deleting task 5, undo, redo, undo, then renaming tasks
 * 1 and 2 used to rename tasks 3 and 4 on the server, because the link id map
 * ("re:1" -> 3 for link 1) was merged into the task id map.
 */
import { describe, expect, it } from 'vitest'
import { History } from '../../gantt/engine/history'
import { remapChangeSet, removeTasksChangeSet } from '../../gantt/engine/changes'
import type { ChangeSet, GanttId } from '../../gantt/engine/types'
import type { PlanChangeSet, PlanOut, TaskOut } from '../../../types/changePlan'
import { planToModel, toPlanChangeSet, translateIdMap } from './ecrAdapter'

/** A fake server with separate id sequences for tasks and links (like the backend). */
function fakeServer() {
  let taskSeq = 0, linkSeq = 0
  const tasks: TaskOut[] = []
  const links: { id: number; from_task_id: number; to_task_id: number; type: 'FS'; lag_days: number }[] = []
  const task = (): TaskOut => ({
    id: ++taskSeq, change_id: 1, plan: 'detailed', name: `T${taskSeq}`, lane: null, department_id: null, kind: 'work',
    is_idea: false, start_date: '2026-10-01', duration_days: 2, end_date: '2026-10-03', predecessors: [], sort_order: taskSeq,
    progress_pct: 0, actual_start: null, actual_finish: null, baseline_start: null, baseline_finish: null, notes: null,
  })
  for (let i = 0; i < 6; i++) tasks.push(task())
  const addLink = (f: number, t: number) => links.push({ id: ++linkSeq, from_task_id: f, to_task_id: t, type: 'FS', lag_days: 0 })
  addLink(4, 5); addLink(5, 6)
  const plan = (): PlanOut => ({
    plan: 'detailed', tasks: tasks.map((t) => ({ ...t })), links: links.map((l) => ({ ...l })), revision: 0, baseline_set: false,
    can_edit: true, can_edit_dates: true, progress_department_ids: [],
    summary: { start: null, finish: null, duration_days: 0, buffer_days: 0, critical_ids: [], ideas: 0 },
    validation: { errors: [], warnings: [] }, deadlines: [],
  })
  const apply = (pcs: PlanChangeSet) => {
    const idMap: Record<string, number> = {}, linkIdMap: Record<string, number> = {}
    const ref = (v: unknown): number => {
      if (typeof v === 'number') { if (!tasks.some((t) => t.id === v)) throw new Error(`404 block ${v}`); return v }
      const m = idMap[String(v)]
      if (m == null) throw new Error(`unknown ref ${String(v)}`)
      return m
    }
    for (const lid of pcs.links_delete) { const i = links.findIndex((l) => l.id === lid); if (i < 0) throw new Error(`404 link ${lid}`); links.splice(i, 1) }
    for (const d of pcs.tasks_delete) {
      const i = tasks.findIndex((t) => t.id === d); if (i < 0) throw new Error(`404 block ${d}`)
      tasks.splice(i, 1)
      for (let j = links.length - 1; j >= 0; j--) if (links[j].from_task_id === d || links[j].to_task_id === d) links.splice(j, 1)
    }
    for (const u of pcs.tasks_upsert) {
      if (typeof u.id === 'number') {
        const t = tasks.find((x) => x.id === u.id); if (!t) throw new Error(`404 block ${u.id}`)
        Object.assign(t, { ...u, id: t.id }); continue
      }
      const t = { ...task(), ...u, id: taskSeq, predecessors: [] } as TaskOut
      tasks.push(t); idMap[String(u.id)] = t.id
    }
    for (const l of pcs.links_upsert) {
      const nl = { id: ++linkSeq, from_task_id: ref(l.from_task_id), to_task_id: ref(l.to_task_id), type: 'FS' as const, lag_days: 0 }
      links.push(nl); if (l.id != null) linkIdMap[String(l.id)] = nl.id
    }
    return { idMap, linkIdMap }
  }
  return { tasks, links, plan, apply }
}

describe('task and link ids are separate id spaces', () => {
  it('delete, undo, redo, undo, then renaming tasks 1 and 2 renames tasks 1 and 2', () => {
    const srv = fakeServer()
    const h = new History()
    /** The queue's permanent map keeps temporary (string) ids only, tasks and links apart. */
    let tasksMap: Record<string, GanttId> = {}
    let linksMap: Record<string, GanttId> = {}
    const tempOnly = (m: Record<string, GanttId>) => Object.fromEntries(Object.entries(m).filter(([k]) => !/^-?\d+$/.test(k)))
    const model = () => { const m = planToModel(srv.plan()); return { tasks: m.tasks, links: m.links } }
    const send = (cs: ChangeSet) => {
      const c = remapChangeSet(cs, tasksMap, linksMap)
      const out = srv.apply(toPlanChangeSet(c, model()))
      const idMap = translateIdMap(out.idMap)
      const linkIdMap = translateIdMap(out.linkIdMap)
      tasksMap = { ...tasksMap, ...tempOnly(idMap) }
      linksMap = { ...linksMap, ...tempOnly(linkIdMap) }
      h.remap(idMap, linkIdMap)
    }
    const del = removeTasksChangeSet(model(), [5])!
    h.push(model(), del); send(del)
    let u = h.peekUndo()!; send(u.cs); h.confirmUndo(u.id)
    const r = h.peekRedo()!; send(r.cs); h.confirmRedo(r.id)
    u = h.peekUndo()!; send(u.cs); h.confirmUndo(u.id)
    // Task 5 came back twice (now 8); links 1 and 2 came back as 5 and 6.
    expect(srv.tasks.map((t) => t.id)).toEqual([1, 2, 3, 4, 6, 8])
    const ren: ChangeSet = { label: 'rename', updateTasks: [{ id: 1, patch: { name: 'RENAMED-1' } }, { id: 2, patch: { name: 'RENAMED-2' } }] }
    h.push(model(), ren)
    send(ren)
    expect(srv.tasks.find((t) => t.id === 1)!.name).toBe('RENAMED-1')
    expect(srv.tasks.find((t) => t.id === 2)!.name).toBe('RENAMED-2')
    expect(srv.tasks.find((t) => t.id === 3)!.name).toBe('T3')
    expect(srv.tasks.find((t) => t.id === 4)!.name).toBe('T4')
    // And the links point at the re-created task.
    expect(srv.links.map((l) => `${l.from_task_id}->${l.to_task_id}`).sort()).toEqual(['4->8', '8->6'])
  })

  it('translateIdMap keeps task and link maps apart', () => {
    expect(translateIdMap({ 're:5': 7 })).toEqual({ 5: 7 })
    expect(translateIdMap({ 're:1': 3 })).toEqual({ 1: 3 })
  })
})
