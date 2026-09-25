/**
 * Plan checks that do not depend on a module's business rules. Adapters add
 * their own (buffers, deadlines) or show the server's list instead.
 */
import { endOf, isIsoDay, makeCal, normStart, shift, toDay } from './calendar'
import { findCycle, schedule } from './schedule'
import { buildTree, key } from './tree'
import type { GanttCalendar, GanttLink, GanttTask, Issue } from './types'

const err = (code: string, message: string, taskId: Issue['taskId'], linkId: Issue['linkId'] = null): Issue =>
  ({ level: 'error', code, message, taskId, linkId })
const warn = (code: string, message: string, taskId: Issue['taskId'], linkId: Issue['linkId'] = null): Issue =>
  ({ level: 'warning', code, message, taskId, linkId })

/** Is the link satisfied by the tasks' current dates? */
export function linkViolated(
  from: GanttTask, to: GanttTask, link: GanttLink, calendar?: Partial<GanttCalendar> | null,
): boolean {
  const cal = makeCal(calendar)
  const ps = normStart(cal, toDay(from.start))
  const pe = endOf(cal, ps, from.duration)
  const ss = normStart(cal, toDay(to.start))
  const se = endOf(cal, ss, to.duration)
  const lag = Math.round(link.lagDays || 0)
  switch (link.type) {
    case 'SS': return ss < normStart(cal, shift(cal, ps, lag))
    case 'FF': return se < shift(cal, pe, lag)
    case 'SF': return se < shift(cal, ps, lag)
    default: return ss < normStart(cal, shift(cal, pe, lag))
  }
}

export function validate(
  tasks: GanttTask[], links: GanttLink[], calendar?: Partial<GanttCalendar> | null,
): Issue[] {
  const out: Issue[] = []
  const tree = buildTree(tasks)
  const byId = tree.byId
  for (const t of tasks) {
    if (!(t.name ?? '').trim()) out.push(err('empty_name', 'A task has no name', t.id))
    if (!isIsoDay(t.start)) out.push(err('bad_date', `'${t.name}' has no valid start date`, t.id))
    if (!Number.isFinite(t.duration) || t.duration < 0) out.push(err('negative_duration', `'${t.name}' has a negative duration`, t.id))
    if (t.parentId != null && !byId.has(key(t.parentId))) out.push(warn('unknown_parent', `'${t.name}' has a parent that does not exist`, t.id))
    if (t.parentId != null && byId.has(key(t.parentId)) && tree.parentOf.get(key(t.id)) == null) {
      out.push(err('parent_loop', `'${t.name}' is nested inside itself`, t.id))
    }
    const c = t.constraint
    if (c && c.type !== 'asap' && !isIsoDay(c.date)) {
      out.push(err('constraint_date', `'${t.name}' has a ${c.type.toUpperCase()} constraint without a date`, t.id))
    }
    if ((t.progress ?? 0) < 0 || (t.progress ?? 0) > 100) out.push(err('progress_range', `'${t.name}' progress is outside 0 to 100`, t.id))
  }
  const seen = new Set<string>()
  for (const l of links) {
    const f = byId.get(key(l.from)), t = byId.get(key(l.to))
    if (!f || !t) { out.push(err('unknown_predecessor', 'A link points at a task that does not exist', t?.id ?? null, l.id)); continue }
    if (key(l.from) === key(l.to)) { out.push(err('self_link', `'${t.name}' is linked to itself`, t.id, l.id)); continue }
    const pair = `${key(l.from)}>${key(l.to)}`
    if (seen.has(pair)) out.push(warn('duplicate_link', `'${f.name}' and '${t.name}' are linked twice`, t.id, l.id))
    seen.add(pair)
    if (isIsoDay(f.start) && isIsoDay(t.start) && !tree.children.get(key(f.id))?.length
      && !tree.children.get(key(t.id))?.length && linkViolated(f, t, l, calendar)) {
      out.push(err('dependency_violation', `'${t.name}' is scheduled before its ${l.type} link from '${f.name}' allows`, t.id, l.id))
    }
  }
  const valid = tasks.every((t) => isIsoDay(t.start) && Number.isFinite(t.duration))
  const cycle = findCycle(tasks, links.filter((l) => byId.has(key(l.from)) && byId.has(key(l.to))))
  if (cycle.length) out.push(err('cycle', 'The dependencies form a loop', null))
  else if (valid) {
    for (const i of schedule(tasks, links, calendar).issues) out.push(i)
  }
  return out
}
