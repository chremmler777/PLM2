import { describe, expect, it } from 'vitest'
import { durationHours, exportMspdi, importMspdi, MSPDI_NS } from './mspdi'
import type { GanttCalendar, GanttLink, GanttTask } from './types'

const CAL: GanttCalendar = { mode: 'calendar', workdays: [1, 2, 3, 4, 5], holidays: ['2026-12-25'] }
const WORK: GanttCalendar = { mode: 'working', workdays: [1, 2, 3, 4, 5], holidays: ['2026-10-07'] }

const calTasks: GanttTask[] = [
  { id: 1, parentId: null, name: 'Phase 1', start: '2026-10-05', duration: 10 },
  {
    id: 2, parentId: 1, name: 'Tool rework & <check> "A"', start: '2026-10-05', duration: 5, kind: 'downtime',
    lane: 'Tool Engineer', progress: 40, notes: 'a & b <c>', baselineStart: '2026-10-05', baselineEnd: '2026-10-09',
    actualStart: '2026-10-05', actualEnd: '2026-10-08',
  },
  { id: 3, parentId: 1, name: 'Supplier parts', start: '2026-10-10', duration: 5, kind: 'supplier', isIdea: true, lane: 'Supplier', constraint: { type: 'snet', date: '2026-10-09' } },
  { id: 4, parentId: null, name: 'Gate', start: '2026-10-15', duration: 0, kind: 'milestone', constraint: { type: 'fnlt', date: '2026-10-16' } },
  { id: 5, parentId: null, name: 'Approval', start: '2026-10-16', duration: 2, kind: 'customer', lane: 'Customer', constraint: { type: 'mfo', date: '2026-10-18' } },
  { id: 6, parentId: null, name: 'SOP', start: '2026-10-20', duration: 1, constraint: { type: 'mso', date: '2026-10-20' } },
]
const links: GanttLink[] = [
  { id: 'a', from: 2, to: 3, type: 'FS', lagDays: 0 },
  { id: 'b', from: 3, to: 4, type: 'SS', lagDays: 2 },
  { id: 'c', from: 4, to: 5, type: 'FF', lagDays: -1 },
  { id: 'd', from: 2, to: 6, type: 'SF', lagDays: 3 },
]

const workTasks: GanttTask[] = [
  { id: 1, parentId: null, name: 'Phase 1', start: '2026-10-05', duration: 8 },
  { id: 2, parentId: 1, name: 'A', start: '2026-10-05', duration: 5, progress: 20, baselineStart: '2026-10-05', baselineEnd: '2026-10-10', actualStart: '2026-10-05', actualEnd: '2026-10-12' },
  { id: 3, parentId: 1, name: 'B', start: '2026-10-13', duration: 3, lane: 'X', constraint: { type: 'fnlt', date: '2026-10-19' } },
  { id: 4, parentId: null, name: 'M', start: '2026-10-16', duration: 0, constraint: { type: 'mfo', date: '2026-10-16' } },
  { id: 5, parentId: null, name: 'C', start: '2026-10-19', duration: 2, notes: 'n' },
]

const parse = (xml: string) => new DOMParser().parseFromString(xml, 'application/xml')
const taskEls = (doc: Document) => Array.from(doc.getElementsByTagName('Task'))
const val = (el: Element, tag: string) => el.getElementsByTagName(tag)[0]?.textContent ?? null
const linkSet = (ls: GanttLink[]) => ls.map((l) => `${l.from}>${l.to}:${l.type}${l.lagDays}`).sort()

