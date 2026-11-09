/**
 * Timing as a table you type into (Christoph 2026-11-09: "make it easy to
 * use, like typing timing"). One row per task: what it starts after, its
 * start, its duration in days or weeks, and the finish it gives. Every edit
 * is a ChangeSet through the Gantt (same undo, same planning-rule check, same
 * save), so the chart follows at once.
 */
import { useMemo, useState } from 'react'
import DateInput from '../../gantt/DateInput'
import { endOf, fmtShort, makeCal, normStart, toDay, toIso } from '../../gantt/engine/calendar'
import { key } from '../../gantt/engine/tree'
import type { ChangeSet, GanttCalendar, GanttLink, GanttTask } from '../../gantt/engine/types'
import { KIND_LABEL } from './ganttMath'
import type { TaskKind } from '../../../types/changePlan'

interface Props {
  tasks: GanttTask[]
  links: GanttLink[]
  calendar?: GanttCalendar | null
  rowNo: Map<number, number>
  /** Start and duration may be typed. */
  canDates: boolean
  /** "Starts after" may be changed (links). */
  canLinks: boolean
  onApply: (cs: ChangeSet) => void
}

type Unit = 'd' | 'wk'

const cell = 'px-2 py-1 align-middle'
const input = 'h-7 rounded border border-slate-600 bg-slate-900 px-1.5 text-xs text-slate-100 disabled:opacity-50'

