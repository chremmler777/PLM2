import { describe, expect, it } from 'vitest'
import { autoPushChangeSet, autoSchedulePatches, cascade, downstream, findCycle, push, schedule, wouldCycle } from './schedule'
import { validate } from './validate'
import type { GanttCalendar, GanttLink, GanttTask, LinkType, ScheduleOptions } from './types'

const CAL: Partial<GanttCalendar> = { mode: 'calendar', workdays: [1, 2, 3, 4, 5], holidays: [] }
const WORK: Partial<GanttCalendar> = { mode: 'working', workdays: [1, 2, 3, 4, 5], holidays: [] }

const T = (id: string | number, start: string, duration: number, more: Partial<GanttTask> = {}): GanttTask =>
  ({ id, name: `T${id}`, start, duration, ...more })
let n = 0
const L = (from: string | number, to: string | number, type: LinkType = 'FS', lagDays = 0): GanttLink =>
  ({ id: `l${n++}`, from, to, type, lagDays })

function run(tasks: GanttTask[], links: GanttLink[] = [], cal = CAL, opts?: ScheduleOptions) {
  const r = schedule(tasks, links, cal, opts)
  const get = (id: string | number) => r.byId.get(id)!
  return { r, get }
}

describe('single tasks', () => {
  it('keeps a lone task and makes it critical', () => {
    const { get, r } = run([T('A', '2026-10-05', 5)])
    expect(get('A')).toMatchObject({ start: '2026-10-05', end: '2026-10-10', totalSlack: 0, freeSlack: 0, critical: true })
    expect(r.start).toBe('2026-10-05')
    expect(r.finish).toBe('2026-10-10')
    expect(r.criticalIds).toEqual(['A'])
  })
  it('treats a negative duration as zero', () => {
    const { get } = run([T('A', '2026-10-05', -3)])
    expect(get('A').end).toBe('2026-10-05')
  })
  it('snaps a weekend start in working mode', () => {
    const { get } = run([T('A', '2026-10-10', 2)], [], WORK)
    expect(get('A')).toMatchObject({ start: '2026-10-12', end: '2026-10-14' })
  })
  it('moves a start that falls on a holiday', () => {
    const { get } = run([T('A', '2026-10-05', 2)], [], { ...WORK, holidays: ['2026-10-05'] })
    expect(get('A')).toMatchObject({ start: '2026-10-06', end: '2026-10-08' })
  })
  it('stretches over a holiday inside the task', () => {
    const { get } = run([T('A', '2026-10-05', 3)], [], { ...WORK, holidays: ['2026-10-06'] })
    expect(get('A').end).toBe('2026-10-09')
  })
  it('leaves an empty plan without dates', () => {
    const r = schedule([], [], CAL)
    expect(r.start).toBeNull()
    expect(r.finish).toBeNull()
    expect(r.criticalIds).toEqual([])
  })
  it('reports progress, clamped', () => {
    const { get } = run([T('A', '2026-10-05', 5, { progress: 140 }), T('B', '2026-10-05', 5, { progress: -5 })])
    expect(get('A').progress).toBe(100)
    expect(get('B').progress).toBe(0)
  })
})

