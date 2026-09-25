/**
 * The change-plan specific tools that sit in the generic Gantt toolbar:
 * seed, buffer and bank build presets, server auto-schedule, alignment of
 * the selection and MS Project import. Fixed width, so selecting never moves
 * the chart.
 */
import { useEffect, useRef, useState, type ReactNode } from 'react'

export const btn =
  'inline-flex items-center gap-1 rounded-md border border-slate-600 bg-slate-800 px-2 py-1 text-xs text-slate-200 hover:bg-slate-700 disabled:opacity-40 disabled:cursor-not-allowed'
export const btnPrimary =
  'inline-flex items-center gap-1 rounded-md bg-sky-600 px-2.5 py-1 text-xs font-medium text-white hover:bg-sky-500 disabled:opacity-40 disabled:cursor-not-allowed'

const menuItem = 'flex w-full items-center gap-2 px-3 py-1.5 text-left text-xs text-slate-200 hover:bg-slate-800 disabled:opacity-40'

export function Menu({ label, ariaLabel, children, testId, disabled }: {
  label: ReactNode; ariaLabel: string; children: (close: () => void) => ReactNode; testId?: string; disabled?: boolean
}) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!open) return
    const onDown = (e: MouseEvent) => { if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false) }
    document.addEventListener('mousedown', onDown)
    return () => document.removeEventListener('mousedown', onDown)
  }, [open])
  return (
    <div className="relative" ref={ref}>
      <button type="button" className={btn} aria-haspopup="menu" aria-expanded={open} disabled={disabled}
        aria-label={ariaLabel} data-testid={testId} onClick={() => setOpen((o) => !o)}>
        {label}<span className="text-[9px] text-slate-500">&#9662;</span>
      </button>
      {open && (
        <div role="menu" className="absolute left-0 z-40 mt-1 min-w-[200px] rounded-md border border-slate-700 bg-slate-900 py-1 shadow-xl">
          {children(() => setOpen(false))}
        </div>
      )}
    </div>
  )
}

export type AlignAction = 'snap' | 'match_start' | 'match_end' | 'parallel'

interface Props {
  canStructure: boolean
  canDates: boolean
  empty: boolean
  seedLabel?: string
  onSeed?: () => void
  onBuffer: () => void
  onBankBuild: () => void
  onSchedule?: () => void
  selectionCount: number
  onAlign: (a: AlignAction) => void
  groupByLane: boolean
  onGroupByLane: (v: boolean) => void
  onImport?: (file: File) => void
  onCalendar?: () => void
  calendarLabel?: string
}

export default function PlanToolbar(p: Props) {
  const fileRef = useRef<HTMLInputElement>(null)
  return (
    <>
      {p.canStructure && (
        <>
          <button type="button" className={btn} onClick={p.onBuffer} data-testid="gantt-add-buffer"
            title="Safety buffer: after the selection, or in front of the last milestone">+ Buffer</button>
          <button type="button" className={btn} onClick={p.onBankBuild} data-testid="gantt-add-bank-build"
            title="Bank build idea: ends where the first tool downtime (or the selection) starts">+ Bank build idea</button>
        </>
      )}
      {p.canDates && (
        <Menu label="Align" ariaLabel="Align the selected tasks" testId="gantt-align" disabled={p.selectionCount === 0}>
          {(close) => (
            <>
              <button type="button" role="menuitem" className={menuItem} data-testid="gantt-align-snap"
                onClick={() => { close(); p.onAlign('snap') }}>Snap to predecessors</button>
              <button type="button" role="menuitem" className={menuItem} disabled={p.selectionCount < 2}
                onClick={() => { close(); p.onAlign('match_start') }}>Match start of the first selected</button>
              <button type="button" role="menuitem" className={menuItem} disabled={p.selectionCount < 2}
                onClick={() => { close(); p.onAlign('match_end') }}>Match end of the first selected</button>
              {p.canStructure && (
                <button type="button" role="menuitem" className={menuItem} disabled={p.selectionCount < 2}
                  onClick={() => { close(); p.onAlign('parallel') }}>Run in parallel (drop their links)</button>
              )}
            </>
          )}
        </Menu>
      )}
      <label className="flex cursor-pointer items-center gap-1.5 px-1 text-xs text-slate-300">
        <input type="checkbox" className="accent-sky-500" checked={p.groupByLane} data-testid="gantt-group-toggle"
          onChange={(e) => p.onGroupByLane(e.target.checked)} />
        Lanes
      </label>
      {/* Less-used actions in one menu: the toolbar stays on one line. */}
      {(p.onSchedule || p.onCalendar || p.onImport || p.onSeed) && (
        <Menu label="More" ariaLabel="More plan actions" testId="gantt-more">
          {(close) => (
            <>
              {p.onSchedule && !p.empty && (
                <button type="button" role="menuitem" className={menuItem} data-testid="gantt-schedule"
                  title="Moves every task that starts before its predecessors allow. Never pulls tasks earlier."
                  onClick={() => { close(); p.onSchedule?.() }}>Auto-schedule now</button>
              )}
              {p.onCalendar && (
                <button type="button" role="menuitem" className={menuItem} data-testid="gantt-calendar"
                  onClick={() => { close(); p.onCalendar?.() }}>{p.calendarLabel ?? 'Calendar'}</button>
              )}
              {p.onImport && (
                <button type="button" role="menuitem" className={menuItem} data-testid="gantt-import"
                  onClick={() => { close(); fileRef.current?.click() }}>Import MS Project (.xml)</button>
              )}
              {p.onSeed && !p.empty && (
                <button type="button" role="menuitem" className={menuItem} data-testid="gantt-reseed"
                  onClick={() => { close(); p.onSeed?.() }}>{p.seedLabel}</button>
              )}
            </>
          )}
        </Menu>
      )}
      {p.onImport && (
        <input ref={fileRef} type="file" accept=".xml,application/xml,text/xml" className="hidden" data-testid="gantt-import-file"
          onChange={(e) => { const f = e.target.files?.[0]; e.target.value = ''; if (f) p.onImport?.(f) }} />
      )}
    </>
  )
}
