/**
 * Plan checks on the dates as they stand. A port of the backend's
 * `engine_issues` (same codes and levels), plus a few model checks the
 * backend refuses on write (bad dates, parent loops, progress range,
 * constraint without a date, duplicate links).
 *
 * Errors: empty_name, bad_date, negative_duration, unknown_predecessor,
 * self_link, dependency_violation, cycle, summary_finish_link (FF/SF into a
 * summary), summary_pin (mso/mfo on a summary), parent_loop,
 * constraint_date, progress_range.
 * Warnings: constraint_conflict (also a link a pinned task breaks),
 * summary_link (a link on a summary, applied to the tasks under it, or
 * between a task and its own summary), duplicate_link, unknown_parent.
 */
import { isIsoDay, makeCal, toDay, type Cal } from './calendar'
import { buildGraph, leafConstraints } from './schedule'
import { key, leaves } from './tree'
import type { GanttCalendar, GanttLink, GanttTask, Issue } from './types'

const err = (code: string, message: string, taskId: Issue['taskId'], linkId: Issue['linkId'] = null): Issue =>
  ({ level: 'error', code, message, taskId, linkId })
const warn = (code: string, message: string, taskId: Issue['taskId'], linkId: Issue['linkId'] = null): Issue =>
  ({ level: 'warning', code, message, taskId, linkId })

const VERBS: Record<GanttLink['type'], [string, string]> = {
  FS: ['starts', 'ends'], SS: ['starts', 'starts'], FF: ['ends', 'ends'], SF: ['ends', 'starts'],
}
const lagTxt = (lag: number) => (lag ? ` (lag ${lag > 0 ? '+' : ''}${lag}d)` : '')

/** Start / end index of a task as it stands. */
function spanIdx(cal: Cal, t: GanttTask) {
  const s = cal.idx(toDay(t.start))
  return { s, e: s + Math.max(0, Math.round(t.duration || 0)) }
}

/**
 * Is the link satisfied by the tasks' current dates? `cal` may be passed
 * pre-built (a Cal) to avoid rebuilding the calendar per link.
 */
export function linkViolated(
  from: GanttTask, to: GanttTask, link: GanttLink, calendar?: Partial<GanttCalendar> | Cal | null,
): boolean {
  const cal = calendar && 'idx' in calendar ? calendar as Cal : makeCal(calendar as Partial<GanttCalendar> | null)
  const p = spanIdx(cal, from), s = spanIdx(cal, to)
  const lag = Math.round(link.lagDays || 0)
  const d = s.e - s.s
  const need = link.type === 'SS' ? p.s + lag : link.type === 'FF' ? p.e + lag - d
    : link.type === 'SF' ? p.s + lag - d : p.e + lag
  return s.s < need
}

