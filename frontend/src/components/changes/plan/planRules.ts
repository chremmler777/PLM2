/**
 * Planning rules (Christoph 2026-11-09), the browser's copy of backend
 * services/plan_rules.py: a move that breaks one is refused before it is
 * sent, with the same message the server would give.
 *
 *  a. a tool change starts only after its mold bank build is finished;
 *  b. a trial starts only after the tool and gauge changes are finished;
 *  c. an assembly trial starts only after the line change is finished;
 *  d. a line change starts only after its assembly bank build is finished.
 *
 * A bank build linked into changes covers those; unlinked, it covers every
 * change of its pair. Only committed blocks are enforced (an idea warns).
 */
import { endOf, fmtIso, makeCal, normStart, toDay, toIso, type Cal } from '../../gantt/engine/calendar'
import { key } from '../../gantt/engine/tree'
import type { GanttCalendar, GanttLink, GanttModel, GanttTask } from '../../gantt/engine/types'

export type RuleRole = 'tool_change' | 'gauge_change' | 'line_change' | 'mold_bank_build'
  | 'assembly_bank_build' | 'trial' | 'assembly_trial'

export const ROLE_LABEL: Record<RuleRole, string> = {
  tool_change: 'Tool change', gauge_change: 'Gauge change', line_change: 'Line change',
  mold_bank_build: 'Mold bank build', assembly_bank_build: 'Assembly bank build',
  trial: 'Trial', assembly_trial: 'Assembly trial',
}

const TOOL_TAGS = new Set(['tool_change', 'steel_insert', 'hot_runner', 'tool_transfer'])
const GAUGE_TAGS = new Set(['gauge_change', 'measurement_equipment'])
const LINE_TAGS = new Set(['fixture_change', 'eoat_change', 'equipment_change', 'line_layout'])
const NEUTRAL_TAGS = new Set(['spare_part'])
const ASSEMBLY_DEPARTMENTS = new Set(['Manufacturing Engineer'])
const ASSEMBLY_RX = /assembl|montage|\bline\b|linie/i
const GAUGE_RX = /gauge|lehre|checking fixture|pr(?:ue|ü)fmittel/i
const TOOL_RX = /tool change|tool rework|werkzeug(?:ä|ae)nderung/i
const LINE_RX = /line change|assembly line|linien(?:ä|ae)nderung/i

/** Mirrors plan_rules.classify. */
export function classify(kind: string | null | undefined, name: string | null | undefined, lane: string | null | undefined,
  departmentName: string | null | undefined, tag: string | null | undefined): RuleRole | null {
  const k = kind || 'work'
  const n = name ?? ''
  const assemblyOwner = ASSEMBLY_DEPARTMENTS.has((lane ?? '').trim()) || ASSEMBLY_DEPARTMENTS.has((departmentName ?? '').trim())
  if (k === 'bank_build') return ASSEMBLY_RX.test(n) || assemblyOwner ? 'assembly_bank_build' : 'mold_bank_build'
  if (k === 'sampling') return ASSEMBLY_RX.test(n) || assemblyOwner ? 'assembly_trial' : 'trial'
  if (k !== 'work' && k !== 'supplier' && k !== 'downtime') return null
  if (tag && NEUTRAL_TAGS.has(tag)) return null
  if ((tag && GAUGE_TAGS.has(tag)) || GAUGE_RX.test(n)) return 'gauge_change'
  if ((tag && LINE_TAGS.has(tag)) || LINE_RX.test(n) || ((k === 'supplier' || k === 'downtime') && assemblyOwner)) return 'line_change'
  if ((tag && TOOL_TAGS.has(tag)) || k === 'downtime' || TOOL_RX.test(n)) return 'tool_change'
  return null
}

/** The role of a Gantt task from what it carries now (own lane, department, costing tag). */
export const roleOf = (t: GanttTask): RuleRole | null => classify(
  t.kind, t.name, (t.meta?.own_lane as string | null | undefined) ?? t.lane,
  t.meta?.department_name as string | null | undefined, t.meta?.source_tag as string | null | undefined)