describe('link types, calendar mode', () => {
  const A = T('A', '2026-10-05', 5) // ends 10
  it('FS pushes the successor to the predecessor end', () => {
    expect(run([A, T('B', '2026-10-05', 2)], [L('A', 'B')]).get('B').start).toBe('2026-10-10')
  })
  it('FS with a positive lag', () => {
    expect(run([A, T('B', '2026-10-05', 2)], [L('A', 'B', 'FS', 3)]).get('B').start).toBe('2026-10-13')
  })
  it('FS with a lead (negative lag)', () => {
    expect(run([A, T('B', '2026-10-01', 2)], [L('A', 'B', 'FS', -2)]).get('B').start).toBe('2026-10-08')
  })
  it('never pulls a later successor earlier (push mode)', () => {
    const { get } = run([A, T('B', '2026-10-20', 2)], [L('A', 'B')])
    expect(get('B').start).toBe('2026-10-20')
    expect(get('A').totalSlack).toBe(10)
    expect(get('A').freeSlack).toBe(10)
    expect(get('B').critical).toBe(true)
    expect(get('A').critical).toBe(false)
  })
  it('SS with a lag', () => {
    expect(run([A, T('B', '2026-10-01', 2)], [L('A', 'B', 'SS', 2)]).get('B').start).toBe('2026-10-07')
  })
  it('SS with a lead', () => {
    expect(run([A, T('B', '2026-10-01', 2)], [L('A', 'B', 'SS', -2)]).get('B').start).toBe('2026-10-03')
  })
  it('FF with a lag moves the successor end', () => {
    const { get } = run([A, T('B', '2026-10-05', 3)], [L('A', 'B', 'FF', 1)])
    expect(get('B')).toMatchObject({ start: '2026-10-08', end: '2026-10-11' })
  })
  it('FF with a lead can leave the successor where it is', () => {
    const { get } = run([A, T('B', '2026-10-05', 3)], [L('A', 'B', 'FF', -2)])
    expect(get('B')).toMatchObject({ start: '2026-10-05', end: '2026-10-08' })
  })
  it('SF with zero lag: successor ends when the predecessor starts', () => {
    const { get } = run([A, T('B', '2026-10-01', 3)], [L('A', 'B', 'SF')])
    expect(get('B')).toMatchObject({ start: '2026-10-02', end: '2026-10-05' })
  })
  it('SF with a lag', () => {
    const { get } = run([A, T('B', '2026-10-01', 3)], [L('A', 'B', 'SF', 4)])
    expect(get('B')).toMatchObject({ start: '2026-10-06', end: '2026-10-09' })
  })
  it('takes the latest of several predecessors', () => {
    const { get } = run([A, T('B', '2026-10-05', 8), T('C', '2026-10-05', 1)], [L('A', 'C'), L('B', 'C')])
    expect(get('C').start).toBe('2026-10-13')
  })
  it('cascades through a chain', () => {
    const { get } = run([A, T('B', '2026-10-05', 2), T('C', '2026-10-05', 2)], [L('A', 'B'), L('B', 'C')])
    expect(get('C')).toMatchObject({ start: '2026-10-12', end: '2026-10-14' })
  })
  it('ignores links to unknown tasks', () => {
    const { get, r } = run([A], [L('A', 'Z'), L('Y', 'A')])
    expect(get('A').start).toBe('2026-10-05')
    expect(r.cycle).toEqual([])
  })
  it('works with numeric ids', () => {
    const r = schedule([T(1, '2026-10-05', 2), T(2, '2026-10-05', 2)], [L(1, 2)], CAL)
    expect(r.byId.get(2)!.start).toBe('2026-10-07')
  })
})

describe('link types, working mode', () => {
  it('FS over a weekend', () => {
    const { get } = run([T('A', '2026-10-08', 3), T('B', '2026-10-05', 1)], [L('A', 'B')], WORK)
    expect(get('A').end).toBe('2026-10-13')
    expect(get('B').start).toBe('2026-10-13')
  })
  it('FS from a Friday finish starts on Monday', () => {
    const { get } = run([T('A', '2026-10-05', 5), T('B', '2026-10-05', 1)], [L('A', 'B')], WORK)
    expect(get('B')).toMatchObject({ start: '2026-10-12', end: '2026-10-13' })
  })
  it('FS lag counts working days', () => {
    const { get } = run([T('A', '2026-10-05', 5), T('B', '2026-10-05', 3)], [L('A', 'B', 'FS', 2)], WORK)
    expect(get('B')).toMatchObject({ start: '2026-10-14', end: '2026-10-17' })
  })
  it('FS lead counts working days back', () => {
    const { get } = run([T('A', '2026-10-05', 5), T('B', '2026-10-01', 2)], [L('A', 'B', 'FS', -1)], WORK)
    expect(get('B')).toMatchObject({ start: '2026-10-09', end: '2026-10-13' })
  })
  it('FS landing on a holiday moves to the next working day', () => {
    const { get } = run([T('A', '2026-10-05', 5), T('B', '2026-10-05', 1)], [L('A', 'B')], { ...WORK, holidays: ['2026-10-12'] })
    expect(get('B').start).toBe('2026-10-13')
  })
  it('SS lag over a weekend snaps to Monday', () => {
    const { get } = run([T('A', '2026-10-08', 5), T('B', '2026-10-05', 1)], [L('A', 'B', 'SS', 2)], WORK)
    expect(get('B').start).toBe('2026-10-12')
  })
  it('FF with zero lag ends together', () => {
    const { get } = run([T('A', '2026-10-05', 5), T('B', '2026-10-05', 2)], [L('A', 'B', 'FF')], WORK)
    expect(get('B')).toMatchObject({ start: '2026-10-08', end: '2026-10-10' })
  })
  it('SF with a lag in working days', () => {
    const { get } = run([T('A', '2026-10-05', 5), T('B', '2026-10-01', 2)], [L('A', 'B', 'SF', 3)], WORK)
    expect(get('B')).toMatchObject({ start: '2026-10-06', end: '2026-10-08' })
  })
  it('a milestone after a Friday finish sits on Monday', () => {
    const { get } = run([T('A', '2026-10-05', 5), T('M', '2026-10-05', 0)], [L('A', 'M')], WORK)
    expect(get('M')).toMatchObject({ start: '2026-10-12', end: '2026-10-12', totalSlack: 0, critical: true })
  })
  it('slack counts working days', () => {
    const { get } = run([T('A', '2026-10-05', 10), T('B', '2026-10-05', 5)], [], WORK)
    expect(get('B').totalSlack).toBe(5)
  })
  it('supports a Sunday to Thursday week', () => {
    const cal = { mode: 'working' as const, workdays: [7, 1, 2, 3, 4], holidays: [] }
    const { get } = run([T('A', '2026-10-07', 2), T('B', '2026-10-05', 1)], [L('A', 'B')], cal)
    // Wed 7 + Thu 8 -> exclusive Fri 9, next working day Sun 11.
    expect(get('B').start).toBe('2026-10-11')
  })
})

