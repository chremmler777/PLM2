/**
 * MS Project XML (MSPDI) export and import, same conventions as the
 * backend exporter (`plan_engine.build_mspdi` / `parse_mspdi`):
 * - UIDs 1..n in outline order; OutlineLevel / OutlineNumber / WBS from the tree.
 * - Idea tasks are left out unless `includeIdeas` (like the server export).
 * - Start is `day T08:00`. Finish is the last day `T17:00` (exclusive end - 1)
 *   in both modes; a milestone's Finish equals its Start.
 * - Calendar mode: elapsed days (DurationFormat 8, PT{24*d}H), every weekday
 *   working, holidays as working exceptions named "Holiday (shading only)".
 *   Working mode: days (DurationFormat 7, PT{8*d}H), the calendar's weekdays,
 *   holidays as non-working exceptions.
 * - Links: Type 0 FF, 1 FS, 2 SF, 3 SS; LinkLag in tenths of minutes
 *   (14400 per elapsed day, LagFormat 8; 4800 per working day, LagFormat 7).
 * - Constraints: 0 ASAP, 2 MSO, 3 MFO, 4 SNET, 7 FNLT; start constraints at
 *   T08:00, finish ones like Finish. mso / mfo on a summary are not written.
 *   A task without a constraint gets SNET on its own start, so MS Project
 *   keeps the dates as drawn (the import reads SNET on the own start back as
 *   no constraint).
 * - Summary PercentComplete is the rolled-up progress; kind in Text1, idea
 *   flag in Flag1 (ExtendedAttribute); the lane is a resource + assignment.
 *
 * Import reads the same and common MS Project variants: a start at or after
 * the end of the working day is the next day, a finish after noon is the end
 * of that day (exclusive end = next day). The project summary task (UID 0),
 * blank rows and rows without a start are skipped (their outline children
 * move up a level). FF/SF links into a summary and mso/mfo on a summary are
 * refused (the backend refuses them too).
 */
import { endFromIdx, isIsoDay, makeCal, toDay, toIso } from './calendar'
import { schedule } from './schedule'
import { buildTree, key } from './tree'
import type {
  ConstraintType, GanttCalendar, GanttLink, GanttTask, LinkType,
} from './types'

export const MSPDI_NS = 'http://schemas.microsoft.com/project'
export const SHADING_HOLIDAY = 'Holiday (shading only)'
const TEXT1 = '188743731'
const FLAG1 = '188743752'

const LINK_CODE: Record<LinkType, number> = { FF: 0, FS: 1, SF: 2, SS: 3 }
const LINK_FROM_CODE: Record<number, LinkType> = { 0: 'FF', 1: 'FS', 2: 'SF', 3: 'SS' }
const CONSTRAINT_CODE: Record<ConstraintType, number> = { asap: 0, mso: 2, mfo: 3, snet: 4, fnlt: 7 }
const CONSTRAINT_FROM_CODE: Record<number, ConstraintType> = { 0: 'asap', 2: 'mso', 3: 'mfo', 4: 'snet', 7: 'fnlt' }

