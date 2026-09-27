/**
 * The task hierarchy: parents (summary tasks), pre-order, WBS numbers,
 * indent / outdent and row moves. The array order of `tasks` is the display
 * order among siblings; a parent always comes before its children in the
 * pre-order produced here, whatever the input order.
 */
import type { ChangeSet, GanttId, GanttTask } from './types'

export const key = (id: GanttId) => String(id)

export interface Tree {
  byId: Map<string, GanttTask>
  children: Map<string, GanttTask[]>
  roots: GanttTask[]
  parentOf: Map<string, string | null>
  /** Tasks in display pre-order. */
  order: GanttTask[]
  depth: Map<string, number>
  wbs: Map<string, string>
}

/** Parent id if it exists and does not create a parent loop, else null. */
function safeParents(tasks: GanttTask[]): Map<string, string | null> {
  const ids = new Set(tasks.map((t) => key(t.id)))
  const parent = new Map<string, string | null>()
  for (const t of tasks) {
    const p = t.parentId != null ? key(t.parentId) : null
    parent.set(key(t.id), p && ids.has(p) && p !== key(t.id) ? p : null)
  }
  // Break parent cycles: walk up; a node that reaches itself loses its parent.
  for (const t of tasks) {
    const start = key(t.id)
    const seen = new Set<string>([start])
    let cur = parent.get(start) ?? null
    while (cur != null) {
      if (seen.has(cur)) { parent.set(start, null); break }
      seen.add(cur)
      cur = parent.get(cur) ?? null
    }
  }
  return parent
}

export function buildTree(tasks: GanttTask[]): Tree {
  const byId = new Map(tasks.map((t) => [key(t.id), t]))
  const parentOf = safeParents(tasks)
  const children = new Map<string, GanttTask[]>()
  const roots: GanttTask[] = []
  for (const t of tasks) {
    const p = parentOf.get(key(t.id)) ?? null
    if (p == null) roots.push(t)
    else {
      if (!children.has(p)) children.set(p, [])
      children.get(p)!.push(t)
    }
  }
  const order: GanttTask[] = []
  const depth = new Map<string, number>()
  const wbs = new Map<string, string>()
  const walk = (list: GanttTask[], d: number, prefix: string) => {
    list.forEach((t, i) => {
      const k = key(t.id)
      const w = prefix ? `${prefix}.${i + 1}` : String(i + 1)
      order.push(t)
      depth.set(k, d)
      wbs.set(k, w)
      walk(children.get(k) ?? [], d + 1, w)
    })
  }
  walk(roots, 0, '')
  return { byId, children, roots, parentOf, order, depth, wbs }
}

export const isSummary = (tree: Tree, id: GanttId) => (tree.children.get(key(id))?.length ?? 0) > 0

/** All descendants (not the task itself), pre-order. */
export function descendants(tree: Tree, id: GanttId): GanttTask[] {
  const out: GanttTask[] = []
  const walk = (k: string) => {
    for (const c of tree.children.get(k) ?? []) { out.push(c); walk(key(c.id)) }
  }
  walk(key(id))
  return out
}

export function ancestors(tree: Tree, id: GanttId): string[] {
  const out: string[] = []
  let cur = tree.parentOf.get(key(id)) ?? null
  while (cur != null) { out.push(cur); cur = tree.parentOf.get(cur) ?? null }
  return out
}

/** Leaf tasks under a task (the task itself when it is a leaf). */
export function leaves(tree: Tree, id: GanttId): GanttTask[] {
  const kids = tree.children.get(key(id)) ?? []
  if (kids.length === 0) { const t = tree.byId.get(key(id)); return t ? [t] : [] }
  return kids.flatMap((c) => leaves(tree, c.id))
}

/** 1-based row number in pre-order: the "ID" column of MS Project. */
export function rowNumbers(tree: Tree): Map<string, number> {
  return new Map(tree.order.map((t, i) => [key(t.id), i + 1]))
}

/** Rows visible with some summaries collapsed. */
export function visibleOrder(tree: Tree, collapsed: Set<string>): GanttTask[] {
  const out: GanttTask[] = []
  const walk = (list: GanttTask[]) => {
    for (const t of list) {
      out.push(t)
      if (!collapsed.has(key(t.id))) walk(tree.children.get(key(t.id)) ?? [])
    }
  }
  walk(tree.roots)
  return out
}

/** Pre-order ids, top-level selection only (children of selected parents drop out). */
export function topLevelSelection(tree: Tree, ids: GanttId[]): string[] {
  const set = new Set(ids.map(key))
  return tree.order.map((t) => key(t.id))
    .filter((k) => set.has(k) && !ancestors(tree, k).some((a) => set.has(a)))
}

const eqId = (a: GanttId | null | undefined, b: GanttId | null | undefined) =>
  (a == null && b == null) || (a != null && b != null && key(a) === key(b))

/**
 * Indent: each selected task becomes the last child of its previous sibling
 * (MS Project). Tasks without a previous sibling stay. Returns a ChangeSet
 * with parentId patches and the new order, or null when nothing changes.
 */
