/**
 * The time half of the Gantt: header (two tick rows, markers) and the SVG
 * body (shading, rows, markers, links, bars). Pure rendering of what the
 * container computed; every pointer action is handed back via callbacks.
 * Only rows in [first, last] are drawn (virtualised).
 */
import { memo, useEffect, useState, type PointerEvent as ReactPointerEvent, type RefObject } from 'react'
import { fmtShort, toDay, type Cal } from './engine/calendar'
import { key } from './engine/tree'
import type { GanttLink, GanttTask } from './engine/types'
import {
  anchorX, barGeo, linkSides, majorTicks, minorTicks, offDaySpans, routeLink, textWidth, xOf,
  type BarGeo, type Obstacle, type Range, type Row, type Zoom,
} from './layout'
import { DEFAULT_KIND, v, type GanttKindStyle } from './theme'

export interface GanttMarker {
  id: string
  date: string
  label: string
  color?: string
  /** Default dashed. */
  dashed?: boolean
}

export interface TaskGeo { s: number; e: number; milestone: boolean; summary: boolean }

export const HEADER_H = 44

export interface LinkDraft { x1: number; y1: number; x2: number; y2: number }

export const MARKER_STRIP = 16

interface HeaderProps {
  range: Range
  ppd: number
  unit: Zoom
  today: number | null
  markers: GanttMarker[]
  /** The scroll container: the month label cut at the left edge stays readable. */
  scrollerRef?: RefObject<HTMLElement>
  cal: Cal
}

/** Follows the horizontal scroll of the chart, re-rendering only the header. */
function useScrollLeft(ref?: RefObject<HTMLElement>): number {
  const [left, setLeft] = useState(0)
  useEffect(() => {
    const el = ref?.current
    if (!el) return
    let frame = 0
    const onScroll = () => {
      cancelAnimationFrame(frame)
      frame = requestAnimationFrame(() => setLeft(Math.max(0, el.scrollLeft)))
    }
    onScroll()
    el.addEventListener('scroll', onScroll, { passive: true })
    return () => { cancelAnimationFrame(frame); el.removeEventListener('scroll', onScroll) }
  }, [ref])
  return left
}

