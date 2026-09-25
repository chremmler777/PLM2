/**
 * The release checklist: what has to be true before a change is live, each
 * point owned by a department. Members of the owner department (and PM, the
 * change lead, admins) tick it done or not applicable; n.a. needs a note.
 */
import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { changeReleaseApi } from '../../../api/changeRelease'
import type { ReleaseCheck, ReleaseCheckStatus } from '../../../types/changeRelease'
import { fmtDate, inputCls, sectionLabel } from '../offer/offerFormat'
import { releaseKey } from './releaseKeys'

const errDetail = (e: unknown): string | undefined =>
  (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail

const CHIP: Record<ReleaseCheckStatus, { label: string; on: string }> = {
  open: { label: 'Open', on: 'bg-slate-700 text-slate-100' },
  done: { label: 'Done', on: 'bg-emerald-700 text-white' },
  na: { label: 'N.a.', on: 'bg-slate-600 text-slate-100' },
}

function CheckRow({ changeId, check, canEdit }: {
  changeId: number; check: ReleaseCheck; canEdit: boolean
}) {
  const qc = useQueryClient()
  const [editing, setEditing] = useState<null | 'done' | 'na'>(null)
  const [note, setNote] = useState('')
  const save = useMutation({
    mutationFn: (body: { status: ReleaseCheckStatus; note?: string }) =>
      changeReleaseApi.setCheck(changeId, check.key, body),
    onSuccess: () => {
      setEditing(null); setNote('')
      qc.invalidateQueries({ queryKey: releaseKey(changeId) })
      qc.invalidateQueries({ queryKey: ['change-my-actions', changeId] })
      qc.invalidateQueries({ queryKey: ['change', changeId] })
    },
    onError: (e: unknown) => toast.error(errDetail(e) ?? 'Could not save the check'),
  })

  const pick = (s: ReleaseCheckStatus) => {
    if (s === 'open') { save.mutate({ status: 'open' }); return }
    setEditing(s); setNote('')
  }

  return (
    <li data-testid={`release-check-${check.key}`}
      className={`rounded-lg border px-3 py-2 ${check.status === 'open' ? 'border-slate-700 bg-slate-900/40' : 'border-slate-800 bg-slate-900/20'}`}>
      <div className="flex flex-wrap items-center gap-3">
        <span className={`h-2 w-2 shrink-0 rounded-full ${check.status === 'done' ? 'bg-emerald-400'
          : check.status === 'na' ? 'bg-slate-500' : 'bg-amber-400'}`} />
        <div className="min-w-0 flex-1">
          <div className={`text-sm ${check.status === 'open' ? 'text-slate-100' : 'text-slate-400'}`}>{check.label}</div>
          {check.hint && <div className="text-[11px] text-sky-300/80">{check.hint}</div>}
          {check.status !== 'open' && (check.by_name || check.note) && (
            <div className="text-[11px] text-slate-500">
              {check.by_name}{check.at ? `, ${fmtDate(check.at)}` : ''}{check.note ? `: ${check.note}` : ''}
            </div>
          )}
        </div>
        {canEdit ? (
          <div role="radiogroup" aria-label={`Status ${check.label}`}
            className="inline-flex rounded-lg border border-slate-700 bg-slate-900 p-0.5 text-xs">
            {(['open', 'done', 'na'] as ReleaseCheckStatus[]).map((s) => (
              <button key={s} type="button" role="radio" aria-checked={check.status === s}
                data-testid={`release-check-${check.key}-${s}`}
                disabled={save.isPending}
                onClick={() => pick(s)}
                className={`rounded-md px-2 py-0.5 ${check.status === s ? CHIP[s].on : 'text-slate-400 hover:text-slate-200'}`}>
                {CHIP[s].label}
              </button>
            ))}
          </div>
        ) : (
          <span className={`rounded-md px-2 py-0.5 text-xs ${CHIP[check.status].on}`}>{CHIP[check.status].label}</span>
        )}
      </div>
      {editing && (
        <div className="mt-2 flex flex-wrap items-center gap-2 pl-5">
          <input autoFocus data-testid={`release-check-${check.key}-note`} value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder={editing === 'na' ? 'Why does this not apply? (required)' : 'Note (optional)'}
            className={`${inputCls} min-w-0 flex-1`} />
          <button type="button" data-testid={`release-check-${check.key}-confirm`}
            disabled={(editing === 'na' && !note.trim()) || save.isPending}
            onClick={() => save.mutate({ status: editing, ...(note.trim() ? { note: note.trim() } : {}) })}
            className="rounded-lg bg-sky-600 px-2.5 py-1 text-xs text-white hover:bg-sky-500 disabled:opacity-50">
            {editing === 'na' ? 'Mark not applicable' : 'Mark done'}
          </button>
          <button type="button" onClick={() => setEditing(null)} className="px-1 text-xs text-slate-400 hover:text-slate-200">
            Cancel
          </button>
        </div>
      )}
    </li>
  )
}

export default function ReleaseChecklist({
  changeId, checks, myDepartmentIds, canManage, editable,
}: {
  changeId: number
  checks: ReleaseCheck[]
  myDepartmentIds: number[]
  /** PM, the change lead, admin: every row. */
  canManage: boolean
  /** Only while the change is in validation. */
  editable: boolean
}) {
  const groups = new Map<string, ReleaseCheck[]>()
  for (const c of checks) {
    const k = c.department_name ?? 'Other'
    groups.set(k, [...(groups.get(k) ?? []), c])
  }
  if (checks.length === 0) {
    return <p className="text-xs text-slate-500">The checklist appears when the change reaches validation.</p>
  }
  return (
    <div className="space-y-4">
      {[...groups.entries()].map(([dept, rows]) => {
        const open = rows.filter((r) => r.status === 'open').length
        return (
          <div key={dept}>
            <div className="mb-1.5 flex items-center gap-2">
              <span className={sectionLabel}>{dept}</span>
              <span className={`text-[11px] ${open ? 'text-amber-300' : 'text-emerald-400'}`}>
                {open ? `${open} open` : '✓ complete'}
              </span>
            </div>
            <ul className="space-y-1.5">
              {rows.map((c) => (
                <CheckRow key={c.key} changeId={changeId} check={c}
                  canEdit={editable && (canManage || (c.department_id != null && myDepartmentIds.includes(c.department_id)))} />
              ))}
            </ul>
          </div>
        )
      })}
    </div>
  )
}
