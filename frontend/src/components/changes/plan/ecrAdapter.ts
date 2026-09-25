/**
 * The change plan <-> generic Gantt model (spec 2026-09-25 §9, §11).
 *
 * Two server generations:
 * - modern (migration 088, detected by `links` in PlanOut): typed links with
 *   lag, parents, constraints, a plan calendar and the atomic
 *   `POST /plan/changes` that takes a whole ChangeSet with temp ids;
 * - legacy: finish-to-start links only (the `predecessors` list), no parents,
 *   one REST call per edit.
 * Everything here is pure except `persistLegacy`, which runs the calls.
 */
import { key } from '../../gantt/engine/tree'
import type { GanttKindStyle } from '../../gantt/theme'
import { KIND_COLOR, KIND_LABEL } from './ganttMath'
import type { ChangeSet, GanttCalendar, GanttId, GanttLink, GanttTask } from '../../gantt/engine/types'
import type {
  BulkDateUpdate, LinkUpsert, PlanChangeSet, PlanKind, PlanOut, TaskCreate, TaskKind, TaskOut, TaskPatch, TaskUpsert,
} from '../../../types/changePlan'

export interface EcrSupport {
  /** Server has migration 088 (links table, parents, constraints, batch endpoint). */
  modern: boolean
}

export const supportOf = (p: PlanOut): EcrSupport => ({ modern: Array.isArray(p.links) })

export const DEFAULT_ECR_CALENDAR: GanttCalendar = { mode: 'calendar', workdays: [1, 2, 3, 4, 5], holidays: [] }

/** Display lane: the lane, else the owner department's name. */
export const ecrLane = (t: TaskOut) => t.lane?.trim() || t.department_name || null

export function taskToGantt(t: TaskOut): GanttTask {
  return {
    id: t.id,
    parentId: t.parent_id ?? null,
    name: t.name,
    start: t.start_date,
    duration: t.duration_days,
    kind: t.kind,
    lane: ecrLane(t),
    isIdea: t.is_idea,
    progress: t.progress_pct,
    baselineStart: t.baseline_start,
    baselineEnd: t.baseline_finish,
    actualStart: t.actual_start,
    actualEnd: t.actual_finish,
    constraint: t.constraint_type && t.constraint_type !== 'asap'
      ? { type: t.constraint_type, date: t.constraint_date ?? null } : null,
    notes: t.notes,
    meta: {
      department_id: t.department_id, department_name: t.department_name ?? null,
      own_lane: t.lane, sort_order: t.sort_order, source_position_id: t.source_position_id ?? null,
    },
  }
}

export interface EcrModel {
  tasks: GanttTask[]
  links: GanttLink[]
  calendar: GanttCalendar
  support: EcrSupport
}

export function planToModel(p: PlanOut): EcrModel {
  const support = supportOf(p)
  const sorted = [...p.tasks].sort((a, b) => a.sort_order - b.sort_order || a.id - b.id)
  const tasks = sorted.map(taskToGantt)
  const ids = new Set(sorted.map((t) => t.id))
  const links: GanttLink[] = support.modern
    ? (p.links ?? []).filter((l) => ids.has(l.from_task_id) && ids.has(l.to_task_id)).map((l) => ({
      id: l.id, from: l.from_task_id, to: l.to_task_id, type: l.type, lagDays: l.lag_days,
    }))
    : sorted.flatMap((t) => t.predecessors.filter((pid) => ids.has(pid)).map((pid) => ({
      id: `p${pid}-${t.id}`, from: pid, to: t.id, type: 'FS' as const, lagDays: 0,
    })))
  const cal = p.calendar
  const calendar: GanttCalendar = cal
    ? { mode: cal.mode === 'working' ? 'working' : 'calendar', workdays: cal.workdays?.length ? cal.workdays : [1, 2, 3, 4, 5], holidays: cal.holidays ?? [] }
    : DEFAULT_ECR_CALENDAR
  return { tasks, links, calendar, support }
}

// ------------------------------------------------------------------ patches

const isReal = (id: GanttId): id is number => typeof id === 'number'