export interface RuleViolation { code: string; message: string; taskId: string; otherId: string; idea: boolean }

export function checkRules(tasks: GanttTask[], links: GanttLink[], calendar?: GanttCalendar | null): RuleViolation[] {
  const cal: Cal = makeCal(calendar)
  const parents = new Set(tasks.map((t) => t.parentId).filter((p) => p != null).map((p) => key(p!)))
  const leaves = tasks.filter((t) => !parents.has(key(t.id)))
  const by: Record<RuleRole, GanttTask[]> = {
    tool_change: [], gauge_change: [], line_change: [], mold_bank_build: [], assembly_bank_build: [], trial: [], assembly_trial: [],
  }
  for (const t of leaves) { const r = roleOf(t); if (r) by[r].push(t) }
  const start = (t: GanttTask) => toDay(t.start)
  const end = (t: GanttTask) => endOf(cal, normStart(cal, toDay(t.start)), t.duration)
  const last = (t: GanttTask) => (t.duration > 0 ? end(t) - 1 : start(t))
  const linked = new Map<string, Set<string>>()
  for (const l of links) {
    const s = linked.get(key(l.from)) ?? new Set<string>()
    s.add(key(l.to)); linked.set(key(l.from), s)
  }
  const out: RuleViolation[] = []
  const add = (code: string, message: string, t: GanttTask, o: GanttTask) =>
    out.push({ code, message, taskId: key(t.id), otherId: key(o.id), idea: !!(t.isIdea || o.isIdea) })

  const banks = (bankRole: RuleRole, changeRole: RuleRole, code: string, what: string, word: string) => {
    for (const b of by[bankRole]) {
      const own = by[changeRole].filter((c) => linked.get(key(b.id))?.has(key(c.id)))
      for (const c of own.length ? own : by[changeRole]) {
        if (start(c) < end(b)) {
          add(code, `${what} '${c.name}' starts ${fmtIso(c.start)}, before the ${word} bank build '${b.name}' is finished `
            + `(${fmtIso(toIso(last(b)))}): the ${what.toLowerCase()} may only start after the ${word} bank build`, c, b)
        }
      }
    }
  }
  banks('mold_bank_build', 'tool_change', 'tool_change_during_bank_build', 'Tool change', 'mold')
  banks('assembly_bank_build', 'line_change', 'line_change_during_bank_build', 'Line change', 'assembly')

  const trials = (trialRole: RuleRole, pre: RuleRole[], code: string, what: string, needs: string) => {
    const before = pre.flatMap((r) => by[r])
    for (const tr of by[trialRole]) {
      const late = before.filter((p) => start(tr) < end(p))
      if (!late.length) continue
      const p = late.reduce((a, b) => (end(b) > end(a) ? b : a))
      add(code, `${what} '${tr.name}' starts ${fmtIso(tr.start)}, before '${p.name}' is finished (${fmtIso(toIso(last(p)))}): ${needs}`, tr, p)
    }
  }
  trials('trial', ['tool_change', 'gauge_change'], 'trial_before_change_done', 'Trial',
    'a trial may only start once the tool and gauge changes are finished')
  trials('assembly_trial', ['line_change'], 'assembly_trial_before_line_done', 'Assembly trial',
    'an assembly trial may only start once the line change is finished')
  return out
}

const keyOf = (v: RuleViolation) => `${v.code}|${v.taskId}|${v.otherId}`

/** The first rule a change newly breaks between committed blocks (old breaks never block), else null. */
export function newViolation(before: GanttModel, after: GanttModel, calendar?: GanttCalendar | null): RuleViolation | null {
  const had = new Set(checkRules(before.tasks, before.links, calendar).filter((v) => !v.idea).map(keyOf))
  return checkRules(after.tasks, after.links, calendar).find((v) => !v.idea && !had.has(keyOf(v))) ?? null
}
