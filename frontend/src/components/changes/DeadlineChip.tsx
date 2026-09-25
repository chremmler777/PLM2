import { Check, Clock } from 'lucide-react'
import { t } from '../../i18n/cmLabels'
import { daysUntil, formatCalendarDate } from '../../lib/format'
import type { ChangeRequest } from '../../types/change'

const STATE_CLASS: Record<string, string> = {
  on_track: 'bg-sky-500/10 text-sky-300 border-sky-500/30',
  at_risk: 'bg-amber-500/10 text-amber-300 border-amber-500/30',
  overdue: 'bg-red-500/10 text-red-300 border-red-500/30',
}

/** A due date relative to today, the same words in every list: "in 5 d", "today", "2 d overdue". */
export function deadlineText(days: number): string {
  if (days === 0) return t('tasks.dueToday')
  return days > 0 ? t('tasks.dueIn').replace('{n}', String(days))
    : t('tasks.dueOverdue').replace('{n}', String(Math.abs(days)))
}

export function DeadlineChip({ date, state, kind }: {
  date: string | null; state: string | null
  /** Named deadlines read as a sentence ("Release in 114 d"); lists keep the short chip. */
  kind?: 'quote' | 'release'
}) {
  if (!date) return null
  const days = daysUntil(date)
  if (Number.isNaN(days)) return null
  const what = kind === 'release' ? 'Release' : kind === 'quote' ? 'Quote' : null
  const label = what
    ? (days >= 0 ? `${what} in ${days} d` : `${what} ${Math.abs(days)} d overdue`)
    : deadlineText(days)
  return (
    <span data-testid="deadline-chip"
      className={`inline-flex items-center gap-1 whitespace-nowrap rounded border px-2 py-0.5 text-xs tabular-nums ${STATE_CLASS[state ?? 'on_track']}`}
      title={formatCalendarDate(date)}>
      {!what && <Clock aria-hidden="true" size={12} className="shrink-0" />}
      {label}
    </span>
  )
}

// Once the quote is out the door the on-time/late verdict is frozen history —
// it stops counting down and is shown as a fact rather than a live deadline.
export function QuotedFactChip({ change }: { change: ChangeRequest }) {
  if (change.quoted_on_time === null) return null
  const ok = change.quoted_on_time
  return (
    <span data-testid="quoted-fact-chip"
      className={`inline-flex items-center gap-1 rounded border px-2 py-0.5 text-xs ${
        ok ? 'bg-emerald-500/10 text-emerald-300 border-emerald-500/30'
           : 'bg-red-500/10 text-red-300 border-red-500/30'}`}
      title={change.required_by_date ? formatCalendarDate(change.required_by_date) : undefined}>
      {ok && <Check aria-hidden="true" size={12} className="shrink-0" />}
      {ok ? t('deadline.quotedOnTime') : t('deadline.quotedLate')}
    </span>
  )
}