describe('mixed chains and slack', () => {
  it('chain SS, FF, FS lead: everything critical', () => {
    const tasks = [T('A', '2026-10-05', 4), T('B', '2026-10-01', 3), T('C', '2026-10-01', 2), T('D', '2026-10-01', 1)]
    const links = [L('A', 'B', 'SS', 1), L('B', 'C', 'FF', 2), L('C', 'D', 'FS', -1)]
    const { get, r } = run(tasks, links)
    expect(get('B')).toMatchObject({ start: '2026-10-06', end: '2026-10-09' })
    expect(get('C')).toMatchObject({ start: '2026-10-09', end: '2026-10-11' })
    expect(get('D')).toMatchObject({ start: '2026-10-10', end: '2026-10-11' })
    expect(r.criticalIds).toEqual(['A', 'B', 'C', 'D'])
  })
  it('parallel branches: the short branch has slack', () => {
    const tasks = [T('A', '2026-10-05', 2), T('B', '2026-10-05', 5), T('C', '2026-10-05', 2), T('D', '2026-10-05', 1)]
    const { get } = run(tasks, [L('A', 'B'), L('A', 'C'), L('B', 'D'), L('C', 'D')])
    expect(get('D').start).toBe('2026-10-12')
    expect(get('C')).toMatchObject({ totalSlack: 3, freeSlack: 3, critical: false, lateStart: '2026-10-10', lateEnd: '2026-10-12' })
    expect(get('B').critical).toBe(true)
    expect(get('A').critical).toBe(true)
  })
  it('free slack is smaller than total slack when the successor has slack', () => {
    const tasks = [T('A', '2026-10-05', 10), T('B', '2026-10-05', 2), T('C', '2026-10-10', 2)]
    const { get } = run(tasks, [L('B', 'C')])
    expect(get('C')).toMatchObject({ totalSlack: 3, freeSlack: 3 })
    expect(get('B')).toMatchObject({ totalSlack: 6, freeSlack: 3 })
  })
  it('free slack through an SS link', () => {
    const tasks = [T('A', '2026-10-05', 10), T('B', '2026-10-05', 2), T('C', '2026-10-09', 2)]
    const { get } = run(tasks, [L('B', 'C', 'SS', 1)])
    expect(get('B').freeSlack).toBe(3)
  })
  it('a milestone at the end of the chain is critical', () => {
    const { get } = run([T('A', '2026-10-05', 5), T('M', '2026-10-01', 0)], [L('A', 'M')])
    expect(get('M')).toMatchObject({ start: '2026-10-10', end: '2026-10-10', totalSlack: 0, critical: true })
  })
})

describe('push vs pull', () => {
  const tasks = [T('A', '2026-10-05', 3), T('B', '2026-10-20', 2), T('C', '2026-10-20', 2)]
  const links = [L('A', 'C')]
  it('push keeps later starts', () => {
    const { get } = run(tasks, links)
    expect(get('B').start).toBe('2026-10-20')
    expect(get('C').start).toBe('2026-10-20')
  })
  it('pull starts free tasks at the project start and linked ones after their predecessors', () => {
    const { get } = run(tasks, links, CAL, { pull: true })
    expect(get('B').start).toBe('2026-10-05')
    expect(get('C').start).toBe('2026-10-08')
  })
  it('pull honours an explicit project start', () => {
    const { get } = run(tasks, links, CAL, { pull: true, projectStart: '2026-10-01' })
    expect(get('A').start).toBe('2026-10-01')
    expect(get('C').start).toBe('2026-10-04')
  })
  it('pull still respects snet', () => {
    const t2 = [T('A', '2026-10-05', 3), T('B', '2026-10-20', 2, { constraint: { type: 'snet', date: '2026-10-07' } })]
    expect(run(t2, [], CAL, { pull: true }).get('B').start).toBe('2026-10-07')
  })
  it('autoSchedulePatches lists only moved tasks', () => {
    const p = autoSchedulePatches([T('A', '2026-10-05', 3), T('B', '2026-10-05', 1), T('C', '2026-10-20', 1)], [L('A', 'B'), L('A', 'C')], CAL)
    expect(p).toEqual([{ id: 'B', patch: { start: '2026-10-08' } }])
  })
  it('autoSchedulePatches in pull mode moves tasks earlier', () => {
    const p = autoSchedulePatches([T('A', '2026-10-05', 3), T('C', '2026-10-20', 1)], [L('A', 'C')], CAL, { pull: true })
    expect(p).toEqual([{ id: 'C', patch: { start: '2026-10-08' } }])
  })
  it('autoSchedulePatches never patches summaries', () => {
    const p = autoSchedulePatches([T('S', '2026-01-01', 0), T('A', '2026-10-05', 1, { parentId: 'S' })], [], CAL)
    expect(p).toEqual([])
  })
})

