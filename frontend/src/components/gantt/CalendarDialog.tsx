/**
 * Plan calendar editor: calendar days or working days, the working weekdays,
 * holidays (add / remove), and automatic scheduling. Switching the mode asks
 * whether durations stay as numbers or are converted (calendar d x 5/7 ->
 * working d, and back).
 */
import { useState } from 'react'
import { isIsoDay } from './engine/calendar'
import type { GanttCalendar } from './engine/types'
import DateInput from './DateInput'
import { formatDateInput } from './dateText'

export interface CalendarSave {
  calendar: GanttCalendar
  /** Convert durations and lags on a mode switch. */
  convert: boolean
  auto?: boolean
}

interface Props {
  calendar: GanttCalendar
  /** Show the automatic scheduling switch with this value. */
  auto?: boolean
  canEdit: boolean
  saving?: boolean
  onSave: (s: CalendarSave) => void
  onClose: () => void
}

const DAYS: [number, string][] = [[1, 'Mon'], [2, 'Tue'], [3, 'Wed'], [4, 'Thu'], [5, 'Fri'], [6, 'Sat'], [7, 'Sun']]
const MAX_HOLIDAYS = 5000

export default function CalendarDialog(p: Props) {
  const [mode, setMode] = useState(p.calendar.mode)
  const [workdays, setWorkdays] = useState<number[]>([...p.calendar.workdays])
  const [holidays, setHolidays] = useState<string[]>([...p.calendar.holidays].sort())
  const [convert, setConvert] = useState<boolean | null>(null)
  const [auto, setAuto] = useState(p.auto)
  const [newDay, setNewDay] = useState('')
  const switched = mode !== p.calendar.mode
  const ok = workdays.length > 0 && (!switched || convert !== null) && holidays.length <= MAX_HOLIDAYS
  const addHoliday = () => {
    if (!isIsoDay(newDay) || holidays.includes(newDay)) return
    setHolidays([...holidays, newDay].sort())
    setNewDay('')
  }
  const dirty = switched || workdays.join() !== [...p.calendar.workdays].sort().join()
    || holidays.join() !== [...p.calendar.holidays].sort().join() || auto !== p.auto
  const box = 'rounded border border-slate-600 bg-slate-900 px-2 py-1 text-sm text-slate-100 [color-scheme:dark] disabled:opacity-60'
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50" role="dialog" aria-modal="true" aria-label="Plan calendar"
      data-testid="calendar-dialog" onKeyDown={(e) => { if (e.key === 'Escape') { e.stopPropagation(); p.onClose() } }}>
      <div className="w-full max-w-md space-y-4 rounded-xl border border-slate-700 bg-slate-800 p-5 text-sm text-slate-200 shadow-xl">
        <h3 className="text-base font-semibold text-slate-100">Plan calendar</h3>
        <fieldset className="space-y-1" disabled={!p.canEdit}>
          <legend className="mb-1 text-[10px] uppercase tracking-wide text-slate-500">Durations count</legend>
          <label className="flex items-center gap-2"><input type="radio" name="cal-mode" checked={mode === 'calendar'}
            onChange={() => { setMode('calendar'); setConvert(null) }} /> Calendar days (every day counts)</label>
          <label className="flex items-center gap-2"><input type="radio" name="cal-mode" checked={mode === 'working'}
            onChange={() => { setMode('working'); setConvert(null) }} /> Working days (weekends and holidays skipped)</label>
        </fieldset>
        {switched && (
          <fieldset className="space-y-1 rounded-md border border-amber-700/60 bg-amber-950/30 p-2" data-testid="calendar-convert">
            <legend className="px-1 text-xs text-amber-200">Existing durations</legend>
            <label className="flex items-start gap-2"><input type="radio" name="cal-convert" checked={convert === false} onChange={() => setConvert(false)} />
              <span>Keep them as numbers <span className="block text-[11px] text-slate-400">
                {mode === 'working' ? 'Tasks get longer: 5 days now means 5 working days.' : 'Tasks get shorter: 5 working days become 5 calendar days.'}
              </span></span></label>
            <label className="flex items-start gap-2"><input type="radio" name="cal-convert" checked={convert === true} onChange={() => setConvert(true)} />
              <span>Convert them <span className="block text-[11px] text-slate-400">
                {mode === 'working' ? 'Calendar days x 5/7 become working days (and lags too).' : 'Working days x 7/5 become calendar days (and lags too).'}
              </span></span></label>
          </fieldset>
        )}
        <fieldset disabled={!p.canEdit}>
          <legend className="mb-1 text-[10px] uppercase tracking-wide text-slate-500">Working days</legend>
          <div className="flex flex-wrap gap-2">
            {DAYS.map(([d, name]) => (
              <label key={d} className="flex items-center gap-1">
                <input type="checkbox" aria-label={name} checked={workdays.includes(d)}
                  onChange={(e) => setWorkdays(e.target.checked ? [...workdays, d].sort((a, b) => a - b) : workdays.filter((x) => x !== d))} />
                {name}
              </label>
            ))}
          </div>
          {workdays.length === 0 && <p className="mt-1 text-xs text-red-300">At least one working day is needed.</p>}
        </fieldset>
        <div>
          <p className="mb-1 text-[10px] uppercase tracking-wide text-slate-500">
            Holidays {mode === 'calendar' ? '(shading only in calendar days)' : ''}
          </p>
          <ul className="max-h-36 space-y-0.5 overflow-y-auto" data-testid="calendar-holidays">
            {holidays.length === 0 && <li className="text-xs text-slate-500">None.</li>}
            {holidays.map((h) => (
              <li key={h} className="flex items-center gap-2 text-xs">
                <span className="tabular-nums">{formatDateInput(h)}</span>
                {p.canEdit && (
                  <button type="button" aria-label={`Remove holiday ${formatDateInput(h)}`} className="text-red-300 hover:text-red-200"
                    onClick={() => setHolidays(holidays.filter((x) => x !== h))}>&#10005;</button>
                )}
              </li>
            ))}
          </ul>
          {p.canEdit && (
            <div className="mt-1.5 flex items-center gap-2">
              <div className="w-36"><DateInput aria-label="New holiday" className={`${box} w-full`} value={newDay} onChange={setNewDay} /></div>
              <button type="button" className="rounded bg-slate-700 px-2 py-1 text-xs hover:bg-slate-600 disabled:opacity-40"
                disabled={!isIsoDay(newDay)} onClick={addHoliday}>Add holiday</button>
            </div>
          )}
        </div>
        {p.auto !== undefined && (
          <label className="flex items-start gap-2">
            <input type="checkbox" checked={!!auto} disabled={!p.canEdit} aria-label="Automatic scheduling" onChange={(e) => setAuto(e.target.checked)} />
            <span>Automatic scheduling <span className="block text-[11px] text-slate-400">
              Moving a task, a link or a lag pushes its successors along, as in MS Project. Off: tasks stay where they are drawn and Auto-schedule does it on demand.
            </span></span>
          </label>
        )}
        <div className="flex justify-end gap-2">
          <button type="button" className="rounded-lg border border-slate-600 px-3 py-1.5 text-slate-300 hover:bg-slate-700" onClick={p.onClose}>
            {p.canEdit ? 'Cancel' : 'Close'}</button>
          {p.canEdit && (
            <button type="button" className="rounded-lg bg-sky-600 px-3 py-1.5 text-white hover:bg-sky-500 disabled:opacity-40" data-testid="calendar-save"
              disabled={!ok || !dirty || p.saving}
              onClick={() => p.onSave({ calendar: { mode, workdays, holidays }, convert: switched && convert === true, ...(p.auto !== undefined ? { auto } : {}) })}>
              Save calendar</button>
          )}
        </div>
      </div>
    </div>
  )
}
