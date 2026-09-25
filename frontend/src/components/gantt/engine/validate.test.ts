import { describe, expect, it } from 'vitest'
import { linkViolated, validate } from './validate'
import type { GanttLink, GanttTask } from './types'

const T = (id: number, more: Partial<GanttTask> = {}): GanttTask =>
  ({ id, name: `T${id}`, start: '2026-10-05', duration: 5, ...more })
const L = (from: number, to: number, type: GanttLink['type'] = 'FS', lagDays = 0, id = `${from}-${to}`): GanttLink =>
  ({ id, from, to, type, lagDays })
const codes = (tasks: GanttTask[], links: GanttLink[] = [], cal?: Parameters<typeof validate>[2]) =>
  validate(tasks, links, cal).map((i) => i.code)

describe('linkViolated', () => {
  const A = T(1)
  it('FS: successor before the predecessor end', () => {
    expect(linkViolated(A, T(2, { start: '2026-10-09' }), L(1, 2))).toBe(true)
    expect(linkViolated(A, T(2, { start: '2026-10-10' }), L(1, 2))).toBe(false)
  })
  it('FS lag and lead', () => {
    expect(linkViolated(A, T(2, { start: '2026-10-11' }), L(1, 2, 'FS', 2))).toBe(true)
    expect(linkViolated(A, T(2, { start: '2026-10-08' }), L(1, 2, 'FS', -2))).toBe(false)
  })
  it('SS', () => {
    expect(linkViolated(A, T(2, { start: '2026-10-05' }), L(1, 2, 'SS', 1))).toBe(true)
    expect(linkViolated(A, T(2, { start: '2026-10-06' }), L(1, 2, 'SS', 1))).toBe(false)
  })
  it('FF', () => {
    expect(linkViolated(A, T(2, { start: '2026-10-05', duration: 3 }), L(1, 2, 'FF'))).toBe(true)
    expect(linkViolated(A, T(2, { start: '2026-10-07', duration: 3 }), L(1, 2, 'FF'))).toBe(false)
  })
  it('SF', () => {
    expect(linkViolated(A, T(2, { start: '2026-10-01', duration: 3 }), L(1, 2, 'SF'))).toBe(true)
    expect(linkViolated(A, T(2, { start: '2026-10-02', duration: 3 }), L(1, 2, 'SF'))).toBe(false)
  })
  it('working mode: Monday start after a Friday finish is fine', () => {
    const cal = { mode: 'working' as const, workdays: [1, 2, 3, 4, 5], holidays: [] }
    expect(linkViolated(A, T(2, { start: '2026-10-12' }), L(1, 2), cal)).toBe(false)
    expect(linkViolated(A, T(2, { start: '2026-10-10' }), L(1, 2), cal)).toBe(false) // snaps to Monday
    expect(linkViolated(A, T(2, { start: '2026-10-09' }), L(1, 2), cal)).toBe(true)
  })
})

describe('validate', () => {
  it('a clean plan has no issues', () => expect(codes([T(1), T(2, { start: '2026-10-10' })], [L(1, 2)])).toEqual([]))
  it('empty name', () => expect(codes([T(1, { name: '  ' })])).toEqual(['empty_name']))
  it('bad start date', () => expect(codes([T(1, { start: '2026-02-30' })])).toContain('bad_date'))
  it('negative duration', () => expect(codes([T(1, { duration: -1 })])).toContain('negative_duration'))
  it('unknown parent', () => expect(codes([T(1, { parentId: 9 })])).toContain('unknown_parent'))
  it('parent loop', () => expect(codes([T(1, { parentId: 2 }), T(2, { parentId: 1 })])).toContain('parent_loop'))
  it('constraint without a date', () => expect(codes([T(1, { constraint: { type: 'mso' } })])).toContain('constraint_date'))
  it('asap needs no date', () => expect(codes([T(1, { constraint: { type: 'asap' } })])).toEqual([]))
  it('progress out of range', () => expect(codes([T(1, { progress: 120 })])).toContain('progress_range'))
  it('link to an unknown task', () => expect(codes([T(1)], [L(1, 9)])).toEqual(['unknown_predecessor']))
  it('self link', () => expect(codes([T(1)], [L(1, 1)])).toContain('self_link'))
  it('duplicate link is a warning', () => {
    const issues = validate([T(1), T(2, { start: '2026-10-10' })], [L(1, 2, 'FS', 0, 'a'), L(1, 2, 'SS', 0, 'b')])
    expect(issues.find((i) => i.code === 'duplicate_link')).toMatchObject({ level: 'warning', linkId: 'b' })
  })
  it('dependency violation names the link', () => {
    const issues = validate([T(1), T(2)], [L(1, 2)])
    expect(issues[0]).toMatchObject({ code: 'dependency_violation', level: 'error', taskId: 2, linkId: '1-2' })
  })
  it('links on summaries are not checked as violations', () => {
    expect(codes([T(1), T(2, { start: '2026-10-01' }), T(3, { parentId: 2 })], [L(1, 2)])).not.toContain('dependency_violation')
  })
  it('cycle', () => expect(codes([T(1), T(2, { start: '2026-10-10' })], [L(1, 2), L(2, 1)])).toContain('cycle'))
  it('includes constraint conflicts from the schedule', () => {
    expect(codes([T(1, { constraint: { type: 'fnlt', date: '2026-10-07' } })])).toEqual(['constraint_conflict'])
  })
})