export const ChartHeader = memo(function ChartHeader({ range, ppd, unit, today, markers, scrollerRef, cal }: HeaderProps) {
  const scrollLeft = useScrollLeft(scrollerRef)
  const width = Math.max(1, (range.to - range.from) * ppd)
  const H = HEADER_H + (markers.length ? MARKER_STRIP : 0)
  const major = majorTicks(range, ppd, unit)
  const minor = minorTicks(range, ppd, unit)
  return (
    <svg width={width} height={H} className="block select-none" data-testid="gantt-chart-header">
      <rect width={width} height={H} style={{ fill: v('headerBg') }} />
      {major.map((m) => {
        // Keep the label of the tick that is cut at the left edge readable.
        const labelW = m.label.length * 6.4
        const lx = Math.max(m.x + 6, Math.min(scrollLeft + 6, m.x + m.w - labelW - 6))
        // A tick mostly scrolled under the grid keeps no label (it would peek out cut).
        const hideLabel = lx < scrollLeft + 2
        return (
          <g key={`M${m.day}`}>
            <line x1={m.x + 0.5} x2={m.x + 0.5} y1={0} y2={HEADER_H} style={{ stroke: v('gridLine') }} />
            {m.label && !hideLabel && <text x={lx} y={15} fontSize={11} fontWeight={600} style={{ fill: v('text') }}>{m.label}</text>}
          </g>
        )
      })}
      <line x1={0} x2={width} y1={22.5} y2={22.5} style={{ stroke: v('gridLine') }} />
      {minor.map((t) => {
        const off = unit === 'day' && !cal.isWork(t.day)
        return (
          <g key={`m${t.day}`}>
            {off && <rect x={t.x} y={23} width={t.w} height={HEADER_H - 23} style={{ fill: v('offDay') }} />}
            <line x1={t.x + 0.5} x2={t.x + 0.5} y1={23} y2={HEADER_H} style={{ stroke: v('rowLine') }} />
            {t.label && (
              <text x={t.x + t.w / 2} y={37} fontSize={10} textAnchor="middle"
                style={{ fill: unit === 'day' && t.day === today ? v('today') : v('textFaint') }}>{t.label}</text>
            )}
          </g>
        )
      })}
      <line x1={0} x2={width} y1={H - 0.5} y2={H - 0.5} style={{ stroke: v('gridLine') }} />
      {markers.length > 0 && <line x1={0} x2={width} y1={HEADER_H - 0.5} y2={HEADER_H - 0.5} style={{ stroke: v('rowLine') }} />}
      {(() => {
        // One strip: a label goes right of its line, else left of it, else it
        // shrinks to its date; the full text stays in the tooltip.
        let end = -Infinity
        return markerLabels(markers, range, ppd).map(({ m, x, text }) => {
          const c = m.color ?? '#94a3b8'
          const short = fmtShort(toDay(m.date))
          const place = (t: string) => {
            const w = t.length * 5.6 + 10
            const right = x + 2, left = x - w - 2
            if (right >= end + 2 && right + w <= width) return { t, w, at: right }
            if (left >= end + 2 && left >= 0) return { t, w, at: left }
            return null
          }
          const pos = place(text) ?? place(short)
          if (pos) end = pos.at + pos.w
          return (
            <g key={m.id} data-testid={`gantt-marker-label-${m.id}`}>
              <path d={`M${x - 4},${HEADER_H - 6} L${x + 4},${HEADER_H - 6} L${x},${HEADER_H} Z`} fill={c} />
              <line x1={x} x2={x} y1={HEADER_H} y2={H} stroke={c} strokeWidth={1.5} />
              {pos && (
                <>
                  <rect x={pos.at} y={HEADER_H + 2} width={pos.w} height={MARKER_STRIP - 4} rx={3} fill={c} fillOpacity={0.18} stroke={c} strokeWidth={0.75} />
                  <text x={pos.at + 5} y={HEADER_H + MARKER_STRIP - 5} fontSize={9.5} fontWeight={600} fill={c}>{pos.t}</text>
                </>
              )}
              <title>{text}</title>
            </g>
          )
        })
      })()}
      {today != null && today >= range.from && today <= range.to && (() => {
        const x = xOf(today, range, ppd)
        return <path d={`M${x - 5},${HEADER_H - 8} L${x + 5},${HEADER_H - 8} L${x},${HEADER_H - 1} Z`} style={{ fill: v('today') }} />
      })()}
    </svg>
  )
})

export interface ChartBodyProps {
  uid: string
  rows: Row[]
  rowH: number
  first: number
  last: number
  range: Range
  ppd: number
  unit: Zoom
  cal: Cal
  geo: Map<string, TaskGeo>
  links: GanttLink[]
  kinds: Record<string, GanttKindStyle>
  selected: Set<string>
  critical: Set<string> | null
  showBaselines: boolean
  showProgress: boolean
  pending: Set<string>
  flashKey: string | null
  markers: GanttMarker[]
  today: number | null
  linkLabels: (l: GanttLink) => string
  brokenLinks: Set<string>
  canDrag: (t: GanttTask) => boolean
  canLink: boolean
  canProgress: (t: GanttTask) => boolean
  linkDraft: LinkDraft | null
  svgRef?: RefObject<SVGSVGElement>
  onBarDown?: (e: ReactPointerEvent, t: GanttTask, mode: 'move' | 'start' | 'end' | 'progress') => void
  onLinkHandleDown?: (e: ReactPointerEvent, t: GanttTask, side: 'start' | 'end') => void
  onLinkClick?: (e: React.MouseEvent, l: GanttLink) => void
  onLinkKey?: (e: React.KeyboardEvent, l: GanttLink) => void
  onBarKey?: (e: React.KeyboardEvent, t: GanttTask) => void
  onBackgroundDown?: (e: ReactPointerEvent) => void
  onBarContext?: (e: React.MouseEvent, t: GanttTask) => void
  onBarDoubleClick?: (t: GanttTask) => void
}

const PAD = 7

/** Deadline and custom marker labels, staggered on two lines so neighbours never overlap. */
function markerLabels(markers: GanttMarker[], range: Range, ppd: number) {
  const ends = [-Infinity, -Infinity]
  return [...markers]
    .map((m) => ({ m, x: xOf(toDay(m.date), range, ppd), text: `${m.label} ${fmtShort(toDay(m.date))}` }))
    .sort((a, b) => a.x - b.x)
    .map((l) => {
      const w = l.text.length * 5.8 + 10
      const level = l.x >= ends[0] ? 0 : l.x >= ends[1] ? 1 : 0
      ends[level] = l.x + w
      return { ...l, level }
    })
}