export default function TimingTable({ tasks, links, calendar, rowNo, canDates, canLinks, onApply }: Props) {
  const cal = useMemo(() => makeCal(calendar), [calendar])
  const weekLen = cal.mode === 'working' ? Math.max(1, (calendar?.workdays ?? [1, 2, 3, 4, 5]).length) : 7
  const [units, setUnits] = useState<Record<string, Unit>>({})
  const [drafts, setDrafts] = useState<Record<string, string>>({})
  const parents = useMemo(() => new Set(tasks.map((t) => t.parentId).filter((p) => p != null).map((p) => key(p!))), [tasks])
  const byKey = useMemo(() => new Map(tasks.map((t) => [key(t.id), t])), [tasks])
  const endDay = (t: GanttTask) => endOf(cal, normStart(cal, toDay(t.start)), t.duration)

  const unitOf = (t: GanttTask): Unit => units[key(t.id)] ?? (t.duration > 0 && t.duration % weekLen === 0 ? 'wk' : 'd')
  const shown = (t: GanttTask) => {
    const u = unitOf(t)
    return u === 'wk' ? String(Math.round((t.duration / weekLen) * 10) / 10) : String(t.duration)
  }

  const setDuration = (t: GanttTask, raw: string) => {
    setDrafts((d) => { const n = { ...d }; delete n[key(t.id)]; return n })
    const v = Number(raw.replace(',', '.'))
    if (!Number.isFinite(v) || v < 0) return
    const days = unitOf(t) === 'wk' ? Math.round(v * weekLen) : Math.round(v)
    if (days === t.duration) return
    onApply({ label: 'Edit duration', updateTasks: [{ id: t.id, patch: { duration: days } }] })
  }
  const setStart = (t: GanttTask, iso: string) => {
    if (!iso || iso === t.start) return
    onApply({ label: 'Edit start', updateTasks: [{ id: t.id, patch: { start: iso } }] })
  }
  const setAfter = (t: GanttTask, predKey: string) => {
    const into = links.filter((l) => key(l.to) === key(t.id))
    const pred = predKey ? byKey.get(predKey) : undefined
    const cs: ChangeSet = {
      label: 'Starts after',
      removeLinks: into.map((l) => l.id),
      addLinks: pred ? [{ id: `tt-${key(t.id)}-${predKey}-${Date.now()}`, from: pred.id, to: t.id, type: 'FS', lagDays: 0 }] : [],
    }
    // starts when the predecessor ends: the chart follows at once
    if (pred) {
      const s = toIso(normStart(cal, endDay(pred)))
      if (s !== t.start) cs.updateTasks = [{ id: t.id, patch: { start: s } }]
    }
    onApply(cs)
  }

  return (
    <div className="overflow-x-auto rounded-lg border border-slate-700" data-testid="timing-table">
      <table className="w-full min-w-[640px] text-xs text-slate-200">
        <thead className="bg-slate-800/70 text-[11px] uppercase tracking-wide text-slate-400">
          <tr>
            <th className={`${cell} w-8 text-right`}>#</th>
            <th className={`${cell} text-left`}>Task</th>
            <th className={`${cell} text-left`}>Starts after</th>
            <th className={`${cell} text-left`}>Start</th>
            <th className={`${cell} text-left`}>Duration</th>
            <th className={`${cell} text-left`}>Finish</th>
          </tr>
        </thead>
        <tbody>
          {tasks.map((t) => {
            const k = key(t.id)
            const summary = parents.has(k)
            const into = links.filter((l) => key(l.to) === k)
            const single = into.length === 1 && into[0].type === 'FS' && !into[0].lagDays ? key(into[0].from) : ''
            const several = into.length > 1 || (into.length === 1 && !single)
            const last = t.duration > 0 ? endDay(t) - 1 : normStart(cal, toDay(t.start))
            const kind = (t.kind ?? 'work') as TaskKind
            return (
              <tr key={k} className="border-t border-slate-800" data-testid={`timing-row-${k}`}>
                <td className={`${cell} text-right tabular-nums text-slate-400`}>{typeof t.id === 'number' ? rowNo.get(t.id) : ''}</td>
                <td className={cell}>
                  <span className={summary ? 'font-semibold' : ''}>{t.name}</span>
                  {t.isIdea && <span className="ml-1.5 rounded bg-slate-700 px-1 text-[10px] font-semibold uppercase">Idea</span>}
                  {kind === 'bank_build' && (
                    <span className="ml-1.5 rounded border border-dashed border-amber-600 px-1 text-[10px] font-semibold uppercase text-amber-300"
                      title="Estimate - floats with the PO; PM discusses the bank build when the PO arrives">Estimate</span>
                  )}
                  {kind === 'buffer' && <span className="ml-1.5 text-[10px] uppercase text-slate-400">{KIND_LABEL.buffer}</span>}
                </td>
                <td className={cell}>
                  {several ? (
                    <span className="text-slate-400" title="Several links or a lag: edit them in the chart or the task panel">
                      {into.map((l) => (typeof l.from === 'number' ? `#${rowNo.get(l.from) ?? '?'}` : '')).join(', ')} (chart)</span>
                  ) : (
                    <select aria-label={`${t.name} starts after`} className={`${input} max-w-[220px]`} value={single}
                      disabled={!canLinks || summary} onChange={(e) => setAfter(t, e.target.value)}>
                      <option value="">- (own start)</option>
                      {tasks.filter((o) => key(o.id) !== k && !parents.has(key(o.id))).map((o) => (
                        <option key={key(o.id)} value={key(o.id)}>
                          {typeof o.id === 'number' ? `#${rowNo.get(o.id)} ` : ''}{o.name}</option>
                      ))}
                    </select>
                  )}
                </td>
                <td className={cell}>
                  <DateInput value={t.start} disabled={!canDates || summary} className={`${input} w-28`}
                    onChange={(iso) => setStart(t, iso)} />
                </td>
                <td className={cell}>
                  {kind === 'milestone' ? <span className="text-slate-400">Milestone</span> : (
                    <span className="inline-flex items-center gap-1">
                      <input aria-label={`${t.name} duration`} inputMode="decimal" className={`${input} w-14 text-right tabular-nums`}
                        disabled={!canDates || summary} value={drafts[k] ?? shown(t)}
                        onChange={(e) => setDrafts((d) => ({ ...d, [k]: e.target.value }))}
                        onBlur={(e) => setDuration(t, e.target.value)}
                        onKeyDown={(e) => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur() }} />
                      <select aria-label={`${t.name} duration unit`} className={input} value={unitOf(t)} disabled={summary}
                        onChange={(e) => { setUnits((u) => ({ ...u, [k]: e.target.value as Unit })); setDrafts((d) => { const n = { ...d }; delete n[k]; return n }) }}>
                        <option value="d">{cal.mode === 'working' ? 'wd' : 'days'}</option>
                        <option value="wk">weeks</option>
                      </select>
                    </span>
                  )}
                </td>
                <td className={`${cell} whitespace-nowrap tabular-nums text-slate-300`}>{fmtShort(last)}</td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
