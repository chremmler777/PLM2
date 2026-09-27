/**
 * Task panel docked under the chart (it never covers the timeline). Editors
 * change everything before the baseline; after it only dates (as a
 * deviation) and notes. A member of the task's department (track mode)
 * changes progress and actual dates only; everyone else reads.
 *
 * A server update (drag, auto-schedule, another user) refreshes only the
 * fields the user has not touched, so typing is never wiped.
 */
import { useEffect, useMemo, useRef, useState } from 'react'
import type { TaskKind, TaskOut, TaskPatch } from '../../../types/changePlan'
import { TASK_KINDS } from '../../../types/changePlan'
import { KIND_COLOR, KIND_LABEL, laneOf } from './ganttMath'
import { btn, btnPrimary } from './GanttToolbar'
import { X } from 'lucide-react'
import { btnIcon } from '../../common/buttonStyles'
import {
  durationFromLastDay, endOf, lastDay, makeCal, normStart, toDay, toIso, todayDay,
} from '../../gantt/engine/calendar'
import {
  LIMITS, inYearRange, type ChangeSet, type ConstraintType, type GanttCalendar, type GanttLink, type LinkType,
} from '../../gantt/engine/types'
import DateInput from '../../gantt/DateInput'
import { formatDateInput } from '../../gantt/dateText'
import TaskLinks from './TaskLinks'
import { departmentLabel, pickableDepartments } from '../../../lib/departments'

interface Props {
  task: TaskOut
  tasks: TaskOut[]
  rowNo: Map<number, number>
  /** Every department, retired ones included (is_active false). */
  departments: { id: number; name: string; is_active?: boolean }[]
  /** Name, kind, lane, links, idea (structure; false after the baseline). */
  canEdit: boolean
  /** Start and duration. */
  canDates: boolean
  /** Progress and actuals (track mode). */
  canProgress: boolean
  track: boolean
  baselineSet: boolean
  saving: boolean
  /** Plan calendar (durations in working days in working mode). */
  calendar?: GanttCalendar
  /** Typed links (servers with the links table): shown as editable lists instead of "Starts after". */
  links?: GanttLink[]
  linkTypes?: LinkType[]
  allowLag?: boolean
  /** Constraints are available (servers with the links table). */
  constraints?: boolean
  /** The task is a summary (no must-start/finish-on, no FF/SF into it, dates rolled up). */
  isSummary?: boolean
  summaryIds?: Set<number>
  onLinks?: (cs: ChangeSet) => void
  onSave: (patch: TaskPatch) => void
  onDelete?: () => void
  onClose: () => void
}

const field = 'w-full rounded-md border border-slate-600 bg-slate-900 px-2 py-1 text-sm text-slate-100 [color-scheme:dark] disabled:opacity-60'
const label = 'block text-[11px] font-medium uppercase tracking-wide text-slate-400 mb-1'

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
  constraint_type: string
  /** As shown: the start day for snet / mso, the last day for fnlt / mfo. */
  constraint_date: string
}

const FINISH = new Set(['fnlt', 'mfo'])
/** Stored finish constraint dates are exclusive ends; the panel shows the last day. */
const shownConstraintDate = (t: TaskOut) => (t.constraint_date && FINISH.has(t.constraint_type ?? '')
  ? toIso(toDay(t.constraint_date) - 1) : t.constraint_date ?? '')

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
  constraint_type: t.constraint_type ?? 'asap',
  constraint_date: shownConstraintDate(t),
})

const CONSTRAINT_LABEL: Record<ConstraintType, string> = {
  asap: 'As soon as possible', snet: 'Start no earlier than', fnlt: 'Finish no later than',
  mso: 'Must start on', mfo: 'Must finish on',
}

const same = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b)

