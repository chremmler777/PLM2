/**
 * MS Project XML (MSPDI) export and import.
 *
 * Export conventions (the backend exporter uses the same):
 * - UIDs 1..n in display pre-order; OutlineLevel / OutlineNumber from the tree.
 * - Calendar mode: elapsed days (DurationFormat 8), Start `day T08:00`,
 *   Finish = exclusive end `T08:00`, Duration PT{24*d}H0M0S.
 *   Working mode: days (DurationFormat 7), Start `T08:00`, Finish = last
 *   working day `T17:00`, Duration PT{8*d}H0M0S; the calendar's weekdays and
 *   holidays go into the Standard calendar.
 * - Links: Type 0 FF, 1 FS, 2 SF, 3 SS; LinkLag in tenths of minutes
 *   (14400 per elapsed day with LagFormat 8, 4800 per working day with
 *   LagFormat 7).
 * - Constraints: 0 ASAP, 2 MSO, 3 MFO, 4 SNET, 7 FNLT. Finish constraint
 *   dates are written like Finish (exclusive T08:00 elapsed, last day T17:00).
 * - Baseline Number 0 carries baselineStart/baselineEnd; kind goes to Text1
 *   and the idea flag to Flag1 (ExtendedAttribute), the lane to a resource.
 *
 * Import reads the same and the common MS Project variants: a finish time
 * after noon means "end of that day" (exclusive end = next day), a time at or
 * before noon means the exclusive end itself. The project summary task
 * (UID 0 / OutlineLevel 0) is skipped.
 */
import { endOf, isIsoDay, makeCal, toDay, toIso } from './calendar'
import { buildTree, key } from './tree'
import type {
  ConstraintType, GanttCalendar, GanttLink, GanttTask, LinkType,
} from './types'

export const MSPDI_NS = 'http://schemas.microsoft.com/project'
const TEXT1 = '188743731'
const FLAG1 = '188743752'

const LINK_CODE: Record<LinkType, number> = { FF: 0, FS: 1, SF: 2, SS: 3 }
const LINK_FROM_CODE: Record<number, LinkType> = { 0: 'FF', 1: 'FS', 2: 'SF', 3: 'SS' }
const CONSTRAINT_CODE: Record<ConstraintType, number> = { asap: 0, mso: 2, mfo: 3, snet: 4, fnlt: 7 }
const CONSTRAINT_FROM_CODE: Record<number, ConstraintType> = { 0: 'asap', 1: 'asap', 2: 'mso', 3: 'mfo', 4: 'snet', 5: 'asap', 6: 'snet', 7: 'fnlt' }