describe('exportMspdi', () => {
  const xml = exportMspdi(calTasks, links, { name: 'CR-1-quote.xml', title: 'CR-1 quote plan', calendar: CAL, includeIdeas: true })
  const doc = parse(xml)
  it('parses as XML with the MSPDI namespace', () => {
    expect(doc.getElementsByTagName('parsererror')).toHaveLength(0)
    expect(doc.documentElement.localName).toBe('Project')
    expect(doc.documentElement.namespaceURI).toBe(MSPDI_NS)
  })
  it('writes project name, title and dates', () => {
    expect(val(doc.documentElement, 'Name')).toBe('CR-1-quote.xml')
    expect(val(doc.documentElement, 'Title')).toBe('CR-1 quote plan')
    expect(val(doc.documentElement, 'StartDate')).toBe('2026-10-05T08:00:00')
  })
  it('writes one Task per task with UIDs 1..n in pre-order', () => {
    const ts = taskEls(doc)
    expect(ts).toHaveLength(6)
    expect(ts.map((t) => val(t, 'UID'))).toEqual(['1', '2', '3', '4', '5', '6'])
  })
  it('writes outline levels, WBS and the summary flag', () => {
    const ts = taskEls(doc)
    expect(ts.map((t) => val(t, 'OutlineLevel'))).toEqual(['1', '2', '2', '1', '1', '1'])
    expect(val(ts[2], 'OutlineNumber')).toBe('1.2')
    expect(val(ts[0], 'Summary')).toBe('1')
    expect(val(ts[1], 'Summary')).toBe('0')
  })
  it('writes elapsed durations in calendar mode', () => {
    const t = taskEls(doc)[1]
    expect(val(t, 'Duration')).toBe('PT120H0M0S')
    expect(val(t, 'DurationFormat')).toBe('8')
    expect(val(t, 'Start')).toBe('2026-10-05T08:00:00')
    // Finish is the last day at 17:00 in both modes (backend parity).
    expect(val(t, 'Finish')).toBe('2026-10-09T17:00:00')
  })
  it('marks milestones', () => expect(val(taskEls(doc)[3], 'Milestone')).toBe('1'))
  it('writes link type codes and lag in tenths of minutes', () => {
    const pl = Array.from(doc.getElementsByTagName('PredecessorLink'))
    const rows = pl.map((p) => [val(p, 'PredecessorUID'), val(p, 'Type'), val(p, 'LinkLag'), val(p, 'LagFormat')])
    expect(rows).toEqual([
      ['2', '1', '0', '8'],
      ['3', '3', '28800', '8'],
      ['4', '0', '-14400', '8'],
      ['2', '2', '43200', '8'],
    ])
  })
  it('writes constraint codes and dates', () => {
    const ts = taskEls(doc)
    // Summary: none; unconstrained leaf: SNET on its own start (keeps MS Project from moving it).
    expect(ts.map((t) => val(t, 'ConstraintType'))).toEqual([null, '4', '4', '7', '3', '2'])
    expect(val(ts[1], 'ConstraintDate')).toBe('2026-10-05T08:00:00')
    expect(val(ts[2], 'ConstraintDate')).toBe('2026-10-09T08:00:00')
    expect(val(ts[3], 'ConstraintDate')).toBe('2026-10-15T17:00:00')
  })
  it('writes baseline 0', () => {
    const b = taskEls(doc)[1].getElementsByTagName('Baseline')[0]
    expect(val(b, 'Number')).toBe('0')
    expect(val(b, 'Start')).toBe('2026-10-05T08:00:00')
    expect(val(b, 'Finish')).toBe('2026-10-08T17:00:00')
  })
  it('writes kind in Text1 and the idea flag in Flag1', () => {
    const ea = Array.from(taskEls(doc)[2].getElementsByTagName('ExtendedAttribute'))
    expect(ea.map((e) => [val(e, 'FieldID'), val(e, 'Value')])).toEqual([['188743731', 'supplier'], ['188743752', '1']])
  })
  it('writes lanes as resources with assignments', () => {
    const res = Array.from(doc.getElementsByTagName('Resource')).map((r) => val(r, 'Name'))
    expect(res).toEqual(['Customer', 'Supplier', 'Tool Engineer'])
    expect(doc.getElementsByTagName('Assignment')).toHaveLength(3)
  })
  it('escapes special characters', () => {
    expect(xml).toContain('Tool rework &amp; &lt;check&gt; &quot;A&quot;')
    expect(val(taskEls(doc)[1], 'Name')).toBe('Tool rework & <check> "A"')
  })
  it('writes the calendar week and holidays', () => {
    const wd = Array.from(doc.getElementsByTagName('WeekDay'))
    const regular = wd.filter((w) => val(w, 'DayType') !== '0')
    // Calendar mode: every day works (elapsed durations); holidays only shade.
    expect(regular.map((w) => val(w, 'DayWorking'))).toEqual(['1', '1', '1', '1', '1', '1', '1'])
    expect(xml).toContain('<FromDate>2026-12-25T00:00:00</FromDate>')
    expect(xml).toContain('<Name>Holiday (shading only)</Name>')
    const w = parse(exportMspdi(workTasks, [], { calendar: WORK }))
    expect(Array.from(w.getElementsByTagName('WeekDay')).map((x) => val(x, 'DayWorking'))).toEqual(['0', '1', '1', '1', '1', '1', '0'])
  })
  it('leaves idea tasks out by default (like the server export)', () => {
    const d2 = parse(exportMspdi(calTasks, links, { calendar: CAL }))
    expect(taskEls(d2)).toHaveLength(5)
    // Links touching the idea (2->3, 3->4) drop out; 4->5 (UID 3) and 2->6 (UID 2) stay.
    expect(Array.from(d2.getElementsByTagName('PredecessorUID')).map((e) => e.textContent)).toEqual(['3', '2'])
  })
  it('uses working-day units in working mode', () => {
    const d2 = parse(exportMspdi(workTasks, [{ id: 'x', from: 2, to: 3, type: 'FS', lagDays: 2 }], { calendar: WORK }))
    const t = taskEls(d2)[1]
    expect(val(t, 'Duration')).toBe('PT40H0M0S')
    expect(val(t, 'DurationFormat')).toBe('7')
    expect(val(t, 'Finish')).toBe('2026-10-12T17:00:00')
    const pl = d2.getElementsByTagName('PredecessorLink')[0]
    expect([val(pl, 'LinkLag'), val(pl, 'LagFormat')]).toEqual(['9600', '7'])
  })
  it('exports an empty plan', () => {
    const d2 = parse(exportMspdi([], []))
    expect(d2.getElementsByTagName('parsererror')).toHaveLength(0)
    expect(taskEls(d2)).toHaveLength(0)
  })
})

