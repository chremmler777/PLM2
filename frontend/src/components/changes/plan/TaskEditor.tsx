/**
 * Right-side drawer for one task. Editors change everything; a member of the
 * task's department (track mode) changes progress and actual dates only;
 * everyone else reads.
 */
import { useEffect, useMemo, useState } from 'react'
import type { TaskKind, TaskOut, TaskPatch } from '../../../types/changePlan'
import { TASK_KINDS } from '../../../types/changePlan'
import {
  KIND_COLOR, KIND_LABEL, addDaysIso, durationFromInclusiveEnd, fmtIso, inclusiveEnd, laneOf,
  taskGeo, toDay, toIso,
} from './ganttMath'
import { btn, btnPrimary } from './GanttToolbar'

interface Props {
  task: TaskOut
  tasks: TaskOut[]
  rowNo: Map<number, number>
  departments: { id: number; name: string }[]
  /** Name, kind, lane, links, notes. */
  canEdit: boolean
  /** Start and duration. */
  canDates: boolean
  /** Progress and actuals (track mode). */
  canProgress: boolean
  track: boolean
  baselineSet: boolean
  saving: boolean
  onSave: (patch: TaskPatch) => void
  onDelete?: () => void
  onClose: () => void
}

const field = 'w-full rounded-md border border-slate-600 bg-slate-900 px-2 py-1 text-sm text-slate-100 [color-scheme:dark] disabled:opacity-60'
const label = 'block text-[10px] font-medium uppercase tracking-wide text-slate-500 mb-1'

interface Form {
  name: string
  kind: TaskKind
  lane: string
  department_id: string
  start_date: string
  duration: string
  predecessors: number[]
  is_idea: boolean
  notes: string
  progress_pct: number
  actual_start: string
  actual_finish: string
}

const formOf = (t: TaskOut): Form => ({
  name: t.name,
  kind: t.kind,
  lane: t.lane ?? '',
  department_id: t.department_id != null ? String(t.department_id) : '',
  start_date: t.start_date,
  duration: String(t.duration_days),
  predecessors: [...t.predecessors],
  is_idea: t.is_idea,
  notes: t.notes ?? '',
  progress_pct: t.progress_pct,
  actual_start: t.actual_start ?? '',
  actual_finish: t.actual_finish ?? '',
})

