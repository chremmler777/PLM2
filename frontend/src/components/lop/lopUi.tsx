/** Small shared pieces of the LOP screen. */
import type { ReactNode } from 'react'
import type { TeamPerson } from './lopTeam'

export const inputCls =
  'h-7 rounded-md border border-slate-600 bg-slate-900 px-2 text-xs text-slate-100 ' +
  'focus:border-sky-500 focus:outline-none disabled:opacity-50'

export const labelCls = 'flex flex-col gap-0.5 text-[11px] text-slate-400'

export function InlineError({ children }: { children: ReactNode }) {
  if (!children) return null
  return <p role="alert" className="mt-1 text-xs text-red-300">{children}</p>
}

export function DefaultMarker({ testId, title }: { testId: string; title: string }) {
  return (
    <span data-testid={testId} title={title}
      className="ml-1 rounded border border-dashed border-slate-500 px-1 text-[10px] text-slate-400">
      default
    </span>
  )
}

/**
 * Additional owners of a line: the chosen people as chips with a remove, and
 * a select that adds one more. The main owner is never offered.
 */
export function OwnersPicker({ people, value, mainId, onChange, testId }: {
  people: TeamPerson[]; value: number[]; mainId: number | null; onChange(ids: number[]): void; testId?: string
}) {
  const chosen = value.filter((id) => id !== mainId)
  const name = (id: number) => people.find((p) => p.id === id)?.name ?? `person ${id}`
  const free = people.filter((p) => p.id !== mainId && !chosen.includes(p.id))
  return (
    <div className={labelCls} data-testid={testId}>
      <span id={testId ? `${testId}-label` : undefined}>Additional owners</span>
      <div className="flex flex-wrap items-center gap-1.5">
        {chosen.map((id) => (
          <span key={id} className="flex h-7 items-center gap-1 rounded-md border border-slate-600 px-2 text-xs text-slate-100">
            {name(id)}
            <button type="button" aria-label={`Remove ${name(id)} as additional owner`}
              className="text-slate-500 hover:text-red-300" onClick={() => onChange(chosen.filter((x) => x !== id))}>✕</button>
          </span>
        ))}
        {free.length > 0 && (
          <select className={inputCls} value="" aria-label="Add an additional owner"
            onChange={(e) => { if (e.target.value) onChange([...chosen, Number(e.target.value)]) }}>
            <option value="">{chosen.length ? 'add another…' : 'none · add…'}</option>
            <PersonOptions people={free} />
          </select>
        )}
      </div>
    </div>
  )
}

export function PersonOptions({ people }: { people: TeamPerson[] }) {
  return <>{people.map((p) => <option key={p.id} value={p.id}>{p.name} ({p.department})</option>)}</>
}