/** Generic task patch -> ECR field patch (only the fields present). */
export function patchToEcr(patch: Partial<GanttTask>, before?: GanttTask): TaskPatch {
  const out: TaskPatch = {}
  if ('name' in patch && patch.name !== undefined) out.name = patch.name
  if ('start' in patch && patch.start !== undefined) out.start_date = patch.start
  if ('duration' in patch && patch.duration !== undefined) out.duration_days = patch.duration
  if ('kind' in patch && patch.kind !== undefined) out.kind = patch.kind as TaskKind
  if ('lane' in patch) {
    // The displayed lane falls back to the department name: write only a real change.
    const next = patch.lane?.trim() || null
    if (!before || next !== (before.lane ?? null)) out.lane = next
  }
  if ('isIdea' in patch && patch.isIdea !== undefined) out.is_idea = !!patch.isIdea
  if ('progress' in patch && patch.progress !== undefined) out.progress_pct = Math.round(patch.progress ?? 0)
  if ('notes' in patch) out.notes = patch.notes ?? null
  if ('actualStart' in patch) out.actual_start = patch.actualStart ?? null
  if ('actualEnd' in patch) out.actual_finish = patch.actualEnd ?? null
  if ('parentId' in patch) out.parent_id = patch.parentId == null ? null : (patch.parentId as number)
  if ('constraint' in patch) {
    const c = patch.constraint
    out.constraint_type = !c || c.type === 'asap' ? null : c.type
    out.constraint_date = !c || c.type === 'asap' ? null : c.date ?? null
  }
  if (patch.meta && 'department_id' in patch.meta) out.department_id = (patch.meta.department_id as number | null) ?? null
  return out
}

const DATE_KEYS: (keyof TaskPatch)[] = ['start_date', 'duration_days']

/** Does a ChangeSet move or resize any task? (The reason dialog after the baseline.) */
export function hasDateChanges(cs: ChangeSet): boolean {
  return (cs.updateTasks ?? []).some((u) => 'start' in u.patch || 'duration' in u.patch)
}

/**
 * sort_order values for a new display order: keep a task's value while the
 * sequence stays strictly increasing, give the others the next free value.
 */
export function sortOrders(order: GanttId[], current: Map<string, number>): Map<string, number> {
  const out = new Map<string, number>()
  let prev = -Infinity
  for (const id of order) {
    const cur = current.get(key(id))
    if (cur != null && cur > prev) { prev = cur; continue }
    prev = Number.isFinite(prev) ? prev + 1 : 1
    out.set(key(id), prev)
  }
  return out
}

/** Generic ChangeSet -> the batch body of `POST /plan/changes` (modern servers). */
export function toPlanChangeSet(cs: ChangeSet, before: GanttTask[]): PlanChangeSet {
  const byKey = new Map(before.map((t) => [key(t.id), t]))
  const ups = new Map<string, TaskUpsert>()
  const up = (id: GanttId): TaskUpsert => {
    const k = key(id)
    if (!ups.has(k)) ups.set(k, { id })
    return ups.get(k)!
  }
  for (const t of cs.addTasks ?? []) {
    const u = up(t.id)
    Object.assign(u, {
      name: t.name, kind: (t.kind as TaskKind) ?? 'work', lane: t.lane?.trim() || null,
      department_id: (t.meta?.department_id as number | null | undefined) ?? null,
      start_date: t.start, duration_days: t.duration, is_idea: !!t.isIdea, notes: t.notes ?? null,
      ...(t.parentId != null ? { parent_id: t.parentId } : {}),
      ...(t.constraint && t.constraint.type !== 'asap' ? { constraint_type: t.constraint.type, constraint_date: t.constraint.date ?? null } : {}),
      ...(t.progress ? { progress_pct: Math.round(t.progress) } : {}),
    })
  }
  for (const u of cs.updateTasks ?? []) {
    const p = patchToEcr(u.patch, byKey.get(key(u.id)))
    Object.assign(up(u.id), p)
  }
  if (cs.order?.length) {
    const current = new Map(before.map((t) => [key(t.id), Number(t.meta?.sort_order ?? 0)]))
    for (const t of cs.addTasks ?? []) current.delete(key(t.id))
    sortOrders(cs.order, current).forEach((v, k) => {
      const id = cs.order!.find((x) => key(x) === k)!
      up(id).sort_order = v
    })
  }
  const removed = new Set((cs.removeTasks ?? []).map(key))
  const tasks_upsert = [...ups.values()].filter((u) => !removed.has(key(u.id!)) && Object.keys(u).length > 1)
  const links_upsert: LinkUpsert[] = [
    ...(cs.addLinks ?? []).map((l) => ({ id: l.id, from_task_id: l.from, to_task_id: l.to, type: l.type, lag_days: l.lagDays })),
    ...(cs.updateLinks ?? []).filter((u) => isReal(u.id)).map((u) => ({
      id: u.id, ...(u.patch.type ? { type: u.patch.type } : {}), ...(u.patch.lagDays !== undefined ? { lag_days: u.patch.lagDays } : {}),
    })),
  ]
  return {
    tasks_upsert,
    tasks_delete: (cs.removeTasks ?? []).filter(isReal),
    links_upsert,
    links_delete: (cs.removeLinks ?? []).filter(isReal),
  }
}