describe('constraints', () => {
  it('asap has no effect', () => {
    expect(run([T('A', '2026-10-05', 3, { constraint: { type: 'asap' } })]).get('A').start).toBe('2026-10-05')
  })
  it('snet pushes a task later', () => {
    expect(run([T('A', '2026-10-05', 3, { constraint: { type: 'snet', date: '2026-10-07' } })]).get('A').start).toBe('2026-10-07')
  })
  it('snet earlier than the start keeps the start (push)', () => {
    expect(run([T('A', '2026-10-05', 3, { constraint: { type: 'snet', date: '2026-10-01' } })]).get('A').start).toBe('2026-10-05')
  })
  it('snet on a Sunday in working mode starts Monday', () => {
    const { get } = run([T('A', '2026-10-05', 1, { constraint: { type: 'snet', date: '2026-10-11' } })], [], WORK)
    expect(get('A').start).toBe('2026-10-12')
  })
  it('mso pins the start, even earlier than planned', () => {
    const { get, r } = run([T('A', '2026-10-10', 3, { constraint: { type: 'mso', date: '2026-10-07' } })])
    expect(get('A').start).toBe('2026-10-07')
    expect(r.issues).toEqual([])
  })
  it('mso before a predecessor ends: conflict and negative slack', () => {
    const tasks = [T('A', '2026-10-05', 5), T('B', '2026-10-05', 2, { constraint: { type: 'mso', date: '2026-10-08' } })]
    const { get, r } = run(tasks, [L('A', 'B')])
    expect(get('B').start).toBe('2026-10-08')
    expect(get('A').totalSlack).toBe(-2)
    expect(get('A').critical).toBe(true)
    // The conflict is reported by validate on the dates as they stand (pinned link).
    expect(r.issues).toEqual([])
    expect(validate(tasks, [L('A', 'B')], CAL).filter((i) => i.code === 'constraint_conflict')[0]).toMatchObject({ level: 'warning', taskId: 'B' })
  })
  it('mfo pins the (exclusive) finish', () => {
    const { get } = run([T('A', '2026-10-01', 3, { constraint: { type: 'mfo', date: '2026-10-12' } })])
    expect(get('A')).toMatchObject({ start: '2026-10-09', end: '2026-10-12' })
  })
  it('mfo in working mode', () => {
    const { get } = run([T('A', '2026-10-01', 2, { constraint: { type: 'mfo', date: '2026-10-13' } })], [], WORK)
    expect(get('A')).toMatchObject({ start: '2026-10-09', end: '2026-10-13' })
  })
  it('mfo conflicting with a predecessor is reported', () => {
    const tasks = [T('A', '2026-10-05', 5), T('B', '2026-10-05', 2, { constraint: { type: 'mfo', date: '2026-10-09' } })]
    expect(validate(tasks, [L('A', 'B')], CAL).map((i) => i.code)).toContain('constraint_conflict')
  })
  it('fnlt met: slack against the constraint date', () => {
    const { get, r } = run([T('A', '2026-10-05', 3, { constraint: { type: 'fnlt', date: '2026-10-10' } }), T('B', '2026-10-05', 10)])
    expect(get('A').totalSlack).toBe(2)
    expect(r.issues).toEqual([])
  })
  it('fnlt missed: warning and negative slack', () => {
    const tasks = [T('A', '2026-10-05', 5, { constraint: { type: 'fnlt', date: '2026-10-08' } })]
    const { get } = run(tasks)
    expect(get('A').totalSlack).toBe(-2)
    expect(get('A').critical).toBe(true)
    expect(validate(tasks, [], CAL)[0]).toMatchObject({ code: 'constraint_conflict', taskId: 'A' })
  })
  it('fnlt does not move the task forward', () => {
    expect(run([T('A', '2026-10-05', 5, { constraint: { type: 'fnlt', date: '2026-10-08' } })]).get('A').start).toBe('2026-10-05')
  })
  it('a constraint without a date is ignored', () => {
    expect(run([T('A', '2026-10-05', 3, { constraint: { type: 'snet', date: null } })]).get('A').start).toBe('2026-10-05')
  })
})

