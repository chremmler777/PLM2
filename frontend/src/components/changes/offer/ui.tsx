/** Small controls the offer and release workspaces share. */
import { useEffect, useId, useLayoutEffect, useRef, useState, type ReactNode, type TextareaHTMLAttributes } from 'react'
import { Check } from 'lucide-react'
import { formatNumber } from '../../../lib/format'
import { inputCls, parseNum, sectionLabel } from './offerFormat'

/** How a number reads at rest: en-US, "13,200", "4.2" (lib/format). */
const shownNum = (v: number | null | undefined): string =>
  v == null || !Number.isFinite(v) ? '' : formatNumber(v, { max: 4 })
/**
 * How it reads while editing: no grouping, dot decimals ("13200", "4.2").
 * parseNum reads "1.234" as 1234 (a dot group), so a value with exactly
 * three decimals and a short integer part gets a trailing zero ("1.2340")
 * and an unedited focus and blur keeps the number.
 */
const editNum = (v: number | null | undefined): string => {
  if (v == null || !Number.isFinite(v)) return ''
  const s = String(v)
  return /^[+-]?[1-9]\d{0,2}\.\d{3}$/.test(s) ? `${s}0` : s
}

/**
 * A number input that keeps what is typed ("12," mid-entry) and reports a
 * parsed number (dot or comma decimals) or null for empty. Focus selects the
 * whole value, so typing replaces it rather than appending to it; while the
 * typed text reads differently from the number it stands for ("12,50",
 * "1.234") the parsed value is shown next to it.
 */
export function NumField({
  value, onChange, disabled, className = '', ariaLabel, testId, placeholder, step,
}: {
  value: number | null | undefined
  onChange: (v: number | null) => void
  disabled?: boolean
  /** Sizes the field (w-28, w-full, ...). */
  className?: string
  ariaLabel: string
  testId?: string
  placeholder?: string
  step?: string
}) {
  const [text, setText] = useState(shownNum(value))
  const [focused, setFocused] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)
  // The click that focused the field must not drop the selection again.
  const keepSelection = useRef(false)
  const previewId = useId()
  const parsed = parseNum(text)
  const invalid = text.trim() !== '' && parsed === null
  const preview = focused && parsed !== null && shownNum(parsed) !== text.trim() ? shownNum(parsed) : null
  // Formatted (en-US grouping) at rest; the rest text is never parsed: focus
  // swaps in the plain edit text first. While typing the text stays as typed.
  useEffect(() => {
    if (!focused) setText(shownNum(value))
  }, [value, focused])
  // Select everything once the edit text is in place (after the focus render).
  useLayoutEffect(() => {
    if (focused && inputRef.current === document.activeElement) inputRef.current?.select()
  }, [focused])
  return (
    <span className={`relative inline-block align-middle ${className}`}>
      <input ref={inputRef} type="text" inputMode="decimal" aria-label={ariaLabel} data-testid={testId}
        disabled={disabled} placeholder={placeholder} data-step={step}
        aria-invalid={invalid || undefined}
        aria-describedby={preview ? previewId : undefined}
        title={invalid ? 'Not a number. For example 1234.5 or 1,234.50' : undefined}
        value={text}
        onMouseDown={() => { keepSelection.current = document.activeElement !== inputRef.current }}
        onFocus={() => { setFocused(true); setText(editNum(value)) }}
        onMouseUp={(e) => { if (keepSelection.current) { e.preventDefault(); keepSelection.current = false } }}
        onBlur={() => { keepSelection.current = false; setFocused(false) }}
        onChange={(e) => {
          keepSelection.current = false
          setText(e.target.value)
          const n = parseNum(e.target.value)
          if (n !== null || e.target.value.trim() === '') onChange(n)
        }}
        className={`${inputCls} w-full text-right tabular-nums ${invalid ? '!border-rose-500' : ''}`} />
      {preview && (
        <span id={previewId} data-testid={testId ? `${testId}-preview` : undefined} aria-live="polite"
          className="pointer-events-none absolute right-0 top-full z-10 mt-0.5 whitespace-nowrap rounded bg-slate-800 px-1.5 py-0.5 text-[11px] tabular-nums text-sky-200 shadow">
          = {preview}
        </span>
      )}
    </span>
  )
}