export function validate(
  tasks: GanttTask[], links: GanttLink[], calendar?: Partial<GanttCalendar> | null,
): Issue[] {
  const errors: Issue[] = []
  const warnings: Issue[] = []
  const valid = tasks.filter((t) => isIsoDay(t.start) && Number.isFinite(t.duration))
  const cal = makeCal(calendar)
  const g = buildGraph(tasks, links)
  const { tree, summaries, anc } = g
  const byKey = tree.byId
  for (const t of tasks) {
    const k = key(t.id)
    if (!(t.name ?? '').trim()) errors.push(err('empty_name', 'A task has no name', t.id))
    if (!isIsoDay(t.start)) errors.push(err('bad_date', `'${t.name}' has no valid start date`, t.id))
    if (!Number.isFinite(t.duration) || t.duration < 0) errors.push(err('negative_duration', `'${t.name}' has a negative duration`, t.id))
    if (t.parentId != null && !byKey.has(key(t.parentId))) warnings.push(warn('unknown_parent', `'${t.name}' has a parent that does not exist`, t.id))
    if (t.parentId != null && byKey.has(key(t.parentId)) && key(t.parentId) !== k && tree.parentOf.get(k) == null) {
      errors.push(err('parent_loop', `'${t.name}' is nested inside itself`, t.id))
    }
    const c = t.constraint
    if (c && c.type !== 'asap' && !isIsoDay(c.date)) {
      errors.push(err('constraint_date', `'${t.name}' has a ${c.type.toUpperCase()} constraint without a date`, t.id))
    }
    if (summaries.has(k) && c && (c.type === 'mso' || c.type === 'mfo') && c.date) {
      errors.push(err('summary_pin', `'${t.name}' is a summary: a must-start-on or must-finish-on constraint on it is not allowed (put it on a task under it)`, t.id))
    }
    if ((t.progress ?? 0) < 0 || (t.progress ?? 0) > 100) errors.push(err('progress_range', `'${t.name}' progress is outside 0 to 100`, t.id))
  }
  const seen = new Set<string>()
  for (const l of links) {
    const f = byKey.get(key(l.from)), t = byKey.get(key(l.to))
    if (!f || !t) {
      errors.push(err('unknown_predecessor', `'${t?.name ?? 'A task'}' depends on a task that does not exist (${String(l.from)})`, t?.id ?? null, l.id))
      continue
    }
    if (key(l.from) === key(l.to)) { errors.push(err('self_link', `'${t.name}' is linked to itself`, t.id, l.id)); continue }
    const pair = `${key(l.from)}>${key(l.to)}`
    if (seen.has(pair)) warnings.push(warn('duplicate_link', `'${f.name}' and '${t.name}' are linked twice`, t.id, l.id))
    seen.add(pair)
    const fk = key(l.from), tk = key(l.to)
    if ((anc.get(tk) ?? []).includes(fk) || (anc.get(fk) ?? []).includes(tk)) {
      warnings.push(warn('summary_link', `The link between '${f.name}' and '${t.name}' joins a summary and a task under it and is not used for scheduling`, t.id, l.id))
    } else if (summaries.has(tk) && (l.type === 'FF' || l.type === 'SF')) {
      errors.push(err('summary_finish_link', `The ${l.type} link from '${f.name}' into the summary '${t.name}' is not allowed (link to a task under it)`, t.id, l.id))
    } else if (summaries.has(fk) || summaries.has(tk)) {
      warnings.push(warn('summary_link', `The link from '${f.name}' to '${t.name}' is on a summary task: it applies to the tasks under it`, t.id, l.id))
    }
  }
  if (!g.order || links.some((l) => key(l.from) === key(l.to))) errors.push(err('cycle', 'The dependencies form a loop', null))
  if (valid.length !== tasks.length) return [...errors, ...warnings]

  // Dates as they stand, summaries rolled up.
  const cons = leafConstraints(tasks, g)
  const es = new Map<string, number>()
  const ef = new Map<string, number>()
  for (const k of g.leaves) { const s = spanIdx(cal, byKey.get(k)!); es.set(k, s.s); ef.set(k, s.e) }
  for (const t of [...tree.order].reverse()) {
    const k = key(t.id)
    const kids = g.realKids.get(k)
    if (!kids?.length) continue
    es.set(k, Math.min(...kids.map((c) => es.get(c)!)))
    ef.set(k, Math.max(...kids.map((c) => ef.get(c)!)))
  }
  const pinned = (k: string) => (cons.get(k) ?? []).some((c) => c.type === 'mso' || c.type === 'mfo')
  const done = new Set<string>()
  for (const l of g.links) {
    const p = byKey.get(l.from)!, s = byKey.get(l.to)!
    const dk = `${l.from}>${l.to}>${l.type}>${l.lag}`
    if (done.has(dk)) continue
    const [v1, v2] = VERBS[l.type]
    const text = `'${s.name}' ${v1} before '${p.name}' ${v2}${lagTxt(l.lag)}`
    let bad: boolean
    let isPinned: boolean
    if (summaries.has(l.to)) {
      const need = (l.type === 'SS' ? es.get(l.from)! : ef.get(l.from)!) + l.lag
      const under = leaves(tree, l.to).map((x) => key(x.id)).filter((x) => es.get(x)! < need)
      bad = under.length > 0
      isPinned = bad && under.every(pinned)
    } else {
      const d = ef.get(l.to)! - es.get(l.to)!
      const pEs = es.get(l.from)!, pEf = ef.get(l.from)!
      const need = l.type === 'SS' ? pEs + l.lag : l.type === 'FF' ? pEf + l.lag - d : l.type === 'SF' ? pEs + l.lag - d : pEf + l.lag
      bad = es.get(l.to)! < need
      isPinned = bad && pinned(l.to)
    }
    if (!bad) continue
    done.add(dk)
    if (isPinned) warnings.push(warn('constraint_conflict', `${text}, pinned by its constraint`, s.id, l.id))
    else errors.push(err('dependency_violation', text, s.id, l.id))
  }
  // A leaf: its own constraint and the snet of every summary above it. A summary: its fnlt against its rolled-up finish.
  const checks: [GanttTask, { type: string; date: number; iso: string }[]][] = []
  for (const k of g.leaves) {
    const t = byKey.get(k)!
    const c = t.constraint
    const ownC = c && c.type !== 'asap' && c.date && isIsoDay(c.date) ? [{ type: c.type, date: toDay(c.date), iso: c.date }] : []
    const inherited = (cons.get(k) ?? []).slice(ownC.length).filter((x) => x.type === 'snet')
      .map((x) => ({ ...x, iso: new Date(x.date * 86_400_000).toISOString().slice(0, 10) }))
    checks.push([t, [...ownC, ...inherited]])
  }
  for (const k of summaries) {
    const t = byKey.get(k)!
    if (t.constraint?.type === 'fnlt' && t.constraint.date && isIsoDay(t.constraint.date)) {
      checks.push([t, [{ type: 'fnlt', date: toDay(t.constraint.date), iso: t.constraint.date }]])
    }
  }
  for (const [t, cs] of checks) {
    const k = key(t.id)
    const s = es.get(k)!, e = ef.get(k)!
    for (const c of cs) {
      const ci = cal.idx(c.date)
      let bad: string | null = null
      if (c.type === 'snet' && s < ci) bad = `'${t.name}' starts before its start-no-earlier-than date ${c.iso}`
      else if (c.type === 'mso' && s !== ci) bad = `'${t.name}' does not start on its must-start-on date ${c.iso}`
      else if (c.type === 'mfo' && e !== ci) bad = `'${t.name}' does not end on its must-finish-on date ${c.iso}`
      else if (c.type === 'fnlt' && e > ci) bad = `'${t.name}' ends after its finish-no-later-than date ${c.iso}`
      if (bad) warnings.push(warn('constraint_conflict', bad, t.id))
    }
  }
  return [...errors, ...warnings]
}