describe('idea tasks', () => {
  it('are left out of the finish, slack and critical path', () => {
    const { get, r } = run([T('A', '2026-10-05', 5), T('I', '2026-10-05', 20, { isIdea: true })])
    expect(r.finish).toBe('2026-10-10')
    expect(get('I')).toMatchObject({ totalSlack: null, freeSlack: null, critical: false })
    expect(get('A').critical).toBe(true)
  })
  it('a link out of an idea never drives (forward, push, critical path); links into an idea drive it', () => {
    const { get } = run([T('I', '2026-10-05', 3, { isIdea: true }), T('A', '2026-10-05', 2)], [L('I', 'A')])
    expect(get('A').start).toBe('2026-10-05')
    expect(get('I').critical).toBe(false)
    const into = run([T('A', '2026-10-05', 2), T('I', '2026-10-01', 3, { isIdea: true })], [L('A', 'I')])
    expect(into.get('I').start).toBe('2026-10-07')
    const tasks = [T('I', '2026-10-05', 3, { isIdea: true }), T('A', '2026-10-05', 2), T('B', '2026-10-07', 1)]
    const lk = [L('I', 'A'), L('A', 'B')]
    expect(push(tasks, lk, CAL, ['I'])).toEqual([])
    expect([...downstream(tasks, lk, ['I']).keys()]).toEqual([])
  })
  it('a summary drives exactly when committed work lies below it; its own flag is ignored', () => {
    const ideaOnly = [T('S', '2026-10-05', 0), T('I', '2026-10-05', 5, { parentId: 'S', isIdea: true }), T('A', '2026-10-05', 2)]
    expect(run(ideaOnly, [L('S', 'A')]).get('A').start).toBe('2026-10-05')
    const mixed = [T('S', '2026-10-05', 0, { isIdea: true }), T('R', '2026-10-05', 3, { parentId: 'S' }), T('A', '2026-10-05', 2)]
    expect(run(mixed, [L('S', 'A')]).get('A').start).toBe('2026-10-08')
  })
  it('warns bank_build_late when the idea ends after its successor starts', () => {
    const issues = validate([T('I', '2026-10-05', 3, { isIdea: true }), T('A', '2026-10-06', 2)], [L('I', 'A')], CAL)
    expect(issues.map((i) => [i.code, i.level])).toEqual([['bank_build_late', 'warning']])
    expect(validate([T('I', '2026-10-01', 3, { isIdea: true }), T('A', '2026-10-06', 2)], [L('I', 'A')], CAL)).toEqual([])
    // any link type: the idea's end against the linked block's start
    expect(validate([T('I', '2026-10-05', 3, { isIdea: true }), T('A', '2026-10-06', 2)], [L('I', 'A', 'SS')], CAL).map((i) => i.code)).toEqual(['bank_build_late'])
  })
  it('only the idea flag of the leaf counts (backend rule), not an idea summary', () => {
    const { get, r } = run([T('S', '2026-10-05', 0, { isIdea: true }), T('A', '2026-10-05', 9, { parentId: 'S' }), T('B', '2026-10-05', 2, { isIdea: true })])
    expect(r.finish).toBe('2026-10-14')
    expect(get('A').totalSlack).toBe(0)
    expect(get('B').totalSlack).toBeNull()
  })
  it('a plan of only ideas has no finish', () => {
    expect(run([T('I', '2026-10-05', 3, { isIdea: true })]).r.finish).toBeNull()
  })
})

