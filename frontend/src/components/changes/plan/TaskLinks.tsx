/**
 * Links of one task in the task panel (MS Project "Predecessors" and
 * "Successors" tabs): type and lag editable, add and remove. Every edit goes
 * out at once as a ChangeSet (one undo step). Old dependencies are listed
 * read-only.
 */
import { useEffect, useRef, useState } from 'react'
import { tempId } from '../../gantt/engine/notation'
import { key } from '../../gantt/engine/tree'
import { LIMITS, type ChangeSet, type GanttId, type GanttLink, type LinkType } from '../../gantt/engine/types'

interface Props {
  taskId: GanttId
  links: GanttLink[]
  /** Other tasks, in row order. */
  tasks: { id: GanttId; name: string; row?: number; summary?: boolean }[]
  canEdit: boolean
  /** Link types the server accepts here (FS only on older servers). */
  types: LinkType[]
  allowLag: boolean
  /** Is the task itself a summary (no FF/SF into it). */
  summary: boolean
  unit: string
  onChange: (cs: ChangeSet) => void
}

const field = 'rounded border border-slate-600 bg-slate-900 px-1 py-0.5 text-xs text-slate-100 [color-scheme:dark] disabled:opacity-60'
const TYPE_TEXT: Record<LinkType, string> = { FS: 'FS', SS: 'SS', FF: 'FF', SF: 'SF' }

/**
 * Lag field controlled from the model: shows the link's current lag (also
 * after undo or a server refresh), commits on blur or Enter only when the
 * number changed, Escape or an invalid entry restores it.
 */
function LagInput({ label, value, disabled, onCommit }: { label: string; value: number; disabled: boolean; onCommit: (n: number) => void }) {
  const [text, setText] = useState(String(value))
  const [focused, setFocused] = useState(false)
  const sent = useRef<number | null>(null)
  const skipBlur = useRef(false)
  useEffect(() => { sent.current = null; if (!focused) setText(String(value)) }, [value, focused])
  const commit = (raw: string) => {
    const n = Math.round(Number(raw))
    if (raw.trim() === '' || !Number.isFinite(n) || Math.abs(n) > LIMITS.maxLag || n === value) { setText(String(value)); return }
    if (n === sent.current) return
    sent.current = n
    onCommit(n)
  }
  return (
    <input aria-label={label} type="number" className={`${field} w-14`} min={-LIMITS.maxLag} max={LIMITS.maxLag}
      value={text} disabled={disabled}
      onChange={(e) => setText(e.target.value)}
      onFocus={() => setFocused(true)}
      onBlur={(e) => { setFocused(false); if (skipBlur.current) { skipBlur.current = false; return } commit(e.target.value) }}
      onKeyDown={(e) => {
        if (e.key === 'Enter') { e.preventDefault(); commit((e.target as HTMLInputElement).value) }
        if (e.key === 'Escape') {
          e.preventDefault(); e.stopPropagation()
          setText(String(value)); skipBlur.current = true; (e.target as HTMLInputElement).blur()
        }
      }} />
  )
}

