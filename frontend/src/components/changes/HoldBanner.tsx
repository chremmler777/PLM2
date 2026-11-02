import { useId, useState } from 'react'
import { PauseCircle } from 'lucide-react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { changesApi } from '../../api/changes'
import { apiErrorMessage } from '../../lib/apiError'
import { addDaysIso, formatCalendarDate, todayIso } from '../../lib/format'
import { btnSm } from '../common/buttonStyles'
import { t } from '../../i18n/cmLabels'

/**
 * A change on hold says until when and why (Christoph 2026-11-02):
 * "On hold until 16 Nov 2026: waiting for the customer's drawing". On and
 * after the review date it says what is owed; the lead or Project
 * Management sets a new date with a short reason (on the history).
 */
export default function HoldBanner({ changeId, reviewDate, reason, canMove, now }: {
  changeId: number
  reviewDate?: string | null
  reason?: string | null
  /** The lead, Project Management or an admin (the backend's rule). */
  canMove: boolean
  /** Today, YYYY-MM-DD (tests). */
  now?: string
}) {
  const qc = useQueryClient()
  const dateId = useId()
  const reasonId = useId()
  const today = now ?? todayIso()
  const [open, setOpen] = useState(false)
  const [day, setDay] = useState('')
  const [why, setWhy] = useState('')
  const move = useMutation({
    mutationFn: () => changesApi.moveHoldReview(changeId, day, why.trim()),
    onSuccess: () => {
      toast.success(t('hold.moved'))
      setOpen(false)
      qc.invalidateQueries({ queryKey: ['change', changeId] })
    },
    onError: (e: unknown) => toast.error(apiErrorMessage(e, 'Could not save the review date')),
  })
  const why0 = reason?.trim()
  const head = reviewDate
    ? (why0 ? t('hold.until').replace('{d}', formatCalendarDate(reviewDate)).replace('{x}', why0)
      : t('hold.untilNoReason').replace('{d}', formatCalendarDate(reviewDate)))
    : why0 ?? null
  if (!head) return null
  const min = addDaysIso(today, 1)
  const max = addDaysIso(today, 92)
  const state = reviewDate && reviewDate === today ? 'due' : reviewDate && reviewDate < today ? 'past' : null
  const badDay = !day || day < min || day > max || day === reviewDate
  return (
    <div role="status" data-testid="hold-banner"
      className="mt-3 rounded-lg border border-amber-700/60 bg-amber-950/30 px-4 py-2 text-sm text-amber-100">
      <p className="flex items-start gap-2">
        <PauseCircle aria-hidden="true" size={16} className="mt-0.5 shrink-0 text-amber-300" />
        <span data-testid="hold-line">{head}</span>
        {canMove && reviewDate && !open && (
          <button type="button" data-testid="hold-move" className={`${btnSm.secondary} ml-auto`}
            onClick={() => { setDay(addDaysIso(reviewDate < today ? today : reviewDate, 14)); setWhy(''); setOpen(true) }}>
            {t('hold.move')}
          </button>
        )}
      </p>
      {state && (
        <p data-testid="hold-state" className={`mt-1 text-xs ${state === 'past' ? 'text-red-300' : 'text-amber-200'}`}>
          {t(state === 'past' ? 'hold.past' : 'hold.due')}
        </p>
      )}
      {open && (
        <form className="mt-2 flex flex-wrap items-end gap-2" data-testid="hold-move-form"
          onSubmit={(e) => { e.preventDefault(); if (!badDay && why.trim()) move.mutate() }}>
          <div>
            <label htmlFor={dateId} className="mb-1 block text-xs text-slate-300">{t('hold.moveDate')}</label>
            <input id={dateId} type="date" data-testid="hold-move-date" required value={day} min={min} max={max}
              onChange={(e) => setDay(e.target.value)}
              className="rounded-lg border border-slate-600 bg-slate-900 p-1.5 text-sm text-slate-100" />
          </div>
          <div className="min-w-[14rem] flex-1">
            <label htmlFor={reasonId} className="mb-1 block text-xs text-slate-300">{t('hold.moveReason')}</label>
            <input id={reasonId} data-testid="hold-move-reason" required value={why}
              placeholder={t('hold.moveReasonHint')} onChange={(e) => setWhy(e.target.value)}
              className="w-full rounded-lg border border-slate-600 bg-slate-900 p-1.5 text-sm text-slate-100 placeholder-slate-500" />
          </div>
          <button type="submit" data-testid="hold-move-save" className={btnSm.primary}
            disabled={badDay || !why.trim() || move.isPending}>{t('hold.moveSave')}</button>
          <button type="button" className={btnSm.secondary} onClick={() => setOpen(false)}>Back</button>
        </form>
      )}
    </div>
  )
}
