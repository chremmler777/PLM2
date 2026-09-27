/** Deterministic demo plans for the visual harness and component tests. */
import { addDaysIso } from '../engine/calendar'
import type { GanttLink, GanttModel, GanttTask, LinkType } from '../engine/types'
import type { GanttKindStyle } from '../theme'

export const DEMO_KINDS: Record<string, GanttKindStyle> = {
  work: { label: 'Work', color: '#0ea5e9' },
  supplier: { label: 'Supplier', color: '#8b5cf6' },
  downtime: { label: 'Tool downtime', color: '#f43f5e' },
  bank_build: { label: 'Bank build', color: '#f59e0b' },
  sampling: { label: 'Sampling', color: '#14b8a6' },
  validation: { label: 'Validation', color: '#10b981' },
  customer: { label: 'Customer', color: '#6366f1' },
  buffer: { label: 'Buffer', color: '#64748b', pattern: 'hatch' },
  milestone: { label: 'Milestone', color: '#e2e8f0', milestone: true },
}
const KIND_KEYS = Object.keys(DEMO_KINDS).filter((k) => k !== 'milestone')
const LANES = ['Development', 'Tool Engineer', 'Supplier', 'APQP', 'Customer', 'Scheduling']

/** Deterministic plan: phases of 10 tasks under a summary, chained with mixed link types. */
export function demoModel(n: number, start = '2026-10-05'): GanttModel {
  const tasks: GanttTask[] = []
  const links: GanttLink[] = []
  let seed = 7
  const rnd = () => { seed = (seed * 16807) % 2147483647; return seed / 2147483647 }
  let phase = 0
  let cursor = 0
  let prevLeaf: number | null = null
  let id = 1
  while (tasks.length < n) {
    const sumId = id++
    phase++
    tasks.push({ id: sumId, name: `Phase ${phase}: ${['Design', 'Tooling', 'Sampling', 'Validation', 'Launch'][phase % 5]}`, start: addDaysIso(start, cursor), duration: 1 })
    for (let i = 0; i < 9 && tasks.length < n; i++) {
      const tid = id++
      const ms = i === 8
      const dur = ms ? 0 : 1 + Math.floor(rnd() * 9)
      const kind = ms ? 'milestone' : KIND_KEYS[Math.floor(rnd() * KIND_KEYS.length)]
      tasks.push({
        id: tid, parentId: sumId, name: ms ? `Gate ${phase}` : `${DEMO_KINDS[kind].label} step ${phase}.${i + 1} with a longer name`,
        start: addDaysIso(start, cursor), duration: dur, kind, lane: LANES[Math.floor(rnd() * LANES.length)],
        progress: Math.floor(rnd() * 11) * 10, isIdea: kind === 'bank_build' && rnd() > 0.5,
        baselineStart: addDaysIso(start, cursor - 2), baselineEnd: addDaysIso(start, cursor - 2 + dur),
      })
      if (prevLeaf != null) {
        const r = rnd()
        const type: LinkType = r < 0.7 ? 'FS' : r < 0.82 ? 'SS' : r < 0.94 ? 'FF' : 'SF'
        const lag = type === 'FS' ? Math.floor(rnd() * 3) - 1 : 0
        links.push({ id: `l${tid}`, from: prevLeaf, to: tid, type, lagDays: lag })
      }
      cursor += Math.max(1, Math.floor(dur * 0.7))
      prevLeaf = tid
    }
  }
  return { tasks, links }
}

