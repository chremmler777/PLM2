import { useState } from 'react'
import { toastError } from '../../lib/apiError'
import { btnSm } from '../common/buttonStyles'
import { Pencil } from 'lucide-react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { changesApi } from '../../api/changes'
import { DeadlineChip } from './DeadlineChip'
import DateInput from '../gantt/DateInput'
import { t } from '../../i18n/cmLabels'
import type { ChangeRequest } from '../../types/change'


/** A change that has stopped or finished has no live deadline to move. */
const ENDED = new Set(['rejected', 'closed', 'cancelled'])

// The same editor drives both phases: the quote deadline (required_by_*) up to
// the quote, and the release deadline (release_due_*) after acceptance.
export function DeadlineEditor({ change, kind = 'quote' }:
    { change: ChangeRequest; kind?: 'quote' | 'release' }) {
  const dateField = kind === 'release' ? 'release_due_date' : 'required_by_date'
  const reasonField = kind === 'release' ? 'release_due_reason' : 'required_by_reason'
  const curDate = change[dateField]
  const curReason = change[reasonField]
  // The quote deadline is fixed once the change leaves capture: moving it is a
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
      toast.success(t(kind === 'release' ? 'deadline.savedRelease' : 'deadline.savedQuote'))
      setOpen(false)
    },
    onError: (e: unknown) => toastError(e, 'Could not save the deadline'),
  })
  if (ENDED.has(change.status)) return null
  const what = t(kind === 'release' ? 'deadline.release' : 'deadline.quote')
  return (
    <span className="inline-flex flex-wrap items-center gap-1.5">
      <DeadlineChip date={curDate} state={change.deadline_state} kind={kind} />
      <button type="button"
        title={pushback ? t('deadline.pushbackTitle') : curDate ? `${t('deadline.set')}: ${what}` : undefined}
        aria-label={!pushback && curDate ? `${t('deadline.set')}: ${what}` : undefined}
        data-testid="deadline-edit"
        aria-expanded={open}
        onClick={() => setOpen((o) => {
          // Re-seed from the current change each time the editor opens, so a
          // reopen after an external update doesn't show stale local edits.
          if (!o) {
            setDate(curDate?.slice(0, 10) ?? '')
            // A pushback needs its own justification: the previous one is
            // history, not a prefill to submit again.
            setReason(pushback ? '' : curReason ?? '')
          }
          return !o
        })}
        className="text-xs text-slate-400 hover:text-slate-200 underline decoration-dotted underline-offset-2">
        {pushback ? t('deadline.pushback')
          : curDate ? <Pencil aria-hidden="true" size={12} className="inline" />
          : `+ ${what}`}
      </button>
      {pushback && curReason && !open && (
        <span className="text-xs text-slate-500 truncate max-w-[16rem]" title={curReason}>
          {curReason}
        </span>
      )}
      {open && (
        // Its own block under the chip: a pushback is a small form, and
        // squeezing it into the chip's line made it unreadable.
        <span data-testid="deadline-form"
          className="basis-full mt-1 flex flex-col gap-2 rounded-lg border border-slate-600 bg-slate-900/60 p-2.5">
          {pushback && (
            <span className="text-xs font-medium text-slate-200">{t('deadline.pushbackTitle')}</span>
          )}
          <span className="flex flex-col gap-1">
            <span className="text-[11px] text-slate-400">
              {pushback ? t('deadline.newQuote')
                : kind === 'release' ? t('deadline.newRelease') : t('deadline.quote')}
            </span>
            <DateInput value={date} onChange={setDate}
              aria-label={pushback ? t('deadline.newQuote') : what}
              className="w-36 bg-slate-800 border border-slate-600 rounded px-2 py-1 text-xs text-slate-100" />
          </span>
          {pushback ? (
            <label className="flex flex-col gap-1">
              <span className="text-[11px] text-slate-400">{t('deadline.pushbackWhy')}</span>
              <textarea value={reason} rows={2} data-testid="deadline-reason"
                placeholder={t('deadline.pushbackHint')}
                onChange={(e) => setReason(e.target.value)}
                className="bg-slate-800 border border-slate-600 rounded px-2 py-1 text-xs text-slate-100 w-full" />
            </label>
          ) : (
            <input type="text" value={reason} placeholder={t('deadline.reason')}
              aria-label={t('deadline.reason')}
              data-testid="deadline-reason"
              onChange={(e) => setReason(e.target.value)}
              className="bg-slate-800 border border-slate-600 rounded px-2 py-1 text-xs text-slate-100 w-full" />
          )}
          <span className="flex gap-2">
            <button type="button" data-testid="deadline-save"
              className={btnSm.primary}
              disabled={save.isPending || (pushback && !(date && reason.trim()))}
              onClick={() => save.mutate({
                // End-of-day UTC: picking *today* must not render as overdue.
                [dateField]: date ? `${date}T23:59:59Z` : null,
                [reasonField]: reason.trim() || null,
              })}>
              {pushback ? t('deadline.pushbackSave') : t('deadline.set')}
            </button>
            <button type="button" className="text-xs text-slate-400 hover:text-slate-200 px-1"
              onClick={() => setOpen(false)}>
              {t('common.cancel')}
            </button>
          </span>
        </span>
      )}
    </span>
  )
}
