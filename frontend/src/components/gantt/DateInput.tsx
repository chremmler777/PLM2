/**
 * A date field that always shows dd.mm.yyyy (no locale mm/dd from the native
 * picker). It parses dd.mm.yyyy, dd.mm.yy and ISO yyyy-mm-dd, and offers a
 * small month calendar in a popover. Value in and out: ISO `YYYY-MM-DD` or ''.
 */
import { useEffect, useId, useRef, useState } from 'react'
import { MONTHS, dayOf, isIsoDay, isoWeekday, toDay, toIso, todayDay, ymd } from './engine/calendar'
import { formatDateInput, parseDateInput } from './dateText'

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
  onKeyDown?: (e: React.KeyboardEvent<HTMLInputElement>) => void
  onBlur?: () => void
  autoFocus?: boolean
  placeholder?: string
}

export default function DateInput(p: Props) {
  const [text, setText] = useState(formatDateInput(p.value))
  const [open, setOpen] = useState(false)
  const [month, setMonth] = useState(() => {
    const d = isIsoDay(p.value) ? toDay(p.value) : todayDay()
    const { y, m } = ymd(d)
    return { y, m }
  })
  const wrap = useRef<HTMLDivElement>(null)
  const input = useRef<HTMLInputElement>(null)
  const popId = useId()
  useEffect(() => { setText(formatDateInput(p.value)) }, [p.value])
  useEffect(() => { if (p.autoFocus) { input.current?.focus(); input.current?.select() } }, [p.autoFocus])
  useEffect(() => {
    if (!open) return
    const down = (e: Event) => { if (wrap.current && !wrap.current.contains(e.target as Node)) setOpen(false) }
    document.addEventListener('pointerdown', down, true)
    return () => document.removeEventListener('pointerdown', down, true)
  }, [open])

  const inRange = (iso: string) => (!p.min || iso >= p.min) && (!p.max || iso <= p.max)
  const commitText = () => {
    if (!text.trim()) { if (p.value !== '') p.onChange(''); return }
    const iso = parseDateInput(text)
    if (iso && inRange(iso)) { if (iso !== p.value) p.onChange(iso); setText(formatDateInput(iso)) }
    else setText(formatDateInput(p.value)) // not a date: back to the last good value
  }
  const pick = (iso: string) => { setOpen(false); setText(formatDateInput(iso)); p.onChange(iso); input.current?.focus() }

  const first = dayOf(month.y, month.m, 1)
  const lead = isoWeekday(first) - 1
  const days = dayOf(month.y, month.m + 1, 1) - first
  const cells: (number | null)[] = [...Array(lead).fill(null), ...Array.from({ length: days }, (_, i) => first + i)]
  const invalid = text.trim() !== '' && !parseDateInput(text)

  return (
    <div ref={wrap} className="relative">
      <input ref={input} id={p.id} type="text" inputMode="numeric" disabled={p.disabled} aria-label={p['aria-label']}
        aria-invalid={invalid || undefined} placeholder={p.placeholder ?? 'dd.mm.yyyy'}
        className={`${p.className ?? ''} pr-7`} style={p.style} value={text}
        onChange={(e) => setText(e.target.value)}
        onBlur={() => { commitText(); p.onBlur?.() }}
        onKeyDown={(e) => {
          if (e.key === 'Enter') commitText()
          if (e.key === 'ArrowDown' && e.altKey) { e.preventDefault(); setOpen(true) }
          p.onKeyDown?.(e)
        }} />
      {!p.disabled && (
        <button type="button" tabIndex={-1} aria-label="Open calendar" aria-expanded={open} aria-controls={popId}
          className="absolute inset-y-0 right-1 my-auto h-5 w-5 rounded text-[11px] opacity-70 hover:opacity-100"
          onMouseDown={(e) => e.preventDefault()}
          onClick={() => {
            const d = parseDateInput(text) ?? p.value
            if (d && isIsoDay(d)) { const { y, m } = ymd(toDay(d)); setMonth({ y, m }) }
            setOpen((o) => !o)
          }}>&#9638;</button>
      )}
      {open && (
        <div id={popId} role="dialog" aria-label="Pick a date" data-testid="date-popover"
          className="absolute right-0 z-50 mt-1 w-[224px] rounded-md border border-slate-600 bg-slate-900 p-2 text-xs text-slate-200 shadow-xl"
          onKeyDown={(e) => { if (e.key === 'Escape') { e.stopPropagation(); setOpen(false) } }}>
          <div className="mb-1 flex items-center">
            <button type="button" aria-label="Previous month" className="rounded px-1.5 hover:bg-slate-800"
              onClick={() => setMonth(({ y, m }) => (m === 0 ? { y: y - 1, m: 11 } : { y, m: m - 1 }))}>&#8249;</button>
            <span className="flex-1 text-center font-medium">{MONTHS[month.m]} {month.y}</span>
            <button type="button" aria-label="Next month" className="rounded px-1.5 hover:bg-slate-800"
              onClick={() => setMonth(({ y, m }) => (m === 11 ? { y: y + 1, m: 0 } : { y, m: m + 1 }))}>&#8250;</button>
          </div>
          <div className="grid grid-cols-7 gap-0.5 text-center">
            {['Mo', 'Tu', 'We', 'Th', 'Fr', 'Sa', 'Su'].map((d) => <span key={d} className="text-[10px] text-slate-500">{d}</span>)}
            {cells.map((d, i) => {
              if (d == null) return <span key={`e${i}`} />
              const iso = toIso(d)
              const sel = iso === p.value
              return (
                <button key={iso} type="button" disabled={!inRange(iso)} aria-label={formatDateInput(iso)} aria-pressed={sel}
                  className={`rounded py-0.5 tabular-nums disabled:opacity-30 ${sel ? 'bg-sky-600 text-white' : d === todayDay() ? 'ring-1 ring-sky-500' : 'hover:bg-slate-800'}`}
                  onClick={() => pick(iso)}>{ymd(d).d}</button>
              )
            })}
          </div>
        </div>
      )}
    </div>
  )
}