describe('round trip export -> import', () => {
  it('keeps every field in calendar mode', () => {
    const back = importMspdi(exportMspdi(calTasks, links, { calendar: CAL, title: 'T', includeIdeas: true }))
    expect(back.tasks).toEqual(calTasks)
    expect(linkSet(back.links)).toEqual(linkSet(links))
    expect(back.calendar).toEqual(CAL)
    expect(back.warnings).toEqual([])
    expect(back.name).toBe('T')
  })
  it('keeps every field in working mode', () => {
    const wl: GanttLink[] = [{ id: 'x', from: 2, to: 3, type: 'FS', lagDays: 0 }, { id: 'y', from: 3, to: 5, type: 'SS', lagDays: -2 }]
    const back = importMspdi(exportMspdi(workTasks, wl, { calendar: WORK }))
    expect(back.tasks).toEqual(workTasks)
    expect(linkSet(back.links)).toEqual(linkSet(wl))
    expect(back.calendar).toEqual(WORK)
  })
  it('keeps string ids out: imported ids are the UIDs', () => {
    const back = importMspdi(exportMspdi([{ id: 'x', name: 'X', start: '2026-10-05', duration: 1 }], []))
    expect(back.tasks[0].id).toBe(1)
  })
  it('a second round trip is stable', () => {
    const once = importMspdi(exportMspdi(calTasks, links, { calendar: CAL, includeIdeas: true }))
    const twice = importMspdi(exportMspdi(once.tasks, once.links, { calendar: once.calendar, includeIdeas: true }))
    expect(twice.tasks).toEqual(once.tasks)
    expect(linkSet(twice.links)).toEqual(linkSet(once.links))
  })
})