// ------------------------------------------------------------------ legacy

export type LegacyCall =
  | { kind: 'create'; tempId: string; body: TaskCreate; predTemps: string[] }
  | { kind: 'patch'; id: GanttId; body: TaskPatch }
  | { kind: 'bulk'; updates: (Omit<BulkDateUpdate, 'id'> & { id: GanttId })[]; reason?: string }
  | { kind: 'delete'; id: number }

/**
 * Generic ChangeSet -> REST calls for servers without the batch endpoint.
 * Links are finish-to-start predecessors; lags, other types, parents and
 * constraints are refused (the UI does not offer them in legacy mode).
 */
export function toLegacyCalls(cs: ChangeSet, plan: PlanKind, before: GanttTask[], links: GanttLink[], reason?: string): LegacyCall[] {
  const bad = [...(cs.addLinks ?? []), ...(cs.updateLinks ?? []).map((u) => ({ ...u.patch }))]
    .find((l) => (l.type && l.type !== 'FS') || (l.lagDays ?? 0) !== 0)
  if (bad) throw new Error('This plan supports finish-to-start links without lag only')
  const byKey = new Map(before.map((t) => [key(t.id), t]))
  const calls: LegacyCall[] = []
  const removed = new Set((cs.removeTasks ?? []).map(key))

  // Final predecessor lists of every task whose incoming links change.
  const removedLinks = new Set((cs.removeLinks ?? []).map(key))
  const touched = new Set<string>()
  for (const l of cs.addLinks ?? []) touched.add(key(l.to))
  for (const l of links) if (removedLinks.has(key(l.id))) touched.add(key(l.to))
  const predsOf = (k: string): GanttId[] => [
    ...links.filter((l) => key(l.to) === k && !removedLinks.has(key(l.id))).map((l) => l.from),
    ...(cs.addLinks ?? []).filter((l) => key(l.to) === k).map((l) => l.from),
  ]

  for (const t of cs.addTasks ?? []) {
    const preds = predsOf(key(t.id))
    calls.push({
      kind: 'create', tempId: key(t.id), predTemps: preds.filter((x) => !isReal(x)).map(key),
      body: {
        plan, name: t.name, kind: (t.kind as TaskKind) ?? 'work', lane: t.lane?.trim() || null,
        department_id: (t.meta?.department_id as number | null | undefined) ?? null,
        start_date: t.start, duration_days: t.duration, is_idea: !!t.isIdea, notes: t.notes ?? null,
        predecessors: preds.filter(isReal),
      },
    })
    touched.delete(key(t.id))
  }
  const dates: (Omit<BulkDateUpdate, 'id'> & { id: GanttId })[] = []
  const fieldPatches = new Map<string, { id: GanttId; body: TaskPatch }>()
  const addField = (id: GanttId, body: TaskPatch) => {
    const k = key(id)
    const cur = fieldPatches.get(k) ?? { id, body: {} }
    Object.assign(cur.body, body)
    fieldPatches.set(k, cur)
  }
  for (const u of cs.updateTasks ?? []) {
    if (removed.has(key(u.id))) continue
    const p = patchToEcr(u.patch, byKey.get(key(u.id)))
    if ('parent_id' in p || 'constraint_type' in p) throw new Error('This plan does not support subtasks or constraints yet')
    const d: Omit<BulkDateUpdate, 'id'> & { id: GanttId } = { id: u.id }
    for (const k of DATE_KEYS) if (k in p) { (d as Record<string, unknown>)[k] = p[k]; delete p[k] }
    if (d.start_date !== undefined || d.duration_days !== undefined) dates.push(d)
    if (Object.keys(p).length) addField(u.id, p)
  }
  for (const k of touched) {
    if (removed.has(k)) continue
    const t = byKey.get(k)
    if (t) addField(t.id, { predecessors: predsOf(k).filter(isReal) })
  }
  if (cs.order?.length) {
    const current = new Map(before.map((t) => [key(t.id), Number(t.meta?.sort_order ?? 0)]))
    sortOrders(cs.order.filter((id) => isReal(id)), current).forEach((v, k) => {
      const t = byKey.get(k)
      if (t) addField(t.id, { sort_order: v })
    })
  }
  fieldPatches.forEach((f) => calls.push({ kind: 'patch', id: f.id, body: f.body }))
  if (dates.length) calls.push({ kind: 'bulk', updates: dates, ...(reason ? { reason } : {}) })
  for (const id of cs.removeTasks ?? []) if (isReal(id)) calls.push({ kind: 'delete', id })
  return calls
}

