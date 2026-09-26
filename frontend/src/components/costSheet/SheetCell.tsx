/**
 * One cell of the cost sheet. Read-only it formats the value; editable it is
 * an input or select that commits on blur / Enter / change (selects) and only
 * when the value really changed. Escape restores the saved value.
 */
import { useEffect, useId, useRef, useState } from 'react'
import {
  NUMBER_INPUT_HINT, NUMBER_INPUT_INVALID, formatMoney, formatNumber, numberEditText, readNumberInput,
} from '../../lib/format'
import type { CostSheetRow } from '../../types/costSheet'
import { type Column, type SheetContext, deptName, plantName } from './columns'

const INPUT =
  'w-full bg-slate-900/60 border border-slate-700 rounded px-2 py-1 text-sm text-slate-100 ' +
  'placeholder:text-slate-600 focus:outline-none focus:border-sky-500 focus:ring-1 focus:ring-sky-500/40 ' +
  'disabled:opacity-40 disabled:cursor-not-allowed'

/**
 * The raw edit value: no grouping, dot decimals, no exponent, so it reads
 * back through parse() unchanged (lib/format numberEditText).
 */
function toInput(v: unknown, money = false): string {
  if (v === null || v === undefined) return ''
  if (typeof v !== 'number') return String(v)
  return money && Number.isFinite(v) ? v.toFixed(2) : numberEditText(v)
}

type Refusal = 'invalid' | 'ambiguous'

/** The typed value to save, or why it was refused (not a number, or "7,5": see readNumberInput). */
function parse(col: Column, raw: string): { value: unknown } | { refused: Refusal } {
  const t = raw.trim()
  if (col.kind === 'money' || col.kind === 'number') {
    if (!t) return { value: null }
    const r = readNumberInput(t)
    return r.error ? { refused: r.error } : { value: r.value }
  }
  if (col.kind === 'currency') return { value: t.toUpperCase() || 'EUR' }
  return { value: t || null }
}

const REFUSAL_MSG: Record<Refusal, string> = { ambiguous: NUMBER_INPUT_HINT, invalid: NUMBER_INPUT_INVALID }

export function displayValue(col: Column, row: CostSheetRow, ctx: SheetContext): string {
  const v = row[col.key]
  switch (col.kind) {
    case 'money':
      return v === null || v === undefined ? (col.empty ?? '-')
        : formatMoney(v as number, (row[col.currencyKey ?? 'currency'] as string) || 'EUR')
    case 'number':
      return v === null || v === undefined ? '-' : formatNumber(v as number)
    case 'department':
    case 'department_optional':
      return deptName(ctx, v) || col.empty || '-'
    case 'plant':
      return plantName(ctx, v) || col.empty || '-'
    case 'machine_class':
      return (row.machine_class as string) || ctx.machineClasses.find((c) => c.id === v)?.name || '-'
    case 'sampling_mode':
      return v === 'components' ? 'Components' : 'Flat'
    case 'overhead_kind':
      return v === 'per_hour' ? 'Per hour' : 'Percent'
    default:
      return v === null || v === undefined || v === '' ? (col.empty ?? '') : String(v)
  }
}

interface Props {
  col: Column
  row: CostSheetRow
  ctx: SheetContext
  editable: boolean
  onCommit: (value: unknown) => void
}

