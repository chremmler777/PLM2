import { describe, expect, it } from 'vitest'
import { applyChangeSet } from './changes'
import {
  ancestors, buildTree, descendants, indent, isSummary, key, leaves, moveRows, outdent, rowNumbers,
  topLevelSelection, visibleOrder,
} from './tree'
import type { GanttTask } from './types'

const t = (id: number | string, parentId: number | string | null = null): GanttTask =>
  ({ id, parentId, name: `T${id}`, start: '2026-10-05', duration: 1 })

const ids = (list: GanttTask[]) => list.map((x) => x.id)

/** Apply a tree ChangeSet and describe the result as "id:parent" in pre-order. */
function shape(tasks: GanttTask[], cs: ReturnType<typeof indent>) {
  const m = applyChangeSet({ tasks, links: [] }, cs!)
  const tree = buildTree(m.tasks)
  return tree.order.map((x) => `${x.id}:${tree.parentOf.get(key(x.id)) ?? '-'}`).join(' ')
}

describe('buildTree', () => {
  it('orders roots in array order', () => expect(ids(buildTree([t(1), t(2), t(3)]).order)).toEqual([1, 2, 3]))
  it('puts children after their parent even when given before it', () => {
    const tree = buildTree([t(2, 1), t(3, 1), t(1), t(4)])
    expect(ids(tree.order)).toEqual([1, 2, 3, 4])
  })
  it('numbers WBS hierarchically', () => {
    const tree = buildTree([t(1), t(2, 1), t(3, 2), t(4, 1), t(5)])
    expect([...tree.wbs.values()]).toEqual(['1', '1.1', '1.1.1', '1.2', '2'])
  })
  it('records depth', () => {
    const tree = buildTree([t(1), t(2, 1), t(3, 2)])
    expect(tree.depth.get('3')).toBe(2)
    expect(tree.depth.get('1')).toBe(0)
  })
  it('treats an unknown parent as top level', () => {
    const tree = buildTree([t(1, 99)])
    expect(tree.parentOf.get('1')).toBeNull()
    expect(ids(tree.roots)).toEqual([1])
  })
  it('ignores a task being its own parent', () => expect(buildTree([t(1, 1)]).parentOf.get('1')).toBeNull())
  it('breaks parent loops without losing tasks', () => {
    const tree = buildTree([t(1, 2), t(2, 1), t(3)])
    expect(tree.order).toHaveLength(3)
    expect(new Set(ids(tree.order))).toEqual(new Set([1, 2, 3]))
  })
  it('mixes string and number ids by key', () => {
    const tree = buildTree([t('a'), t('b', 'a')])
    expect(tree.parentOf.get('b')).toBe('a')
    expect(tree.wbs.get('b')).toBe('1.1')
  })
  it('gives row numbers in pre-order', () => {
    const rows = rowNumbers(buildTree([t(2, 1), t(1), t(3)]))
    expect(rows.get('1')).toBe(1)
    expect(rows.get('2')).toBe(2)
    expect(rows.get('3')).toBe(3)
  })
})

describe('tree queries', () => {
  const tree = buildTree([t(1), t(2, 1), t(3, 2), t(4, 1), t(5)])
  it('finds summaries', () => {
    expect(isSummary(tree, 1)).toBe(true)
    expect(isSummary(tree, 3)).toBe(false)
  })
  it('lists descendants in pre-order', () => expect(ids(descendants(tree, 1))).toEqual([2, 3, 4]))
  it('lists ancestors nearest first', () => expect(ancestors(tree, 3)).toEqual(['2', '1']))
  it('lists leaves', () => {
    expect(ids(leaves(tree, 1))).toEqual([3, 4])
    expect(ids(leaves(tree, 5))).toEqual([5])
    expect(leaves(tree, 99)).toEqual([])
  })
  it('hides collapsed subtrees', () => {
    expect(ids(visibleOrder(tree, new Set(['2'])))).toEqual([1, 2, 4, 5])
    expect(ids(visibleOrder(tree, new Set(['1'])))).toEqual([1, 5])
  })
  it('keeps only top-level selections in pre-order', () => {
    expect(topLevelSelection(tree, [3, 1, 5])).toEqual(['1', '5'])
    expect(topLevelSelection(tree, [4, 3])).toEqual(['3', '4'])
  })
})

