/**
 * The org's machine classes (tonnage bands). Not versioned: they are the
 * vocabulary the Machines and Sampling rows pick from.
 */
import { useState } from 'react'
import type { MachineClass } from '../../types/costSheet'

function band(c: MachineClass): string {
  if (c.tonnage_min === null && c.tonnage_max === null) return ''
  if (c.tonnage_min === null) return `up to ${c.tonnage_max} t`
  if (c.tonnage_max === null) return `over ${c.tonnage_min} t`
  return `${c.tonnage_min} to ${c.tonnage_max} t`
}

interface Props {
  classes: MachineClass[]
  canEdit: boolean
  onAdd: (body: { name: string; tonnage_min: number | null; tonnage_max: number | null }) => Promise<boolean>
  /** Rename; rows using the class follow. */
  onRename: (id: number, name: string) => Promise<boolean>
}

const INPUT = 'rounded border border-slate-700 bg-slate-900/60 px-2 py-1 text-sm text-slate-100 placeholder:text-slate-600 focus:border-sky-500 focus:outline-none'

export default function MachineClassStrip({ classes, canEdit, onAdd, onRename }: Props) {
  const [open, setOpen] = useState(false)
  const [renaming, setRenaming] = useState<{ id: number; name: string } | null>(null)
  const [name, setName] = useState('')
  const [min, setMin] = useState('')
  const [max, setMax] = useState('')
  const num = (s: string) => (s.trim() === '' ? null : Number(s))

  const submit = async () => {
    if (!name.trim()) return
    if (await onAdd({ name: name.trim(), tonnage_min: num(min), tonnage_max: num(max) })) {
      setName(''); setMin(''); setMax(''); setOpen(false)
    }
  }

  return (
    <div className="flex flex-wrap items-center gap-2 text-sm">
      <span className="text-xs uppercase tracking-wide text-slate-500">Machine classes</span>
      {classes.length === 0 && <span className="text-slate-500">none defined yet</span>}
      {classes.map((c) => renaming?.id === c.id ? (
        <form key={c.id} className="flex items-center gap-1" onSubmit={async (e) => {
          e.preventDefault()
          const name = renaming.name.trim()
          if (!name || name === c.name) { setRenaming(null); return }
          if (await onRename(c.id, name)) setRenaming(null)
        }}>
          <input autoFocus aria-label={`New name for ${c.name}`} className={`${INPUT} w-28`} value={renaming.name}
                 onChange={(e) => setRenaming({ id: c.id, name: e.target.value })}
                 onKeyDown={(e) => { if (e.key === 'Escape') setRenaming(null) }} />
          <button type="submit" className="rounded-md px-2 py-1 text-sky-300 hover:bg-sky-500/10">Rename</button>
        </form>
      ) : (
        <button key={c.id} type="button" disabled={!canEdit}
                onClick={() => setRenaming({ id: c.id, name: c.name })}
                title={canEdit ? `${band(c) || c.name}. Click to rename; rows using it follow.` : band(c)}
                className="rounded-md border border-slate-700 bg-slate-800 px-2 py-0.5 text-slate-200 enabled:hover:border-slate-500 disabled:cursor-default">
          {c.name}{band(c) && <span className="ml-1.5 text-xs text-slate-500">{band(c)}</span>}
        </button>
      ))}
      {canEdit && !open && (
        <button type="button" onClick={() => setOpen(true)}
                className="rounded-md px-2 py-0.5 text-sky-300 hover:bg-sky-500/10">+ Class</button>
      )}
      {canEdit && open && (
        <span className="flex flex-wrap items-center gap-1.5">
          <input aria-label="Class name" className={`${INPUT} w-28`} placeholder="200-450 t" value={name}
                 onChange={(e) => setName(e.target.value)} />
          <input aria-label="From tonnage" className={`${INPUT} w-20`} placeholder="from t" inputMode="numeric"
                 value={min} onChange={(e) => setMin(e.target.value)} />
          <input aria-label="To tonnage" className={`${INPUT} w-20`} placeholder="to t" inputMode="numeric"
                 value={max} onChange={(e) => setMax(e.target.value)} />
          <button type="button" onClick={submit}
                  className="rounded-md bg-sky-600 px-2.5 py-1 text-white hover:bg-sky-500">Add</button>
          <button type="button" onClick={() => setOpen(false)}
                  className="px-2 py-1 text-slate-400 hover:text-slate-200">Cancel</button>
        </span>
      )}
    </div>
  )
}
