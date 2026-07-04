import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { changesApi } from '../../api/changes'
import { DeadlineChip } from './DeadlineChip'
import { t } from '../../i18n/cmLabels'
import type { ChangeRequest } from '../../types/change'

const errDetail = (e: unknown): string | undefined =>
  (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail

export function DeadlineEditor({ change }: { change: ChangeRequest }) {
  const qc = useQueryClient()
  const [open, setOpen] = useState(false)
  const [date, setDate] = useState(change.required_by_date?.slice(0, 10) ?? '')
  const [reason, setReason] = useState(change.required_by_reason ?? '')
  const save = useMutation({
    mutationFn: (body: { required_by_date: string | null; required_by_reason: string | null }) =>
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
      <DeadlineChip date={change.required_by_date} state={change.deadline_state} />
      <button type="button" title={t('deadline.set')} data-testid="deadline-edit"
        onClick={() => setOpen((o) => !o)}
        className="text-xs text-slate-400 hover:text-slate-200 underline decoration-dotted underline-offset-2">
        {change.required_by_date ? '✎' : `+ ${t('deadline.title')}`}
      </button>
      {open && (
        <span className="flex flex-wrap items-center gap-2 ml-1">
          <input type="date" value={date} onChange={(e) => setDate(e.target.value)}
            className="bg-slate-800 border border-slate-600 rounded px-2 py-1 text-xs text-slate-100" />
          <input type="text" value={reason} placeholder={t('deadline.reason')}
            onChange={(e) => setReason(e.target.value)}
            className="bg-slate-800 border border-slate-600 rounded px-2 py-1 text-xs text-slate-100 w-40" />
          <button className="bg-sky-600 hover:bg-sky-500 text-white px-2.5 py-1 rounded text-xs disabled:opacity-50"
            disabled={save.isPending}
            onClick={() => save.mutate({
              // End-of-day UTC: picking *today* must not render as overdue.
              required_by_date: date ? `${date}T23:59:59Z` : null,
              required_by_reason: reason || null,
            })}>
            {t('deadline.set')}
          </button>
        </span>
      )}
    </span>
  )
}