describe('indent', () => {
  it('makes a task the child of its previous sibling', () => {
    const tasks = [t(1), t(2), t(3)]
    expect(shape(tasks, indent(tasks, [2]))).toBe('1:- 2:1 3:-')
  })
  it('does nothing for the first task', () => expect(indent([t(1), t(2)], [1])).toBeNull())
  it('indents a block of siblings under the same previous sibling', () => {
    const tasks = [t(1), t(2), t(3), t(4)]
    expect(shape(tasks, indent(tasks, [2, 3]))).toBe('1:- 2:1 3:1 4:-')
  })
  it('appends to an existing summary as its last child', () => {
    const tasks = [t(1), t(2, 1), t(3)]
    expect(shape(tasks, indent(tasks, [3]))).toBe('1:- 2:1 3:1')
  })
  it('moves a subtree along with its root', () => {
    const tasks = [t(1), t(2), t(3, 2)]
    expect(shape(tasks, indent(tasks, [2]))).toBe('1:- 2:1 3:2')
  })
  it('labels the ChangeSet', () => expect(indent([t(1), t(2)], [2])!.label).toBe('Indent'))
})

describe('outdent', () => {
  it('lifts a last child to its parent level', () => {
    const tasks = [t(1), t(2, 1), t(3)]
    expect(shape(tasks, outdent(tasks, [2]))).toBe('1:- 2:- 3:-')
  })
  it('adopts the siblings that followed it (MS Project)', () => {
    const tasks = [t(1), t(2, 1), t(3, 1), t(4, 1)]
    expect(shape(tasks, outdent(tasks, [2]))).toBe('1:- 2:- 3:2 4:2')
  })
  it('lifts from a nested level to the grandparent', () => {
    const tasks = [t(1), t(2, 1), t(3, 2)]
    expect(shape(tasks, outdent(tasks, [3]))).toBe('1:- 2:1 3:1')
  })
  it('is a no-op on top-level tasks', () => expect(outdent([t(1), t(2)], [1, 2])).toBeNull())
  it('places the lifted task after its old parent subtree', () => {
    const tasks = [t(1), t(2, 1), t(3, 1), t(5)]
    const r = applyChangeSet({ tasks, links: [] }, outdent(tasks, [3])!)
    expect(ids(buildTree(r.tasks).order)).toEqual([1, 2, 3, 5])
  })
  it('indent then outdent restores the shape', () => {
    const tasks = [t(1), t(2), t(3)]
    const a = applyChangeSet({ tasks, links: [] }, indent(tasks, [2])!).tasks
    expect(shape(a, outdent(a, [2]))).toBe('1:- 2:- 3:-')
  })
})

describe('moveRows', () => {
  const tasks = [t(1), t(2), t(3), t(4, 3), t(5)]
  it('moves a row before a target', () => {
    const r = applyChangeSet({ tasks, links: [] }, moveRows(tasks, [5], 2, 'before')!)
    expect(ids(buildTree(r.tasks).order)).toEqual([1, 5, 2, 3, 4])
  })
  it('moves after the target including its subtree', () => {
    const r = applyChangeSet({ tasks, links: [] }, moveRows(tasks, [1], 3, 'after')!)
    expect(ids(buildTree(r.tasks).order)).toEqual([2, 3, 4, 1, 5])
  })
  it('carries a subtree along', () => {
    const r = applyChangeSet({ tasks, links: [] }, moveRows(tasks, [3], 1, 'before')!)
    expect(ids(buildTree(r.tasks).order)).toEqual([3, 4, 1, 2, 5])
  })
  it('takes the target parent', () => {
    const cs = moveRows(tasks, [5], 4, 'before')!
    expect(cs.updateTasks).toEqual([{ id: 5, patch: { parentId: 3 } }])
    expect(shape(tasks, cs)).toBe('1:- 2:- 3:- 5:3 4:3')
  })
  it('refuses a move onto itself', () => expect(moveRows(tasks, [2], 2, 'after')).toBeNull())
  it('refuses a move into its own subtree', () => expect(moveRows(tasks, [3], 4, 'after')).toBeNull())
  it('returns null for a no-op', () => expect(moveRows(tasks, [2], 1, 'after')).toBeNull())
  it('labels multi-row moves', () => expect(moveRows(tasks, [1, 2], 5, 'after')!.label).toBe('Move 2 rows'))
})