/* eslint-disable no-control-regex -- XML 1.0 forbids these control characters: strip them */
const esc = (s: string) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
  .replace(/"/g, '&quot;').replace(/[\u0000-\u0008\u000B\u000C\u000E-\u001F]/g, '')
/* eslint-enable no-control-regex */

export interface MspdiExportOptions {
  name?: string
  title?: string
  calendar?: Partial<GanttCalendar> | null
  /** Keep idea tasks (the server export leaves them out). Default false. */
  includeIdeas?: boolean
}

export function exportMspdi(tasks: GanttTask[], links: GanttLink[], opts: MspdiExportOptions = {}): string {
  const cal = makeCal(opts.calendar)
  const working = cal.mode === 'working'
  const list0 = opts.includeIdeas ? tasks : tasks.filter((t) => !t.isIdea)
  const tree = buildTree(list0)
  const list = tree.order
  const kept = new Set(list.map((t) => key(t.id)))
  const keptLinks = links.filter((l) => kept.has(key(l.from)) && kept.has(key(l.to)))
  const sched = schedule(list, keptLinks, opts.calendar, { move: false })
  const uid = new Map(list.map((t, i) => [key(t.id), i + 1]))
  const hasKids = (t: GanttTask) => (tree.children.get(key(t.id))?.length ?? 0) > 0
  const ts = (day: number, time = '08:00:00') => `${toIso(day)}T${time}`
  /** Exclusive end -> MS Project finish moment (last day 17:00). */
  const fin = (endDay: number) => ts(endDay - 1, '17:00:00')
  const dur = (d: number) => `PT${(working ? 8 : 24) * d}H0M0S`
  const fmt = working ? 7 : 8
  const lines: string[] = []
  const el = (tag: string, v: string | number, ind = '    ') => lines.push(`${ind}<${tag}>${esc(String(v))}</${tag}>`)

  // Dates as they stand (index space), summaries rolled up.
  const span = new Map<string, { s: number; e: number; si: number; ei: number }>()
  for (const t of [...list].reverse()) {
    const k = key(t.id)
    const kids = tree.children.get(k) ?? []
    if (kids.length) {
      const cs = kids.map((c) => span.get(key(c.id))!)
      span.set(k, {
        s: Math.min(...cs.map((c) => c.s)), e: Math.max(...cs.map((c) => c.e)),
        si: Math.min(...cs.map((c) => c.si)), ei: Math.max(...cs.map((c) => c.ei)),
      })
    } else {
      const si = cal.idx(toDay(t.start))
      const ei = si + Math.max(0, Math.round(t.duration || 0))
      span.set(k, { s: cal.dateAt(si), e: endFromIdx(cal, si, ei), si, ei })
    }
  }
  const all = [...span.values()]
  const today = todayLocal()
  const pStart = all.length ? Math.min(...all.map((x) => x.s)) : today
  const pEnd = all.length ? Math.max(...all.map((x) => x.e)) : pStart
  const week = working ? cal.source.workdays : [1, 2, 3, 4, 5, 6, 7]

  lines.push('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>')
  lines.push(`<Project xmlns="${MSPDI_NS}">`)
  el('SaveVersion', 14, '  ')
  el('Name', opts.name ?? 'plan.xml', '  ')
  el('Title', opts.title ?? opts.name ?? 'Plan', '  ')
  el('ScheduleFromStart', 1, '  ')
  el('StartDate', ts(pStart), '  ')
  el('FinishDate', pEnd > pStart ? fin(pEnd) : ts(pStart), '  ')
  el('CalendarUID', 1, '  ')
  el('DefaultStartTime', '08:00:00', '  ')
  el('DefaultFinishTime', '17:00:00', '  ')
  el('MinutesPerDay', 480, '  ')
  el('MinutesPerWeek', 480 * week.length, '  ')
  el('DaysPerMonth', working ? 20 : 30, '  ')
  el('DurationFormat', fmt, '  ')
  el('NewTasksAreManual', 0, '  ')
  lines.push('  <ExtendedAttributes>')
  lines.push(`    <ExtendedAttribute><FieldID>${TEXT1}</FieldID><FieldName>Text1</FieldName><Alias>Kind</Alias></ExtendedAttribute>`)
  lines.push(`    <ExtendedAttribute><FieldID>${FLAG1}</FieldID><FieldName>Flag1</FieldName><Alias>Idea</Alias></ExtendedAttribute>`)
  lines.push('  </ExtendedAttributes>')

  // Calendar: MSPDI DayType 1 = Sunday .. 7 = Saturday; ours 1 = Monday .. 7 = Sunday.
  lines.push('  <Calendars>', '    <Calendar>')
  el('UID', 1, '      '); el('Name', working ? 'Working days' : 'Elapsed days', '      '); el('IsBaseCalendar', 1, '      ')
  lines.push('      <WeekDays>')
  const times = '<WorkingTimes><WorkingTime><FromTime>08:00:00</FromTime><ToTime>12:00:00</ToTime></WorkingTime><WorkingTime><FromTime>13:00:00</FromTime><ToTime>17:00:00</ToTime></WorkingTime></WorkingTimes>'
  for (let dt = 1; dt <= 7; dt++) {
    const iso = dt === 1 ? 7 : dt - 1
    const on = week.includes(iso)
    lines.push(`        <WeekDay><DayType>${dt}</DayType><DayWorking>${on ? 1 : 0}</DayWorking>${on ? times : ''}</WeekDay>`)
  }
  lines.push('      </WeekDays>')
  if (cal.source.holidays.length) {
    lines.push('      <Exceptions>')
    for (const h of cal.source.holidays) {
      lines.push(`        <Exception><EnteredByOccurrences>0</EnteredByOccurrences><TimePeriod><FromDate>${h}T00:00:00</FromDate><ToDate>${h}T23:59:00</ToDate></TimePeriod><Occurrences>1</Occurrences><Name>${working ? 'Holiday' : SHADING_HOLIDAY}</Name><Type>1</Type><DayWorking>${working ? 0 : 1}</DayWorking>${working ? '' : times}</Exception>`)
    }
    lines.push('      </Exceptions>')
  }
  lines.push('    </Calendar>', '  </Calendars>')

  lines.push('  <Tasks>')
  for (const t of list) {
    const k = key(t.id)
    const n = uid.get(k)!
    const sum = hasKids(t)
    const sp = span.get(k)!
    const d = Math.max(0, sp.ei - sp.si)
    const ind = '      '
    lines.push('    <Task>')
    el('UID', n, ind); el('ID', n, ind); el('Name', t.name, ind)
    el('Type', 1, ind); el('IsNull', 0, ind)
    el('WBS', tree.wbs.get(k)!, ind); el('OutlineNumber', tree.wbs.get(k)!, ind)
    el('OutlineLevel', (tree.depth.get(k) ?? 0) + 1, ind)
    el('Start', ts(sp.s), ind)
    el('Finish', d > 0 ? fin(sp.e) : ts(sp.s), ind)
    el('Duration', dur(d), ind); el('DurationFormat', fmt, ind)
    el('Milestone', !sum && t.duration === 0 ? 1 : 0, ind)
    el('Summary', sum ? 1 : 0, ind)
    el('PercentComplete', sum ? sched.byId.get(t.id)?.progress ?? 0 : Math.round(t.progress ?? 0), ind)
    if (t.actualStart && isIsoDay(t.actualStart)) el('ActualStart', ts(toDay(t.actualStart)), ind)
    if (t.actualEnd && isIsoDay(t.actualEnd)) el('ActualFinish', ts(toDay(t.actualEnd), '17:00:00'), ind)
    const c = t.constraint
    if (c && c.type !== 'asap' && c.date && isIsoDay(c.date) && !(sum && (c.type === 'mso' || c.type === 'mfo'))) {
      el('ConstraintType', CONSTRAINT_CODE[c.type], ind)
      el('ConstraintDate', c.type === 'snet' || c.type === 'mso' ? ts(toDay(c.date)) : fin(toDay(c.date)), ind)
    } else if (!sum) {
      // Keep MS Project from pulling the task to the project start.
      el('ConstraintType', 4, ind)
      el('ConstraintDate', ts(sp.s), ind)
    }
    if (t.notes) el('Notes', t.notes, ind)
    for (const l of keptLinks) {
      if (key(l.to) !== k) continue
      lines.push(`${ind}<PredecessorLink>`)
      el('PredecessorUID', uid.get(key(l.from))!, `${ind}  `)
      el('Type', LINK_CODE[l.type] ?? 1, `${ind}  `)
      el('CrossProject', 0, `${ind}  `)
      el('LinkLag', Math.round(l.lagDays * (working ? 4800 : 14400)), `${ind}  `)
      el('LagFormat', working ? 7 : 8, `${ind}  `)
      lines.push(`${ind}</PredecessorLink>`)
    }
    if (t.kind) lines.push(`${ind}<ExtendedAttribute><FieldID>${TEXT1}</FieldID><Value>${esc(t.kind)}</Value></ExtendedAttribute>`)
    if (t.isIdea) lines.push(`${ind}<ExtendedAttribute><FieldID>${FLAG1}</FieldID><Value>1</Value></ExtendedAttribute>`)
    if (t.baselineStart && t.baselineEnd && isIsoDay(t.baselineStart) && isIsoDay(t.baselineEnd)) {
      const bs = toDay(t.baselineStart), be = toDay(t.baselineEnd)
      lines.push(`${ind}<Baseline>`)
      el('Number', 0, `${ind}  `)
      el('Start', ts(bs), `${ind}  `)
      el('Finish', be > bs ? fin(be) : ts(bs), `${ind}  `)
      el('Duration', dur(Math.max(0, cal.idx(be) - cal.idx(bs))), `${ind}  `)
      el('DurationFormat', fmt, `${ind}  `)
      lines.push(`${ind}</Baseline>`)
    }
    lines.push('    </Task>')
  }
  lines.push('  </Tasks>')

  const lanes = [...new Set(list.map((t) => t.lane).filter((l): l is string => !!l))].sort()
  const rid = new Map(lanes.map((l, i) => [l, i + 1]))
  lines.push('  <Resources>')
  for (const [lane, i] of rid) lines.push(`    <Resource><UID>${i}</UID><ID>${i}</ID><Name>${esc(lane)}</Name><Type>1</Type></Resource>`)
  lines.push('  </Resources>')
  lines.push('  <Assignments>')
  let a = 0
  for (const t of list) {
    if (!t.lane || !rid.has(t.lane) || hasKids(t)) continue
    a++
    lines.push(`    <Assignment><UID>${a}</UID><TaskUID>${uid.get(key(t.id))}</TaskUID><ResourceUID>${rid.get(t.lane)}</ResourceUID><Units>1</Units></Assignment>`)
  }
  lines.push('  </Assignments>')
  lines.push('</Project>')
  return lines.join('\n')
}

/** Today in the viewer's local calendar (not UTC). */
function todayLocal(): number {
  const n = new Date()
  return Math.round(Date.UTC(n.getFullYear(), n.getMonth(), n.getDate()) / 86_400_000)
}

// ------------------------------------------------------------------ import

export interface MspdiImport {
  name: string | null
  tasks: GanttTask[]
  links: GanttLink[]
  calendar: GanttCalendar
  warnings: string[]
}

const kids = (el: Element, tag: string): Element[] =>
  Array.from(el.children).filter((c) => c.localName === tag)
const kid = (el: Element | null | undefined, tag: string): Element | undefined =>
  (el ? Array.from(el.children).find((c) => c.localName === tag) : undefined)
const txt = (el: Element | null | undefined, tag: string): string | null => {
  const k = kid(el, tag)
  return k ? (k.textContent ?? '').trim() : null
}
const num = (el: Element | null | undefined, tag: string): number | null => {
  const v = txt(el, tag)
  if (v == null || v === '') return null
  const n = Number(v)
  return Number.isFinite(n) ? n : null
}

/** "PT40H0M0S" / "P2DT4H" -> hours. */
export function durationHours(v: string | null): number | null {
  if (!v) return null
  const m = /^P(?:(\d+(?:\.\d+)?)D)?(?:T(?:(\d+(?:\.\d+)?)H)?(?:(\d+(?:\.\d+)?)M)?(?:(\d+(?:\.\d+)?)S)?)?$/.exec(v.trim())
  if (!m) return null
  return Number(m[1] ?? 0) * 24 + Number(m[2] ?? 0) + Number(m[3] ?? 0) / 60 + Number(m[4] ?? 0) / 3600
}

const datePart = (v: string | null) => (v && isIsoDay(v.slice(0, 10)) ? v.slice(0, 10) : null)
const hourOf = (v: string | null) => {
  const m = v ? /T(\d{2}):(\d{2})/.exec(v) : null
  return m ? Number(m[1]) + Number(m[2]) / 60 : 0
}
/** Exclusive end from an MSPDI finish timestamp: after noon is the end of that day. */
const exclusiveEnd = (v: string | null): number | null => {
  const d = datePart(v)
  if (!d) return null
  return toDay(d) + (hourOf(v) >= 12 ? 1 : 0)
}

const ELAPSED_FORMATS = new Set([4, 6, 8, 10, 12, 20, 36, 38, 40, 42, 44, 52])

export function importMspdi(xml: string): MspdiImport {
  const doc = new DOMParser().parseFromString(xml, 'application/xml')
  const root = doc.documentElement
  if (!root || root.localName !== 'Project' || doc.getElementsByTagName('parsererror').length) {
    throw new Error('This file is not an MS Project XML file')
  }
  const warnings: string[] = []
  const minutesPerDay = num(root, 'MinutesPerDay') ?? 480

  // Calendar: the project calendar (CalendarUID) or the first base calendar.
  const calUid = num(root, 'CalendarUID')
  const calEls = kids(kid(root, 'Calendars') ?? root, 'Calendar')
  const calEl = calEls.find((c) => num(c, 'UID') === calUid) ?? calEls[0]
  const dayEnd = (() => {
    const m = /^(\d{1,2}):(\d{2})/.exec(txt(root, 'DefaultFinishTime') ?? '')
    return m && Number(m[1]) < 24 && Number(m[2]) < 60 ? Number(m[1]) + Number(m[2]) / 60 : 17
  })()
  /** A start moment as a day: at or after the end of the working day it is the next day. */
  const startDay = (v: string | null): string | null => {
    const d = datePart(v)
    if (!d) return null
    return hourOf(v) >= dayEnd ? toIso(toDay(d) + 1) : d
  }
  let workdays: number[] = [1, 2, 3, 4, 5]
  const found = new Map<number, boolean>()
  const holidays: string[] = []
  const shading: string[] = []
  const period = (el: Element) => {
    const tp = kid(el, 'TimePeriod')
    const from = datePart(txt(tp, 'FromDate'))
    const to = datePart(txt(tp, 'ToDate'))
    if (!from || !to || toDay(from) > toDay(to)) return [] as string[]
    const out: string[] = []
    for (let d = toDay(from); d <= toDay(to) && out.length < 400; d++) out.push(toIso(d))
    return out
  }
  if (calEl) {
    for (const wd of kids(kid(calEl, 'WeekDays') ?? calEl, 'WeekDay')) {
      const dt = num(wd, 'DayType') ?? -1
      const on = (num(wd, 'DayWorking') ?? 1) === 1
      if (dt >= 1 && dt <= 7) found.set(dt === 1 ? 7 : dt - 1, on)
      else if (dt === 0 && !on) holidays.push(...period(wd))
    }
    if (found.size) {
      const on = [...found].filter(([, w]) => w).map(([d]) => d).sort((a, b) => a - b)
      if (on.length) workdays = on
    }
    for (const ex of kids(kid(calEl, 'Exceptions') ?? calEl, 'Exception')) {
      const nm = txt(ex, 'Name') ?? ''
      const workingEx = (num(ex, 'DayWorking') ?? 0) === 1
      if (workingEx && !nm.startsWith(SHADING_HOLIDAY)) continue
      if ((num(ex, 'Type') ?? 1) !== 1) warnings.push(`Calendar exception '${nm || '?'}' repeats; only single days are read`)
      const days = period(ex)
      if (workingEx) shading.push(...days)
      else holidays.push(...days)
    }
  }
  const projFormat = num(root, 'DurationFormat') ?? 7
  const taskEls = kids(kid(root, 'Tasks') ?? root, 'Task').filter((te) => {
    const id = num(te, 'UID')
    return id != null && id !== 0 && num(te, 'IsNull') !== 1 && (num(te, 'OutlineLevel') ?? 1) !== 0
  })
  const leafFmts = taskEls.filter((te) => num(te, 'Summary') !== 1).map((te) => num(te, 'DurationFormat') ?? projFormat)
  const elapsedPlan = leafFmts.length ? leafFmts.every((f) => ELAPSED_FORMATS.has(f)) : ELAPSED_FORMATS.has(projFormat)
  const mode: GanttCalendar['mode'] = elapsedPlan ? 'calendar' : 'working'
  if (elapsedPlan && workdays.length === 7) workdays = [1, 2, 3, 4, 5]
  const calendar: GanttCalendar = {
    mode, workdays,
    holidays: [...new Set(elapsedPlan ? [...holidays, ...shading] : holidays)].sort(),
  }
  const cal = makeCal(calendar)
  const countWork = (a: number, b: number) => Math.max(0, cal.idx(b) - cal.idx(a))

  // Resources and assignments -> lanes.
  const resName = new Map<number, string>()
  for (const r of kids(kid(root, 'Resources') ?? root, 'Resource')) {
    const u = num(r, 'UID'); const n = txt(r, 'Name')
    if (u != null && n) resName.set(u, n)
  }
  const laneOf = new Map<number, string>()
  for (const a of kids(kid(root, 'Assignments') ?? root, 'Assignment')) {
    const t = num(a, 'TaskUID'); const r = num(a, 'ResourceUID')
    if (t != null && r != null && resName.has(r) && !laneOf.has(t)) laneOf.set(t, resName.get(r)!)
  }

  const tasks: GanttTask[] = []
  const links: GanttLink[] = []
  // A skipped row keeps its place on the outline stack (id null) so its
  // children move up to the nearest kept ancestor instead of a sibling.
  const stack: { level: number; id: number | null }[] = []
  const known = new Set<number>()
  const pendingLinks: { from: number; to: number; type: LinkType; lag: number }[] = []
  for (const te of taskEls) {
    const id = num(te, 'UID')!
    const level = Math.max(1, num(te, 'OutlineLevel') ?? 1)
    const name = (txt(te, 'Name') ?? '').trim()
    while (stack.length && stack[stack.length - 1].level >= level) stack.pop()
    const start = startDay(txt(te, 'Start'))
    if (!start || !name) {
      warnings.push(`Task ${id}${name ? ` "${name}"` : ''} has no ${name ? 'start date' : 'name'} and was skipped`)
      stack.push({ level, id: null })
      continue
    }
    const parentId = [...stack].reverse().find((x) => x.id != null)?.id ?? null
    stack.push({ level, id })
    known.add(id)

    const milestone = num(te, 'Milestone') === 1
    const fmt = num(te, 'DurationFormat')
    const hours = durationHours(txt(te, 'Duration'))
    let duration: number
    if (milestone) duration = 0
    else if (hours != null) {
      const elapsed = fmt != null ? ELAPSED_FORMATS.has(fmt) : mode === 'calendar'
      const perDay = elapsed ? 24 : minutesPerDay / 60
      duration = Math.max(0, Math.round(hours / perDay))
      if (elapsed !== (mode === 'calendar')) {
        // Mixed units: derive from the dates instead.
        const end = exclusiveEnd(txt(te, 'Finish'))
        if (end != null) duration = Math.max(0, mode === 'calendar' ? end - toDay(start) : countWork(toDay(start), end))
      }
    } else {
      const end = exclusiveEnd(txt(te, 'Finish'))
      duration = end != null ? Math.max(0, mode === 'calendar' ? end - toDay(start) : countWork(toDay(start), end)) : 1
    }

    const task: GanttTask = { id, parentId, name, start, duration }
    // A summary's percent is rolled up from its children: not stored.
    const pct = num(te, 'Summary') === 1 ? 0 : num(te, 'PercentComplete')
    if (pct) task.progress = Math.max(0, Math.min(100, pct))
    const notes = txt(te, 'Notes')
    if (notes) task.notes = notes
    const as = startDay(txt(te, 'ActualStart'))
    if (as) task.actualStart = as
    const af = datePart(txt(te, 'ActualFinish'))
    if (af) task.actualEnd = af
    const ct = num(te, 'ConstraintType')
    if (ct != null && ct !== 0) {
      const type = CONSTRAINT_FROM_CODE[ct] ?? 'asap'
      const raw = txt(te, 'ConstraintDate')
      if (type !== 'asap' && raw) {
        const finishType = type === 'fnlt' || type === 'mfo'
        const d = finishType ? exclusiveEnd(raw) : (startDay(raw) ? toDay(startDay(raw)!) : null)
        // SNET on the task's own start is how exporters keep dates: no constraint.
        if (d != null && !(type === 'snet' && toIso(d) === start)) task.constraint = { type, date: toIso(d) }
      }
      if (!(ct in CONSTRAINT_FROM_CODE)) warnings.push(`"${name}": constraint type ${ct} is not supported and was dropped`)
    }
    for (const ea of kids(te, 'ExtendedAttribute')) {
      const f = txt(ea, 'FieldID'); const v = txt(ea, 'Value')
      if (f === TEXT1 && v) task.kind = v
      if (f === FLAG1 && (v === '1' || v?.toLowerCase() === 'yes')) task.isIdea = true
    }
    if (laneOf.has(id)) task.lane = laneOf.get(id)!
    for (const b of kids(te, 'Baseline')) {
      if ((num(b, 'Number') ?? 0) !== 0) continue
      const bs = startDay(txt(b, 'Start'))
      if (!bs) continue
      const bh = durationHours(txt(b, 'Duration'))
      const bfmt = num(b, 'DurationFormat') ?? fmt
      let be: number | null = null
      if (bh != null) {
        const elapsed = bfmt != null ? ELAPSED_FORMATS.has(bfmt) : mode === 'calendar'
        const bd = Math.round(bh / (elapsed ? 24 : minutesPerDay / 60))
        be = elapsed ? toDay(bs) + bd : endFromIdx(cal, cal.idx(toDay(bs)), cal.idx(toDay(bs)) + bd)
        if (bd === 0) be = toDay(bs)
      } else be = exclusiveEnd(txt(b, 'Finish'))
      if (be != null) { task.baselineStart = bs; task.baselineEnd = toIso(be) }
    }
    for (const pl of kids(te, 'PredecessorLink')) {
      const from = num(pl, 'PredecessorUID')
      if (from == null) continue
      const type = LINK_FROM_CODE[num(pl, 'Type') ?? 1] ?? 'FS'
      const lagRaw = num(pl, 'LinkLag') ?? 0
      const lf = num(pl, 'LagFormat')
      const elapsed = lf != null ? ELAPSED_FORMATS.has(lf) : mode === 'calendar'
      const perDay = elapsed ? 14400 : minutesPerDay * 10
      pendingLinks.push({ from, to: id, type, lag: Math.round(lagRaw / perDay) })
    }
    tasks.push(task)
  }
  // What MS Project and the backend refuse on a summary.
  const parents = new Set(tasks.map((t) => t.parentId).filter((x): x is number => typeof x === 'number'))
  for (const t of tasks) {
    if (parents.has(t.id as number) && (t.constraint?.type === 'mso' || t.constraint?.type === 'mfo')) {
      throw new Error(`'${t.name}' is a summary task with a must-start-on or must-finish-on constraint, which MS Project does not allow`)
    }
  }
  let n = 0
  for (const l of pendingLinks) {
    if (!known.has(l.from)) { warnings.push(`A link from task ${l.from} points outside the plan and was skipped`); continue }
    if (parents.has(l.to) && (l.type === 'FF' || l.type === 'SF')) {
      const t = tasks.find((x) => x.id === l.to)
      throw new Error(`The ${l.type} link into the summary task '${t?.name ?? l.to}' is not allowed (MS Project refuses finish links into a summary)`)
    }
    links.push({ id: `L${++n}`, from: l.from, to: l.to, type: l.type, lagDays: l.lag === 0 ? 0 : l.lag })
  }
  return { name: txt(root, 'Title') ?? txt(root, 'Name'), tasks, links, calendar, warnings }
}