export interface LegacyApi {
  createTask: (body: TaskCreate) => Promise<PlanOut>
  patchTask: (id: number, body: TaskPatch) => Promise<PlanOut>
  bulkPatch: (updates: BulkDateUpdate[], reason?: string) => Promise<PlanOut>
  deleteTask: (id: number) => Promise<PlanOut>
}

/** Run legacy calls in order, resolving temp ids of created tasks. Returns the last plan and the id map. */
export async function persistLegacy(calls: LegacyCall[], api: LegacyApi, known: number[]): Promise<{ plan: PlanOut | null; idMap: Record<string, number> }> {
  const idMap: Record<string, number> = {}
  const seen = new Set(known)
  let plan: PlanOut | null = null
  const real = (id: GanttId): number => (typeof id === 'number' ? id : idMap[key(id)])
  for (const c of calls) {
    if (c.kind === 'create') {
      const body = { ...c.body, predecessors: [...(c.body.predecessors ?? []), ...c.predTemps.map((t) => idMap[t]).filter((x) => x != null)] }
      plan = await api.createTask(body)
      const created = plan.tasks.find((t) => !seen.has(t.id))
      if (created) { idMap[c.tempId] = created.id; seen.add(created.id) }
    } else if (c.kind === 'patch') {
      const id = real(c.id)
      if (id == null) continue
      const body = { ...c.body }
      if (body.predecessors) body.predecessors = body.predecessors.map((x) => real(x)).filter((x) => x != null)
      plan = await api.patchTask(id, body)
    } else if (c.kind === 'bulk') {
      const updates = c.updates.map((u) => ({ ...u, id: real(u.id) })).filter((u) => u.id != null) as BulkDateUpdate[]
      if (updates.length) plan = await api.bulkPatch(updates, c.reason)
    } else {
      plan = await api.deleteTask(c.id)
    }
  }
  return { plan, idMap }
}

// ------------------------------------------------------------------ look + saves

export const ECR_KINDS: Record<string, GanttKindStyle> = Object.fromEntries(
  (Object.keys(KIND_LABEL) as (keyof typeof KIND_LABEL)[]).map((k) => [k, {
    label: KIND_LABEL[k], color: KIND_COLOR[k].fill,
    ...(k === 'buffer' ? { pattern: 'hatch' as const } : {}), ...(k === 'milestone' ? { milestone: true } : {}),
  }]))

/** One save chain per change plan, shared by every planner instance on the page. */
const chains = new Map<string, Promise<unknown>>()
export function serialized<T>(chainKey: string, fn: () => Promise<T>): Promise<T> {
  const prev = chains.get(chainKey) ?? Promise.resolve()
  const next = prev.catch(() => undefined).then(fn)
  chains.set(chainKey, next)
  void next.finally(() => { if (chains.get(chainKey) === next) chains.delete(chainKey) }).catch(() => undefined)
  return next
}

