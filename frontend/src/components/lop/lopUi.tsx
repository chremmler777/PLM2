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

export function PersonOptions({ people }: { people: TeamPerson[] }) {
  return <>{people.map((p) => <option key={p.id} value={p.id}>{p.name} ({p.department})</option>)}</>
}
