/**
 * ChangeSets: apply to a model, invert (for undo), remap temporary ids, and
 * the builders for the compound edits (delete with children and links,
 * duplicate, chain-link).
 */
import { tempId } from './notation'
import { buildTree, descendants, key, topLevelSelection } from './tree'
import type { ChangeSet, GanttId, GanttLink, GanttModel, GanttTask } from './types'

export function isEmptyChangeSet(cs: ChangeSet | null | undefined): boolean {
  if (!cs) return true
  return !cs.addTasks?.length && !cs.updateTasks?.length && !cs.removeTasks?.length
    && !cs.addLinks?.length && !cs.updateLinks?.length && !cs.removeLinks?.length && !cs.order?.length
}

/**
 * The model after the ChangeSet. Pure. Adding an id that already exists is
 * skipped (idempotent reconcile), links to removed tasks are dropped, and
 * `order` reorders the known tasks (unknown ids ignored, missing ones kept at
 * the end in their old order).
 */
export function applyChangeSet(model: GanttModel, cs: ChangeSet): GanttModel {
  let tasks = model.tasks
  let links = model.links
  if (cs.removeTasks?.length) {
    const gone = new Set(cs.removeTasks.map(key))
    tasks = tasks.filter((t) => !gone.has(key(t.id)))
  }
  if (cs.addTasks?.length) {
    const have = new Set(tasks.map((t) => key(t.id)))
    tasks = [...tasks, ...cs.addTasks.filter((t) => !have.has(key(t.id)))]
  }
  if (cs.updateTasks?.length) {
    const patches = new Map<string, Partial<GanttTask>>()
    for (const u of cs.updateTasks) patches.set(key(u.id), { ...(patches.get(key(u.id)) ?? {}), ...u.patch })
    tasks = tasks.map((t) => (patches.has(key(t.id)) ? { ...t, ...patches.get(key(t.id)), id: t.id } : t))
  }
  if (cs.order?.length) {
    const pos = new Map(cs.order.map((id, i) => [key(id), i]))
    const indexed = tasks.map((t, i) => ({ t, i }))
    indexed.sort((a, b) => (pos.get(key(a.t.id)) ?? 1e9 + a.i) - (pos.get(key(b.t.id)) ?? 1e9 + b.i))
    tasks = indexed.map((x) => x.t)
  }
  if (cs.removeLinks?.length) {
    const gone = new Set(cs.removeLinks.map(key))
    links = links.filter((l) => !gone.has(key(l.id)))
  }
  if (cs.addLinks?.length) {
    const have = new Set(links.map((l) => key(l.id)))
    links = [...links, ...cs.addLinks.filter((l) => !have.has(key(l.id)))]
  }
  if (cs.updateLinks?.length) {
    const patches = new Map(cs.updateLinks.map((u) => [key(u.id), u.patch]))
    links = links.map((l) => (patches.has(key(l.id)) ? { ...l, ...patches.get(key(l.id)), id: l.id } : l))
  }
  const ids = new Set(tasks.map((t) => key(t.id)))
  if (links.some((l) => !ids.has(key(l.from)) || !ids.has(key(l.to)))) {
    links = links.filter((l) => ids.has(key(l.from)) && ids.has(key(l.to)))
  }
  // A parent that was removed leaves its (not removed) children at top level.
  if (tasks.some((t) => t.parentId != null && !ids.has(key(t.parentId)))) {
    tasks = tasks.map((t) => (t.parentId != null && !ids.has(key(t.parentId)) ? { ...t, parentId: null } : t))
  }
  return { tasks, links }
}

/** Apply several ChangeSets in order. */
export const applyAll = (model: GanttModel, list: ChangeSet[]) => list.reduce(applyChangeSet, model)

/**
 * The ChangeSet that undoes `cs` when applied to `applyChangeSet(model, cs)`.
 * `model` is the state BEFORE cs.
 */