describe('summary tasks', () => {
  it('roll up start, end and weighted progress', () => {
    const tasks = [T('S', '2026-01-01', 0), T('A', '2026-10-05', 3, { parentId: 'S', progress: 100 }), T('B', '2026-10-10', 2, { parentId: 'S', progress: 0 })]
    const { get } = run(tasks)
    expect(get('S')).toMatchObject({ start: '2026-10-05', end: '2026-10-12', isSummary: true, progress: 60 })
  })
  it('roll up nested levels', () => {
    const tasks = [T('S', '2026-01-01', 0), T('S2', '2026-01-01', 0, { parentId: 'S' }), T('A', '2026-10-05', 3, { parentId: 'S2' }), T('B', '2026-10-20', 1, { parentId: 'S' })]
    const { get } = run(tasks)
    expect(get('S2')).toMatchObject({ start: '2026-10-05', end: '2026-10-08' })
    expect(get('S')).toMatchObject({ start: '2026-10-05', end: '2026-10-21' })
  })
  it('take the minimum slack of their leaves and are critical with them', () => {
    const tasks = [T('S', '2026-01-01', 0), T('A', '2026-10-05', 3, { parentId: 'S' }), T('B', '2026-10-05', 10, { parentId: 'S' })]
    const { get } = run(tasks)
    expect(get('A').totalSlack).toBe(7)
    // Summary free slack is the minimum of its children (backend rule).
    expect(get('S')).toMatchObject({ totalSlack: 0, critical: true, freeSlack: 0 })
  })
  it('a summary with only slack leaves is not critical', () => {
    const tasks = [T('S', '2026-01-01', 0), T('A', '2026-10-05', 3, { parentId: 'S' }), T('X', '2026-10-05', 10)]
    expect(run(tasks).get('S')).toMatchObject({ totalSlack: 7, critical: false })
  })
  it('a link into a summary applies to every leaf', () => {
    const tasks = [T('X', '2026-10-05', 5), T('S', '2026-01-01', 0), T('A', '2026-10-05', 2, { parentId: 'S' }), T('B', '2026-10-06', 1, { parentId: 'S' })]
    const { get } = run(tasks, [L('X', 'S')])
    expect(get('A').start).toBe('2026-10-10')
    expect(get('B').start).toBe('2026-10-10')
    expect(get('S')).toMatchObject({ start: '2026-10-10', end: '2026-10-12' })
  })
  it('an FF or SF link into a summary is refused: not scheduled, reported', () => {
    const tasks = [T('X', '2026-10-05', 5), T('S', '2026-01-01', 0), T('A', '2026-10-05', 2, { parentId: 'S' }), T('B', '2026-10-05', 4, { parentId: 'S' })]
    for (const type of ['FF', 'SF'] as const) {
      const { get } = run(tasks, [L('X', 'S', type)])
      expect(get('A').start).toBe('2026-10-05')
      expect(get('B').start).toBe('2026-10-05')
      expect(validate(tasks, [L('X', 'S', type)], CAL).map((i) => i.code)).toContain('summary_finish_link')
    }
  })
  it('mso / mfo on a summary are refused: not scheduled, reported', () => {
    const tasks = [T('S', '2026-01-01', 0, { constraint: { type: 'mso', date: '2026-10-20' } }), T('A', '2026-10-05', 2, { parentId: 'S' })]
    expect(run(tasks).get('A').start).toBe('2026-10-05')
    expect(validate(tasks, [], CAL).map((i) => i.code)).toContain('summary_pin')
  })
  it('fnlt on a summary caps the late finish of its leaves and warns on the rolled-up finish', () => {
    const tasks = [T('S', '2026-01-01', 0, { constraint: { type: 'fnlt', date: '2026-10-08' } }), T('A', '2026-10-05', 5, { parentId: 'S' }), T('X', '2026-10-05', 9)]
    expect(run(tasks).get('A').totalSlack).toBe(-2)
    expect(validate(tasks, [], CAL).find((i) => i.code === 'constraint_conflict')).toMatchObject({ taskId: 'S' })
  })
  it('an SF link out of a summary reads its earliest start', () => {
    const tasks = [T('S', '2026-01-01', 0), T('A', '2026-10-07', 2, { parentId: 'S' }), T('B', '2026-10-05', 6, { parentId: 'S' }), T('Y', '2026-10-01', 2)]
    // SF: Y.end >= S.start (5 Oct) + 3 -> Y ends 8 Oct, starts 6 Oct.
    expect(run(tasks, [L('S', 'Y', 'SF', 3)]).get('Y').start).toBe('2026-10-06')
  })
  it('a link between a summary and its own leaf is ignored with a warning, not a cycle', () => {
    const tasks = [T('S', '2026-01-01', 0), T('A', '2026-10-05', 2, { parentId: 'S' }), T('B', '2026-10-05', 1, { parentId: 'S' })]
    const { r, get } = run(tasks, [L('S', 'B')])
    expect(r.cycle).toEqual([])
    expect(get('B').start).toBe('2026-10-05')
    expect(validate(tasks, [L('S', 'B')], CAL).map((i) => i.code)).toEqual(['summary_link'])
  })
  it('an FS link out of a summary waits for its last leaf', () => {
    const tasks = [T('S', '2026-01-01', 0), T('A', '2026-10-05', 2, { parentId: 'S' }), T('B', '2026-10-05', 6, { parentId: 'S' }), T('Y', '2026-10-05', 1)]
    const { get } = run(tasks, [L('S', 'Y')])
    expect(get('Y').start).toBe('2026-10-11')
    expect(get('A').totalSlack).toBe(4)
    expect(get('B').critical).toBe(true)
  })
  it('an SS link out of a summary uses its earliest leaf start', () => {
    const tasks = [T('S', '2026-01-01', 0), T('A', '2026-10-07', 2, { parentId: 'S' }), T('B', '2026-10-05', 6, { parentId: 'S' }), T('Y', '2026-10-01', 1)]
    expect(run(tasks, [L('S', 'Y', 'SS', 1)]).get('Y').start).toBe('2026-10-06')
  })
  it('a constraint on a summary pushes its leaves', () => {
    const tasks = [T('S', '2026-01-01', 0, { constraint: { type: 'snet', date: '2026-10-08' } }), T('A', '2026-10-05', 2, { parentId: 'S' })]
    expect(run(tasks).get('A').start).toBe('2026-10-08')
  })
  it('links into nested summaries reach the deepest leaves', () => {
    const tasks = [T('X', '2026-10-05', 3), T('S', '2026-01-01', 0), T('S2', '2026-01-01', 0, { parentId: 'S' }), T('A', '2026-10-05', 1, { parentId: 'S2' })]
    expect(run(tasks, [L('X', 'S')]).get('A').start).toBe('2026-10-08')
  })
})

