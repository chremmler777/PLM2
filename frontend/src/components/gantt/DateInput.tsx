/**
 * A date field that always shows "25 Sep 2026" (no locale mm/dd from the
 * native picker). It reads "25 Sep 2026", "25 sep 26", "Sep 25, 2026",
 * "September 25 2026", ISO yyyy-mm-dd, dd.mm.yyyy, dd.mm.yy (00-69 = 20xx,
 * 70-99 = 19xx) and dd-mm-yyyy, echoes the date it read under the field
 * while typing ("= 25 Sep 2026"), refuses slashes (ambiguous) and years
 * outside 1900-2200 with a message, and offers a small month calendar in a
 * popover (portal into the closest open <dialog>, else the body; kept inside
 * the viewport, arrow keys move the day). Value in and out: ISO `YYYY-MM-DD` or ''. */
import { useCallback, useEffect, useId, useLayoutEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { MONTHS, dayOf, isIsoDay, isoWeekday, toDay, toIso, todayDay, ymd } from './engine/calendar'
import { DATE_PLACEHOLDER, formatDateInput, readDateInput } from './dateText'

interface Props {
  value: string
  onChange: (iso: string) => void
  disabled?: boolean
  id?: string
  className?: string
  style?: React.CSSProperties
  'aria-label'?: string
  /** Latest allowed day (ISO), e.g. tomorrow for actual dates. */
  max?: string
  min?: string
  /** An empty field is refused with "<label> is required" (the value stays). */
  required?: boolean
  onKeyDown?: (e: React.KeyboardEvent<HTMLInputElement>) => void
  onBlur?: () => void
  autoFocus?: boolean
  placeholder?: string
  /**
   * Report a complete, valid date (four-digit year or ISO) or an emptied field
   * while typing, not only on blur / Enter, so dependent UI (a "still
   * missing" list, a filter) follows the keystrokes. The text is left as typed.
   */
  commitOnChange?: boolean
}

const POP_W = 224
const POP_H = 250

/**
 * Where the calendar popover mounts: the closest open <dialog>, else the body.
 * A modal dialog (showModal) sits in the top layer and makes the rest of the
 * page inert, so a popover portalled to the body would be hidden under it and
 * unclickable.
 */
function popHost(from: Element | null): HTMLElement {
  return from?.closest<HTMLElement>('dialog[open]') ?? document.body
}

/**
 * The viewport point a `position: fixed` child of the host is measured from:
 * (0, 0), unless the host is a dialog that sets a containing block for fixed
 * descendants (transform, filter, perspective, contain, will-change), then
 * its padding box.
 */
function fixedOrigin(host: HTMLElement): { x: number; y: number } {
  if (host === document.body) return { x: 0, y: 0 }
  const cs = getComputedStyle(host)
  const set = (v: string | undefined) => !!v && v !== 'none' && v !== 'auto' && v !== 'normal'
  const makesBlock = set(cs.transform) || set(cs.filter) || set(cs.perspective)
    || /paint|layout|strict|content/.test(cs.contain || '')
    || /transform|filter|perspective/.test(cs.willChange || '')
  if (!makesBlock) return { x: 0, y: 0 }
  const r = host.getBoundingClientRect()
  return { x: r.left + host.clientLeft, y: r.top + host.clientTop }
}

export default function DateInput(p: Props) {
  const [text, setText] = useState(formatDateInput(p.value))
  const [open, setOpen] = useState(false)
  const [focusDay, setFocusDay] = useState<number>(() => (isIsoDay(p.value) ? toDay(p.value) : todayDay()))
  const [pos, setPos] = useState<{ left: number; top: number } | null>(null)
  const [message, setMessage] = useState<string | null>(null)
  const wrap = useRef<HTMLDivElement>(null)
  const input = useRef<HTMLInputElement>(null)
  const pop = useRef<HTMLDivElement>(null)
  const popId = useId()
  const msgId = useId()
  // A value this field just reported while typing must not reformat the text
  // under the cursor.
  const emitted = useRef<string | null>(null)
  useEffect(() => {
    if (emitted.current !== null && emitted.current === p.value) { emitted.current = null; return }
    emitted.current = null
    setText(formatDateInput(p.value)); setMessage(null)
  }, [p.value])
  useEffect(() => { if (p.autoFocus) { input.current?.focus(); input.current?.select() } }, [p.autoFocus])

  const inside = (n: Node | null) => !!n && (!!wrap.current?.contains(n) || !!pop.current?.contains(n))
  useEffect(() => {
    if (!open) return
    const down = (e: Event) => { if (!inside(e.target as Node)) setOpen(false) }
    document.addEventListener('pointerdown', down, true)
    return () => document.removeEventListener('pointerdown', down, true)
  }, [open])

  // Below the field, right-aligned; above when there is no room below; always
  // inside the viewport. Follows the field when anything scrolls.
  const place = useCallback(() => {
    const r = wrap.current?.getBoundingClientRect()
    if (!r) return
    const vw = window.innerWidth || document.documentElement.clientWidth
    const vh = window.innerHeight || document.documentElement.clientHeight
    const h = pop.current?.offsetHeight || POP_H
    let top = r.bottom + 4
    if (top + h > vh - 4 && r.top - 4 - h >= 4) top = r.top - 4 - h
    top = Math.max(4, Math.min(top, vh - h - 4))
    const left = Math.max(4, Math.min(r.right - POP_W, vw - POP_W - 4))
    const o = fixedOrigin(popHost(wrap.current))
    setPos({ left: left - o.x, top: top - o.y })
  }, [])
  useLayoutEffect(() => {
    if (!open) return
    place()
    window.addEventListener('resize', place)
    window.addEventListener('scroll', place, true)
    return () => { window.removeEventListener('resize', place); window.removeEventListener('scroll', place, true) }
  }, [open, place])
  // Keyboard focus follows the highlighted day while the popover is open.
  useEffect(() => {
    if (!open) return
    const b = pop.current?.querySelector<HTMLButtonElement>(`[data-day="${focusDay}"]`)
    if (b && pop.current?.contains(document.activeElement)) b.focus()
  }, [focusDay, open])

  const label = p['aria-label'] ?? 'Date'
  const inRange = (iso: string) => (!p.min || iso >= p.min) && (!p.max || iso <= p.max)
  const commitText = () => {
    if (!text.trim()) {
      if (p.required) { setText(formatDateInput(p.value)); setMessage(`${label} is required`); return }
      setMessage(null)
      if (p.value !== '') p.onChange('')
      return
    }
    const r = readDateInput(text)
    if (r.iso && inRange(r.iso)) {
      setMessage(null)
      if (r.iso !== p.value) p.onChange(r.iso)
      setText(formatDateInput(r.iso))
      return
    }
    // Not usable: back to the last good value, and say why.
    const why = r.error ?? (p.min && r.iso && r.iso < p.min ? `Not before ${formatDateInput(p.min)}` : `Not after ${formatDateInput(p.max)}`)
    setMessage(p.value ? `${why} (kept ${formatDateInput(p.value)})` : why)
    setText(formatDateInput(p.value))
  }
  const openAt = (iso: string | null, focus: boolean) => {
    const d = iso && isIsoDay(iso) ? toDay(iso) : isIsoDay(p.value) ? toDay(p.value) : todayDay()
    setFocusDay(d)
    setOpen(true)
    if (focus) requestAnimationFrame(() => pop.current?.querySelector<HTMLButtonElement>(`[data-day="${d}"]`)?.focus())
  }
  const close = (refocus: boolean) => { setOpen(false); if (refocus) input.current?.focus() }
  const pick = (iso: string) => { setOpen(false); setText(formatDateInput(iso)); setMessage(null); p.onChange(iso); input.current?.focus() }

  const { y, m } = ymd(focusDay)
  const first = dayOf(y, m, 1)
  const lead = isoWeekday(first) - 1
  const days = dayOf(y, m + 1, 1) - first
  const cells: (number | null)[] = [...Array(lead).fill(null), ...Array.from({ length: days }, (_, i) => first + i)]
  const typed = readDateInput(text)
  const invalid = text.trim() !== '' && !typed.iso
  const shownMessage = message ?? (invalid ? typed.error : null)
  // What the typed text reads as, while it is not yet in the shown form.
  const echo = !shownMessage && typed.iso && text.trim() !== formatDateInput(typed.iso) ? formatDateInput(typed.iso) : null
  const shiftMonth = (dm: number) => setFocusDay((d) => {
    const c = ymd(d)
    const last = dayOf(c.y, c.m + dm + 1, 1) - dayOf(c.y, c.m + dm, 1)
    return dayOf(c.y, c.m + dm, Math.min(c.d, last))
  })

  const onDayKey = (e: React.KeyboardEvent) => {
    const step: Record<string, number> = { ArrowLeft: -1, ArrowRight: 1, ArrowUp: -7, ArrowDown: 7 }
    if (e.key in step) { e.preventDefault(); setFocusDay((d) => d + step[e.key]); return }
    if (e.key === 'PageUp' || e.key === 'PageDown') { e.preventDefault(); shiftMonth(e.key === 'PageUp' ? -1 : 1); return }
    if (e.key === 'Home' || e.key === 'End') {
      e.preventDefault()
      setFocusDay((d) => d - (isoWeekday(d) - 1) + (e.key === 'End' ? 6 : 0))
    }
  }

  return (
    <div ref={wrap} className="relative"
      // The whole control commits: the field, the calendar button and the
      // popover (a portal, but its focus events bubble here through React).
      // Tab from the field to the calendar button and then a click elsewhere
      // still commits the typed date.
      onBlur={(e) => {
        if (inside(e.relatedTarget as Node | null)) return
        setOpen(false)
        commitText(); p.onBlur?.()
      }}>
      <input ref={input} id={p.id} type="text" autoComplete="off" spellCheck={false} data-date-input="" disabled={p.disabled} aria-label={p['aria-label']}
        aria-invalid={invalid || !!message || undefined} aria-describedby={shownMessage || echo ? msgId : undefined}
        placeholder={p.placeholder ?? DATE_PLACEHOLDER}
        className={`${p.className ?? ''} pr-7`} style={p.style} value={text}
        onChange={(e) => {
          const v = e.target.value
          setText(v); setMessage(null)
          if (!p.commitOnChange) return
          const s = v.trim()
          const next = !s ? '' : (/^\d{4}-\d{2}-\d{2}$|\d{4}$/.test(s) ? readDateInput(s).iso : null)
          if (next === null || (next && !inRange(next)) || next === p.value) return
          emitted.current = next
          p.onChange(next)
        }}
        onKeyDown={(e) => {
          if (e.key === 'Escape' && open) { e.preventDefault(); e.stopPropagation(); close(false); return }
          if (e.key === 'Enter') commitText()
          if (e.key === 'ArrowDown' && e.altKey) { e.preventDefault(); openAt(readDateInput(text).iso, true); return }
          if (open && (e.key === 'ArrowDown' || e.key === 'ArrowUp')) {
            // Into the calendar, on the highlighted day.
            e.preventDefault()
            pop.current?.querySelector<HTMLButtonElement>(`[data-day="${focusDay}"]`)?.focus()
            return
          }
          p.onKeyDown?.(e)
        }} />
      {!p.disabled && (
        <button type="button" aria-label="Open calendar" aria-expanded={open} aria-controls={popId} aria-haspopup="dialog"
          className="absolute inset-y-0 right-1 my-auto h-5 w-5 rounded text-[11px] opacity-70 hover:opacity-100 focus-visible:opacity-100 focus-visible:outline focus-visible:outline-1 focus-visible:outline-sky-500"
          onMouseDown={(e) => e.preventDefault()}
          onKeyDown={(e) => { if (e.key === 'Escape' && open) { e.preventDefault(); e.stopPropagation(); close(true) } }}
          onClick={(e) => {
            if (open) { setOpen(false); return }
            // Keyboard activation (detail 0) moves focus into the calendar; a
            // mouse click keeps it in the field (Escape, arrows keep working).
            openAt(readDateInput(text).iso, e.detail === 0)
            if (e.detail !== 0) input.current?.focus()
          }}>&#9638;</button>
      )}
      {shownMessage && (
        <p id={msgId} role="alert" className="mt-0.5 text-[11px] text-red-300" data-testid="date-input-error">{shownMessage}</p>
      )}
      {echo && (
        <p id={msgId} aria-live="polite" className="mt-0.5 text-[11px] tabular-nums text-slate-400" data-testid="date-input-echo">= {echo}</p>
      )}
      {open && createPortal(
        <div ref={pop} id={popId} role="dialog" aria-label="Pick a date" data-testid="date-popover"
          className="fixed z-[70] w-[224px] rounded-md border border-slate-600 bg-slate-900 p-2 text-xs text-slate-200 shadow-xl"
          style={{ left: pos?.left ?? 0, top: pos?.top ?? 0, visibility: pos ? 'visible' : 'hidden' }}
          // A mouse press keeps focus where it is (the field), so a click on a day always lands.
          onMouseDown={(e) => e.preventDefault()}
          onKeyDown={(e) => {
            if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); close(true) }
          }}>
          <div className="mb-1 flex items-center">
            <button type="button" aria-label="Previous month" className="rounded px-1.5 hover:bg-slate-800"
              onClick={() => shiftMonth(-1)}>&#8249;</button>
            <span className="flex-1 text-center font-medium" aria-live="polite">{MONTHS[m]} {y}</span>
            <button type="button" aria-label="Next month" className="rounded px-1.5 hover:bg-slate-800"
              onClick={() => shiftMonth(1)}>&#8250;</button>
          </div>
          <div className="grid grid-cols-7 gap-0.5 text-center" role="grid" onKeyDown={onDayKey}>
            {['Mo', 'Tu', 'We', 'Th', 'Fr', 'Sa', 'Su'].map((d) => <span key={d} className="text-[10px] text-slate-500">{d}</span>)}
            {cells.map((d, i) => {
              if (d == null) return <span key={`e${i}`} />
              const iso = toIso(d)
              const sel = iso === p.value
              const focus = d === focusDay
              return (
                <button key={iso} type="button" data-day={d} tabIndex={focus ? 0 : -1} disabled={!inRange(iso)}
                  aria-label={formatDateInput(iso)} aria-pressed={sel}
                  className={`rounded py-0.5 tabular-nums disabled:opacity-30 focus-visible:outline focus-visible:outline-1 focus-visible:outline-sky-400 ${sel ? 'bg-sky-600 text-white' : d === todayDay() ? 'ring-1 ring-sky-500' : 'hover:bg-slate-800'} ${focus && !sel ? 'bg-slate-800' : ''}`}
                  onClick={() => pick(iso)}>{ymd(d).d}</button>
              )
            })}
          </div>
        </div>,
        popHost(wrap.current),
      )}
    </div>
  )
}