/* eslint-disable no-control-regex -- XML 1.0 forbids these control characters: strip them */
const esc = (s: string) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
  .replace(/"/g, '&quot;').replace(/[\u0000-\u0008\u000B\u000C\u000E-\u001F]/g, '')
/* eslint-enable no-control-regex */

export interface MspdiExportOptions {
  name?: string
  title?: string
  calendar?: Partial<GanttCalendar> | null
  /** Leave out idea tasks (the ECR export does). Default false. */
  skipIdeas?: boolean
}

export function exportMspdi(tasks: GanttTask[], links: GanttLink[], opts: MspdiExportOptions = {}): string {
  const cal = makeCal(opts.calendar)
  const working = cal.mode === 'working'
  const tree = buildTree(opts.skipIdeas ? tasks.filter((t) => !t.isIdea) : tasks)
  const list = tree.order
  const uid = new Map(list.map((t, i) => [key(t.id), i + 1]))
  const hasKids = (t: GanttTask) => (tree.children.get(key(t.id))?.length ?? 0) > 0
  const startTs = (iso: string) => `${iso}T08:00:00`
  /** Exclusive end day -> MSPDI finish timestamp. */
  const finishTs = (endDay: number, dur: number) => (working
    ? `${toIso(dur > 0 ? endDay - 1 : endDay)}T${dur > 0 ? '17:00:00' : '08:00:00'}`
    : `${toIso(endDay)}T08:00:00`)
  const dur = (d: number) => `PT${(working ? 8 : 24) * d}H0M0S`
  const fmt = working ? 7 : 8
  const lines: string[] = []
  const el = (tag: string, v: string | number, ind = '    ') => lines.push(`${ind}<${tag}>${esc(String(v))}</${tag}>`)

  // Summary dates: rolled up from children.
  const span = new Map<string, { s: number; e: number }>()
  for (const t of [...list].reverse()) {
    const k = key(t.id)
    const kids = tree.children.get(k) ?? []
    if (kids.length) {
      span.set(k, {
        s: Math.min(...kids.map((c) => span.get(key(c.id))!.s)),
        e: Math.max(...kids.map((c) => span.get(key(c.id))!.e)),
      })
    } else {
      const s = toDay(t.start)
      span.set(k, { s, e: endOf(cal, s, t.duration) })
    }
  }
  const all = [...span.values()]
  const pStart = all.length ? Math.min(...all.map((x) => x.s)) : toDay(new Date().toISOString().slice(0, 10))
  const pEnd = all.length ? Math.max(...all.map((x) => x.e)) : pStart

  lines.push('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>')
  lines.push(`<Project xmlns="${MSPDI_NS}">`)
  el('SaveVersion', 14, '  ')
  el('Name', opts.name ?? 'plan.xml', '  ')
  el('Title', opts.title ?? opts.name ?? 'Plan', '  ')
  el('ScheduleFromStart', 1, '  ')
  el('StartDate', startTs(toIso(pStart)), '  ')
  el('FinishDate', `${toIso(pEnd)}T08:00:00`, '  ')
  el('CalendarUID', 1, '  ')
  el('DefaultStartTime', '08:00:00', '  ')
  el('MinutesPerDay', 480, '  ')
  el('MinutesPerWeek', 2400, '  ')
  el('DaysPerMonth', 20, '  ')
  el('DurationFormat', fmt, '  ')
  lines.push('  <ExtendedAttributes>')
  lines.push(`    <ExtendedAttribute><FieldID>${TEXT1}</FieldID><FieldName>Text1</FieldName><Alias>Kind</Alias></ExtendedAttribute>`)
  lines.push(`    <ExtendedAttribute><FieldID>${FLAG1}</FieldID><FieldName>Flag1</FieldName><Alias>Idea</Alias></ExtendedAttribute>`)
  lines.push('  </ExtendedAttributes>')

  // Calendar: MSPDI DayType 1 = Sunday .. 7 = Saturday; ours 1 = Monday .. 7 = Sunday.
  lines.push('  <Calendars>', '    <Calendar>')
  el('UID', 1, '      '); el('Name', 'Standard', '      '); el('IsBaseCalendar', 1, '      ')
  lines.push('      <WeekDays>')
  const workdays = new Set(cal.source.workdays)
  for (let dt = 1; dt <= 7; dt++) {
    const iso = dt === 1 ? 7 : dt - 1
    const on = workdays.has(iso)
    lines.push('        <WeekDay>')
    el('DayType', dt, '          '); el('DayWorking', on ? 1 : 0, '          ')
    if (on) {
      lines.push('          <WorkingTimes>')
      for (const [a, b] of [['08:00:00', '12:00:00'], ['13:00:00', '17:00:00']]) lines.push(`            <WorkingTime><FromTime>${a}</FromTime><ToTime>${b}</ToTime></WorkingTime>`)
      lines.push('          </WorkingTimes>')
    }
    lines.push('        </WeekDay>')
  }
  {
    for (const h of cal.source.holidays) {
      lines.push('        <WeekDay>')
      el('DayType', 0, '          '); el('DayWorking', 0, '          ')
      lines.push(`          <TimePeriod><FromDate>${h}T00:00:00</FromDate><ToDate>${h}T23:59:00</ToDate></TimePeriod>`)
      lines.push('        </WeekDay>')
    }
  }
  lines.push('      </WeekDays>', '    </Calendar>', '  </Calendars>')

  lines.push('  <Tasks>')
  const wbs = tree.wbs
  for (const t of list) {
    const k = key(t.id)
    const n = uid.get(k)!
    const sum = hasKids(t)
    const sp = span.get(k)!
    const d = sum ? Math.max(0, (working ? countWork(cal, sp.s, sp.e) : sp.e - sp.s)) : Math.max(0, t.duration)
    lines.push('    <Task>')
    const ind = '      '
    el('UID', n, ind); el('ID', n, ind); el('Name', t.name, ind)
    el('Type', 1, ind); el('IsNull', 0, ind)
    el('WBS', wbs.get(k)!, ind); el('OutlineNumber', wbs.get(k)!, ind)
    el('OutlineLevel', (tree.depth.get(k) ?? 0) + 1, ind)
    el('Start', startTs(toIso(sp.s)), ind)
    el('Finish', finishTs(sp.e, d), ind)
    el('Duration', dur(d), ind); el('DurationFormat', fmt, ind)
    el('Milestone', !sum && t.duration === 0 ? 1 : 0, ind)
    el('Summary', sum ? 1 : 0, ind)
    el('PercentComplete', Math.round(t.progress ?? 0), ind)
    if (t.actualStart && isIsoDay(t.actualStart)) el('ActualStart', startTs(t.actualStart), ind)
    if (t.actualEnd && isIsoDay(t.actualEnd)) el('ActualFinish', `${t.actualEnd}T17:00:00`, ind)
    const c = t.constraint
    if (c && c.type !== 'asap' && c.date && isIsoDay(c.date)) {
      el('ConstraintType', CONSTRAINT_CODE[c.type], ind)
      const finishType = c.type === 'fnlt' || c.type === 'mfo'
      el('ConstraintDate', finishType ? finishTs(toDay(c.date), 1) : startTs(c.date), ind)
    } else {
      el('ConstraintType', 0, ind)
    }
    if (t.notes) el('Notes', t.notes, ind)
    for (const l of links) {
      if (key(l.to) !== k || !uid.has(key(l.from))) continue
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
      const bd = working ? countWork(cal, bs, be) : be - bs
      lines.push(`${ind}<Baseline>`)
      el('Number', 0, `${ind}  `)
      el('Start', startTs(t.baselineStart), `${ind}  `)
      el('Finish', finishTs(be, bd), `${ind}  `)
      el('Duration', dur(bd), `${ind}  `)
      el('DurationFormat', fmt, `${ind}  `)
      lines.push(`${ind}</Baseline>`)
    }
    lines.push('    </Task>')
  }
  lines.push('  </Tasks>')

  const lanes = [...new Set(list.map((t) => t.lane).filter((l): l is string => !!l))].sort()
  const rid = new Map(lanes.map((l, i) => [l, i + 1]))
  lines.push('  <Resources>')
  for (const [lane, i] of rid) {
    lines.push(`    <Resource><UID>${i}</UID><ID>${i}</ID><Name>${esc(lane)}</Name><Type>1</Type></Resource>`)
  }
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

function countWork(cal: ReturnType<typeof makeCal>, a: number, b: number): number {
  let n = 0
  for (let d = a; d < b; d++) if (cal.isWork(d)) n++
  return n
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
/** Exclusive end from an MSPDI finish timestamp. */
const exclusiveEnd = (v: string | null): number | null => {
  const d = datePart(v)
  if (!d) return null
  return toDay(d) + (hourOf(v) > 12 ? 1 : 0)
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
  const workdays: number[] = []
  const holidays: string[] = []
  let allDays = true
  if (calEl) {
    for (const wd of kids(kid(calEl, 'WeekDays') ?? calEl, 'WeekDay')) {
      const dt = num(wd, 'DayType')
      const on = num(wd, 'DayWorking') === 1
      if (dt != null && dt >= 1 && dt <= 7) {
        if (on) workdays.push(dt === 1 ? 7 : dt - 1)
        else allDays = false
      } else if (dt === 0 && !on) {
        const tp = kid(wd, 'TimePeriod')
        const from = datePart(txt(tp, 'FromDate'))
        const to = datePart(txt(tp, 'ToDate'))
        if (from && to) for (let d = toDay(from); d <= toDay(to) && d - toDay(from) < 400; d++) holidays.push(toIso(d))
      }
    }
  }
  const projFormat = num(root, 'DurationFormat')
  const elapsedProject = projFormat != null && ELAPSED_FORMATS.has(projFormat)
  const mode: GanttCalendar['mode'] = elapsedProject || (allDays && workdays.length === 7) ? 'calendar' : 'working'
  const calendar: GanttCalendar = {
    mode, workdays: workdays.length ? workdays.sort((a, b) => a - b) : [1, 2, 3, 4, 5],
    holidays: [...new Set(holidays)].sort(),
  }
  const cal = makeCal(calendar)

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
  const stack: { level: number; id: number }[] = []
  const known = new Set<number>()
  const pendingLinks: { from: number; to: number; type: LinkType; lag: number }[] = []
  for (const te of kids(kid(root, 'Tasks') ?? root, 'Task')) {
    const id = num(te, 'UID')
    if (id == null) continue
    const level = num(te, 'OutlineLevel') ?? 1
    if (level === 0 || id === 0 || num(te, 'IsNull') === 1) continue
    const name = txt(te, 'Name') ?? ''
    const start = datePart(txt(te, 'Start'))
    if (!start) { warnings.push(`Task ${id} "${name}" has no start date and was skipped`); continue }
    while (stack.length && stack[stack.length - 1].level >= level) stack.pop()
    const parentId = stack.length ? stack[stack.length - 1].id : null
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
        if (end != null) duration = Math.max(0, mode === 'calendar' ? end - toDay(start) : countWork(cal, toDay(start), end))
      }
    } else {
      const end = exclusiveEnd(txt(te, 'Finish'))
      duration = end != null ? Math.max(0, mode === 'calendar' ? end - toDay(start) : countWork(cal, toDay(start), end)) : 1
    }

    const task: GanttTask = { id, parentId, name, start, duration }
    const pct = num(te, 'PercentComplete')
    if (pct) task.progress = Math.max(0, Math.min(100, pct))
    const notes = txt(te, 'Notes')
    if (notes) task.notes = notes
    const as = datePart(txt(te, 'ActualStart'))
    if (as) task.actualStart = as
    const af = datePart(txt(te, 'ActualFinish'))
    if (af) task.actualEnd = af
    const ct = num(te, 'ConstraintType')
    if (ct != null && ct !== 0) {
      const type = CONSTRAINT_FROM_CODE[ct] ?? 'asap'
      const raw = txt(te, 'ConstraintDate')
      if (type !== 'asap' && raw) {
        const finishType = type === 'fnlt' || type === 'mfo'
        const d = finishType ? exclusiveEnd(raw) : (datePart(raw) ? toDay(datePart(raw)!) : null)
        if (d != null) task.constraint = { type, date: toIso(d) }
      }
      if (ct === 1 || ct === 5 || ct === 6) warnings.push(`"${name}": constraint type ${ct} is not supported and was simplified`)
    }
    for (const ea of kids(te, 'ExtendedAttribute')) {
      const f = txt(ea, 'FieldID'); const v = txt(ea, 'Value')
      if (f === TEXT1 && v) task.kind = v
      if (f === FLAG1 && (v === '1' || v?.toLowerCase() === 'yes')) task.isIdea = true
    }
    if (laneOf.has(id)) task.lane = laneOf.get(id)!
    for (const b of kids(te, 'Baseline')) {
      if ((num(b, 'Number') ?? 0) !== 0) continue
      const bs = datePart(txt(b, 'Start'))
      if (!bs) continue
      const bh = durationHours(txt(b, 'Duration'))
      const bfmt = num(b, 'DurationFormat') ?? fmt
      let be: number | null = null
      if (bh != null) {
        const elapsed = bfmt != null ? ELAPSED_FORMATS.has(bfmt) : mode === 'calendar'
        const bd = Math.round(bh / (elapsed ? 24 : minutesPerDay / 60))
        be = elapsed ? toDay(bs) + bd : endOf(cal, toDay(bs), bd)
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
  let n = 0
  for (const l of pendingLinks) {
    if (!known.has(l.from)) { warnings.push(`A link from task ${l.from} points outside the plan and was skipped`); continue }
    links.push({ id: `L${++n}`, from: l.from, to: l.to, type: l.type, lagDays: l.lag === 0 ? 0 : l.lag })
  }
  return { name: txt(root, 'Title') ?? txt(root, 'Name'), tasks, links, calendar, warnings }
}