const MSP = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Project xmlns="http://schemas.microsoft.com/project">
  <Name>Tooling.xml</Name>
  <MinutesPerDay>480</MinutesPerDay>
  <CalendarUID>3</CalendarUID>
  <Calendars>
    <Calendar><UID>1</UID><Name>Night</Name><WeekDays>
      <WeekDay><DayType>1</DayType><DayWorking>1</DayWorking></WeekDay>
    </WeekDays></Calendar>
    <Calendar><UID>3</UID><Name>Standard</Name><WeekDays>
      <WeekDay><DayType>1</DayType><DayWorking>0</DayWorking></WeekDay>
      <WeekDay><DayType>2</DayType><DayWorking>1</DayWorking></WeekDay>
      <WeekDay><DayType>3</DayType><DayWorking>1</DayWorking></WeekDay>
      <WeekDay><DayType>4</DayType><DayWorking>1</DayWorking></WeekDay>
      <WeekDay><DayType>5</DayType><DayWorking>1</DayWorking></WeekDay>
      <WeekDay><DayType>6</DayType><DayWorking>1</DayWorking></WeekDay>
      <WeekDay><DayType>7</DayType><DayWorking>0</DayWorking></WeekDay>
      <WeekDay><DayType>0</DayType><DayWorking>0</DayWorking>
        <TimePeriod><FromDate>2026-12-24T00:00:00</FromDate><ToDate>2026-12-26T23:59:00</ToDate></TimePeriod></WeekDay>
    </WeekDays></Calendar>
  </Calendars>
  <Tasks>
    <Task><UID>0</UID><ID>0</ID><Name>Tooling</Name><OutlineLevel>0</OutlineLevel><Start>2026-10-05T08:00:00</Start></Task>
    <Task><UID>10</UID><ID>1</ID><Name>Design</Name><OutlineLevel>1</OutlineLevel><Summary>1</Summary>
      <Start>2026-10-05T08:00:00</Start><Finish>2026-10-09T17:00:00</Finish><Duration>PT40H0M0S</Duration><DurationFormat>7</DurationFormat></Task>
    <Task><UID>11</UID><ID>2</ID><Name>Concept</Name><OutlineLevel>2</OutlineLevel>
      <Start>2026-10-05T08:00:00</Start><Finish>2026-10-06T17:00:00</Finish><Duration>PT16H0M0S</Duration><DurationFormat>7</DurationFormat>
      <PercentComplete>50</PercentComplete></Task>
    <Task><UID>12</UID><ID>3</ID><Name>Detail</Name><OutlineLevel>2</OutlineLevel>
      <Start>2026-10-07T08:00:00</Start><Finish>2026-10-09T17:00:00</Finish>
      <ConstraintType>5</ConstraintType><ConstraintDate>2026-10-07T08:00:00</ConstraintDate>
      <PredecessorLink><PredecessorUID>11</PredecessorUID><Type>1</Type><LinkLag>4800</LinkLag><LagFormat>7</LagFormat></PredecessorLink></Task>
    <Task><UID>13</UID><ID>4</ID><Name>Review</Name><OutlineLevel>1</OutlineLevel><Milestone>1</Milestone>
      <Start>2026-10-09T17:00:00</Start><Finish>2026-10-09T17:00:00</Finish><Duration>PT0H0M0S</Duration>
      <ConstraintType>7</ConstraintType><ConstraintDate>2026-10-16T17:00:00</ConstraintDate>
      <PredecessorLink><PredecessorUID>12</PredecessorUID><Type>1</Type></PredecessorLink>
      <PredecessorLink><PredecessorUID>99</PredecessorUID><Type>1</Type></PredecessorLink>
      <Baseline><Number>1</Number><Start>2026-01-01T08:00:00</Start></Baseline></Task>
    <Task><UID>14</UID><ID>5</ID><Name>No date</Name><OutlineLevel>1</OutlineLevel></Task>
  </Tasks>
  <Resources><Resource><UID>1</UID><Name>Design team</Name></Resource></Resources>
  <Assignments><Assignment><TaskUID>11</TaskUID><ResourceUID>1</ResourceUID></Assignment></Assignments>
