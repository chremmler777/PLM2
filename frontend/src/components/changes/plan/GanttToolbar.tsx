/**
 * Everything the planner can do, in one row, plus the selection bar that
 * appears while tasks are selected.
 */
import { useEffect, useRef, useState, type ReactNode } from 'react'
import type { TaskKind } from '../../../types/changePlan'
import { KIND_COLOR, KIND_LABEL, ZOOMS, type Zoom } from './ganttMath'

export const btn =
  'inline-flex items-center gap-1 rounded-md border border-slate-600 bg-slate-800 px-2 py-1 text-xs text-slate-200 hover:bg-slate-700 disabled:opacity-40 disabled:cursor-not-allowed'
export const btnPrimary =
  'inline-flex items-center gap-1 rounded-md bg-sky-600 px-2.5 py-1 text-xs font-medium text-white hover:bg-sky-500 disabled:opacity-40 disabled:cursor-not-allowed'

function Menu({ label, ariaLabel, children, testId }: {
  label: ReactNode; ariaLabel: string; children: (close: () => void) => ReactNode; testId?: string
}) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!open) return
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', onDown)
    return () => document.removeEventListener('mousedown', onDown)
  }, [open])
  return (
    <div className="relative" ref={ref}>
      <button type="button" className={btn} aria-haspopup="menu" aria-expanded={open}
        aria-label={ariaLabel} data-testid={testId} onClick={() => setOpen((o) => !o)}>
        {label}<span className="text-[9px] text-slate-500">&#9662;</span>
      </button>
      {open && (
        <div role="menu" className="absolute left-0 z-30 mt-1 min-w-[180px] rounded-md border border-slate-700 bg-slate-900 py-1 shadow-xl">
          {children(() => setOpen(false))}
        </div>
      )}
    </div>
  )
}

const menuItem = 'flex w-full items-center gap-2 px-3 py-1.5 text-left text-xs text-slate-200 hover:bg-slate-800'

export type AddPreset = 'buffer' | 'bank_build' | 'milestone'
export type AlignAction = 'snap' | 'match_start' | 'match_end' | 'parallel'

interface Props {
  canStructure: boolean
  canDates: boolean
  canSchedule: boolean
  empty: boolean
  seedLabel: string
  zoom: Zoom
  onZoom: (z: Zoom) => void
  critical: boolean
  onCritical: (v: boolean) => void
  onAddTask: (kind: TaskKind) => void
  onAddPreset: (p: AddPreset) => void
  onSchedule: () => void
  onExport: (fmt: 'xml' | 'csv') => void
  onSeed?: () => void
  saving: boolean
  selectionCount: number
  onAlign: (a: AlignAction) => void
  onDeleteSelection?: () => void
  onClearSelection: () => void
}

const TASK_KINDS_MENU: TaskKind[] = ['work', 'supplier', 'downtime', 'sampling', 'validation', 'customer']