export default function TaskEditor(p: Props) {
  const { task } = p
  const [f, setF] = useState<Form>(() => formOf(task))
  // A server update (drag, auto-schedule) refreshes the form.
  useEffect(() => { setF(formOf(task)) }, [task])
  const set = <K extends keyof Form>(k: K, v: Form[K]) => setF((prev) => ({ ...prev, [k]: v }))

  const milestone = f.kind === 'milestone'
  const dur = milestone ? 0 : Math.max(0, Math.floor(Number(f.duration) || 0))
  const startOk = /^\d{4}-\d{2}-\d{2}$/.test(f.start_date)
  const endIncl = startOk ? toIso(inclusiveEnd({ start: toDay(f.start_date), dur })) : ''
  const readOnly = !p.canEdit && !p.canDates && !p.canProgress

  const laneOptions = useMemo(() => {
    const s = new Set<string>(['Customer', 'Supplier', ...p.departments.map((d) => d.name)])
    p.tasks.forEach((t) => { if (t.lane) s.add(t.lane) })
    return [...s].sort((a, b) => a.localeCompare(b))
  }, [p.departments, p.tasks])

  const others = p.tasks
    .filter((t) => t.id !== task.id)
    .sort((a, b) => (p.rowNo.get(a.id) ?? 0) - (p.rowNo.get(b.id) ?? 0))

  const patch = (): TaskPatch => {
    const out: TaskPatch = {}
    if (p.canEdit) {
      if (f.name.trim() !== task.name) out.name = f.name.trim()
      if (f.kind !== task.kind) out.kind = f.kind
      if ((f.lane.trim() || null) !== (task.lane ?? null)) out.lane = f.lane.trim() || null
      const dep = f.department_id ? Number(f.department_id) : null
      if (dep !== task.department_id) out.department_id = dep
      const preds = [...f.predecessors].sort((a, b) => a - b)
      if (preds.join(',') !== [...task.predecessors].sort((a, b) => a - b).join(',')) out.predecessors = preds
      if (f.is_idea !== task.is_idea) out.is_idea = f.is_idea
      if ((f.notes.trim() || null) !== (task.notes ?? null)) out.notes = f.notes.trim() || null
    }
    if (p.canDates && startOk) {
      if (f.start_date !== task.start_date) out.start_date = f.start_date
      if (dur !== task.duration_days) out.duration_days = dur
    }
    if (p.canProgress) {
      if (f.progress_pct !== task.progress_pct) out.progress_pct = f.progress_pct
      if ((f.actual_start || null) !== (task.actual_start ?? null)) out.actual_start = f.actual_start || null
      if ((f.actual_finish || null) !== (task.actual_finish ?? null)) out.actual_finish = f.actual_finish || null
    }
    return out
  }
  const changes = patch()
  const dirty = Object.keys(changes).length > 0
  const nameMissing = p.canEdit && !f.name.trim()

  const geo = taskGeo(task)
  const col = KIND_COLOR[task.kind] ?? KIND_COLOR.work

  return (
    <aside role="dialog" aria-label={`Task ${task.name}`} data-testid="task-editor"
      onKeyDown={(e) => { if (e.key === 'Escape') p.onClose() }}
      className="fixed inset-y-0 right-0 z-40 flex w-full max-w-[380px] flex-col border-l border-slate-700 bg-slate-900 shadow-2xl">
      <header className="flex items-start gap-2 border-b border-slate-700 px-4 py-3">
        <span className="mt-1 h-3 w-3 shrink-0 rounded-sm" style={{ background: col.fill }} />
        <div className="min-w-0 flex-1">
          <p className="text-[10px] uppercase tracking-wide text-slate-500">
            #{p.rowNo.get(task.id)} {KIND_LABEL[task.kind]} {task.is_idea ? '(idea)' : ''}
          </p>
          <h3 className="truncate text-sm font-semibold text-slate-100">{task.name}</h3>
          <p className="text-xs text-slate-400">
            {fmtIso(task.start_date)}{geo.dur > 0 ? ` to ${fmtIso(toIso(inclusiveEnd(geo)))}` : ''}, {laneOf(task)}
          </p>
        </div>
        <button type="button" onClick={p.onClose} aria-label="Close task editor"
          className="rounded p-1 text-slate-400 hover:bg-slate-800 hover:text-slate-200">&#10005;</button>
      </header>

      <div className="flex-1 space-y-4 overflow-y-auto px-4 py-4">
        {readOnly && (
          <p className="rounded-md border border-slate-700 bg-slate-800/60 px-3 py-2 text-xs text-slate-400">
            Read only. Plan editors (PM, Sales, Scheduling, change lead) change the plan.
          </p>
        )}
        <div>
          <label className={label} htmlFor="te-name">Name</label>
          <input id="te-name" className={field} value={f.name} disabled={!p.canEdit}
            onChange={(e) => set('name', e.target.value)} />
          {nameMissing && <p className="mt-1 text-xs text-red-300">A task needs a name.</p>}
        </div>
        <div className="grid grid-cols-2 gap-2">
          <div>
            <label className={label} htmlFor="te-kind">Kind</label>
            <select id="te-kind" className={field} value={f.kind} disabled={!p.canEdit}
              onChange={(e) => {
                const k = e.target.value as TaskKind
                setF((prev) => ({ ...prev, kind: k, duration: k === 'milestone' ? '0' : (prev.duration === '0' ? '1' : prev.duration) }))
              }}>
              {TASK_KINDS.map((k) => <option key={k} value={k}>{KIND_LABEL[k]}</option>)}
            </select>
          </div>
          <div>
            <label className={label} htmlFor="te-lane">Lane</label>
            <input id="te-lane" className={field} value={f.lane} list="te-lanes" disabled={!p.canEdit}
              placeholder="Department, Customer, Supplier" onChange={(e) => set('lane', e.target.value)} />
            <datalist id="te-lanes">{laneOptions.map((l) => <option key={l} value={l} />)}</datalist>
          </div>
        </div>
        <div>
          <label className={label} htmlFor="te-dept">Owner department</label>
          <select id="te-dept" className={field} value={f.department_id} disabled={!p.canEdit}
            onChange={(e) => set('department_id', e.target.value)}>
            <option value="">None</option>
            {p.departments.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
          </select>
          <p className="mt-1 text-[11px] text-slate-500">Members of this department report progress on the task.</p>
        </div>

        <div className="grid grid-cols-[minmax(0,1fr)_60px_minmax(0,1fr)] gap-2">
          <div>
            <label className={label} htmlFor="te-start">Start</label>
            <input id="te-start" type="date" className={`${field} px-1.5`} value={f.start_date} disabled={!p.canDates}
              onChange={(e) => set('start_date', e.target.value)} />
          </div>
          <div>
            <label className={label} htmlFor="te-dur">Days</label>
            <input id="te-dur" type="number" min={milestone ? 0 : 1} className={field} value={milestone ? '0' : f.duration}
              disabled={!p.canDates || milestone} onChange={(e) => set('duration', e.target.value)} />
          </div>
          <div>
            <label className={label} htmlFor="te-end">{milestone ? 'On' : 'Last day'}</label>
            <input id="te-end" type="date" className={`${field} px-1.5`} value={endIncl} disabled={!p.canDates || milestone || !startOk}
              onChange={(e) => {
                if (!e.target.value) return
                set('duration', String(durationFromInclusiveEnd(toDay(f.start_date), toDay(e.target.value))))
              }} />
          </div>
        </div>
        {p.baselineSet && p.canDates && (
          <p className="text-[11px] text-amber-300/90">Timing is validated. Moving dates asks for a reason and records a deviation.</p>
        )}
        {startOk && !milestone && dur > 0 && (
          <p className="-mt-2 text-[11px] text-slate-500">Next task can start {fmtIso(addDaysIso(f.start_date, dur))}.</p>
        )}

        <div>
          <span className={label}>Starts after</span>
          {others.length === 0 ? (
            <p className="text-xs text-slate-500">No other tasks yet.</p>
          ) : (
            <div className="max-h-40 space-y-0.5 overflow-y-auto rounded-md border border-slate-700 p-1.5" role="group"
              aria-label="Predecessors">
              {others.map((o) => (
                <label key={o.id} className="flex cursor-pointer items-center gap-2 rounded px-1 py-0.5 text-xs text-slate-300 hover:bg-slate-800">
                  <input type="checkbox" className="accent-sky-500" disabled={!p.canEdit}
                    checked={f.predecessors.includes(o.id)}
                    aria-label={`Starts after #${p.rowNo.get(o.id)} ${o.name}`}
                    onChange={(e) => set('predecessors', e.target.checked
                      ? [...f.predecessors, o.id] : f.predecessors.filter((x) => x !== o.id))} />
                  <span className="w-6 text-right tabular-nums text-slate-500">{p.rowNo.get(o.id)}</span>
                  <span className="truncate">{o.name}</span>
                </label>
              ))}
            </div>
          )}
        </div>

        <label className="flex cursor-pointer items-start gap-2 text-sm text-slate-300">
          <input type="checkbox" className="mt-0.5 accent-amber-500" checked={f.is_idea} disabled={!p.canEdit}
            onChange={(e) => set('is_idea', e.target.checked)} />
          <span>
            Idea block
            <span className="block text-[11px] text-slate-500">A proposal (for example a parallel bank build). Not on the critical path; must be resolved before timing is validated.</span>
          </span>
        </label>

        <div>
          <label className={label} htmlFor="te-notes">Notes</label>
          <textarea id="te-notes" rows={3} className={field} value={f.notes} disabled={!p.canEdit}
            onChange={(e) => set('notes', e.target.value)} />
        </div>

        {p.track && (
          <div className="space-y-3 rounded-md border border-slate-700 p-3">
            <p className={label}>Tracking</p>
            <div>
              <div className="flex items-center justify-between text-xs text-slate-300">
                <label htmlFor="te-progress">Progress</label>
                <span className="tabular-nums">{f.progress_pct}%</span>
              </div>
              <input id="te-progress" type="range" min={0} max={100} step={5} className="w-full accent-emerald-500"
                value={f.progress_pct} disabled={!p.canProgress}
                onChange={(e) => set('progress_pct', Number(e.target.value))} />
            </div>
            <div className="grid grid-cols-2 gap-2">
              <div>
                <label className={label} htmlFor="te-as">Actual start</label>
                <input id="te-as" type="date" className={field} value={f.actual_start} disabled={!p.canProgress}
                  onChange={(e) => set('actual_start', e.target.value)} />
              </div>
              <div>
                <label className={label} htmlFor="te-af">Actual finish</label>
                <input id="te-af" type="date" className={field} value={f.actual_finish} disabled={!p.canProgress}
                  onChange={(e) => set('actual_finish', e.target.value)} />
              </div>
            </div>
            {task.baseline_start && (
              <p className="text-[11px] text-slate-500">
                Baseline {fmtIso(task.baseline_start)}
                {task.baseline_finish ? ` to ${fmtIso(addDaysIso(task.baseline_finish, geo.dur > 0 ? -1 : 0))}` : ''}
              </p>
            )}
          </div>
        )}
      </div>

      {!readOnly && (
        <footer className="flex items-center gap-2 border-t border-slate-700 px-4 py-3">
          {p.onDelete && (
            <button type="button" className={`${btn} text-red-300`} onClick={p.onDelete}>Delete task</button>
          )}
          <div className="ml-auto flex gap-2">
            <button type="button" className={btn} onClick={() => setF(formOf(task))} disabled={!dirty}>Reset</button>
            <button type="button" className={btnPrimary} data-testid="task-editor-save"
              disabled={!dirty || nameMissing || !startOk || p.saving}
              onClick={() => p.onSave(changes)}>Save</button>
          </div>
        </footer>
      )}
    </aside>
  )
}
