/**
 * Shared scheduling vectors: the backend service and this engine must agree.
 *
 * Format (backend/tests/data/gantt_vectors.json, and the sample fixture next
 * to this file):
 * {"cases": [{
 *   "name": "fs chain",
 *   "calendar": {"mode": "calendar"|"working", "workdays": [1..7, Mon=1], "holidays": ["YYYY-MM-DD"]},
 *   "options": {"pull": false,                        // optional, default push
 *               "cycle": true,                        // optional: the plan has a loop
 *               "refused": "summary_pin",             // optional: validate reports this error
 *               "push": {"sources": ["A"], "also": []}},  // optional: the push of an edit (only driven tasks move)
 *   "tasks": [{"id": 1, "start": "YYYY-MM-DD", "duration": 5,
 *              "constraint": {"type": "snet", "date": "YYYY-MM-DD"},   // optional
 *              "parentId": null, "isIdea": false}],                    // optional
 *   "links": [{"from": 1, "to": 2, "type": "FS", "lag": 2}],
 *   "expected": {"<id>": {"start": "YYYY-MM-DD", "end": "YYYY-MM-DD" (exclusive),
 *                          "total_slack": 0 | null, "critical": true,
 *                          "free_slack": 0 (optional)}}
 * }]}
 * Only the keys present in `expected` are compared.
 */
import { describe, expect, it } from 'vitest'
import { pushSchedule, schedule } from './schedule'
import { validate } from './validate'
import type { GanttCalendar, GanttLink, GanttTask, LinkType } from './types'
import sample from './__fixtures__/gantt_vectors.sample.json'

export interface VectorCase {
  name: string
  calendar?: Partial<GanttCalendar>
  options?: { pull?: boolean; projectStart?: string; cycle?: boolean; refused?: string; push?: { sources: (string | number)[]; also: (string | number)[] } }
  tasks: { id: number | string; start: string; duration: number; constraint?: GanttTask['constraint']; parentId?: number | string | null; isIdea?: boolean }[]
  links: { from: number | string; to: number | string; type: LinkType; lag: number }[]
  expected: Record<string, { start?: string; end?: string; total_slack?: number | null; critical?: boolean; free_slack?: number | null }>
}

export function runVector(c: VectorCase) {
  const tasks: GanttTask[] = c.tasks.map((t) => ({ ...t, name: `T${t.id}` }))
  const links: GanttLink[] = c.links.map((l, i) => ({ id: `v${i}`, from: l.from, to: l.to, type: l.type, lagDays: l.lag }))
  // push: only what the sources drive (and `also` tasks) may move; everything else keeps its dates.
  const r = c.options?.push
    ? pushSchedule(tasks, links, c.calendar, c.options.push.sources, c.options.push.also).result
    : schedule(tasks, links, c.calendar, c.options)
  if (c.options?.cycle !== undefined && (r.cycle.length > 0) !== c.options.cycle) throw new Error(`cycle expected ${c.options.cycle}`)
  if (c.options?.refused) {
    const codes = validate(tasks, links, c.calendar).filter((i) => i.level === 'error').map((i) => i.code)
    if (!codes.includes(c.options.refused)) throw new Error(`expected error ${c.options.refused}, got ${codes.join(', ')}`)
  }
  const got: VectorCase['expected'] = {}
  for (const [id, exp] of Object.entries(c.expected)) {
    const s = [...r.byId.values()].find((x) => String(x.id) === id)
    if (!s) { got[id] = {}; continue }
    const o: VectorCase['expected'][string] = {}
    if ('start' in exp) o.start = s.start
    if ('end' in exp) o.end = s.end
    if ('total_slack' in exp) o.total_slack = s.totalSlack
    if ('critical' in exp) o.critical = s.critical
    if ('free_slack' in exp) o.free_slack = s.freeSlack
    got[id] = o
  }
  return got
}

// Vite resolves this at build time; an empty object when the backend file does not exist yet.
const backendFiles = import.meta.glob('../../../../../backend/tests/data/gantt_vectors.json', { eager: true, import: 'default' })

describe('shared vectors (frontend sample fixture)', () => {
  for (const c of (sample as unknown as { cases: VectorCase[] }).cases) {
    it(c.name, () => expect(runVector(c)).toEqual(c.expected))
  }
})

const backend = Object.values(backendFiles)[0] as { cases: VectorCase[] } | undefined
describe.skipIf(!backend)('shared vectors (backend/tests/data/gantt_vectors.json)', () => {
  for (const c of backend?.cases ?? []) {
    it(c.name, () => expect(runVector(c)).toEqual(c.expected))
  }
})
