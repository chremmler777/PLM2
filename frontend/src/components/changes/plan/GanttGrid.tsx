/**
 * The left half of the Gantt: one row per lane header and per task, the same
 * heights as the timeline so both halves line up.
 */
import type { MouseEvent } from 'react'
import type { TaskOut } from '../../../types/changePlan'
import {
  HEADER_H, ROW_H, fmtDay, gridWidth, inclusiveEnd, predecessorText, type Geo, type Row,
} from './ganttMath'

interface GridColumns {
  compact: boolean
  track: boolean
}

const cell = 'px-1.5 truncate tabular-nums'

export function GridHeader({ compact, track }: GridColumns) {
  return (
    <div className="flex items-end text-[10px] uppercase tracking-wide text-slate-500 border-b border-slate-700 bg-slate-900"
      style={{ height: HEADER_H, width: gridWidth({ compact, track }) }}>
      {compact ? (
        <div className="px-3 pb-1.5">Task</div>
      ) : (
        <div className="flex w-full pb-1.5">
          <div className="w-[28px] text-right pr-1.5">#</div>
          <div className="w-[196px] px-1.5">Task</div>
          <div className="w-[74px] px-1.5">Start</div>
          <div className="w-[74px] px-1.5">End</div>
          <div className="w-[44px] px-1.5 text-right">Days</div>
          <div className="w-[58px] px-1.5">After</div>
          {track && <div className="w-[50px] px-1.5 text-right">Done</div>}
        </div>
      )}
    </div>
  )
}

interface GridBodyProps extends GridColumns {
  rows: Row[]
  geos: Map<number, Geo>
  rowNo: Map<number, number>
  selected: Set<number>
  flashId: number | null
  issueIds: Set<number>
  onToggleLane: (lane: string) => void
  onRowClick?: (e: MouseEvent, task: TaskOut) => void
}

export function GridBody(p: GridBodyProps) {
  const width = gridWidth(p)
  return (
    <div style={{ width }} className="text-xs" data-testid="gantt-grid">
      {p.rows.map((r) => {
        if (r.type === 'lane') {
          return (
            <button key={`lane-${r.lane}`} type="button" style={{ height: ROW_H }}
              className="flex w-full items-center gap-1.5 px-2 bg-slate-800/80 border-b border-slate-700/70 text-left hover:bg-slate-800"
              aria-expanded={!r.collapsed} aria-label={`${r.collapsed ? 'Expand' : 'Collapse'} lane ${r.lane}`}
              data-testid={`gantt-lane-${r.lane}`}
              onClick={() => p.onToggleLane(r.lane)}>
              <span className={`text-slate-500 text-[10px] transition-transform ${r.collapsed ? '' : 'rotate-90'}`}>&#9656;</span>
              <span className="text-[10px] uppercase tracking-wide font-semibold text-slate-300 truncate">{r.lane}</span>
              <span className="text-[10px] text-slate-500">{r.count}</span>
            </button>
          )
        }
        const t = r.task
        const g = p.geos.get(t.id)!
        const sel = p.selected.has(t.id)
        const flagged = p.issueIds.has(t.id)
        return (
          <div key={t.id} role="row" tabIndex={-1} style={{ height: ROW_H }}
            aria-selected={sel}
            data-testid={`gantt-row-${t.id}`}
            className={`flex items-center border-b border-slate-800 cursor-pointer select-none ${
              sel ? 'bg-sky-900/40' : 'hover:bg-slate-800/60'} ${
              p.flashId === t.id ? 'ring-1 ring-inset ring-amber-400' : ''}`}
            onClick={(e) => p.onRowClick?.(e, t)}>
            {p.compact ? (
              <div className={`${cell} pl-3 text-slate-200`} title={t.name}>
                {t.is_idea && <span className="mr-1 text-[9px] font-bold text-amber-400">IDEA</span>}
                {t.name}
              </div>
            ) : (
              <>
                <div className="w-[28px] text-right pr-1.5 text-slate-500 tabular-nums">{p.rowNo.get(t.id)}</div>
                <div className={`w-[196px] ${cell} text-slate-200 flex items-center gap-1`} title={t.name}>
                  {flagged && <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-red-400" aria-label="Has a plan issue" />}
                  {t.is_idea && <span className="shrink-0 rounded border border-dashed border-amber-500/70 px-1 text-[9px] font-semibold uppercase text-amber-300">idea</span>}
                  <span className="truncate">{t.name || <em className="text-slate-500">unnamed</em>}</span>
                </div>
                <div className={`w-[74px] ${cell} text-slate-300`}>{fmtDay(g.start)}</div>
                <div className={`w-[74px] ${cell} text-slate-300`}>{fmtDay(inclusiveEnd(g))}</div>
                <div className={`w-[44px] ${cell} text-right text-slate-300`}>{g.dur === 0 ? '-' : g.dur}</div>
                <div className={`w-[58px] ${cell} text-slate-400`}>{predecessorText(t, p.rowNo)}</div>
                {p.track && (
                  <div className={`w-[50px] ${cell} text-right ${t.progress_pct >= 100 ? 'text-emerald-300' : 'text-slate-300'}`}>
                    {t.progress_pct}%
                  </div>
                )}
              </>
            )}
          </div>
        )
      })}
    </div>
  )
}
