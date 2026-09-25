/**
 * Floating parts of the Gantt: context menu, link editor popover and the
 * built-in task information dialog (used when the host gives no editor).
 */
import { useEffect, useRef, useState } from 'react'
import { isIsoDay } from './engine/calendar'
import { CONSTRAINT_TYPES, LIMITS, LINK_TYPES, inYearRange, type ConstraintType, type GanttLink, type GanttTask, type LinkType } from './engine/types'
import { v } from './theme'

export interface MenuItem {
  label: string
  onSelect: () => void
  disabled?: boolean
  danger?: boolean
  shortcut?: string
  testId?: string
}
export type MenuEntry = MenuItem | 'separator'

/** Close on outside pointer, Escape, scroll. */
function useDismiss(open: boolean, onClose: () => void, ref: React.RefObject<HTMLElement>) {
  useEffect(() => {
    if (!open) return
    const down = (e: Event) => { if (ref.current && !ref.current.contains(e.target as Node)) onClose() }
    const key = (e: KeyboardEvent) => { if (e.key === 'Escape') { e.stopPropagation(); onClose() } }
    document.addEventListener('pointerdown', down, true)
    document.addEventListener('keydown', key, true)
    return () => {
      document.removeEventListener('pointerdown', down, true)
      document.removeEventListener('keydown', key, true)
    }
  }, [open, onClose, ref])
}

const clampPos = (x: number, y: number, w: number, h: number) => {
  const vw = typeof window !== 'undefined' ? window.innerWidth || 1024 : 1024
  const vh = typeof window !== 'undefined' ? window.innerHeight || 768 : 768
  return { left: Math.max(4, Math.min(x, vw - w - 4)), top: Math.max(4, Math.min(y, vh - h - 4)) }
}

export function ContextMenu({ x, y, items, onClose }: { x: number; y: number; items: MenuEntry[]; onClose: () => void }) {
  const ref = useRef<HTMLDivElement>(null)
  useDismiss(true, onClose, ref)
  useEffect(() => { ref.current?.querySelector<HTMLButtonElement>('button:not([disabled])')?.focus() }, [])
  const pos = clampPos(x, y, 220, items.length * 28)
  return (
    <div ref={ref} role="menu" data-testid="gantt-context-menu"
      className="fixed z-50 min-w-[210px] rounded-md border py-1 text-xs shadow-2xl"
      style={{ ...pos, background: v('panel'), borderColor: v('gridLine'), color: v('text') }}
      onKeyDown={(e) => {
        if (e.key !== 'ArrowDown' && e.key !== 'ArrowUp') return
        e.preventDefault()
        const btns = [...(ref.current?.querySelectorAll<HTMLButtonElement>('button:not([disabled])') ?? [])]
        const i = btns.indexOf(document.activeElement as HTMLButtonElement)
        btns[(i + (e.key === 'ArrowDown' ? 1 : -1) + btns.length) % btns.length]?.focus()
      }}>
      {items.map((it, i) => (it === 'separator'
        ? <div key={`s${i}`} className="my-1 h-px" style={{ background: v('gridLine') }} />
        : (
          <button key={it.label} type="button" role="menuitem" disabled={it.disabled} data-testid={it.testId}
            className="flex w-full items-center gap-3 px-3 py-1.5 text-left hover:bg-[var(--g-hover-bg)] focus:bg-[var(--g-hover-bg)] focus:outline-none disabled:opacity-40"
            style={{ color: it.danger ? v('linkBad') : undefined }}
            onClick={() => { onClose(); it.onSelect() }}>
            <span className="flex-1">{it.label}</span>
            {it.shortcut && <span style={{ color: v('textFaint') }}>{it.shortcut}</span>}
          </button>
        )))}
    </div>
  )
}

const TYPE_LABEL: Record<LinkType, string> = {
  FS: 'Finish to start (FS)', SS: 'Start to start (SS)', FF: 'Finish to finish (FF)', SF: 'Start to finish (SF)',
}

