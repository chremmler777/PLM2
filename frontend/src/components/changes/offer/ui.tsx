/** Small controls the offer and release workspaces share. */
import { useEffect, useState, type ReactNode } from 'react'
import { inputCls, parseNum, sectionLabel } from './offerFormat'

/**
 * A number input that keeps what is typed ("12," mid-entry) and reports a
 * parsed number (comma or dot decimals) or null for empty.
 */
export function NumField({
  value, onChange, disabled, className = '', ariaLabel, testId, placeholder, step,
}: {
  value: number | null | undefined
  onChange: (v: number | null) => void
  disabled?: boolean
  className?: string
  ariaLabel: string
  testId?: string
  placeholder?: string
  step?: string
}) {
  const [text, setText] = useState(value == null ? '' : String(value).replace('.', ','))
  const [focused, setFocused] = useState(false)
  const invalid = text.trim() !== '' && parseNum(text) === null
  useEffect(() => {
    if (!focused) setText(value == null ? '' : String(value).replace('.', ','))
  }, [value, focused])
  return (
    <input type="text" inputMode="decimal" aria-label={ariaLabel} data-testid={testId}
      disabled={disabled} placeholder={placeholder} data-step={step}
      aria-invalid={invalid || undefined}
      title={invalid ? 'Not a number. Use a comma for decimals, e.g. 1.234,50' : undefined}
      value={text}
      onFocus={() => setFocused(true)}
      onBlur={() => setFocused(false)}
      onChange={(e) => {
        setText(e.target.value)
        const n = parseNum(e.target.value)
        if (n !== null || e.target.value.trim() === '') onChange(n)
      }}
      className={`${inputCls} text-right tabular-nums ${invalid ? '!border-rose-500' : ''} ${className}`} />
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

export function Segmented<T extends string>({
  value, options, onChange, disabled, testId,
}: {
  value: T
  options: { value: T; label: string }[]
  onChange: (v: T) => void
  disabled?: boolean
  testId?: string
}) {
  return (
    <div role="radiogroup" data-testid={testId}
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
          aria-label={done ? 'complete' : 'open'}>
          {done ? '✓' : n}
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

export function Field({ label, children, className = '' }: {
  label: string; children: ReactNode; className?: string
}) {
  return (
    <label className={`block ${className}`}>
      <span className="mb-1 block text-[11px] text-slate-500">{label}</span>
      {children}
    </label>
  )
}
