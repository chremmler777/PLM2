import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { changesApi } from '../../api/changes'
import { DeadlineChip } from './DeadlineChip'
import { t } from '../../i18n/cmLabels'
import type { ChangeRequest } from '../../types/change'

const errDetail = (e: unknown): string | undefined =>
  (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail

// The same editor drives both phases: the quote deadline (required_by_*) up to
// the quote, and the release deadline (release_due_*) after acceptance.
export function DeadlineEditor({ change, kind = 'quote' }:
    { change: ChangeRequest; kind?: 'quote' | 'release' }) {
  const dateField = kind === 'release' ? 'release_due_date' : 'required_by_date'
  const reasonField = kind === 'release' ? 'release_due_reason' : 'required_by_reason'
  const curDate = change[dateField]
  const curReason = change[reasonField]
  // The quote-by date is fixed once the change leaves capture: moving it is a
  // pushback, and the backend rejects the PATCH unless a reason rides along.
  const pushback = kind === 'quote' && change.status !== 'captured'
  const qc = useQueryClient()
  const [open, setOpen] = useState(false)
  const [date, setDate] = useState(curDate?.slice(0, 10) ?? '')
  const [reason, setReason] = useState(curReason ?? '')
  const save = useMutation({
    mutationFn: (body: Record<string, string | null>) =>
      changesApi.update(change.id, body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['change', change.id] })
      toast.success('Deadline saved')
      setOpen(false)
    },
    onError: (e: unknown) => toast.error(errDetail(e) ?? 'Failed to save deadline'),
  })
  return (
    <span className="inline-flex items-center gap-1.5">
      <DeadlineChip date={curDate} state={change.deadline_state} />
      <button type="button" title={pushback ? t('deadline.pushback') : t('deadline.set')}
        data-testid="deadline-edit"
        onClick={() => setOpen((o) => {
          // Re-seed from the current change each time the editor opens, so a
          // reopen after an external update doesn't show stale local edits.
          if (!o) {
            setDate(curDate?.slice(0, 10) ?? '')
            // A pushback needs its own justification — the previous one is
            // history, not a prefill to submit again.
            setReason(pushback ? '' : curReason ?? '')
          }
          return !o
        })}
        className="text-xs text-slate-400 hover:text-slate-200 underline decoration-dotted underline-offset-2">
        {pushback ? t('deadline.pushback')
          : curDate ? '✎'
          : `+ ${t(kind === 'release' ? 'deadline.release' : 'deadline.quote')}`}
      </button>
      {pushback && curReason && !open && (
        <span className="text-xs text-slate-500 truncate max-w-[16rem]" title={curReason}>
          {curReason}
        </span>
      )}
      {open && (
        <span className="flex flex-wrap items-center gap-2 ml-1">
          <input type="date" value={date} onChange={(e) => setDate(e.target.value)}
            className="bg-slate-800 border border-slate-600 rounded px-2 py-1 text-xs text-slate-100" />
          {pushback ? (
            <textarea value={reason} rows={2} data-testid="deadline-reason"
              placeholder={t('deadline.pushbackHint')}
              onChange={(e) => setReason(e.target.value)}
              className="bg-slate-800 border border-slate-600 rounded px-2 py-1 text-xs text-slate-100 w-64" />
          ) : (
            <input type="text" value={reason} placeholder={t('deadline.reason')}
              data-testid="deadline-reason"
              onChange={(e) => setReason(e.target.value)}
              className="bg-slate-800 border border-slate-600 rounded px-2 py-1 text-xs text-slate-100 w-40" />
          )}
          <button data-testid="deadline-save"
            className="bg-sky-600 hover:bg-sky-500 text-white px-2.5 py-1 rounded text-xs disabled:opacity-50"
            disabled={save.isPending || (pushback && !(date && reason.trim()))}
            onClick={() => save.mutate({
              // End-of-day UTC: picking *today* must not render as overdue.
              [dateField]: date ? `${date}T23:59:59Z` : null,
              [reasonField]: reason.trim() || null,
            })}>
            {t('deadline.set')}
          </button>
        </span>
      )}
    </span>
  )
}