export default function TaskEditor(p: Props) {
  const { task } = p
  const [f, setF] = useState<Form>(() => formOf(task))
  const touched = useRef(new Set<keyof Form>())
  const lastId = useRef(task.id)
  useEffect(() => {
    const fresh = formOf(task)
    if (lastId.current !== task.id) {
      // Another task: start over.
      lastId.current = task.id
      touched.current.clear()
      setF(fresh)
      return
    }
    setF((prev) => {
      const next = { ...prev }
      for (const k of Object.keys(fresh) as (keyof Form)[]) {
        // A touched field that now matches the server was saved: untouch it.
        if (touched.current.has(k) && same(prev[k], fresh[k])) touched.current.delete(k)
        if (!touched.current.has(k)) (next as Record<string, unknown>)[k] = fresh[k]
      }
      return next
    })
  }, [task])
  const set = <K extends keyof Form>(k: K, v: Form[K]) => {
    touched.current.add(k)
    setF((prev) => ({ ...prev, [k]: v }))
  }
  const canNotes = p.canEdit || p.canDates
  // Actual dates lie in the past or today, in the viewer's own calendar. (The
  // server allows one more day, for viewers in another time zone.)
  const maxActual = toIso(todayDay())

  const cal = useMemo(() => makeCal(p.calendar), [p.calendar])
  const working = cal.mode === 'working'
  const milestone = f.kind === 'milestone'
  const dur = milestone ? 0 : Math.max(0, Math.floor(Number(f.duration) || 0))
  const startOk = /^\d{4}-\d{2}-\d{2}$/.test(f.start_date) && inYearRange(f.start_date)
  // Only the actuals changed in this edit are checked: stored ones (maybe
  // "tomorrow" here, or out of order from before) never block other edits.
  const startEdited = (f.actual_start || null) !== (task.actual_start ?? null)
  const finishEdited = (f.actual_finish || null) !== (task.actual_finish ?? null)
  const actualFuture = (startEdited && !!f.actual_start && f.actual_start > maxActual)
    || (finishEdited && !!f.actual_finish && f.actual_finish > maxActual)
  const actualOrder = (startEdited || finishEdited)
    && !!f.actual_start && !!f.actual_finish && f.actual_finish < f.actual_start
  const actualsOk = !actualFuture && !actualOrder
  const endIncl = startOk ? toIso(lastDay(cal, toDay(f.start_date), dur)) : ''
  const constraintOk = f.constraint_type === 'asap' || (/^\d{4}-\d{2}-\d{2}$/.test(f.constraint_date) && inYearRange(f.constraint_date))
  const readOnly = !p.canEdit && !p.canDates && !p.canProgress

  const laneOptions = useMemo(() => {
    const s = new Set<string>(['Customer', 'Supplier',
      ...p.departments.filter((d) => d.is_active !== false).map((d) => d.name)])
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
      if (!p.links) {
        const preds = [...f.predecessors].sort((a, b) => a - b)
        if (preds.join(',') !== [...task.predecessors].sort((a, b) => a - b).join(',')) out.predecessors = preds
      }
      if (f.is_idea !== task.is_idea) out.is_idea = f.is_idea
      if (p.constraints && constraintOk) {
        const type = f.constraint_type === 'asap' ? null : f.constraint_type as ConstraintType
        const date = type ? (FINISH.has(type) ? toIso(toDay(f.constraint_date) + 1) : f.constraint_date) : null
        if ((type ?? null) !== (task.constraint_type && task.constraint_type !== 'asap' ? task.constraint_type : null)
          || (type && date !== task.constraint_date)) {
          out.constraint_type = type
          out.constraint_date = date
        }
      }
    }
    if (canNotes && (f.notes.trim() || null) !== (task.notes ?? null)) out.notes = f.notes.trim() || null
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
  // Reset stays available while the form differs from the task, even when an
  // unusable entry (a cleared field) produces no patch.
  const edited = dirty || JSON.stringify(f) !== JSON.stringify(formOf(task))
  const nameMissing = p.canEdit && !f.name.trim()

  const col = KIND_COLOR[task.kind] ?? KIND_COLOR.work
  const s0 = normStart(cal, toDay(task.start_date))
  const headerLast = lastDay(cal, s0, task.duration_days)

  return (
    <aside role="region" aria-label={`Task ${task.name}`} data-testid="task-editor"
      onKeyDown={(e) => { if (e.key === 'Escape') { e.preventDefault(); p.onClose() } }}
      className="flex flex-col rounded-lg border border-slate-700 bg-slate-900">
      <header className="flex items-start gap-2 border-b border-slate-700 px-4 py-3">
        <span className="mt-1 h-3 w-3 shrink-0 rounded-sm" style={{ background: col.fill }} />
        <div className="min-w-0 flex-1">
          <p className="text-[11px] uppercase tracking-wide text-slate-400">
            #{p.rowNo.get(task.id)} {KIND_LABEL[task.kind]} {task.is_idea ? '(idea)' : ''}
          </p>
          <h3 className="truncate text-sm font-semibold text-slate-100">{task.name}</h3>
          <p className="text-xs text-slate-400">
            {formatDateInput(toIso(s0))}{task.duration_days > 0 ? ` to ${formatDateInput(toIso(headerLast))}` : ''}, {laneOf(task)}
          </p>
        </div>
        <button type="button" onClick={p.onClose} aria-label="Close task editor"
          className={btnIcon}><X aria-hidden="true" size={16} /></button>
      </header>

      <div className="grid gap-4 px-4 py-4 md:grid-cols-2 xl:grid-cols-3">
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
                touched.current.add('kind'); touched.current.add('duration')
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
            {pickableDepartments(p.departments, [task.department_id]).map((d) =>
              <option key={d.id} value={d.id}>{departmentLabel(d)}</option>)}
          </select>
          <p className="mt-1 text-[11px] text-slate-400">Members of this department report progress on the task.</p>
        </div>

        <div className="grid grid-cols-[minmax(0,1fr)_60px_minmax(0,1fr)] gap-2">
          <div>
            <label className={label} htmlFor="te-start">Start</label>
            <DateInput id="te-start" aria-label="Start" required className={`${field} px-1.5`} value={f.start_date} disabled={!p.canDates}
              onChange={(iso) => set('start_date', iso)} />
          </div>
          <div>
            <label className={label} htmlFor="te-dur">{working ? 'Work days' : 'Days'}</label>
            <input id="te-dur" type="number" min={milestone ? 0 : 1} max={LIMITS.maxDuration} className={field} value={milestone ? '0' : f.duration}
              disabled={!p.canDates || milestone || p.isSummary} onChange={(e) => set('duration', e.target.value)} />
          </div>
          <div>
            <label className={label} htmlFor="te-end">{milestone ? 'On' : 'Last day'}</label>
            <DateInput id="te-end" aria-label={milestone ? 'On' : 'Last day'} className={`${field} px-1.5`} value={endIncl}
              disabled={!p.canDates || milestone || !startOk}
              onChange={(iso) => {
                if (!iso) return
                set('duration', String(durationFromLastDay(cal, toDay(f.start_date), toDay(iso))))
              }} />
          </div>
        </div>
        {p.baselineSet && p.canDates && (
          <p className="text-[11px] text-amber-300/90">Timing is validated. A date change asks for a reason, moves the successors along and records deviations.</p>
        )}
        {startOk && !milestone && dur > 0 && (
          <p className="-mt-2 text-[11px] text-slate-400">
            Next task can start {formatDateInput(toIso(normStart(cal, endOf(cal, toDay(f.start_date), dur))))}.
          </p>
        )}

        {p.constraints && (
          <div className="grid grid-cols-[minmax(0,1fr)_minmax(0,1fr)] gap-2">
            <div>
              <label className={label} htmlFor="te-ctype">Constraint</label>
              <select id="te-ctype" className={field} value={f.constraint_type} disabled={!p.canEdit}
                onChange={(e) => set('constraint_type', e.target.value)}>
                {(['asap', 'snet', 'fnlt', 'mso', 'mfo'] as ConstraintType[])
                  .filter((c) => !p.isSummary || (c !== 'mso' && c !== 'mfo') || c === f.constraint_type)
                  .map((c) => <option key={c} value={c}>{CONSTRAINT_LABEL[c]}</option>)}
              </select>
            </div>
            <div>
              <label className={label} htmlFor="te-cdate">{FINISH.has(f.constraint_type) ? 'Last day' : 'Date'}</label>
              <DateInput id="te-cdate" aria-label="Constraint date" className={field} value={f.constraint_date}
                disabled={!p.canEdit || f.constraint_type === 'asap'} onChange={(iso) => set('constraint_date', iso)} />
            </div>
          </div>
        )}

        {p.links && p.onLinks ? (
          <TaskLinks taskId={task.id} links={p.links} canEdit={p.canEdit} types={p.linkTypes ?? ['FS']}
            allowLag={p.allowLag ?? false} summary={!!p.isSummary} unit={working ? 'working days' : 'days'}
            tasks={others.map((o) => ({ id: o.id, name: o.name, row: p.rowNo.get(o.id), summary: p.summaryIds?.has(o.id) }))}
            onChange={p.onLinks} />
        ) : (
        <div>
          <span className={label}>Starts after</span>
          {others.length === 0 ? (
            <p className="text-xs text-slate-400">No other tasks yet.</p>
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
                  <span className="w-6 text-right tabular-nums text-slate-400">{p.rowNo.get(o.id)}</span>
                  <span className="truncate">{o.name}</span>
                </label>
              ))}
            </div>
          )}
        </div>
        )}

        {/* A summary is an idea exactly when only ideas lie below it: no flag of its own (spec §11). */}
        {(!p.isSummary || f.is_idea) && (
        <label className="flex cursor-pointer items-start gap-2 text-sm text-slate-300">
          <input type="checkbox" className="mt-0.5 accent-amber-500" checked={f.is_idea} disabled={!p.canEdit || (!!p.isSummary && !f.is_idea)}
            onChange={(e) => set('is_idea', e.target.checked)} />
          <span>
            Idea block
            <span className="block text-[11px] text-slate-400">A proposal (for example a parallel bank build). Not on the critical path, never pushes committed work, holds no tasks; must be resolved before timing is validated.</span>
          </span>
        </label>
        )}

        <div>
          <label className={label} htmlFor="te-notes">Notes</label>
          <textarea id="te-notes" rows={3} className={field} value={f.notes} disabled={!canNotes}
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
                <DateInput id="te-as" aria-label="Actual start" max={maxActual} className={field} value={f.actual_start} disabled={!p.canProgress}
                  onChange={(iso) => set('actual_start', iso)} />
              </div>
              <div>
                <label className={label} htmlFor="te-af">Actual finish</label>
                <DateInput id="te-af" aria-label="Actual finish" max={maxActual} className={field} value={f.actual_finish} disabled={!p.canProgress}
                  onChange={(iso) => set('actual_finish', iso)} />
              </div>
            </div>
            {(actualFuture || actualOrder) && (
              <p role="alert" data-testid="te-actual-error" className="text-[11px] text-red-300">
                {actualFuture ? 'Actual dates cannot lie in the future.' : 'The actual finish cannot be before the actual start.'}
              </p>
            )}
            {task.baseline_start && (
              <p className="text-[11px] text-slate-400">
                Baseline {formatDateInput(task.baseline_start)}
                {task.baseline_finish ? ` to ${formatDateInput(toIso(toDay(task.baseline_finish) - (task.duration_days > 0 ? 1 : 0)))}` : ''}
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
            <button type="button" className={btn} onClick={() => setF(formOf(task))} disabled={!edited}>Reset</button>
            <button type="button" className={btnPrimary} data-testid="task-editor-save"
              disabled={!dirty || nameMissing || !startOk || !actualsOk || !constraintOk || dur > LIMITS.maxDuration || p.saving}
              onClick={() => p.onSave(changes)}>Save</button>
          </div>
        </footer>
      )}
    </aside>
  )
}