export default function TaskLinks(p: Props) {
  const me = key(p.taskId)
  const byKey = new Map(p.tasks.map((t) => [key(t.id), t]))
  const preds = p.links.filter((l) => key(l.to) === me)
  const succs = p.links.filter((l) => key(l.from) === me)
  const [adding, setAdding] = useState<{ dir: 'pred' | 'succ'; other: string; type: LinkType; lag: string } | null>(null)

  /** Types allowed for a link into `toSummary`. */
  const typesInto = (toSummary: boolean) => p.types.filter((t) => !toSummary || (t !== 'FF' && t !== 'SF'))

  const row = (l: GanttLink, dir: 'pred' | 'succ') => {
    const otherKey = key(dir === 'pred' ? l.from : l.to)
    const other = byKey.get(otherKey)
    const intoSummary = dir === 'pred' ? p.summary : !!other?.summary
    const editable = p.canEdit && !l.readOnly
    return (
      <li key={String(l.id)} className="flex items-center gap-1.5" data-testid={`task-link-${key(l.id)}`}>
        <span className="w-6 text-right tabular-nums text-slate-500">{other?.row ?? ''}</span>
        <span className="min-w-0 flex-1 truncate text-slate-200" title={other?.name}>{other?.name ?? otherKey}</span>
        <select aria-label={`Type of the link with ${other?.name ?? otherKey}`} className={field} value={l.type} disabled={!editable}
          onChange={(e) => p.onChange({ label: 'Edit link', updateLinks: [{ id: l.id, patch: { type: e.target.value as LinkType } }] })}>
          {typesInto(intoSummary).concat(typesInto(intoSummary).includes(l.type) ? [] : [l.type]).map((t) => <option key={t} value={t}>{TYPE_TEXT[t]}</option>)}
        </select>
        {p.allowLag && (
          <LagInput label={`Lag of the link with ${other?.name ?? otherKey}`} value={l.lagDays} disabled={!editable}
            onCommit={(n) => p.onChange({ label: 'Edit link', updateLinks: [{ id: l.id, patch: { lagDays: n } }] })} />
        )}
        {l.readOnly ? (
          <span className="text-[10px] text-slate-500" title="Old dependency, re-draw to edit">old</span>
        ) : p.canEdit && (
          <button type="button" aria-label={`Remove the link with ${other?.name ?? otherKey}`} className="rounded px-1 text-red-300 hover:bg-slate-800"
            onClick={() => p.onChange({ label: 'Remove link', removeLinks: [l.id] })}>&#10005;</button>
        )}
      </li>
    )
  }

  const candidates = (dir: 'pred' | 'succ') => p.tasks.filter((t) => key(t.id) !== me
    && !(dir === 'pred' ? preds : succs).some((l) => key(dir === 'pred' ? l.from : l.to) === key(t.id)))

  const add = () => {
    if (!adding || !adding.other) return
    const lag = Math.round(Number(adding.lag) || 0)
    if (Math.abs(lag) > LIMITS.maxLag) return
    const other = byKey.get(adding.other)!
    const from = adding.dir === 'pred' ? other.id : p.taskId
    const to = adding.dir === 'pred' ? p.taskId : other.id
    p.onChange({ label: 'Link tasks', addLinks: [{ id: tempId('link'), from, to, type: adding.type, lagDays: p.allowLag ? lag : 0 }] })
    setAdding(null)
  }

  const section = (dir: 'pred' | 'succ', list: GanttLink[]) => {
    const intoSummary = (otherKey: string) => (dir === 'pred' ? p.summary : !!byKey.get(otherKey)?.summary)
    const a = adding?.dir === dir ? adding : null
    return (
      <div>
        <p className="mb-1 text-[10px] font-medium uppercase tracking-wide text-slate-500">
          {dir === 'pred' ? 'Predecessors' : 'Successors'}
        </p>
        {list.length === 0 && <p className="text-xs text-slate-500">None.</p>}
        <ul className="space-y-1 text-xs" data-testid={`task-links-${dir}`}>{list.map((l) => row(l, dir))}</ul>
        {p.canEdit && (a ? (
          <div className="mt-1.5 flex items-center gap-1.5">
            <select aria-label={dir === 'pred' ? 'New predecessor' : 'New successor'} className={`${field} min-w-0 flex-1`} value={a.other}
              onChange={(e) => {
                const other = e.target.value
                const types = typesInto(intoSummary(other))
                setAdding({ ...a, other, type: types.includes(a.type) ? a.type : types[0] })
              }}>
              <option value="">Choose a task</option>
              {candidates(dir).map((t) => <option key={String(t.id)} value={key(t.id)}>{t.row ? `${t.row} ` : ''}{t.name}</option>)}
            </select>
            <select aria-label="New link type" className={field} value={a.type} onChange={(e) => setAdding({ ...a, type: e.target.value as LinkType })}>
              {typesInto(a.other ? intoSummary(a.other) : false).map((t) => <option key={t} value={t}>{TYPE_TEXT[t]}</option>)}
            </select>
            {p.allowLag && (
              <input aria-label="New link lag" type="number" className={`${field} w-14`} value={a.lag} title={`Lag in ${p.unit}`}
                onChange={(e) => setAdding({ ...a, lag: e.target.value })} />
            )}
            <button type="button" className="rounded bg-sky-600 px-2 py-0.5 text-white disabled:opacity-40" disabled={!a.other} onClick={add}>Add</button>
            <button type="button" className="rounded px-1 text-slate-400 hover:bg-slate-800" onClick={() => setAdding(null)} aria-label="Cancel">&#10005;</button>
          </div>
        ) : (
          <button type="button" className="mt-1 text-xs text-sky-300 hover:text-sky-200" data-testid={`task-link-add-${dir}`}
            onClick={() => setAdding({ dir, other: '', type: 'FS', lag: '0' })}>+ Add {dir === 'pred' ? 'predecessor' : 'successor'}</button>
        ))}
      </div>
    )
  }

  return (
    <div className="space-y-3 rounded-md border border-slate-700 p-2" data-testid="task-links">
      {section('pred', preds)}
      {section('succ', succs)}
    </div>
  )
}