export default function GanttToolbar(p: Props) {
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-2" data-testid="gantt-toolbar">
        {p.canStructure && (
          <>
            <Menu label="+ Task" ariaLabel="Add a task" testId="gantt-add-task">
              {(close) => TASK_KINDS_MENU.map((k) => (
                <button key={k} type="button" role="menuitem" className={menuItem}
                  data-testid={`gantt-add-${k}`}
                  onClick={() => { close(); p.onAddTask(k) }}>
                  <span className="h-2.5 w-2.5 rounded-sm" style={{ background: KIND_COLOR[k].fill }} />
                  {KIND_LABEL[k]}
                </button>
              ))}
            </Menu>
            <button type="button" className={btn} aria-label="Add a buffer" onClick={() => p.onAddPreset('buffer')}>+ Buffer</button>
            <button type="button" className={btn} aria-label="Add a bank build idea" onClick={() => p.onAddPreset('bank_build')}>+ Bank build idea</button>
            <button type="button" className={btn} aria-label="Add a milestone" onClick={() => p.onAddPreset('milestone')}>+ Milestone</button>
            <span className="mx-1 h-5 w-px bg-slate-700" />
          </>
        )}
        {p.canSchedule && !p.empty && (
          <button type="button" className={btn} onClick={p.onSchedule} data-testid="gantt-schedule"
            aria-label="Auto-schedule: move every task to start after its predecessors"
            title="Moves every task that starts before its predecessors end. Never pulls tasks earlier.">
            Auto-schedule
          </button>
        )}
        {p.onSeed && !p.empty && (
          <button type="button" className={btn} onClick={p.onSeed} aria-label={`${p.seedLabel} (replaces the plan)`}>
            {p.seedLabel}
          </button>
        )}

        <div className="ml-auto flex flex-wrap items-center gap-2">
          {p.saving && (
            <span className="flex items-center gap-1.5 text-[11px] text-slate-400" data-testid="gantt-saving" role="status">
              <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-sky-400" />Saving
            </span>
          )}
          <label className="flex cursor-pointer items-center gap-1.5 text-xs text-slate-300">
            <input type="checkbox" className="accent-red-500" checked={p.critical}
              aria-label="Show critical path" onChange={(e) => p.onCritical(e.target.checked)} />
            Critical path
          </label>
          <div className="inline-flex overflow-hidden rounded-md border border-slate-600" role="group" aria-label="Zoom">
            {ZOOMS.map((z) => (
              <button key={z} type="button" aria-pressed={p.zoom === z} aria-label={`Zoom to ${z}s`}
                onClick={() => p.onZoom(z)}
                className={`px-2 py-1 text-xs capitalize ${p.zoom === z ? 'bg-sky-700 text-white' : 'bg-slate-800 text-slate-300 hover:bg-slate-700'}`}>
                {z}
              </button>
            ))}
          </div>
          {!p.empty && (
            <Menu label="Export" ariaLabel="Export the plan" testId="gantt-export">
              {(close) => (
                <>
                  <button type="button" role="menuitem" className={menuItem}
                    onClick={() => { close(); p.onExport('xml') }}>MS Project (.xml)</button>
                  <button type="button" role="menuitem" className={menuItem}
                    onClick={() => { close(); p.onExport('csv') }}>Spreadsheet (.csv)</button>
                </>
              )}
            </Menu>
          )}
        </div>
      </div>

      {p.selectionCount > 0 && (
        <div className="flex flex-wrap items-center gap-2 rounded-md border border-sky-800/60 bg-sky-950/40 px-2 py-1.5"
          data-testid="gantt-selection-bar">
          <span className="text-xs text-sky-200">{p.selectionCount} selected</span>
          {p.canDates && (
            <>
              <button type="button" className={btn} onClick={() => p.onAlign('snap')}
                title="Start each selected task when its latest predecessor ends">Snap to predecessors</button>
              {p.selectionCount > 1 && (
                <>
                  <button type="button" className={btn} onClick={() => p.onAlign('match_start')}
                    title="Give the selection the start of the first selected task">Match start</button>
                  <button type="button" className={btn} onClick={() => p.onAlign('match_end')}
                    title="Give the selection the end of the first selected task">Match end</button>
                </>
              )}
              {p.selectionCount > 1 && p.canStructure && (
                <button type="button" className={btn} onClick={() => p.onAlign('parallel')}
                  title="Remove the links between the selected tasks and start them together">Run in parallel</button>
              )}
            </>
          )}
          {p.onDeleteSelection && (
            <button type="button" className={`${btn} text-red-300`} onClick={p.onDeleteSelection}>Delete</button>
          )}
          <span className="hidden text-[11px] text-slate-500 md:inline">
            {p.canDates ? 'Arrow keys move by a day, shift+arrow by a week. Esc clears.' : 'Esc clears.'}
          </span>
          <button type="button" className="ml-auto text-xs text-slate-400 hover:text-slate-200"
            aria-label="Clear selection" onClick={p.onClearSelection}>Clear</button>
        </div>
      )}
    </div>
  )
}
