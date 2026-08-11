import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { changesApi } from '../../api/changes'
import { useAuth } from '../../contexts/AuthContext'
import { t } from '../../i18n/cmLabels'
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
export default function ConcernStrip({ changeId, editable }: {
  changeId: number; editable: boolean
}) {
  const qc = useQueryClient()
  const { userId, isAdmin } = useAuth()
  const [kind, setKind] = useState<ConcernKind>('needs_info')
  const [note, setNote] = useState('')
  const [adding, setAdding] = useState(false)

  const { data: concerns = [] } = useQuery({
    queryKey: ['change', changeId, 'concerns'],
    queryFn: () => changesApi.listConcerns(changeId),
  })
  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ['change', changeId, 'concerns'] })
    qc.invalidateQueries({ queryKey: ['change', changeId] })
  }

  const raise = useMutation({
    mutationFn: () => changesApi.raiseConcern(changeId, kind, note.trim()),
    onSuccess: () => { setNote(''); setAdding(false); invalidate() },
    onError: (e: unknown) => toast.error(errDetail(e) ?? 'Could not raise the flag'),
  })
  const withdraw = useMutation({
    mutationFn: (concernId: number) => changesApi.withdrawConcern(changeId, concernId),
    onSuccess: invalidate,
    onError: (e: unknown) => toast.error(errDetail(e) ?? 'Could not withdraw'),
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
            onClick={() => setAdding(true)}>+ {t('concern.raise')}</button>
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
              <span className={c.is_open ? '' : 'line-through'}>{c.note}</span>
              <span className="block text-xs opacity-70">
                {c.raised_by_name ?? `#${c.raised_by}`}
                {!c.is_open && ` — ${c.withdrawn_at ? t('concern.withdrawn') : t('concern.answered')}`}
              </span>
            </span>
            {/* Only its author may drop it — not the lead, not an admin. */}
            {c.is_open && editable && c.raised_by === userId && (
              <button className="text-xs underline decoration-dotted flex-shrink-0"
                disabled={withdraw.isPending}
                onClick={() => withdraw.mutate(c.id)}>{t('concern.withdraw')}</button>
            )}
            {c.is_open && isAdmin && c.raised_by !== userId && (
              <span className="text-xs opacity-60 flex-shrink-0" title={t('concern.authorOnly')}>
                {t('concern.theirs')}
              </span>
            )}
          </li>
        ))}
      </ul>

      {adding && (
        <div className="flex gap-2 items-start flex-wrap">
          <select value={kind} onChange={(e) => setKind(e.target.value as ConcernKind)}
            aria-label={t('concern.kind')}
            className="bg-slate-900 border border-slate-600 rounded px-2 py-1 text-xs text-slate-100">
            <option value="needs_info">{t('concern.wantsInfo')}</option>
            <option value="reject_proposal">{t('concern.wouldReject')}</option>
          </select>
          <input value={note} onChange={(e) => setNote(e.target.value)}
            placeholder={t('concern.notePlaceholder')} aria-label={t('concern.note')}
            className="flex-1 min-w-[12rem] bg-slate-900 border border-slate-600 rounded px-2 py-1 text-xs text-slate-100" />
          <button className="bg-sky-600 hover:bg-sky-500 text-white px-2.5 py-1 rounded text-xs disabled:opacity-50"
            disabled={!note.trim() || raise.isPending}
            onClick={() => raise.mutate()}>{t('concern.raise')}</button>
          <button className="text-xs text-slate-400 hover:text-slate-200 px-1"
            onClick={() => { setAdding(false); setNote('') }}>{t('common.cancel')}</button>
        </div>
      )}
    </div>
  )
}