export function invertChangeSet(model: GanttModel, cs: ChangeSet): ChangeSet {
  const tById = new Map(model.tasks.map((t) => [key(t.id), t]))
  const lById = new Map(model.links.map((l) => [key(l.id), l]))
  const out: ChangeSet = { label: cs.label, meta: cs.meta }
  const after = applyChangeSet(model, cs)
  const afterLinkIds = new Set(after.links.map((l) => key(l.id)))

  const added = (cs.addTasks ?? []).filter((t) => !tById.has(key(t.id)))
  if (added.length) out.removeTasks = added.map((t) => t.id)
  const removed = (cs.removeTasks ?? []).map((id) => tById.get(key(id))).filter((t): t is GanttTask => !!t)
  if (removed.length) out.addTasks = removed.map((t) => ({ ...t }))
  const upd: NonNullable<ChangeSet['updateTasks']> = []
  for (const u of cs.updateTasks ?? []) {
    const before = tById.get(key(u.id))
    if (!before) continue
    const patch: Record<string, unknown> = {}
    for (const f of Object.keys(u.patch)) patch[f] = (before as unknown as Record<string, unknown>)[f] ?? null
    upd.push({ id: u.id, patch: patch as Partial<GanttTask> })
  }
  // Children whose parent was removed were lifted to top level: put them back.
  const removedKeys = new Set(removed.map((t) => key(t.id)))
  for (const t of model.tasks) {
    if (t.parentId != null && removedKeys.has(key(t.parentId)) && !removedKeys.has(key(t.id))) {
      upd.push({ id: t.id, patch: { parentId: t.parentId } })
    }
  }
  if (upd.length) out.updateTasks = upd
  if (cs.order?.length || removed.length || added.length) {
    out.order = model.tasks.map((t) => t.id)
  }

  const addedLinks = (cs.addLinks ?? []).filter((l) => !lById.has(key(l.id)))
  if (addedLinks.length) out.removeLinks = addedLinks.map((l) => l.id)
  // Every link that existed before and is gone after (removed explicitly or with a task).
  const lostLinks = model.links.filter((l) => !afterLinkIds.has(key(l.id)))
  if (lostLinks.length) out.addLinks = lostLinks.map((l) => ({ ...l }))
  const lupd: NonNullable<ChangeSet['updateLinks']> = []
  for (const u of cs.updateLinks ?? []) {
    const before = lById.get(key(u.id))
    if (!before || !afterLinkIds.has(key(u.id))) continue
    const patch: Record<string, unknown> = {}
    for (const f of Object.keys(u.patch)) patch[f] = (before as unknown as Record<string, unknown>)[f]
    lupd.push({ id: u.id, patch: patch as Partial<GanttLink> })
  }
  if (lupd.length) out.updateLinks = lupd
  return out
}

/** Replace temporary ids (tasks and links, also inside references). */
/**
 * Replace temporary ids. Task ids (and task references: parent, link ends,
 * order, meta values) use `idMap`; link ids use `linkIdMap` only: the two id
 * spaces overlap (task 5 and link 5 are different things).
 */
export function remapChangeSet(cs: ChangeSet, idMap: Record<string, GanttId>, linkIdMap: Record<string, GanttId> = {}): ChangeSet {
  const m = (id: GanttId): GanttId => (key(id) in idMap ? idMap[key(id)] : id)
  const ml = (id: GanttId): GanttId => (key(id) in linkIdMap ? linkIdMap[key(id)] : id)
  const mo = (id: GanttId | null | undefined) => (id == null ? id : m(id))
  return {
    ...cs,
    addTasks: cs.addTasks?.map((t) => ({ ...t, id: m(t.id), parentId: mo(t.parentId) })),
    updateTasks: cs.updateTasks?.map((u) => ({
      id: m(u.id), patch: 'parentId' in u.patch ? { ...u.patch, parentId: mo(u.patch.parentId) } : u.patch,
    })),
    removeTasks: cs.removeTasks?.map(m),
    addLinks: cs.addLinks?.map((l) => ({ ...l, id: ml(l.id), from: m(l.from), to: m(l.to) })),
    updateLinks: cs.updateLinks?.map((u) => ({
      id: ml(u.id),
      patch: { ...u.patch, ...(u.patch.from != null ? { from: m(u.patch.from) } : {}), ...(u.patch.to != null ? { to: m(u.patch.to) } : {}) },
    })),
    removeLinks: cs.removeLinks?.map(ml),
    order: cs.order?.map(m),
    // Adapter data may carry task ids (e.g. a focus target): remap plain id values.
    ...(cs.meta ? { meta: Object.fromEntries(Object.entries(cs.meta).map(([k, v]) =>
      [k, (typeof v === 'string' || typeof v === 'number') && key(v) in idMap ? idMap[key(v)] : v])) } : {}),
  }
}

/** Does the model already show everything this ChangeSet does? (reconcile) */
export function modelContains(model: GanttModel, cs: ChangeSet): boolean {
  const t = new Map(model.tasks.map((x) => [key(x.id), x as unknown as Record<string, unknown>]))
  const l = new Map(model.links.map((x) => [key(x.id), x as unknown as Record<string, unknown>]))
  const same = (a: unknown, b: unknown) => JSON.stringify(a ?? null) === JSON.stringify(b ?? null)
  if ((cs.addTasks ?? []).some((x) => !t.has(key(x.id)))) return false
  if ((cs.removeTasks ?? []).some((id) => t.has(key(id)))) return false
  for (const u of cs.updateTasks ?? []) {
    const cur = t.get(key(u.id))
    if (!cur) return false
    for (const [f, v] of Object.entries(u.patch)) if (f !== 'meta' && !same(cur[f], v)) return false
  }
  if ((cs.addLinks ?? []).some((x) => !l.has(key(x.id)))) return false
  if ((cs.removeLinks ?? []).some((id) => l.has(key(id)))) return false
  for (const u of cs.updateLinks ?? []) {
    const cur = l.get(key(u.id))
    if (!cur) return false
    for (const [f, v] of Object.entries(u.patch)) if (!same(cur[f], v)) return false
  }
  return true
}