export function LinkPopover(p: {
  x: number; y: number; link: GanttLink; title: string; types: LinkType[]; allowLag: boolean; canEdit: boolean
  unit: string
  onSave: (patch: { type: LinkType; lagDays: number }) => void; onDelete: () => void; onClose: () => void
}) {
  const ref = useRef<HTMLDivElement>(null)
  useDismiss(true, p.onClose, ref)
  const [type, setType] = useState<LinkType>(p.link.type)
  const [lag, setLag] = useState(String(p.link.lagDays))
  const lagNum = Math.round(Number(lag))
  const valid = Number.isFinite(lagNum) && lag.trim() !== '' && Math.abs(lagNum) <= LIMITS.maxLag
  const dirty = type !== p.link.type || (valid && lagNum !== p.link.lagDays)
  const pos = clampPos(p.x, p.y, 260, 190)
  const types = LINK_TYPES.filter((t) => p.types.includes(t) || t === p.link.type)
  return (
    <div ref={ref} role="dialog" aria-label="Edit link" data-testid="gantt-link-popover"
      className="fixed z-50 w-[260px] space-y-2 rounded-md border p-3 text-xs shadow-2xl"
      style={{ ...pos, background: v('panel'), borderColor: v('gridLine'), color: v('text') }}>
      <p className="font-semibold">{p.title}</p>
      <label className="block">
        <span className="mb-0.5 block text-[10px] uppercase tracking-wide" style={{ color: v('textFaint') }}>Type</span>
        <select aria-label="Link type" value={type} disabled={!p.canEdit} onChange={(e) => setType(e.target.value as LinkType)}
          className="w-full rounded border px-1.5 py-1 [color-scheme:dark]" style={{ background: v('bg'), borderColor: v('gridLine'), color: v('text') }}>
          {types.map((t) => <option key={t} value={t}>{TYPE_LABEL[t]}</option>)}
        </select>
      </label>
      {p.allowLag && (
        <label className="block">
          <span className="mb-0.5 block text-[10px] uppercase tracking-wide" style={{ color: v('textFaint') }}>
            Lag in {p.unit} (negative = lead)
          </span>
          <input aria-label="Lag" type="number" min={-LIMITS.maxLag} max={LIMITS.maxLag} value={lag} disabled={!p.canEdit} onChange={(e) => setLag(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter' && dirty && valid) p.onSave({ type, lagDays: lagNum }) }}
            className="w-full rounded border px-1.5 py-1" style={{ background: v('bg'), borderColor: v('gridLine'), color: v('text') }} />
        </label>
      )}
      {p.canEdit && (
        <div className="flex items-center gap-2 pt-1">
          <button type="button" className="rounded border px-2 py-1" data-testid="gantt-link-delete"
            style={{ borderColor: v('linkBad'), color: v('linkBad') }} onClick={p.onDelete}>Remove link</button>
          <button type="button" className="ml-auto rounded px-2 py-1 text-white disabled:opacity-40" data-testid="gantt-link-save"
            style={{ background: v('accent') }} disabled={!dirty || !valid}
            onClick={() => p.onSave({ type, lagDays: lagNum })}>Save</button>
        </div>
      )}
    </div>
  )
}

const CONSTRAINT_LABEL: Record<ConstraintType, string> = {
  asap: 'As soon as possible', snet: 'Start no earlier than', fnlt: 'Finish no later than',
  mso: 'Must start on', mfo: 'Must finish on',
}

/** Built-in "task information" dialog: name, dates, constraint, progress, notes. */
export function TaskDialog(p: {
  task: GanttTask
  canField: (field: string) => boolean
  allowConstraints: boolean
  working: boolean
  /** A summary task: must-start-on / must-finish-on are not offered (the server refuses them). */
  summary?: boolean
  onSave: (patch: Partial<GanttTask>) => void
  onClose: () => void
}) {
  const t = p.task
  const [f, setF] = useState({
    name: t.name, start: t.start, duration: String(t.duration), progress: String(Math.round(t.progress ?? 0)),
    notes: t.notes ?? '', ctype: (t.constraint?.type ?? 'asap') as ConstraintType, cdate: t.constraint?.date ?? '',
  })
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => { ref.current?.querySelector<HTMLInputElement>('input:not([disabled])')?.focus() }, [])
  const dur = Math.max(0, Math.round(Number(f.duration)))
  const patch: Partial<GanttTask> = {}
  if (p.canField('name') && f.name.trim() !== t.name) patch.name = f.name.trim()
  if (p.canField('start') && isIsoDay(f.start) && f.start !== t.start) patch.start = f.start
  if (p.canField('duration') && Number.isFinite(dur) && dur !== t.duration) patch.duration = dur
  if (p.canField('progress') && Number(f.progress) !== Math.round(t.progress ?? 0)) patch.progress = Math.max(0, Math.min(100, Math.round(Number(f.progress) || 0)))
  if (p.canField('notes') && (f.notes.trim() || null) !== (t.notes ?? null)) patch.notes = f.notes.trim() || null
  if (p.allowConstraints && p.canField('constraint')) {
    const cur = t.constraint?.type ?? 'asap'
    const curDate = t.constraint?.date ?? ''
    if (f.ctype !== cur || (f.ctype !== 'asap' && f.cdate !== curDate)) {
      patch.constraint = f.ctype === 'asap' ? { type: 'asap', date: null } : { type: f.ctype, date: f.cdate || null }
    }
  }
  const constraintOk = (f.ctype === 'asap' || isIsoDay(f.cdate)) && !(p.summary && (f.ctype === 'mso' || f.ctype === 'mfo'))
  const ok = f.name.trim() !== '' && isIsoDay(f.start) && inYearRange(f.start) && constraintOk && dur <= LIMITS.maxDuration
  const field = 'w-full rounded border px-2 py-1 text-sm [color-scheme:dark] disabled:opacity-50'
  const fs = { background: v('bg'), borderColor: v('gridLine'), color: v('text') }
  const lab = 'mb-0.5 block text-[10px] uppercase tracking-wide'
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50" onPointerDown={(e) => { if (e.target === e.currentTarget) p.onClose() }}>
      <div ref={ref} role="dialog" aria-modal="true" aria-label={`Task information: ${t.name}`} data-testid="gantt-task-dialog"
        className="w-full max-w-md space-y-3 rounded-xl border p-5 shadow-2xl"
        style={{ background: v('panel'), borderColor: v('gridLine'), color: v('text') }}
        onKeyDown={(e) => { e.stopPropagation(); if (e.key === 'Escape') p.onClose() }}>
        <h3 className="text-sm font-semibold">Task information</h3>
        <label className="block"><span className={lab} style={{ color: v('textFaint') }}>Name</span>
          <input className={field} style={fs} value={f.name} disabled={!p.canField('name')} aria-label="Name"
            onChange={(e) => setF({ ...f, name: e.target.value })} /></label>
        <div className="grid grid-cols-3 gap-2">
          <label className="col-span-2 block"><span className={lab} style={{ color: v('textFaint') }}>Start</span>
            <input type="date" className={field} style={fs} value={f.start} disabled={!p.canField('start')} aria-label="Start"
              onChange={(e) => setF({ ...f, start: e.target.value })} /></label>
          <label className="block"><span className={lab} style={{ color: v('textFaint') }}>{p.working ? 'Work days' : 'Days'}</span>
            <input type="number" min={0} className={field} style={fs} value={f.duration} disabled={!p.canField('duration')} aria-label="Duration"
              onChange={(e) => setF({ ...f, duration: e.target.value })} /></label>
        </div>
        {p.allowConstraints && (
          <div className="grid grid-cols-3 gap-2">
            <label className="col-span-2 block"><span className={lab} style={{ color: v('textFaint') }}>Constraint</span>
              <select className={field} style={fs} value={f.ctype} disabled={!p.canField('constraint')} aria-label="Constraint"
                onChange={(e) => setF({ ...f, ctype: e.target.value as ConstraintType })}>
                {CONSTRAINT_TYPES.filter((c) => !p.summary || (c !== 'mso' && c !== 'mfo') || c === f.ctype)
                  .map((c) => <option key={c} value={c}>{CONSTRAINT_LABEL[c]}</option>)}
              </select></label>
            <label className="block"><span className={lab} style={{ color: v('textFaint') }}>Date</span>
              <input type="date" className={field} style={fs} value={f.cdate} aria-label="Constraint date"
                disabled={!p.canField('constraint') || f.ctype === 'asap'} onChange={(e) => setF({ ...f, cdate: e.target.value })} /></label>
          </div>
        )}
        <label className="block"><span className={lab} style={{ color: v('textFaint') }}>Progress %</span>
          <input type="number" min={0} max={100} className={field} style={fs} value={f.progress} disabled={!p.canField('progress')} aria-label="Progress"
            onChange={(e) => setF({ ...f, progress: e.target.value })} /></label>
        <label className="block"><span className={lab} style={{ color: v('textFaint') }}>Notes</span>
          <textarea rows={3} className={field} style={fs} value={f.notes} disabled={!p.canField('notes')} aria-label="Notes"
            onChange={(e) => setF({ ...f, notes: e.target.value })} /></label>
        <div className="flex justify-end gap-2 pt-1">
          <button type="button" className="rounded border px-3 py-1.5 text-sm" style={{ borderColor: v('gridLine') }} onClick={p.onClose}>Cancel</button>
          <button type="button" className="rounded px-3 py-1.5 text-sm text-white disabled:opacity-40" style={{ background: v('accent') }}
            data-testid="gantt-task-dialog-save" disabled={!ok || Object.keys(patch).length === 0}
            onClick={() => { p.onSave(patch); p.onClose() }}>Save</button>
        </div>
      </div>
    </div>
  )
}
