import { describe, expect, it } from 'vitest'
import { makeCal, toDay } from './engine/calendar'
import type { GanttLink, GanttTask } from './engine/types'
import { BUILTIN_COLUMNS, type CellContext } from './columns'
import type { TaskGeo } from './GanttChart'
import { buildChartSvg, clip, printHtml } from './exportImage'
import { buildRows } from './layout'
import { THEMES } from './theme'

const tasks: GanttTask[] = [
  { id: 1, name: 'Tool <rework> & "fix"', start: '2026-10-05', duration: 5, kind: 'work' },
  { id: 2, name: 'Sampling', start: '2026-10-12', duration: 3, kind: 'buffer', isIdea: true },
  { id: 3, name: 'SOP', start: '2026-10-15', duration: 0 },
]
const links: GanttLink[] = [{ id: 'a', from: 1, to: 2, type: 'FS', lagDays: 0 }, { id: 'b', from: 2, to: 3, type: 'FF', lagDays: 1 }]
const geo = new Map<string, TaskGeo>(tasks.map((t) => [String(t.id), {
  s: toDay(t.start), e: toDay(t.start) + t.duration, milestone: t.duration === 0, summary: false,
}]))
const columns = [BUILTIN_COLUMNS.row, BUILTIN_COLUMNS.name, BUILTIN_COLUMNS.start]
const ctx = (t: GanttTask): CellContext => ({
  geo: geo.get(String(t.id)), rowNo: t.id as number, wbs: String(t.id), predecessors: '', sched: undefined,
  kinds: {}, summary: false, working: false,
})
const range = { from: toDay('2026-09-28'), to: toDay('2026-11-02') }
const input = (over = {}) => ({
  title: 'Plan & co', rows: buildRows(tasks).rows, columns, ctx, geo, links, range, ppd: 10, unit: 'week' as const,
  cal: makeCal(null), theme: THEMES.dark, kinds: { buffer: { label: 'Buffer', color: '#64748b', pattern: 'hatch' as const } },
  markers: [{ id: 'rel', date: '2026-10-20', label: 'Release <1>' }], today: toDay('2026-10-01'),
  critical: new Set(['1']), showBaselines: true, rowH: 28, ...over,
})

describe('buildChartSvg', () => {
  it('produces well-formed SVG', () => {
    const { svg } = buildChartSvg(input())
    const doc = new DOMParser().parseFromString(svg, 'image/svg+xml')
    expect(doc.getElementsByTagName('parsererror').length).toBe(0)
    expect(doc.documentElement.localName).toBe('svg')
  })

  it('contains every task name, escaped', () => {
    const { svg } = buildChartSvg(input())
    expect(svg).toContain('Tool &lt;rework&gt; &amp; &quot;fix&quot;')
    expect(svg).toContain('Sampling')
    expect(svg).toContain('SOP')
    expect(svg).toContain('Release &lt;1&gt;')
  })

  it('is as wide as the grid plus the chart', () => {
    const { width, height } = buildChartSvg(input())
    const gw = columns.reduce((n, c) => n + c.width, 0)
    expect(width).toBe(Math.ceil(gw + (range.to - range.from) * 10))
    // Title 28, scale 44, marker strip 16 (the input has a marker), 3 rows.
    expect(height).toBe(28 + 44 + 16 + 3 * 28)
  })

  it('leaves the title strip out without a title', () => {
    expect(buildChartSvg(input({ title: undefined })).height).toBe(44 + 16 + 3 * 28)
    expect(buildChartSvg(input({ title: undefined, markers: [] })).height).toBe(44 + 3 * 28)
  })

  it('draws the links, a milestone diamond, hatching and a critical frame', () => {
    const { svg } = buildChartSvg(input())
    expect((svg.match(/marker-end="url\(#a\)"/g) ?? []).length).toBe(2)
    expect(svg).toContain('stroke-dasharray="4 3"')
    expect(svg).toContain(THEMES.dark.critical)
  })

  it('uses literal theme colours (no CSS variables)', () => {
    expect(buildChartSvg(input({ theme: THEMES.light })).svg).not.toContain('var(')
  })
})

describe('clip', () => {
  it('keeps short text', () => { expect(clip('abc', 200)).toBe('abc') })
  it('cuts long text with an ellipsis', () => {
    const c = clip('a very long task name that goes on', 60)
    expect(c.endsWith('…')).toBe(true)
    expect(c.length).toBeLessThan(20)
  })
  it('gives nothing for a tiny cell', () => { expect(clip('abcdef', 8)).toBe('') })
})

describe('printHtml', () => {
  it('embeds the svg, escapes the title and prints on load', () => {
    const h = printHtml('<svg id="x"></svg>', 'A & B')
    expect(h).toContain('<svg id="x"></svg>')
    expect(h).toContain('<title>A &amp; B</title>')
    expect(h).toContain('window.print()')
    expect(h).toContain('landscape')
  })
})