export const ChartBody = memo(function ChartBody(p: ChartBodyProps) {
  const { rows, rowH, range, ppd } = p
  const width = Math.max(1, (range.to - range.from) * ppd)
  const height = Math.max(rows.length, 1) * rowH
  const hatch = `g-hatch-${p.uid}`
  const arrow = `g-arrow-${p.uid}`
  const arrowBad = `g-arrow-bad-${p.uid}`
  const arrowCrit = `g-arrow-crit-${p.uid}`
  const barH = rowH - 2 * PAD
  const barTop = (i: number) => i * rowH + (p.showBaselines ? PAD - 2 : PAD)

  const idx = new Map<string, number>()
  rows.forEach((r, i) => { if (r.type === 'task') idx.set(key(r.task.id), i) })
  const bar = (k: string): BarGeo | null => {
    const g = p.geo.get(k)
    return g ? barGeo(g.s, g.e, range, ppd, g.milestone) : null
  }
  const inWindow = (i: number) => i >= p.first && i <= p.last

  // Obstacles for link routing: bars of visible rows.
  const obstacles: Obstacle[] = []
  for (let i = p.first; i <= p.last && i < rows.length; i++) {
    const r = rows[i]
    if (r.type !== 'task') continue
    const b = bar(key(r.task.id))
    if (b) obstacles.push({ row: i, x1: b.milestone ? b.x - 7 : b.x, x2: b.milestone ? b.x + 7 : b.x + b.w })
  }

  const linkPaths: { l: GanttLink; d: string; bad: boolean; crit: boolean }[] = []
  for (const l of p.links) {
    const fi = idx.get(key(l.from)), ti = idx.get(key(l.to))
    if (fi == null || ti == null) continue
    if (Math.max(fi, ti) < p.first || Math.min(fi, ti) > p.last) continue
    const fb = bar(key(l.from)), tb = bar(key(l.to))
    if (!fb || !tb) continue
    const sides = linkSides(l.type)
    const d = routeLink({
      x1: anchorX(fb, sides.from), y1: barTop(fi) + barH / 2, row1: fi, fromSide: sides.from,
      x2: anchorX(tb, sides.to), y2: barTop(ti) + barH / 2, row2: ti, toSide: sides.to,
      rowH, obstacles,
    })
    const crit = !!p.critical && p.critical.has(key(l.from)) && p.critical.has(key(l.to))
    linkPaths.push({ l, d, bad: p.brokenLinks.has(key(l.id)), crit })
  }

  const kindOf = (t: GanttTask): GanttKindStyle => (t.kind && p.kinds[t.kind]) || DEFAULT_KIND

  return (
    <svg ref={p.svgRef} width={width} height={height} className="block select-none" role="group"
      aria-label="Gantt chart: task bars and links" data-testid="gantt-body" onPointerDown={p.onBackgroundDown}>
      <defs>
        <pattern id={hatch} width={6} height={6} patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
          <rect width={6} height={6} fill="#475569" />
          <line x1={0} y1={0} x2={0} y2={6} stroke="#94a3b8" strokeWidth={2} />
        </pattern>
        {[[arrow, 'link'], [arrowBad, 'linkBad'], [arrowCrit, 'critical']].map(([id, tok]) => (
          <marker key={id} id={id} viewBox="0 0 8 8" refX={7} refY={4} markerWidth={7} markerHeight={7} orient="auto">
            <path d="M0,0 L8,4 L0,8 Z" style={{ fill: v(tok as 'link') }} />
          </marker>
        ))}
      </defs>
      <rect width={width} height={height} style={{ fill: v('bg') }} />
      {(p.unit === 'day' || p.unit === 'week') && offDaySpans(range, p.cal).map((w) => (
        <rect key={`off${w.day}`} x={xOf(w.day, range, ppd)} y={0} width={w.len * ppd} height={height}
          style={{ fill: v('offDay') }} />
      ))}
      {rows.map((r, i) => {
        if (!inWindow(i)) return null
        if (r.type === 'group') {
          return <rect key={r.key} x={0} y={i * rowH} width={width} height={rowH} style={{ fill: v('groupBg') }} />
        }
        const k = key(r.task.id)
        return (
          <g key={`row${k}`}>
            {p.selected.has(k) && <rect x={0} y={i * rowH} width={width} height={rowH} style={{ fill: v('selectBg') }} />}
            <line x1={0} x2={width} y1={(i + 1) * rowH - 0.5} y2={(i + 1) * rowH - 0.5} style={{ stroke: v('rowLine') }} />
          </g>
        )
      })}

      {markerLabels(p.markers, range, ppd).map(({ m, x }) => (
        <line key={`mk${m.id}`} data-testid={`gantt-marker-${m.id}`} x1={x} x2={x} y1={0} y2={height}
          stroke={m.color ?? '#94a3b8'} strokeWidth={1.5} strokeDasharray={m.dashed === false ? undefined : '4 3'} />
      ))}
      {p.today != null && p.today >= range.from && p.today <= range.to && (
        <line x1={xOf(p.today, range, ppd)} x2={xOf(p.today, range, ppd)} y1={0} y2={height}
          strokeWidth={1.5} opacity={0.8} style={{ stroke: v('today') }} data-testid="gantt-today" />
      )}

      {linkPaths.map(({ l, d, bad, crit }) => (
        <g key={`ln${key(l.id)}`} data-testid={`gantt-link-${key(l.from)}-${key(l.to)}`} data-link-type={l.type}>
          <path d={d} fill="none" strokeWidth={crit ? 1.75 : 1.25}
            style={{ stroke: bad ? v('linkBad') : crit ? v('critical') : v('link') }}
            markerEnd={`url(#${bad ? arrowBad : crit ? arrowCrit : arrow})`} />
          <path d={d} fill="none" stroke="transparent" strokeWidth={7} className="cursor-pointer focus:outline-none"
            role="button" tabIndex={0} aria-label={`Link ${p.linkLabels(l)}. Enter edits, Delete removes.`} data-testid={`gantt-link-hit-${key(l.id)}`}
            onPointerDown={(e) => e.stopPropagation()}
            onClick={(e) => p.onLinkClick?.(e, l)}
            onKeyDown={(e) => p.onLinkKey?.(e, l)}>
            <title>{`${p.linkLabels(l)}${bad ? ' (not met by the dates)' : ''}${l.readOnly ? '. Old dependency, re-draw to edit' : ''}`}</title>
          </path>
        </g>
      ))}

      {rows.map((r, i) => {
        if (r.type !== 'task' || !inWindow(i)) return null
        const t = r.task
        const k = key(t.id)
        const b = bar(k)
        const g = p.geo.get(k)
        if (!b || !g) return null
        const y = barTop(i)
        const cy = y + barH / 2
        const style = kindOf(t)
        const color = t.color ?? style.color
        const crit = !!p.critical?.has(k) && !t.isIdea
        const sel = p.selected.has(k)
        const drag = p.canDrag(t)
        const tip = `${t.name}${t.isIdea ? ' (idea)' : ''}\n${fmtShort(g.s)}${g.milestone ? '' : ` to ${fmtShort(g.e - 1)}`}`
        const pending = p.pending.has(k)
        // Label right of the bar; left of it when it would run past the chart end.
        const labelRight = b.milestone ? b.x + 12 : b.x + b.w + (p.canLink ? 14 : 6)
        const labelW = textWidth(t.name, 11) + (t.isIdea ? 28 : 0)
        const flip = labelRight + labelW > width - 4 && b.x - labelW - 10 > 0
        const labelX = flip ? (b.milestone ? b.x - 12 : b.x - (p.canLink ? 14 : 6)) : labelRight
        const baseline = p.showBaselines && t.baselineStart && t.baselineEnd ? (() => {
          const bs = toDay(t.baselineStart), be = toDay(t.baselineEnd)
          const bx = xOf(bs, range, ppd)
          return be <= bs
            ? <path d={`M${bx},${i * rowH + rowH - 8} l3,3 l-3,3 l-3,-3 Z`} style={{ fill: v('baseline') }} opacity={0.7}
                data-testid={`gantt-baseline-${k}`} pointerEvents="none" />
            : <rect x={bx} y={i * rowH + rowH - 6} width={Math.max((be - bs) * ppd, 2)} height={3} rx={1.5}
                style={{ fill: v('baseline') }} opacity={0.6} data-testid={`gantt-baseline-${k}`} pointerEvents="none" />
        })() : null
        const slipFrom = p.showBaselines && t.baselineEnd && !b.milestone && !r.summary ? toDay(t.baselineEnd) : null
        const slip = slipFrom != null && g.e > slipFrom ? (
          <rect x={xOf(Math.max(slipFrom, g.s), range, ppd)} y={y + barH - 3} height={3}
            width={(g.e - Math.max(slipFrom, g.s)) * ppd} style={{ fill: v('slip') }} pointerEvents="none"
            data-testid={`gantt-slip-${k}`} />
        ) : null
        const progress = Math.max(0, Math.min(100, t.progress ?? 0))
        // Actual work: a thin bar under the planned one, to the actual finish (or today while running).
        const actual = p.showProgress && t.actualStart && !r.summary ? (() => {
          const as = toDay(t.actualStart)
          const ae = t.actualEnd ? toDay(t.actualEnd) + 1 : (p.today != null && p.today > as ? p.today : as + 1)
          return (
            <rect x={xOf(as, range, ppd)} y={y + barH + 1} width={Math.max((ae - as) * ppd, 2)} height={2.5} rx={1}
              fill="#34d399" pointerEvents="none" data-testid={`gantt-actual-${k}`}>
              <title>{`Actual ${fmtShort(as)}${t.actualEnd ? ` to ${fmtShort(ae - 1)}` : ', running'}`}</title>
            </rect>
          )
        })() : null
        const down = (mode: 'move' | 'start' | 'end' | 'progress') => (e: ReactPointerEvent) => p.onBarDown?.(e, t, mode)

        let shape: JSX.Element
        if (r.summary) {
          const sy = y + 2
          shape = (
            <g data-testid={`gantt-bar-shape-${k}`} onPointerDown={down('move')}
              className={drag ? 'cursor-grab' : 'cursor-pointer'}>
              <path d={`M${b.x},${sy} H${b.x + b.w} V${sy + 7} L${b.x + b.w - 5},${sy + 12} L${b.x + b.w - 10},${sy + 7} H${b.x + 10} L${b.x + 5},${sy + 12} L${b.x},${sy + 7} Z`}
                style={{ fill: crit ? v('critical') : v('summary'), stroke: sel ? v('text') : 'none' }} strokeWidth={1} />
              {progress > 0 && (
                <rect x={b.x} y={sy} width={b.w * progress / 100} height={4} fill="#10b981" pointerEvents="none"
                  data-testid={`gantt-progress-${k}`} />
              )}
            </g>
          )
        } else if (b.milestone || style.milestone) {
          const s = 7
          shape = (
            <path d={`M${b.x},${cy - s} L${b.x + s},${cy} L${b.x},${cy + s} L${b.x - s},${cy} Z`}
              style={{ fill: t.isIdea ? 'transparent' : color, stroke: crit ? v('critical') : sel ? v('accent') : v('summary') }}
              strokeWidth={crit || sel ? 2 : 1} strokeDasharray={t.isIdea ? '3 2' : undefined}
              className={drag ? 'cursor-grab' : 'cursor-pointer'} onPointerDown={down('move')}
              data-testid={`gantt-bar-shape-${k}`} />
          )
        } else {
          const fill = style.pattern === 'hatch' ? `url(#${hatch})` : color
          shape = (
            <>
              {crit && (
                <rect x={b.x - 2.5} y={y - 2.5} width={b.w + 5} height={barH + 5} rx={4} fill="none"
                  strokeWidth={1.5} style={{ stroke: v('critical') }} data-testid={`gantt-critical-${k}`} pointerEvents="none" />
              )}
              <rect x={b.x} y={y} width={b.w} height={barH} rx={3} fill={fill}
                fillOpacity={t.isIdea ? 0.25 : p.showProgress && progress < 100 ? 0.5 : 0.92}
                stroke={sel ? 'currentColor' : t.isIdea ? color : 'none'}
                style={sel ? { color: 'var(--g-text)' } : undefined}
                strokeWidth={sel ? 1.5 : 1.25} strokeDasharray={t.isIdea && !sel ? '4 3' : undefined}
                className={drag ? 'cursor-grab active:cursor-grabbing' : 'cursor-pointer'}
                onPointerDown={down('move')} data-testid={`gantt-bar-shape-${k}`} />
              {p.showProgress && progress > 0 && (
                <rect x={b.x} y={y} width={b.w * progress / 100} height={barH} rx={3} fill={fill} pointerEvents="none"
                  data-testid={`gantt-progress-${k}`} />
              )}
              {slip}
              {drag && b.w >= 24 && (
                <rect x={b.x - 2} y={y} width={6} height={barH} fill="transparent" className="cursor-ew-resize"
                  data-testid={`gantt-resize-start-${k}`} onPointerDown={down('start')} />
              )}
              {drag && (
                <rect x={b.x + b.w - (b.w >= 16 ? 4 : 1)} y={y} width={b.w >= 16 ? 7 : 5} height={barH} fill="transparent"
                  className="cursor-ew-resize" data-testid={`gantt-resize-${k}`} onPointerDown={down('end')} />
              )}
              {p.showProgress && p.canProgress(t) && (
                <path d={`M${b.x + b.w * progress / 100},${y + barH - 1} l4,5 h-8 Z`} className="cursor-col-resize"
                  style={{ fill: v('text') }} opacity={0.8} data-testid={`gantt-progress-handle-${k}`}
                  onPointerDown={down('progress')}>
                  <title>{`Progress ${progress}%: drag to change`}</title>
                </path>
              )}
            </>
          )
        }
        return (
          <g key={k} data-task-id={k} data-testid={`gantt-bar-${k}`} className="group focus:outline-none"
            role="button" tabIndex={0} aria-pressed={sel}
            aria-label={`${t.name}${r.summary ? ' (summary)' : ''}, ${tip.split('\n')[1] ?? ''}. Space selects, Enter opens.`}
            onKeyDown={(e) => p.onBarKey?.(e, t)}
            opacity={pending ? 0.75 : 1}
            onContextMenu={(e) => p.onBarContext?.(e, t)}
            onDoubleClick={() => p.onBarDoubleClick?.(t)}>
            <title>{tip}</title>
            {baseline}
            {shape}
            {actual}
            {p.flashKey === k && (
              <rect x={b.x - 5} y={y - 4} width={Math.max(b.w, 10) + 10} height={barH + 8} rx={5} fill="none"
                strokeWidth={2} style={{ stroke: v('focus') }} className="animate-pulse" pointerEvents="none" />
            )}
            {p.canLink && (['start', 'end'] as const).map((side) => (
              <circle key={side} cx={anchorX(b, side) + (side === 'start' ? -5 : 5)} cy={cy} r={4}
                strokeWidth={1.5} data-side={side} data-task-id={k}
                style={{ fill: v('bg'), stroke: v('accent') }}
                className={`cursor-crosshair transition-opacity ${sel ? 'opacity-100' : 'opacity-0 group-hover:opacity-100'}`}
                data-testid={`gantt-connector-${side}-${k}`}
                onPointerDown={(e) => p.onLinkHandleDown?.(e, t, side)}>
                <title>{side === 'end' ? 'Drag to another bar: finish-to-start (drop on its right half: finish-to-finish)' : 'Drag to another bar: start-to-start (drop on its right half: start-to-finish)'}</title>
              </circle>
            ))}
            <text x={labelX} y={cy + 3.5} fontSize={11} pointerEvents="none" textAnchor={flip ? 'end' : 'start'}
              style={{ fill: t.isIdea ? v('idea') : r.summary ? v('text') : v('textMuted') }}
              fontWeight={r.summary ? 600 : 400}>
              {t.isIdea && <tspan fontSize={9} fontWeight={700}>IDEA </tspan>}
              {t.name}
            </text>
          </g>
        )
      })}

      {p.linkDraft && (
        <line x1={p.linkDraft.x1} y1={p.linkDraft.y1} x2={p.linkDraft.x2} y2={p.linkDraft.y2}
          strokeWidth={1.5} strokeDasharray="4 3" markerEnd={`url(#${arrow})`} pointerEvents="none"
          style={{ stroke: v('accent') }} data-testid="gantt-link-draft" />
      )}
    </svg>
  )
})