export default function SheetCell({ col, row, ctx, editable, onCommit }: Props) {
  const value = row[col.key]
  const money = col.kind === 'money'
  const [draft, setDraft] = useState(toInput(value, money))
  // A refused number stays as typed and is flagged, never silently converted.
  const [refused, setRefused] = useState<Refusal | null>(null)
  // The edit text at focus: left unchanged, it is never re-read (so a stored
  // value is never refused just by focusing and leaving the cell).
  const focusDraft = useRef<string | null>(null)
  const msgId = useId()
  useEffect(() => { setDraft(toInput(value, money)); setRefused(null) }, [value, money])
  const inactive = col.inactive?.(row) ?? false
  const hint = inactive ? null : col.hint?.(row) ?? null
  const caption = hint && (
    <span data-testid={`sheet-cell-hint-${col.key}`} title={hint.title}
      className="block text-[10px] leading-tight text-slate-500">{hint.text}</span>
  )

  if (col.kind === 'computed') {
    return <>{col.render?.(row, ctx)}</>
  }

  if (!editable) {
    const text = displayValue(col, row, ctx)
    const muted = value === null || value === undefined || value === ''
    const warn = muted && !inactive && col.emptyWarn
    return (
      <>
        <span data-empty={warn ? 'true' : undefined}
          className={`${warn ? 'text-amber-300/90' : muted || inactive ? 'text-slate-500' : hint ? 'text-slate-300' : 'text-slate-200'} ${col.numeric ? 'tabular-nums' : ''}`}>
          {inactive && muted ? '' : text}
        </span>
        {caption}
      </>
    )
  }

  const commitSelect = (raw: string) => {
    const next = raw === '' ? null : (/_id$/.test(col.key) ? Number(raw) : raw)
    if (next !== value) onCommit(next)
  }

  const label = `${col.label}`

  if (col.kind === 'department' || col.kind === 'department_optional') {
    return (
      <select aria-label={label} className={INPUT} value={toInput(value)} disabled={inactive}
              onChange={(e) => commitSelect(e.target.value)}>
        {col.kind === 'department_optional' && <option value="">{col.empty ?? '-'}</option>}
        {ctx.departments.filter((d) => d.is_active || d.id === value).map((d) => (
          <option key={d.id} value={d.id}>{d.name}</option>
        ))}
      </select>
    )
  }
  if (col.kind === 'plant') {
    return (
      <select aria-label={label} className={INPUT} value={toInput(value)} disabled={inactive}
              onChange={(e) => commitSelect(e.target.value)}>
        <option value="">{col.empty ?? 'All plants'}</option>
        {ctx.plants.filter((p) => p.is_active || p.id === value).map((p) => (
          <option key={p.id} value={p.id}>{p.name}{p.is_active ? '' : ' (inactive)'}</option>
        ))}
      </select>
    )
  }
  if (col.kind === 'sampling_mode' || col.kind === 'overhead_kind') {
    const opts = col.kind === 'sampling_mode'
      ? [['flat', 'Flat'], ['components', 'Components']]
      : [['percent', 'Percent'], ['per_hour', 'Per hour']]
    return (
      <select aria-label={label} className={INPUT} value={toInput(value)}
              onChange={(e) => commitSelect(e.target.value)}>
        {opts.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
      </select>
    )
  }
  if (col.kind === 'machine_class') {
    return (
      <select aria-label={label} className={INPUT} value={toInput(value)}
              onChange={(e) => commitSelect(e.target.value)}>
        {value == null && <option value="">Pick a class</option>}
        {ctx.machineClasses.filter((c) => c.is_active || c.id === value).map((c) => (
          <option key={c.id} value={c.id}>{c.name}</option>
        ))}
      </select>
    )
  }
  if (col.kind === 'currency') {
    return (
      <select aria-label={label} className={INPUT} value={toInput(value)} disabled={inactive}
              onChange={(e) => commitSelect(e.target.value)}>
        {!value && <option value="">{inactive ? '' : 'Plant'}</option>}
        {ctx.currencies.map((c) => <option key={c} value={c}>{c}</option>)}
      </select>
    )
  }

  const message = refused ? `Not saved. ${REFUSAL_MSG[refused]}` : null
  return (
    <>
      <input
        aria-label={label}
        className={`${INPUT} ${col.numeric ? 'text-right tabular-nums' : ''} ${col.emptyWarn ? 'placeholder:text-amber-400/70' : ''} ${refused ? '!border-rose-500' : ''}`}
        inputMode={col.kind === 'money' || col.kind === 'number' ? 'decimal' : undefined}
        value={draft}
        disabled={inactive}
        placeholder={col.empty ?? ''}
        aria-invalid={refused ? true : undefined}
        aria-describedby={message ? msgId : undefined}
        title={message ?? undefined}
        onFocus={() => { focusDraft.current = draft }}
        onChange={(e) => { setDraft(e.target.value); setRefused(null) }}
        onBlur={() => {
          const untouched = draft === focusDraft.current
          focusDraft.current = null
          if (untouched) return
          const next = parse(col, draft)
          if ('refused' in next) { setRefused(next.refused); return }
          setRefused(null)
          if (next.value !== value) onCommit(next.value)
        }}
        onKeyDown={(e) => {
          if (e.key === 'Enter') (e.target as HTMLInputElement).blur()
          if (e.key === 'Escape') { setDraft(toInput(value, money)); setRefused(null) }
        }}
      />
      {!message && caption}
      {message && (
        <p id={msgId} role="alert" data-testid="sheet-cell-refused"
           className="mt-0.5 text-left text-[11px] leading-tight text-rose-300">
          {message}
        </p>
      )}
    </>
  )
}