export function Toggle({
  checked, onChange, disabled, label, testId,
}: {
  checked: boolean
  onChange: (v: boolean) => void
  disabled?: boolean
  label: string
  testId?: string
}) {
  return (
    <button type="button" role="switch" aria-checked={checked} aria-label={label}
      data-testid={testId} disabled={disabled}
      onClick={() => onChange(!checked)}
      className={`relative inline-flex h-4 w-7 shrink-0 items-center rounded-full transition-colors disabled:opacity-50 ${
        checked ? 'bg-sky-500' : 'bg-slate-600'}`}>
      <span className={`inline-block h-3 w-3 rounded-full bg-white shadow transition-transform ${
        checked ? 'translate-x-3.5' : 'translate-x-0.5'}`} />
    </button>
  )
}

/**
 * A one-of-few choice as a radiogroup. Give the group a name: `ariaLabel`,
 * or `labelledBy` pointing at a visible label's id (or wrap it in
 * FieldGroup). Do not put it inside a <label>: that names only the first
 * option.
 */
export function Segmented<T extends string>({
  value, options, onChange, disabled, testId, ariaLabel, labelledBy,
}: {
  value: T
  options: { value: T; label: string }[]
  onChange: (v: T) => void
  disabled?: boolean
  testId?: string
  ariaLabel?: string
  labelledBy?: string
}) {
  return (
    <div role="radiogroup" data-testid={testId} aria-label={labelledBy ? undefined : ariaLabel}
      aria-labelledby={labelledBy}
      className="inline-flex rounded-lg border border-slate-700 bg-slate-900 p-0.5 text-xs">
      {options.map((o) => (
        <button key={o.value} type="button" role="radio" aria-checked={value === o.value}
          data-testid={testId ? `${testId}-${o.value}` : undefined}
          disabled={disabled}
          onClick={() => onChange(o.value)}
          className={`px-2.5 py-1 rounded-md transition-colors disabled:cursor-not-allowed ${
            value === o.value ? 'bg-slate-700 text-slate-50 shadow-sm' : 'text-slate-400 hover:text-slate-200'}`}>
          {o.label}
        </button>
      ))}
    </div>
  )
}

/** A numbered workspace section with its completion tick. */
export function StepSection({
  id, n, title, done, hint, right, children,
}: {
  id: string
  n: number
  title: string
  done: boolean
  hint?: ReactNode
  right?: ReactNode
  children: ReactNode
}) {
  return (
    <section id={id} data-testid={id}
      className="scroll-mt-28 rounded-xl border border-slate-700 bg-slate-800/60">
      <header className="flex flex-wrap items-center gap-3 border-b border-slate-700/70 px-4 py-3">
        <span className={`flex h-6 w-6 items-center justify-center rounded-full text-xs font-semibold ${
          done ? 'bg-emerald-600 text-white' : 'bg-slate-700 text-slate-300'}`}
>
          {done ? <Check aria-hidden="true" size={14} strokeWidth={3} /> : <span aria-hidden="true">{n}</span>}
          <span className="sr-only">{done ? `Step ${n}, complete` : `Step ${n}, open`}</span>
        </span>
        <h3 className="text-sm font-semibold text-slate-100">{title}</h3>
        {right && <div className="ml-auto flex items-center gap-2">{right}</div>}
      </header>
      <div className="space-y-4 px-4 py-4">
        {hint && <p className="text-xs text-slate-400">{hint}</p>}
        {children}
      </div>
    </section>
  )
}

export function SubLabel({ children }: { children: ReactNode }) {
  return <div className={`${sectionLabel} mb-1.5`}>{children}</div>
}

/**
 * A label above one control. For a group of controls (a Segmented, several
 * radios or inputs) use FieldGroup from components/common instead.
 */
export function Field({ label, children, className = '' }: {
  label: string; children: ReactNode; className?: string
}) {
  return (
    <label className={`block ${className}`}>
      <span className="mb-1 block text-[11px] text-slate-400">{label}</span>
      {children}
    </label>
  )
}

/** A textarea that grows with its text (never shorter than `rows`). */
export function AutoGrowTextarea({ rows = 4, className = '', value, ...rest }:
  TextareaHTMLAttributes<HTMLTextAreaElement> & { rows?: number }) {
  const ref = useRef<HTMLTextAreaElement>(null)
  useLayoutEffect(() => {
    const el = ref.current
    if (!el) return
    el.style.height = 'auto'
    if (el.scrollHeight > el.clientHeight) el.style.height = `${el.scrollHeight + 2}px`
  }, [value])
  return <textarea ref={ref} rows={rows} value={value} className={`resize-y ${className}`} {...rest} />
}
