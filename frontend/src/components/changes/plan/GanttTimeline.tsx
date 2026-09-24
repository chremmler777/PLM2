/**
 * The right half of the Gantt: header (months, weeks or days) and the SVG body
 * with bars, links, deadlines and today. Pure rendering: every interaction is
 * handed back to the planner through callbacks.
 */
import { useEffect, useState, type PointerEvent as ReactPointerEvent, type RefObject } from 'react'
import type { PlanDeadline, TaskOut } from '../../../types/changePlan'
import {
  HEADER_H, KIND_COLOR, ROW_H, deadlineColor, endOf, fmtDay, minorTicks, monthTicks,
  showCritical, taskTooltip, toDay, weekendSpans, xOf,
  type Geo, type Range, type Row, type Zoom,
} from './ganttMath'

export interface LinkPreview { x1: number; y1: number; x2: number; y2: number }

interface HeaderProps {
  range: Range
  ppd: number
  zoom: Zoom
  today: number
  deadlines: PlanDeadline[]
  /** The scroll container: month labels stay readable at the left edge. */
  scrollerRef?: RefObject<HTMLElement>
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
      frame = requestAnimationFrame(() => setLeft(el.scrollLeft))
    }
    onScroll()
    el.addEventListener('scroll', onScroll, { passive: true })
    return () => { cancelAnimationFrame(frame); el.removeEventListener('scroll', onScroll) }
  }, [ref])
  return left
}

export function TimelineHeader({ range, ppd, zoom, today, deadlines, scrollerRef }: HeaderProps) {
  const scrollLeft = useScrollLeft(scrollerRef)
  const width = (range.to - range.from) * ppd
  const months = monthTicks(range, ppd)
  const minor = minorTicks(range, zoom, ppd)
  const tx = xOf(today, range, ppd)
  return (
    <svg width={width} height={HEADER_H} className="block select-none" aria-hidden="true">
      <rect width={width} height={HEADER_H} fill="#0f172a" />
      {months.map((m) => (
        <g key={`m${m.day}`}>
          <line x1={m.x} x2={m.x} y1={0} y2={HEADER_H} stroke="#334155" />
          <text x={Math.max(m.x + 6, Math.min(scrollLeft + 6, m.x + m.w - m.label.length * 7 - 6))}
            y={15} fontSize={11} fontWeight={600} fill="#cbd5e1">{m.label}</text>
        </g>
      ))}
      <line x1={0} x2={width} y1={22} y2={22} stroke="#334155" />
      {minor.map((t) => (
        <g key={`w${t.day}`}>
          <line x1={t.x} x2={t.x} y1={22} y2={HEADER_H} stroke="#1e293b" />
          {t.label && (
            <text x={t.x + t.w / 2} y={37} fontSize={10} textAnchor="middle"
              fill={zoom === 'day' && (t.day === today) ? '#38bdf8' : '#64748b'}>{t.label}</text>
          )}
        </g>
      ))}
      <line x1={0} x2={width} y1={HEADER_H - 0.5} y2={HEADER_H - 0.5} stroke="#334155" />
      {deadlines.map((d) => {
        const x = xOf(toDay(d.date), range, ppd)
        return <path key={d.key} d={`M${x - 4},${HEADER_H - 7} L${x + 4},${HEADER_H - 7} L${x},${HEADER_H - 1} Z`}
          fill={deadlineColor(d.key)} />
      })}
      {tx >= 0 && tx <= width && (
        <path d={`M${tx - 5},${HEADER_H - 8} L${tx + 5},${HEADER_H - 8} L${tx},${HEADER_H - 1} Z`} fill="#38bdf8" />
      )}
    </svg>
  )
}

interface BodyProps {
  rows: Row[]
  geos: Map<number, Geo>
  range: Range
  ppd: number
  zoom: Zoom
  today: number
  deadlines: PlanDeadline[]
  track: boolean
  critical: boolean
  criticalIds: number[]
  selected: Set<number>
  flashId: number | null
  rowNo: Map<number, number>
  /** Bars can be moved and resized. */
  canDrag: boolean
  /** Links can be drawn and removed. */
  canLink: boolean
  linkPreview: LinkPreview | null
  svgRef?: RefObject<SVGSVGElement>
  uid: string
  onBarPointerDown?: (e: ReactPointerEvent, task: TaskOut, mode: 'move' | 'resize') => void
  onLinkStart?: (e: ReactPointerEvent, task: TaskOut) => void
  onLinkClick?: (fromId: number, toId: number) => void
  onBackgroundPointerDown?: (e: ReactPointerEvent) => void
}