</Project>`

describe('importMspdi from MS Project', () => {
  const r = importMspdi(MSP)
  it('uses the project calendar (Mon-Fri) with a holiday period', () => {
    expect(r.calendar).toEqual({ mode: 'working', workdays: [1, 2, 3, 4, 5], holidays: ['2026-12-24', '2026-12-25', '2026-12-26'] })
  })
  it('skips the project summary task and tasks without a start', () => {
    expect(r.tasks.map((t) => t.id)).toEqual([10, 11, 12, 13])
    expect(r.warnings.some((w) => w.includes('No date'))).toBe(true)
  })
  it('builds the hierarchy from outline levels', () => {
    expect(r.tasks.map((t) => t.parentId)).toEqual([null, 10, 10, null])
  })
  it('reads durations in working days', () => {
    expect(r.tasks[1]).toMatchObject({ start: '2026-10-05', duration: 2, progress: 50, lane: 'Design team' })
  })
  it('falls back to the finish date without a Duration element', () => {
    expect(r.tasks[2].duration).toBe(3)
  })
  // A start at the end of the working day (17:00) is the next day (backend rule).
  it('reads a milestone', () => expect(r.tasks[3]).toMatchObject({ start: '2026-10-10', duration: 0 }))
  it('reads a 17:00 finish constraint as the exclusive next day', () => {
    expect(r.tasks[3].constraint).toEqual({ type: 'fnlt', date: '2026-10-17' })
  })
  it('simplifies and warns about unsupported constraint types', () => {
    expect(r.tasks[2].constraint).toBeUndefined()
    expect(r.warnings.some((w) => w.includes('constraint type 5'))).toBe(true)
  })
  it('reads working-day lags (LagFormat 7)', () => {
    expect(r.links.find((l) => l.to === 12)).toMatchObject({ from: 11, type: 'FS', lagDays: 1 })
  })
  it('defaults a link without lag to 0 and skips links to unknown tasks', () => {
    expect(r.links.filter((l) => l.to === 13)).toEqual([{ id: 'L2', from: 12, to: 13, type: 'FS', lagDays: 0 }])
    expect(r.warnings.some((w) => w.includes('99'))).toBe(true)
  })
  it('only reads baseline 0', () => expect(r.tasks[3].baselineStart).toBeUndefined())
  it('reads the project name', () => expect(r.name).toBe('Tooling.xml'))
  it('rejects text that is not XML', () => expect(() => importMspdi('hello')).toThrow(/not an MS Project/))
  it('rejects XML that is not a project', () => expect(() => importMspdi('<a><b/></a>')).toThrow(/not an MS Project/))
  it('reads a file without calendars as Mon-Fri working days', () => {
    const x = importMspdi(`<Project xmlns="${MSPDI_NS}"><Tasks><Task><UID>1</UID><Name>A</Name><Start>2026-10-05T08:00:00</Start><Duration>PT8H0M0S</Duration></Task></Tasks></Project>`)
    expect(x.calendar.mode).toBe('working')
    expect(x.tasks[0]).toMatchObject({ id: 1, duration: 1, parentId: null })
  })
  it('reads elapsed-day durations in a calendar-mode project', () => {
    const x = importMspdi(`<Project xmlns="${MSPDI_NS}"><DurationFormat>8</DurationFormat><Tasks><Task><UID>1</UID><Name>A</Name><Start>2026-10-05T08:00:00</Start><Duration>PT72H0M0S</Duration><DurationFormat>8</DurationFormat></Task></Tasks></Project>`)
    expect(x.calendar.mode).toBe('calendar')
    expect(x.tasks[0].duration).toBe(3)
  })
})

describe('durationHours', () => {
  it('parses MSPDI durations', () => {
    expect(durationHours('PT40H0M0S')).toBe(40)
    expect(durationHours('PT7H30M0S')).toBe(7.5)
    expect(durationHours('P2DT4H')).toBe(52)
    expect(durationHours('P1D')).toBe(24)
  })
  it('returns null for rubbish', () => {
    expect(durationHours(null)).toBeNull()
    expect(durationHours('40h')).toBeNull()
  })
})

describe('MSPDI parity with the backend (review)', () => {
  const sumTasks: GanttTask[] = [
    { id: 1, name: 'Phase', start: '2026-10-05', duration: 0, constraint: { type: 'mso', date: '2026-10-05' } },
    { id: 2, parentId: 1, name: 'A', start: '2026-10-05', duration: 4, progress: 100 },
    { id: 3, parentId: 1, name: 'B', start: '2026-10-09', duration: 2, progress: 0 },
    { id: 4, name: 'Idea', start: '2026-10-05', duration: 2, isIdea: true },
  ]
  const doc = parse(exportMspdi(sumTasks, [], { calendar: CAL }))
  const ts = taskEls(doc)
  it('drops mso/mfo on a summary and writes its rolled-up percent', () => {
    expect(val(ts[0], 'ConstraintType')).toBeNull()
    expect(val(ts[0], 'PercentComplete')).toBe('67')
  })
  it('leaves idea tasks out by default', () => expect(ts).toHaveLength(3))
  it('a summary keeps snet / fnlt', () => {
    const d = parse(exportMspdi([{ ...sumTasks[0], constraint: { type: 'fnlt', date: '2026-10-20' } }, sumTasks[1]], [], { calendar: CAL }))
    expect(val(taskEls(d)[0], 'ConstraintType')).toBe('7')
    expect(val(taskEls(d)[0], 'ConstraintDate')).toBe('2026-10-19T17:00:00')
  })
  const wrap = (tasks: string) => `<Project xmlns="${MSPDI_NS}"><DurationFormat>7</DurationFormat><Tasks>${tasks}</Tasks></Project>`
  it('refuses an FF link into a summary task', () => {
    expect(() => importMspdi(wrap(`
      <Task><UID>1</UID><Name>X</Name><OutlineLevel>1</OutlineLevel><Start>2026-10-05T08:00:00</Start><Duration>PT8H0M0S</Duration></Task>
      <Task><UID>2</UID><Name>S</Name><OutlineLevel>1</OutlineLevel><Summary>1</Summary><Start>2026-10-05T08:00:00</Start>
        <PredecessorLink><PredecessorUID>1</PredecessorUID><Type>0</Type></PredecessorLink></Task>
      <Task><UID>3</UID><Name>C</Name><OutlineLevel>2</OutlineLevel><Start>2026-10-05T08:00:00</Start><Duration>PT8H0M0S</Duration></Task>`))).toThrow(/FF link into the summary/)
  })
  it('refuses must-start-on on a summary task', () => {
    expect(() => importMspdi(wrap(`
      <Task><UID>2</UID><Name>S</Name><OutlineLevel>1</OutlineLevel><Start>2026-10-05T08:00:00</Start>
        <ConstraintType>2</ConstraintType><ConstraintDate>2026-10-06T08:00:00</ConstraintDate></Task>
      <Task><UID>3</UID><Name>C</Name><OutlineLevel>2</OutlineLevel><Start>2026-10-05T08:00:00</Start><Duration>PT8H0M0S</Duration></Task>`))).toThrow(/summary task with a must-start-on/)
  })
  it('a skipped row keeps the outline: its children move up, not under a sibling', () => {
    const r = importMspdi(wrap(`
      <Task><UID>1</UID><Name>Sibling</Name><OutlineLevel>1</OutlineLevel><Start>2026-10-05T08:00:00</Start><Duration>PT8H0M0S</Duration></Task>
      <Task><UID>2</UID><Name>Broken</Name><OutlineLevel>1</OutlineLevel></Task>
      <Task><UID>3</UID><Name>Child</Name><OutlineLevel>2</OutlineLevel><Start>2026-10-05T08:00:00</Start><Duration>PT8H0M0S</Duration></Task>`))
    expect(r.tasks.map((t) => [t.id, t.parentId])).toEqual([[1, null], [3, null]])
  })
  it('reads SNET on the own start as no constraint, and shading holidays back in calendar mode', () => {
    const back = importMspdi(exportMspdi([{ id: 1, name: 'A', start: '2026-10-05', duration: 2 }], [], { calendar: CAL }))
    expect(back.tasks[0].constraint).toBeUndefined()
    expect(back.calendar).toEqual(CAL)
  })
  it('a start at 17:00 is the next day', () => {
    const r = importMspdi(wrap(`<Task><UID>1</UID><Name>M</Name><OutlineLevel>1</OutlineLevel><Milestone>1</Milestone><Start>2026-10-09T17:00:00</Start></Task>`))
    expect(r.tasks[0].start).toBe('2026-10-10')
  })
})
