const STATE_CLASS: Record<string, string> = {
  on_track: 'bg-sky-500/10 text-sky-300 border-sky-500/30',
  at_risk: 'bg-amber-500/10 text-amber-300 border-amber-500/30',
  overdue: 'bg-red-500/10 text-red-300 border-red-500/30',
}

export function DeadlineChip({ date, state }: { date: string | null; state: string | null }) {
  if (!date) return null
  const days = Math.ceil((new Date(date).getTime() - Date.now()) / 864e5)
  const label = days >= 0 ? `${days}d` : `${Math.abs(days)}d over`
  return (
    <span data-testid="deadline-chip"
      className={`inline-flex items-center gap-1 rounded border px-2 py-0.5 text-xs ${STATE_CLASS[state ?? 'on_track']}`}
      title={new Date(date).toLocaleDateString()}>
      ⏱ {label}
    </span>
  )
}
