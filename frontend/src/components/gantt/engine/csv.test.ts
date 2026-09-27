import { describe, expect, it } from 'vitest'
import { CSV_HEADER, csvCell, exportCsv } from './csv'
import type { GanttLink, GanttTask } from './types'

const tasks: GanttTask[] = [
  { id: 1, name: 'Summary', start: '2026-10-05', duration: 0 },
  { id: 2, parentId: 1, name: 'Tool, rework "A"', start: '2026-10-05', duration: 5, lane: 'Tool Engineer', kind: 'downtime', progress: 40, baselineStart: '2026-10-05', baselineEnd: '2026-10-08' },
  { id: 3, parentId: 1, name: '=cmd()', start: '2026-10-12', duration: 2, constraint: { type: 'snet', date: '2026-10-12' }, isIdea: true, notes: 'line1\nline2' },
  { id: 4, name: 'SOP', start: '2026-10-14', duration: 0 },
]
const links: GanttLink[] = [
  { id: 'a', from: 2, to: 3, type: 'FS', lagDays: 2 },
  { id: 'b', from: 3, to: 4, type: 'FS', lagDays: 0 },
]

describe('csvCell', () => {
  it('passes plain values', () => expect(csvCell('abc')).toBe('abc'))
  it('quotes commas, quotes and newlines', () => {
    expect(csvCell('a,b')).toBe('"a,b"')
    expect(csvCell('say "hi"')).toBe('"say ""hi"""')
    expect(csvCell('a\nb')).toBe('"a\nb"')
  })
  it('neutralises formulas', () => {
    expect(csvCell('=1+1')).toBe("'=1+1")
    expect(csvCell('@SUM(A1)')).toBe("'@SUM(A1)")
    expect(csvCell('+x')).toBe("'+x")
  })
  it('keeps negative numbers', () => expect(csvCell(-3)).toBe('-3'))
  it('writes null as empty', () => expect(csvCell(null)).toBe(''))
})

describe('exportCsv', () => {
  const out = exportCsv(tasks, links)
  const lines = out.trimEnd().split('\r\n')
  it('writes the header first', () => expect(lines[0]).toBe(CSV_HEADER.join(',')))
  it('has one row per task in pre-order with WBS', () => {
    expect(lines.slice(1).map((l) => l.split(',')[1])).toEqual(['1', '1.1', '1.2', '2'])
  })
  it('writes the inclusive finish, baseline finish and progress', () => {
    const row = lines[2]
    expect(row).toContain('"Tool, rework ""A"""')
    expect(row).toContain('2026-10-05,2026-10-09,5')
    expect(row).toContain(',40,2026-10-05,2026-10-07,')
  })
  it('writes predecessors in MS Project notation, constraint and idea', () => {
    const row = out.split('\r\n').find((l) => l.startsWith('3,'))!
    expect(row).toContain("'=cmd()")
    expect(row).toContain(',2FS+2d,')
    expect(row).toContain('SNET,2026-10-12,yes')
    expect(row).toContain('"line1\nline2"')
  })
  it('a milestone finishes on its start', () => {
    expect(lines[4]).toContain('2026-10-14,2026-10-14,0,3')
  })
  it('uses working days for the finish in working mode', () => {
    const w = exportCsv([{ id: 1, name: 'A', start: '2026-10-08', duration: 3 }], [], { mode: 'working' })
    expect(w).toContain('2026-10-08,2026-10-12,3')
  })
  it('ends with a line break', () => expect(out.endsWith('\r\n')).toBe(true))
})
