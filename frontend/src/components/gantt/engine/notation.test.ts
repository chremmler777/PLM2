import { describe, expect, it } from 'vitest'
import { formatPredecessor, formatPredecessors, parsePredecessors, predecessorChangeSet, tempId } from './notation'
import { buildTree, rowNumbers } from './tree'
import type { GanttLink, GanttTask } from './types'

describe('parsePredecessors', () => {
  it('reads a plain row as FS without lag', () => {
    expect(parsePredecessors('7').preds).toEqual([{ row: 7, type: 'FS', lag: 0 }])
  })
  it('reads 3FS+2d', () => expect(parsePredecessors('3FS+2d').preds).toEqual([{ row: 3, type: 'FS', lag: 2 }]))
  it('reads 5SS-1d', () => expect(parsePredecessors('5SS-1d').preds).toEqual([{ row: 5, type: 'SS', lag: -1 }]))
  it('is case insensitive', () => expect(parsePredecessors('2ff').preds).toEqual([{ row: 2, type: 'FF', lag: 0 }]))
  it('reads weeks as 7 days in calendar mode', () => {
    expect(parsePredecessors('4SF+1w', 'calendar').preds).toEqual([{ row: 4, type: 'SF', lag: 7 }])
  })
  it('reads weeks as 5 days in working mode', () => {
    expect(parsePredecessors('4SF+1w', 'working').preds).toEqual([{ row: 4, type: 'SF', lag: 5 }])
  })
  it('reads elapsed weeks as 7 days in working mode', () => {
    expect(parsePredecessors('4FS+1ew', 'working').preds[0].lag).toBe(7)
  })
  it('reads a lag without a unit as days', () => expect(parsePredecessors('3FS+4').preds[0].lag).toBe(4))
  it('reads long unit names', () => {
    expect(parsePredecessors('3FS+2days').preds[0].lag).toBe(2)
    expect(parsePredecessors('3FS-1 week').preds[0].lag).toBe(-7)
  })
  it('tolerates spaces', () => expect(parsePredecessors(' 3 FS + 2 d ').preds).toEqual([{ row: 3, type: 'FS', lag: 2 }]))
  it('splits on commas and semicolons', () => {
    expect(parsePredecessors('1, 2SS; 3FF-1d').preds.map((p) => p.row)).toEqual([1, 2, 3])
  })
  it('ignores empty entries', () => expect(parsePredecessors('1,,  ,2').preds).toHaveLength(2))
  it('returns nothing for an empty string', () => expect(parsePredecessors('')).toEqual({ preds: [], errors: [] }))
  it('reports text it cannot read', () => {
    const r = parsePredecessors('1, foo, 3XX')
    expect(r.preds).toHaveLength(1)
    expect(r.errors).toHaveLength(2)
  })
  it('reports duplicates', () => expect(parsePredecessors('2, 2SS').errors[0]).toContain('twice'))
  it('reports row 0', () => expect(parsePredecessors('0').errors[0]).toContain('does not exist'))
  it('rounds a fractional lag', () => expect(parsePredecessors('1FS+1.5d').preds[0].lag).toBe(2))
  it('normalises -0 lag to 0', () => expect(Object.is(parsePredecessors('1FS-0d').preds[0].lag, 0)).toBe(true))
})

describe('formatPredecessor(s)', () => {
  it('writes plain FS as the row', () => expect(formatPredecessor(3, 'FS', 0)).toBe('3'))
  it('writes a lag', () => expect(formatPredecessor(3, 'FS', 2)).toBe('3FS+2d'))
  it('writes a lead', () => expect(formatPredecessor(5, 'SS', -1)).toBe('5SS-1d'))
  it('writes other types without lag', () => expect(formatPredecessor(2, 'FF', 0)).toBe('2FF'))
  it('round-trips through the parser', () => {
    for (const s of ['3', '3FS+2d', '5SS-1d', '2FF', '4SF+7d']) {
      const p = parsePredecessors(s).preds[0]
      expect(formatPredecessor(p.row, p.type, p.lag)).toBe(s)
    }
  })
  it('lists every link into a task sorted by row', () => {
    const tasks: GanttTask[] = [1, 2, 3, 4].map((id) => ({ id, name: `T${id}`, start: '2026-10-05', duration: 1 }))
    const rows = rowNumbers(buildTree(tasks))
    const links: GanttLink[] = [
      { id: 'a', from: 3, to: 4, type: 'SS', lagDays: 1 },
      { id: 'b', from: 1, to: 4, type: 'FS', lagDays: 0 },
      { id: 'c', from: 1, to: 2, type: 'FS', lagDays: 0 },
    ]
    expect(formatPredecessors(4, links, rows)).toBe('1, 3SS+1d')
    expect(formatPredecessors(1, links, rows)).toBe('')
  })
})

describe('predecessorChangeSet', () => {
  const tasks: GanttTask[] = [1, 2, 3, 4].map((id) => ({ id, name: `T${id}`, start: '2026-10-05', duration: 1 }))
  const links: GanttLink[] = [{ id: 'L1', from: 1, to: 4, type: 'FS', lagDays: 0 }, { id: 'L2', from: 2, to: 4, type: 'FS', lagDays: 0 }]
  let k = 0
  const newId = () => `new${k++}`

  it('keeps an unchanged link', () => {
    expect(predecessorChangeSet(4, '1, 2', tasks, links).changes).toBeNull()
  })
  it('updates type and lag in place, keeping the link id', () => {
    const r = predecessorChangeSet(4, '1SS+2d, 2', tasks, links)
    expect(r.changes!.updateLinks).toEqual([{ id: 'L1', patch: { type: 'SS', lagDays: 2 } }])
    expect(r.changes!.addLinks).toEqual([])
    expect(r.changes!.removeLinks).toEqual([])
  })
  it('adds new links with the real task id', () => {
    const r = predecessorChangeSet(4, '1, 2, 3FF', tasks, links, 'calendar', newId)
    expect(r.changes!.addLinks).toEqual([{ id: 'new0', from: 3, to: 4, type: 'FF', lagDays: 0 }])
  })
  it('removes dropped links', () => {
    expect(predecessorChangeSet(4, '2', tasks, links).changes!.removeLinks).toEqual(['L1'])
  })
  it('clears all links for an empty cell', () => {
    expect(predecessorChangeSet(4, '', tasks, links).changes!.removeLinks).toEqual(['L1', 'L2'])
  })
  it('refuses a self reference', () => {
    const r = predecessorChangeSet(4, '4', tasks, links)
    expect(r.changes).toBeNull()
    expect(r.errors[0]).toContain('itself')
  })
  it('refuses unknown rows', () => {
    expect(predecessorChangeSet(4, '9', tasks, links).errors[0]).toContain('Row 9')
  })
  it('passes parse errors through', () => {
    expect(predecessorChangeSet(4, 'abc', tasks, links).errors).toHaveLength(1)
  })
  it('uses row numbers in pre-order with nested tasks', () => {
    const nested: GanttTask[] = [
      { id: 'b', parentId: 'a', name: 'B', start: '2026-10-05', duration: 1 },
      { id: 'a', name: 'A', start: '2026-10-05', duration: 0 },
      { id: 'c', name: 'C', start: '2026-10-05', duration: 1 },
    ]
    const r = predecessorChangeSet('c', '2', nested, [], 'calendar', newId)
    expect(r.changes!.addLinks![0].from).toBe('b')
  })
  it('tempId is unique', () => expect(tempId()).not.toBe(tempId()))
})
