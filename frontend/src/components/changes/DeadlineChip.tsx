import { t } from '../../i18n/cmLabels'
import { daysUntil, formatDate } from '../../lib/format'
import type { ChangeRequest } from '../../types/change'

const STATE_CLASS: Record<string, string> = {
  on_track: 'bg-sky-500/10 text-sky-300 border-sky-500/30',
  at_risk: 'bg-amber-500/10 text-amber-300 border-amber-500/30',
  overdue: 'bg-red-500/10 text-red-300 border-red-500/30',
}

export function DeadlineChip({ date, state }: { date: string | null; state: string | null }) {
  if (!date) return null
  const days = daysUntil(date)
  if (Number.isNaN(days)) return null
  const label = days >= 0 ? `${days}d` : `${Math.abs(days)}d over`
  return (
    <span data-testid="deadline-chip"
      className={`inline-flex items-center gap-1 rounded border px-2 py-0.5 text-xs ${STATE_CLASS[state ?? 'on_track']}`}
      title={formatDate(date)}>
      ⏱ {label}
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
      title={change.required_by_date ? formatDate(change.required_by_date) : undefined}>
      {ok ? `✓ ${t('deadline.quotedOnTime')}` : t('deadline.quotedLate')}
    </span>
  )
}