/** Every task id a ChangeSet touches (for "saving" markers). */
export function touchedTaskIds(cs: ChangeSet): string[] {
  const s = new Set<string>()
  cs.addTasks?.forEach((t) => s.add(key(t.id)))
  cs.updateTasks?.forEach((u) => s.add(key(u.id)))
  cs.removeTasks?.forEach((id) => s.add(key(id)))
  cs.addLinks?.forEach((l) => { s.add(key(l.to)) })
  return [...s]
}

/** Delete tasks with their subtrees and every link touching them. */
export function removeTasksChangeSet(model: GanttModel, ids: GanttId[]): ChangeSet | null {
  const tree = buildTree(model.tasks)
  const top = topLevelSelection(tree, ids)
  if (!top.length) return null
  const all = new Set<string>()
  for (const k of top) { all.add(k); descendants(tree, k).forEach((d) => all.add(key(d.id))) }
  const removeTasks = tree.order.filter((t) => all.has(key(t.id))).map((t) => t.id)
  const removeLinks = model.links.filter((l) => all.has(key(l.from)) || all.has(key(l.to))).map((l) => l.id)
  return {
    label: removeTasks.length === 1 ? 'Delete task' : `Delete ${removeTasks.length} tasks`,
    removeTasks, ...(removeLinks.length ? { removeLinks } : {}),
  }
}

/**
 * Duplicate tasks (with subtrees and the links among the copies), inserted
 * right after the last duplicated block. Copies lose baselines and actuals.
 */
export function duplicateChangeSet(model: GanttModel, ids: GanttId[], newId: () => GanttId = () => tempId('task')): ChangeSet | null {
  const tree = buildTree(model.tasks)
  const top = topLevelSelection(tree, ids)
  if (!top.length) return null
  const map = new Map<string, GanttId>()
  const blocks: GanttTask[] = []
  for (const k of top) {
    for (const t of [tree.byId.get(k)!, ...descendants(tree, k)]) { map.set(key(t.id), newId()); blocks.push(t) }
  }
  const addTasks = blocks.map((t) => ({
    ...t,
    id: map.get(key(t.id))!,
    parentId: t.parentId != null && map.has(key(t.parentId)) ? map.get(key(t.parentId))! : t.parentId ?? null,
    name: top.includes(key(t.id)) ? `${t.name} (copy)` : t.name,
    baselineStart: null, baselineEnd: null, actualStart: null, actualEnd: null, progress: 0,
  }))
  const addLinks = model.links
    .filter((l) => map.has(key(l.from)) && map.has(key(l.to)))
    .map((l) => ({ ...l, id: newId(), from: map.get(key(l.from))!, to: map.get(key(l.to))! }))
  // Insert copies after the last original block.
  const orderKeys = tree.order.map((t) => key(t.id))
  let last = -1
  for (const k of map.keys()) last = Math.max(last, orderKeys.indexOf(k))
  const flat: GanttId[] = [...tree.order.slice(0, last + 1).map((t) => t.id), ...addTasks.map((t) => t.id),
    ...tree.order.slice(last + 1).map((t) => t.id)]
  return {
    label: addTasks.length === 1 ? 'Duplicate task' : `Duplicate ${addTasks.length} tasks`,
    addTasks, ...(addLinks.length ? { addLinks } : {}), order: flat,
  }
}

/** Link the selection as a finish-to-start chain in display order (skips existing links). */
export function chainLinksChangeSet(model: GanttModel, ids: GanttId[], newId: () => GanttId = () => tempId('link')): ChangeSet | null {
  const tree = buildTree(model.tasks)
  const set = new Set(ids.map(key))
  const sel = tree.order.filter((t) => set.has(key(t.id)))
  const addLinks: GanttLink[] = []
  for (let i = 1; i < sel.length; i++) {
    const from = sel[i - 1].id, to = sel[i].id
    if (model.links.some((l) => key(l.from) === key(from) && key(l.to) === key(to))) continue
    addLinks.push({ id: newId(), from, to, type: 'FS', lagDays: 0 })
  }
  return addLinks.length ? { label: 'Link tasks', addLinks } : null
}

/** Remove every link between the selected tasks (or touching a single one). */
export function unlinkChangeSet(model: GanttModel, ids: GanttId[]): ChangeSet | null {
  const set = new Set(ids.map(key))
  const removeLinks = model.links
    .filter((l) => !l.readOnly)
    .filter((l) => (set.size === 1 ? set.has(key(l.from)) || set.has(key(l.to)) : set.has(key(l.from)) && set.has(key(l.to))))
    .map((l) => l.id)
  return removeLinks.length ? { label: 'Unlink tasks', removeLinks } : null
}
