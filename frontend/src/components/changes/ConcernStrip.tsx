import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { changesApi } from '../../api/changes'
import { useAuth } from '../../contexts/AuthContext'
import { t } from '../../i18n/cmLabels'
import { preferredDepartmentId } from '../../lib/departments'
import type { ChangeConcern, ConcernKind } from '../../types/change'

const errDetail = (e: unknown): string | undefined =>
  (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail

const KIND_STYLE: Record<ConcernKind, string> = {
  reject_proposal: 'bg-red-900/60 text-red-200 border-red-800',
  needs_info: 'bg-amber-900/50 text-amber-200 border-amber-800',
}

/**
 * Concerns let the team work the decision in parallel: anyone can flag that
 * they'd reject the change or that something is missing, without waiting for
 * the meeting. Open flags block 'proceed', so the meeting cannot quietly run
 * over an objection — it has to be withdrawn by its author, or answered by a
 * reject / needs-info decision, which closes it.
 *
 * Deliberately no "clear all": only the person who raised a flag may drop it.
 */
export default function ConcernStrip({
  changeId, editable, scoped = false, departments = [], myDepartmentIds = [],
}: {
  changeId: number
  editable: boolean
  /** Assessment phase: every flag belongs to a department, and dropping one
   *  needs a written resolution. */
  scoped?: boolean
  departments?: { id: number; name: string; is_active?: boolean }[]
  myDepartmentIds?: number[]
}) {
  const qc = useQueryClient()
  const { userId, isAdmin } = useAuth()
  const [kind, setKind] = useState<ConcernKind>('needs_info')
  const [note, setNote] = useState('')
  const [adding, setAdding] = useState(false)
  // Which concern is being withdrawn, and the note explaining how it was met.
  const [withdrawing, setWithdrawing] = useState<number | null>(null)
  const [resolution, setResolution] = useState('')
  // A refused flag must say why in place: a toast is missed, and the typed note
  // has to survive so the user can fix the problem and send it again.
  const [failure, setFailure] = useState<string | null>(null)

  // In assessment you flag for your own department (admins for any). In scoping
  // the department is mere attribution — anyone may say "this concerns Packaging"
  // — and "Team" (no department) is the default.
  const selectable = departments.filter((d) => d.is_active !== false)
  const options = !scoped ? selectable
    : isAdmin ? selectable
    : selectable.filter((d) => myDepartmentIds.includes(d.id))
  const [deptId, setDeptId] = useState<number | undefined>(undefined)
  // Scoping starts on "Team". Assessment starts on the master department when
  // the user holds it, and otherwise on nothing at all — they pick.
  const effectiveDept = deptId ?? (scoped
    ? preferredDepartmentId(myDepartmentIds, options)
    : undefined)
  const deptName = (id?: number | null) =>
    id == null ? null : departments.find((d) => d.id === id)?.name ?? `#${id}`

  const { data: concerns = [] } = useQuery({
    queryKey: ['change', changeId, 'concerns'],
    queryFn: () => changesApi.listConcerns(changeId),
  })
  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ['change', changeId, 'concerns'] })
    qc.invalidateQueries({ queryKey: ['change', changeId] })
  }

  const raise = useMutation({
    mutationFn: () => changesApi.raiseConcern(changeId, kind, note.trim(), effectiveDept),
    onSuccess: () => { setNote(''); setAdding(false); setFailure(null); invalidate() },
    onError: (e: unknown) => {
      const detail = errDetail(e) ?? 'Could not raise the flag'
      setFailure(detail)
      toast.error(detail)
    },
  })
  const withdraw = useMutation({
    mutationFn: (vars: { concernId: number; note: string }) =>
      changesApi.withdrawConcern(changeId, vars.concernId, vars.note.trim() || undefined),
    onSuccess: () => { setWithdrawing(null); setResolution(''); setFailure(null); invalidate() },
    onError: (e: unknown) => {
      const detail = errDetail(e) ?? 'Could not withdraw'
      setFailure(detail)
      toast.error(detail)
    },
  })

  const open = concerns.filter((c: ChangeConcern) => c.is_open)
  const settled = concerns.filter((c: ChangeConcern) => !c.is_open)

  return (
    <div className={`rounded-lg border p-3 space-y-2 ${
      open.length > 0 ? 'border-amber-700/60 bg-amber-950/20' : 'border-slate-700 bg-slate-800'}`}>
      <div className="flex items-center gap-2 flex-wrap">
        <span className="font-medium text-slate-100">{t('concern.title')}</span>
        {open.length > 0 && (
          <span className="text-xs px-2 py-0.5 rounded-full bg-amber-900 text-amber-100">
            {t('concern.blocking').replace('{n}', String(open.length))}
          </span>
        )}
        {editable && !adding && (
          <button className="ml-auto text-xs text-sky-300 hover:text-sky-200"
            onClick={() => { setFailure(null); setAdding(true) }}>+ {t('concern.raise')}</button>
        )}
      </div>

      {open.length === 0 && settled.length === 0 && (
        <p className="text-xs text-slate-500">{t('concern.none')}</p>
      )}

      <ul className="space-y-1">
        {[...open, ...settled].map((c: ChangeConcern) => (
          <li key={c.id}
            className={`flex items-start gap-2 text-sm rounded border px-2 py-1.5 ${
              c.is_open ? KIND_STYLE[c.kind] : 'border-slate-700 bg-slate-900/40 text-slate-500'}`}>
            <span className="text-xs font-semibold flex-shrink-0 mt-0.5">
              {c.kind === 'reject_proposal' ? t('concern.wouldReject') : t('concern.wantsInfo')}
            </span>
            <span className="min-w-0 flex-1">
              {c.department_id != null && (
                <span className="mr-1.5 rounded bg-slate-800/80 px-1 py-0 text-[10px] leading-tight align-middle">
                  {deptName(c.department_id)}
                </span>
              )}
              <span className={c.is_open ? '' : 'line-through'}>{c.note}</span>
              <span className="block text-xs opacity-70">
                {c.raised_by_name ?? `#${c.raised_by}`}
                {!c.is_open && ` — ${c.withdrawn_at ? t('concern.withdrawn') : t('concern.answered')}`}
              </span>
              {!c.is_open && c.resolution_note && (
                <span className="block text-xs opacity-70">
                  {t('concern.resolved')}: {c.resolution_note}
                </span>
              )}
              {withdrawing === c.id && (
                <span className="mt-1 flex flex-wrap items-center gap-2">
                  <input value={resolution} onChange={(e) => setResolution(e.target.value)}
                    data-testid="concern-withdraw-note"
                    placeholder={t('concern.resolution')} aria-label={t('concern.resolution')}
                    className="flex-1 min-w-[12rem] bg-slate-900 border border-slate-600 rounded px-2 py-1 text-xs text-slate-100" />
                  <button data-testid="concern-withdraw-confirm"
                    className="bg-sky-600 hover:bg-sky-500 text-white px-2.5 py-1 rounded text-xs disabled:opacity-50"
                    disabled={withdraw.isPending
                      || (c.department_id != null && !resolution.trim())}
                    onClick={() => withdraw.mutate({ concernId: c.id, note: resolution })}>
                    {t('concern.withdraw')}
                  </button>
                  <button className="text-xs text-slate-400 hover:text-slate-200 px-1"
                    onClick={() => { setWithdrawing(null); setResolution('') }}>
                    {t('common.cancel')}
                  </button>
                </span>
              )}
            </span>
            {/* Only its author may drop it — not the lead, not an admin. */}
            {c.is_open && editable && c.raised_by === userId && withdrawing !== c.id && (
              <button className="text-xs underline decoration-dotted flex-shrink-0"
                disabled={withdraw.isPending}
                onClick={() => { setWithdrawing(c.id); setResolution('') }}>
                {t('concern.withdraw')}
              </button>
            )}
            {c.is_open && isAdmin && c.raised_by !== userId && (
              <span className="text-xs opacity-60 flex-shrink-0" title={t('concern.authorOnly')}>
                {t('concern.theirs')}
              </span>
            )}
          </li>
        ))}
      </ul>

      {failure && (
        <p role="alert" data-testid="concern-error"
          className="rounded border border-red-800/60 bg-red-950/40 px-2 py-1 text-xs text-red-200">
          {failure}
        </p>
      )}

      {adding && (
        <div className="flex gap-2 items-start flex-wrap">
          <select value={kind} onChange={(e) => setKind(e.target.value as ConcernKind)}
            aria-label={t('concern.kind')}
            className="bg-slate-900 border border-slate-600 rounded px-2 py-1 text-xs text-slate-100">
            <option value="needs_info">{t('concern.wantsInfo')}</option>
            <option value="reject_proposal">{t('concern.wouldReject')}</option>
          </select>
          {(scoped || options.length > 0) && (
            <select value={effectiveDept ?? ''} aria-label={t('concern.department')}
              onChange={(e) => setDeptId(e.target.value ? Number(e.target.value) : undefined)}
              className="bg-slate-900 border border-slate-600 rounded px-2 py-1 text-xs text-slate-100">
              {scoped
                ? effectiveDept === undefined
                  && <option value="">{t('concern.pickDepartment')}</option>
                : <option value="">{t('concern.team')}</option>}
              {options.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
            </select>
          )}
          <input value={note} onChange={(e) => setNote(e.target.value)}
            placeholder={t('concern.notePlaceholder')} aria-label={t('concern.note')}
            className="flex-1 min-w-[12rem] bg-slate-900 border border-slate-600 rounded px-2 py-1 text-xs text-slate-100" />
          <button className="bg-sky-600 hover:bg-sky-500 text-white px-2.5 py-1 rounded text-xs disabled:opacity-50"
            disabled={!note.trim() || raise.isPending || (scoped && effectiveDept === undefined)}
            onClick={() => raise.mutate()}>{t('concern.raise')}</button>
          <button className="text-xs text-slate-400 hover:text-slate-200 px-1"
            onClick={() => { setAdding(false); setNote(''); setFailure(null) }}>
            {t('common.cancel')}
          </button>
        </div>
      )}
    </div>
  )
}