describe('cycles', () => {
  it('detects a two-task loop and keeps the planned dates', () => {
    const { r, get } = run([T('A', '2026-10-05', 3), T('B', '2026-10-05', 2)], [L('A', 'B'), L('B', 'A')])
    expect(new Set(r.cycle)).toEqual(new Set(['A', 'B']))
    expect(get('B').start).toBe('2026-10-05')
    expect(get('A').totalSlack).toBeNull()
    expect(r.criticalIds).toEqual([])
    expect(r.issues[0]).toMatchObject({ code: 'cycle', level: 'error' })
  })
  it('a self link is not scheduled but findCycle and validate report it', () => {
    const tasks = [T('A', '2026-10-05', 3)]
    expect(run(tasks, [L('A', 'A')]).r.cycle).toEqual([])
    expect(findCycle(tasks, [L('A', 'A')])).toEqual(['A'])
    expect(validate(tasks, [L('A', 'A')], CAL).map((i) => i.code)).toEqual(['self_link', 'cycle'])
  })
  it('a link from a child to its own summary is not a cycle', () => {
    const tasks = [T('S', '2026-01-01', 0), T('A', '2026-10-05', 2, { parentId: 'S' })]
    expect(run(tasks, [L('A', 'S')]).r.cycle).toEqual([])
    expect(wouldCycle(tasks, [], 'A', 'S')).toBe(false)
  })
  it('detects a three-task loop', () => {
    const tasks = [T('A', '2026-10-05', 1), T('B', '2026-10-05', 1), T('C', '2026-10-05', 1), T('D', '2026-10-05', 1)]
    const r = findCycle(tasks, [L('A', 'B'), L('B', 'C'), L('C', 'A'), L('C', 'D')])
    expect(new Set(r).has('A')).toBe(true)
  })
  it('findCycle is empty for a DAG', () => {
    expect(findCycle([T('A', '2026-10-05', 1), T('B', '2026-10-05', 1)], [L('A', 'B')])).toEqual([])
  })
  it('wouldCycle', () => {
    const tasks = [T('A', '2026-10-05', 1), T('B', '2026-10-05', 1), T('C', '2026-10-05', 1)]
    const links = [L('A', 'B'), L('B', 'C')]
    expect(wouldCycle(tasks, links, 'C', 'A')).toBe(true)
    expect(wouldCycle(tasks, links, 'A', 'C')).toBe(false)
    expect(wouldCycle(tasks, links, 'B', 'B')).toBe(true)
  })
  it('autoSchedulePatches does nothing on a cycle', () => {
    expect(autoSchedulePatches([T('A', '2026-10-05', 3), T('B', '2026-10-05', 2)], [L('A', 'B'), L('B', 'A')], CAL)).toEqual([])
  })
  it('rolls summaries up even on a cycle', () => {
    const tasks = [T('S', '2026-01-01', 0), T('A', '2026-10-05', 2, { parentId: 'S' }), T('B', '2026-10-05', 1)]
    const { get, r } = run(tasks, [L('B', 'A'), L('A', 'B')])
    expect(r.cycle.length).toBeGreaterThan(0)
    expect(get('S')).toMatchObject({ start: '2026-10-05', end: '2026-10-07', totalSlack: null })
  })
})

describe('cascade and downstream (backend parity, review)', () => {
  it('pushes successors, successors of summaries above, and leaves under a linked summary; pinned stay', () => {
    const tasks = [
      T('A', '2026-10-05', 3), T('S', '2026-01-01', 0), T('B', '2026-10-08', 2, { parentId: 'S' }),
      T('C', '2026-10-10', 1), T('D', '2026-10-10', 1, { constraint: { type: 'mso', date: '2026-10-10' } }),
    ]
    const links = [L('A', 'S'), L('S', 'C'), L('A', 'D')]
    const moved = { ...tasks[0], start: '2026-10-07' }
    const r = cascade([moved, ...tasks.slice(1)], links, CAL, ['A'])
    expect(r.map((m) => [m.id, m.patch.start, m.cause])).toEqual([['B', '2026-10-10', 'A'], ['C', '2026-10-12', 'A']])
    expect([...downstream(tasks, links, ['A']).keys()].sort()).toEqual(['B', 'C', 'D'])
  })
  it('only moves later, never pulls a successor earlier', () => {
    expect(cascade([T('A', '2026-10-01', 2), T('B', '2026-10-20', 1)], [L('A', 'B')], CAL, ['A'])).toEqual([])
  })
})

describe('cascade keeps started tasks (review)', () => {
  it('a task with an actual start is not moved, but its successors are', () => {
    const tasks = [T('A', '2026-10-07', 3), T('B', '2026-10-08', 2, { actualStart: '2026-10-08' }), T('C', '2026-10-10', 1)]
    const r = cascade(tasks, [L('A', 'B'), L('B', 'C')], CAL, ['A'])
    // B would be pushed to 10 Oct, but it has started; C after B's unchanged end stays too.
    expect(r.map((m) => m.id)).toEqual([])
  })
  it('the walk continues through a started task to its successors', () => {
    const tasks = [T('A', '2026-10-09', 3), T('B', '2026-10-08', 2, { actualStart: '2026-10-08' }), T('C', '2026-10-10', 1)]
    // B stays (started) even though A now ends 12 Oct; C follows B (ends 10 Oct): not pushed; C also after A directly.
    const r = cascade(tasks, [L('A', 'B'), L('B', 'C'), L('A', 'C')], CAL, ['A'])
    expect(r.map((m) => [m.id, m.patch.start])).toEqual([['C', '2026-10-12']])
  })
})