export function indent(tasks: GanttTask[], ids: GanttId[]): ChangeSet | null {
  const tree = buildTree(tasks)
  const sel = topLevelSelection(tree, ids)
  const newParent = new Map<string, string | null>()
  for (const k of sel) {
    const p = tree.parentOf.get(k) ?? null
    const sibs = p == null ? tree.roots : tree.children.get(p) ?? []
    const i = sibs.findIndex((s) => key(s.id) === k)
    // Previous sibling that is not itself being indented under the same parent.
    let j = i - 1
    while (j >= 0 && sel.includes(key(sibs[j].id)) && newParent.has(key(sibs[j].id))) j--
    if (j < 0) continue
    newParent.set(k, key(sibs[j].id))
  }
  if (newParent.size === 0) return null
  const updateTasks = [...newParent].map(([k, p]) => ({ id: tree.byId.get(k)!.id, patch: { parentId: tree.byId.get(p!)!.id } }))
  // Pre-order stays the same when indenting under the previous sibling.
  return { label: 'Indent', updateTasks, order: tree.order.map((t) => t.id) }
}

/**
 * Outdent: each selected task moves up one level, placed right after its old
 * parent; the siblings that followed it become its children (MS Project).
 */
export function outdent(tasks: GanttTask[], ids: GanttId[]): ChangeSet | null {
  let cur = tasks.map((t) => ({ ...t }))
  const tree0 = buildTree(cur)
  const sel = topLevelSelection(tree0, ids).filter((k) => tree0.parentOf.get(k) != null)
  if (sel.length === 0) return null
  const patches = new Map<string, GanttId | null>()
  for (const k of sel) {
    const tree = buildTree(cur)
    const p = tree.parentOf.get(k)
    if (p == null) continue
    const grand = tree.parentOf.get(p) ?? null
    const sibs = tree.children.get(p) ?? []
    const i = sibs.findIndex((s) => key(s.id) === k)
    const following = sibs.slice(i + 1).filter((s) => !sel.includes(key(s.id)))
    const grandId = grand == null ? null : tree.byId.get(grand)!.id
    const me = tree.byId.get(k)!
    patches.set(k, grandId)
    for (const f of following) patches.set(key(f.id), me.id)
    // Rebuild order: put the task (and its subtree + adopted followers) right after the parent's subtree.
    cur = cur.map((t) => (key(t.id) === k ? { ...t, parentId: grandId }
      : following.some((f) => key(f.id) === key(t.id)) ? { ...t, parentId: me.id } : t))
    const t2 = buildTree(cur)
    const order = t2.order.map((t) => key(t.id))
    // Move k's block after p's block within the flat order used as sibling order.
    const block = [k, ...descendants(t2, k).map((d) => key(d.id))]
    const rest = order.filter((x) => !block.includes(x))
    const pBlockEnd = (() => {
      const pd = [p, ...descendants(t2, p).map((d) => key(d.id))]
      let last = rest.indexOf(p)
      for (const x of pd) last = Math.max(last, rest.indexOf(x))
      return last
    })()
    const flat = [...rest.slice(0, pBlockEnd + 1), ...block, ...rest.slice(pBlockEnd + 1)]
    const byKey = new Map(cur.map((t) => [key(t.id), t]))
    cur = flat.map((x) => byKey.get(x)!)
  }
  const updateTasks = [...patches]
    .filter(([k, p]) => !eqId(tree0.byId.get(k)!.parentId ?? null, p))
    .map(([k, p]) => ({ id: tree0.byId.get(k)!.id, patch: { parentId: p } }))
  const order = buildTree(cur).order.map((t) => t.id)
  return { label: 'Outdent', updateTasks, order }
}

/**
 * Move rows (with their subtrees) before or after a target row. The moved
 * tasks take the target's parent. Returns null for a no-op or an invalid move
 * (onto itself or into its own subtree).
 */
export function moveRows(tasks: GanttTask[], ids: GanttId[], targetId: GanttId, where: 'before' | 'after'): ChangeSet | null {
  const tree = buildTree(tasks)
  const sel = topLevelSelection(tree, ids)
  const target = key(targetId)
  if (sel.includes(target)) return null
  if (sel.some((k) => descendants(tree, k).some((d) => key(d.id) === target))) return null
  const targetParent = tree.parentOf.get(target) ?? null
  const blocks = sel.flatMap((k) => [k, ...descendants(tree, k).map((d) => key(d.id))])
  const rest = tree.order.map((t) => key(t.id)).filter((k) => !blocks.includes(k))
  let at = rest.indexOf(target)
  if (where === 'after') {
    // After the target's whole subtree.
    const sub = descendants(tree, target).map((d) => key(d.id))
    for (const x of sub) at = Math.max(at, rest.indexOf(x))
    at += 1
  }
  const flat = [...rest.slice(0, at), ...blocks, ...rest.slice(at)]
  const before = tree.order.map((t) => key(t.id))
  const parentChanges = sel.filter((k) => (tree.parentOf.get(k) ?? null) !== targetParent)
  if (flat.join('|') === before.join('|') && parentChanges.length === 0) return null
  const pid = targetParent == null ? null : tree.byId.get(targetParent)!.id
  return {
    label: sel.length === 1 ? 'Move row' : `Move ${sel.length} rows`,
    updateTasks: parentChanges.map((k) => ({ id: tree.byId.get(k)!.id, patch: { parentId: pid } })),
    order: flat.map((k) => tree.byId.get(k)!.id),
  }
}