const BAR_PAD = 7

/** Deadline labels on two staggered lines so neighbours never overlap. */
function deadlineLabels(deadlines: PlanDeadline[], range: Range, ppd: number) {
  const ends = [-Infinity, -Infinity]
  return [...deadlines]
    .map((d) => ({ d, x: xOf(toDay(d.date), range, ppd), text: `${d.label} ${fmtDay(toDay(d.date))}` }))
    .sort((a, b) => a.x - b.x)
    .map((l) => {
      const w = l.text.length * 5.8 + 10
      const level = l.x >= ends[0] ? 0 : l.x >= ends[1] ? 1 : 0
      ends[level] = l.x + w
      return { ...l, level }
    })
}

export function TimelineBody(p: BodyProps) {
  const { rows, geos, range, ppd, zoom, track } = p
  const width = (p.range.to - p.range.from) * ppd
  const height = Math.max(rows.length, 1) * ROW_H
  const hatch = `gantt-hatch-${p.uid}`
  const arrow = `gantt-arrow-${p.uid}`
  const arrowBad = `gantt-arrow-bad-${p.uid}`

  // Row index of every visible task, for link routing.
  const rowIndex = new Map<number, number>()
  rows.forEach((r, i) => { if (r.type === 'task') rowIndex.set(r.task.id, i) })
  const tasks = rows.flatMap((r) => (r.type === 'task' ? [r.task] : []))

  const barTop = (i: number) => i * ROW_H + (track ? 5 : BAR_PAD)
  const barH = ROW_H - 2 * BAR_PAD

  const links: { from: number; to: number; d: string; bad: boolean }[] = []
  for (const t of tasks) {
    const ti = rowIndex.get(t.id)!
    const tg = geos.get(t.id)!
    for (const pid of t.predecessors) {
      const pi = rowIndex.get(pid)
      const pg = geos.get(pid)
      if (pi == null || !pg) continue
      const x1 = xOf(endOf(pg), range, ppd)
      const y1 = barTop(pi) + barH / 2
      const x2 = xOf(tg.start, range, ppd) - (tg.dur === 0 ? 6 : 0)
      const y2 = barTop(ti) + barH / 2
      let d: string
      if (x2 - x1 >= 12) {
        d = `M${x1},${y1} H${x1 + 6} V${y2} H${x2 - 1}`
      } else {
        const midY = ti > pi ? barTop(ti) - 4 : barTop(ti) + barH + 4
        d = `M${x1},${y1} H${x1 + 6} V${midY} H${x2 - 8} V${y2} H${x2 - 1}`
      }
      links.push({ from: pid, to: t.id, d, bad: tg.start < endOf(pg) })
    }
  }

  const tx = xOf(p.today, range, ppd)

  return (
    <svg ref={p.svgRef} width={width} height={height} className="block select-none"
      role="img" aria-label="Plan timeline" data-testid="gantt-body"
      onPointerDown={p.onBackgroundPointerDown}>
      <defs>
        <pattern id={hatch} width={6} height={6} patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
          <rect width={6} height={6} fill="#475569" />
          <line x1={0} y1={0} x2={0} y2={6} stroke="#94a3b8" strokeWidth={2} />
        </pattern>
        <marker id={arrow} viewBox="0 0 8 8" refX={7} refY={4} markerWidth={7} markerHeight={7} orient="auto">
          <path d="M0,0 L8,4 L0,8 Z" fill="#94a3b8" />
        </marker>
        <marker id={arrowBad} viewBox="0 0 8 8" refX={7} refY={4} markerWidth={7} markerHeight={7} orient="auto">
          <path d="M0,0 L8,4 L0,8 Z" fill="#f87171" />
        </marker>
      </defs>
      <rect width={width} height={height} fill="#0f172a" />
      {zoom !== 'month' && weekendSpans(range).map((w) => (
        <rect key={w.day} x={xOf(w.day, range, ppd)} y={0} width={w.len * ppd} height={height}
          fill="#1e293b" opacity={0.55} />
      ))}
      {rows.map((r, i) => r.type === 'lane'
        ? <rect key={`lane-${r.lane}`} x={0} y={i * ROW_H} width={width} height={ROW_H} fill="#1e293b" opacity={0.7} />
        : <line key={`row-${r.task.id}`} x1={0} x2={width} y1={(i + 1) * ROW_H - 0.5} y2={(i + 1) * ROW_H - 0.5}
            stroke="#1e293b" />)}
      {rows.map((r, i) => (r.type === 'task' && p.selected.has(r.task.id)
        ? <rect key={`sel-${r.task.id}`} x={0} y={i * ROW_H} width={width} height={ROW_H}
            fill="#0c4a6e" opacity={0.35} />
        : null))}

      {/* Deadlines */}
      {deadlineLabels(p.deadlines, range, ppd).map(({ d, x, level, text }) => {
        const c = deadlineColor(d.key)
        return (
          <g key={`dl-${d.key}`} data-testid={`gantt-deadline-${d.key}`}>
            <line x1={x} x2={x} y1={0} y2={height} stroke={c} strokeWidth={1.5} strokeDasharray="4 3" />
            <text x={x + 4} y={level === 0 ? 11 : 23} fontSize={10} fontWeight={600} fill={c}>
              {text}
            </text>
            <title>{`${d.label}: ${fmtDay(toDay(d.date))}`}</title>
          </g>
        )
      })}
      {tx >= 0 && tx <= width && (
        <line x1={tx} x2={tx} y1={0} y2={height} stroke="#38bdf8" strokeWidth={1.5} opacity={0.8} />
      )}

      {/* Links under the bars */}
      {links.map((l) => (
        <g key={`${l.from}-${l.to}`} data-testid={`gantt-link-${l.from}-${l.to}`}>
          <path d={l.d} fill="none" stroke={l.bad ? '#f87171' : '#64748b'} strokeWidth={1.25}
            markerEnd={`url(#${l.bad ? arrowBad : arrow})`} />
          {p.canLink && (
            <path d={l.d} fill="none" stroke="transparent" strokeWidth={9} className="cursor-pointer"
              role="button" aria-label={`Remove link ${p.rowNo.get(l.from)} to ${p.rowNo.get(l.to)}`}
              onPointerDown={(e) => e.stopPropagation()}
              onClick={() => p.onLinkClick?.(l.from, l.to)}>
              <title>Click to remove this link</title>
            </path>
          )}
        </g>
      ))}

      {rows.map((r, i) => {
        if (r.type !== 'task') return null
        const t = r.task
        const g = geos.get(t.id)!
        const x = xOf(g.start, range, ppd)
        const w = Math.max(g.dur * ppd, 2)
        const y = barTop(i)
        const cy = y + barH / 2
        const col = KIND_COLOR[t.kind] ?? KIND_COLOR.work
        const crit = showCritical(t, p.critical, p.criticalIds)
        const sel = p.selected.has(t.id)
        const flash = p.flashId === t.id
        const tip = taskTooltip(t, g, p.rowNo)
        const isMs = t.kind === 'milestone' || g.dur === 0
        const labelX = isMs ? x + 10 : x + w + (p.canLink ? 14 : 6)
        const move = (e: ReactPointerEvent) => p.onBarPointerDown?.(e, t, 'move')

        const baseline = track && t.baseline_start && t.baseline_finish ? (
          <rect x={xOf(toDay(t.baseline_start), range, ppd)} y={i * ROW_H + ROW_H - 7}
            width={Math.max((toDay(t.baseline_finish) - toDay(t.baseline_start)) * ppd, 2)} height={3}
            rx={1.5} fill="#94a3b8" opacity={0.55} data-testid={`gantt-baseline-${t.id}`} />
        ) : null
        const slipFrom = track && t.baseline_finish ? toDay(t.baseline_finish) : null
        const slip = slipFrom != null && endOf(g) > slipFrom && !isMs ? (
          <rect x={xOf(slipFrom, range, ppd)} y={y} height={barH} rx={2}
            width={(endOf(g) - slipFrom) * ppd} fill="#ef4444" opacity={0.85} pointerEvents="none"
            data-testid={`gantt-slip-${t.id}`} />
        ) : null
        const actuals = track ? [t.actual_start, t.actual_finish].map((a, k) => (a ? (
          <line key={k} x1={xOf(toDay(a) + k, range, ppd)} x2={xOf(toDay(a) + k, range, ppd)}
            y1={y - 3} y2={y + barH + 3} stroke="#34d399" strokeWidth={2} pointerEvents="none" />
        ) : null)) : null

        return (
          <g key={t.id} data-task-id={t.id} data-testid={`gantt-bar-${t.id}`} className="group">
            <title>{tip}</title>
            {baseline}
            {isMs ? (
              <path d={`M${x},${cy - 7} L${x + 7},${cy} L${x},${cy + 7} L${x - 7},${cy} Z`}
                  fill={t.is_idea ? 'transparent' : col.fill} stroke={crit ? '#ef4444' : sel ? '#f8fafc' : col.stroke}
                  strokeWidth={crit || sel ? 2 : 1} strokeDasharray={t.is_idea ? '3 2' : undefined}
                  className={p.canDrag ? 'cursor-grab' : 'cursor-pointer'} onPointerDown={move}
                  data-testid={`gantt-bar-shape-${t.id}`} />
            ) : (
              <>
                {crit && (
                  <rect x={x - 2.5} y={y - 2.5} width={w + 5} height={barH + 5} rx={4} fill="none"
                    stroke="#ef4444" strokeWidth={1.5} data-testid={`gantt-critical-${t.id}`} />
                )}
                <rect x={x} y={y} width={w} height={barH} rx={3}
                  fill={t.kind === 'buffer' ? `url(#${hatch})` : col.fill}
                  fillOpacity={t.is_idea ? 0.22 : track ? 0.45 : 0.9}
                  stroke={sel ? '#f8fafc' : t.is_idea ? col.stroke : 'none'}
                  strokeWidth={sel ? 1.5 : 1.25} strokeDasharray={t.is_idea && !sel ? '4 3' : undefined}
                  className={p.canDrag ? 'cursor-grab active:cursor-grabbing' : 'cursor-pointer'}
                  onPointerDown={move} data-testid={`gantt-bar-shape-${t.id}`} />
                {track && t.progress_pct > 0 && (
                  <rect x={x} y={y} width={w * Math.min(100, t.progress_pct) / 100} height={barH} rx={3}
                    fill={t.kind === 'buffer' ? `url(#${hatch})` : col.fill} pointerEvents="none"
                    data-testid={`gantt-progress-${t.id}`} />
                )}
                {slip}
                {flash && (
                  <rect x={x - 4} y={y - 4} width={w + 8} height={barH + 8} rx={5} fill="none"
                    stroke="#fbbf24" strokeWidth={2} className="animate-pulse" pointerEvents="none" />
                )}
                {p.canDrag && (
                  <rect x={x + w - 5} y={y} width={8} height={barH} fill="transparent"
                    className="cursor-ew-resize" data-testid={`gantt-resize-${t.id}`}
                    onPointerDown={(e) => p.onBarPointerDown?.(e, t, 'resize')} />
                )}
              </>
            )}
            {actuals}
            {p.canLink && (
              <circle cx={isMs ? x + 9 : x + w + 6} cy={cy} r={4} fill="#0f172a" stroke="#38bdf8" strokeWidth={1.5}
                className="cursor-crosshair opacity-0 group-hover:opacity-100 transition-opacity"
                data-testid={`gantt-connector-${t.id}`}
                onPointerDown={(e) => p.onLinkStart?.(e, t)}>
                <title>Drag onto another bar to link: that task starts after this one</title>
              </circle>
            )}
            <text x={labelX + (isMs && p.canLink ? 8 : 0)} y={cy + 3.5} fontSize={11}
              fill={t.is_idea ? '#fbbf24' : '#cbd5e1'} pointerEvents="none">
              {t.is_idea && <tspan fontSize={9} fontWeight={700}>IDEA </tspan>}
              {t.name}
            </text>
          </g>
        )
      })}

      {p.linkPreview && (
        <line x1={p.linkPreview.x1} y1={p.linkPreview.y1} x2={p.linkPreview.x2} y2={p.linkPreview.y2}
          stroke="#38bdf8" strokeWidth={1.5} strokeDasharray="4 3" markerEnd={`url(#${arrow})`}
          pointerEvents="none" />
      )}
    </svg>
  )
}