describe('summary progress rollup (review 2, backend parity)', () => {
  it('weights nested summaries by their rolled-up span and rounds half-up', () => {
    // Inner summary S2 spans 5..15 Oct (10 days, 50%), leaf C 10 days at 0%: T = 25 exactly; X at 1/2.
    const tasks = [
      T('T', '2026-01-01', 0), T('S2', '2026-01-01', 0, { parentId: 'T' }),
      T('A', '2026-10-05', 2, { parentId: 'S2', progress: 100 }), T('B', '2026-10-13', 2, { parentId: 'S2', progress: 0 }),
      T('C', '2026-10-05', 10, { parentId: 'T', progress: 0 }),
      T('H', '2026-01-01', 0), T('H1', '2026-10-05', 1, { parentId: 'H', progress: 50 }), T('H2', '2026-10-05', 1, { parentId: 'H', progress: 0 }),
    ]
    const { get } = run(tasks)
    expect(get('S2').progress).toBe(50)
    expect(get('T').progress).toBe(25)
    expect(get('H').progress).toBe(25)
    const half = run([T('H', '2026-01-01', 0), T('H1', '2026-10-05', 1, { parentId: 'H', progress: 5 }), T('H2', '2026-10-05', 1, { parentId: 'H', progress: 0 })])
    expect(half.get('H').progress).toBe(3) // 2.5 rounds up
  })
  it('has no NaN progress for summaries in a cycle', () => {
    const tasks = [T('S', '2026-01-01', 0), T('A', '2026-10-05', 2, { parentId: 'S', progress: 40 }), T('B', '2026-10-05', 2)]
    const { get, r } = run(tasks, [L('A', 'B'), L('B', 'A')])
    expect(r.cycle.length).toBeGreaterThan(0)
    expect(get('S').progress).toBe(40)
  })
})

describe('automatic scheduling rules (backend push parity)', () => {
  it('a task moved under a summary with a predecessor jumps later (parent change may move it)', () => {
    const tasks = [T('X', '2026-10-05', 5), T('S', '2026-01-01', 0), T('A', '2026-10-12', 2, { parentId: 'S' }), T('B', '2026-10-05', 2)]
    const model = { tasks, links: [L('X', 'S')] }
    const r = autoPushChangeSet(model, { updateTasks: [{ id: 'B', patch: { parentId: 'S' } }] }, CAL)
    expect(r.cs.updateTasks).toEqual([{ id: 'B', patch: { parentId: 'S', start: '2026-10-10' } }])
    // The start came from the push (the server makes it too); the parent is the user's.
    expect(r.cs.meta?.derived).toEqual(['B'])
  })
  it('a new task linked after another is placed after it', () => {
    const tasks = [T('X', '2026-10-05', 5)]
    const r = autoPushChangeSet({ tasks, links: [] }, {
      addTasks: [T('N', '2026-10-05', 2)], addLinks: [L('X', 'N')],
    }, CAL)
    expect(r.cs.addTasks![0].start).toBe('2026-10-10')
  })
  it('snet on a summary pushes the leaves below it', () => {
    const tasks = [T('S', '2026-01-01', 0, { constraint: { type: 'snet', date: '2026-10-20' } }), T('A', '2026-10-05', 2, { parentId: 'S' })]
    const moves = push(tasks, [], CAL, [], ['S'])
    expect(moves.map((m) => [m.id, m.patch.start])).toEqual([['A', '2026-10-20']])
  })
  it('a summary source walks from its start gate: its leaves and what they drive (backend parity)', () => {
    const tasks = [T('S', '2026-01-01', 0), T('A', '2026-10-05', 2, { parentId: 'S' }), T('B', '2026-10-06', 2)]
    const cause = downstream(tasks, [L('A', 'B')], ['S'])
    expect([...cause.entries()].sort()).toEqual([['A', 'S'], ['B', 'S']])
  })
  it('a moved task that now violates a link from another moved task is pushed', () => {
    const tasks = [T('A', '2026-10-08', 5), T('B', '2026-10-06', 2)]
    const moves = push(tasks, [L('A', 'B')], CAL, ['A', 'B'])
    expect(moves.map((m) => [m.id, m.patch.start])).toEqual([['B', '2026-10-13']])
    expect([...downstream(tasks, [L('A', 'B')], ['A', 'B']).entries()]).toEqual([])
    expect([...downstream(tasks, [L('A', 'B')], ['A', 'B'], { stop: false }).entries()]).toEqual([['B', 'A']])
  })
})
