/**
 * R37 polish: the close dialog's last look at what the change cost and what
 * it leaves behind. Hours booked against the estimate (and who has not
 * booked), the Assumed answers nobody confirmed yet, the lessons, and the
 * closer's own hours prefilled with what is left of their estimate, so the
 * number is booked in the same breath (skipped stays "not booked").
 * Info only: nothing here holds the close (the guards are the server's).
 */
import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { hoursApi, hoursKey, type HoursMine } from '../../api/hours'
import { changesApi } from '../../api/changes'
import { changeReleaseApi } from '../../api/changeRelease'
import { releaseKey } from './release/releaseKeys'
import type { ChangeConcern } from '../../types/change'
import { formatDayMonth, readNumberInput, todayIso } from '../../lib/format'
import { toastError } from '../../lib/apiError'
import { btnSm } from '../common/buttonStyles'
import { bookBlocked } from './hours/BookHoursDialog'
import { t } from '../../i18n/cmLabels'

const h = (n?: number | null) => `${Math.round((n ?? 0) * 100) / 100} h`

/** An Assumed answer nobody has confirmed yet (the backend's confirm_open). */
export const openAssumption = (c: ChangeConcern) => c.answer_kind === 'assumed' && !c.confirmed_at

function MyHours({ changeId, row }: { changeId: number; row: HoursMine }) {
  const qc = useQueryClient()
  const prefill = row.prefill_hours ?? null
  const [hours, setHours] = useState(prefill != null ? String(prefill) : '')
  useEffect(() => { setHours(prefill != null ? String(prefill) : '') }, [prefill])
  const book = useMutation({
    mutationFn: (n: number) => hoursApi.book(changeId, {
      department_id: row.department_id, hours: n, work_date: todayIso(),
      // a confirmed estimate stays 'estimate' only while the number is the prefill
      source: prefill != null && n === prefill ? 'estimate' : 'typed',
    }),
    onSuccess: (data) => qc.setQueryData(hoursKey(changeId), data),
    onError: (e: unknown) => toastError(e, t('hours.error')),
  })
  const blocked = bookBlocked(row.department_id, hours, todayIso())
  const n = readNumberInput(hours).value
  return (
    <li data-testid={`close-my-hours-${row.department_id}`} className="flex flex-wrap items-center gap-2">
      <span className="min-w-0 flex-1 truncate">
        {row.department_name}{row.source_label ? ` (${row.source_label})` : ''}
      </span>
      <input type="text" inputMode="decimal" aria-label={`${t('hours.hours')} ${row.department_name ?? ''}`}
        data-testid={`close-my-hours-input-${row.department_id}`} value={hours}
        onChange={(e) => setHours(e.target.value)}
        className="w-16 rounded border border-slate-600 bg-slate-900 px-1.5 py-0.5 text-right text-xs tabular-nums text-slate-100" />
      <button type="button" data-testid={`close-my-hours-book-${row.department_id}`}
        className={btnSm.secondary} disabled={!!blocked || book.isPending}
        title={blocked ?? undefined}
        onClick={() => { if (!blocked && n != null) book.mutate(n) }}>
        {t('hours.book')}
      </button>
    </li>
  )
}

export default function CloseSummary({ changeId }: { changeId: number }) {
  const { data: hours } = useQuery({ queryKey: hoursKey(changeId), queryFn: () => hoursApi.get(changeId) })
  const { data: concerns = [] } = useQuery({
    queryKey: ['change', changeId, 'concerns'],
    queryFn: () => changesApi.listConcerns(changeId),
  })
  const { data: release } = useQuery({
    queryKey: releaseKey(changeId),
    queryFn: () => changeReleaseApi.get(changeId),
  })
  const notBooked = (hours?.departments ?? []).filter((d) => d.not_booked)
  const mine = (hours?.mine ?? []).filter((m) => (m.prefill_hours ?? 0) > 0)
  const assumptions = (concerns as ChangeConcern[]).filter(openAssumption)
  const lessons = release?.lessons
  return (
    <div data-testid="close-summary" className="mt-3 space-y-2 rounded-lg border border-slate-700 bg-slate-800/40 p-3 text-sm text-slate-300">
      {hours && (
        <div>
          <p data-testid="close-hours" className="font-medium text-slate-100">
            {t('close.hours').replace('{b}', h(hours.total_booked)).replace('{e}', h(hours.total_estimate))}
          </p>
          {notBooked.length > 0 && (
            <p data-testid="close-not-booked" className="text-xs text-amber-200">
              {t('close.notBooked').replace('{x}', notBooked
                .map((d) => `${d.department_name} (${h(d.estimate_hours)})`).join(', '))}
            </p>
          )}
          {hours.window_open && mine.length > 0 && (
            <div className="mt-1">
              <p className="text-xs text-slate-400">{t('close.myHours')}</p>
              <ul className="space-y-1 text-xs">
                {mine.map((m) => <MyHours key={m.department_id} changeId={changeId} row={m} />)}
              </ul>
            </div>
          )}
        </div>
      )}
      <div data-testid="close-assumptions">
        {assumptions.length === 0 ? (
          <p className="text-xs text-slate-400">{t('close.noAssumptions')}</p>
        ) : (
          <>
            <p className="text-xs font-medium text-amber-200">
              {t('close.assumptions').replace('{n}', String(assumptions.length))}
            </p>
            <ul className="list-disc space-y-0.5 pl-5 text-xs text-amber-100">
              {assumptions.map((c) => (
                <li key={c.id} data-testid={`close-assumption-${c.id}`}>
                  {[`${c.assumed_value ?? ''} ${c.assumed_unit ?? ''}`.trim(), c.note].filter(Boolean).join(': ')}
                  {c.confirm_by_name ? `, ${t('close.confirmBy').replace('{x}', c.confirm_by_name)
                    + (c.confirm_due ? ` ${formatDayMonth(c.confirm_due)}` : '')}` : ''}
                </li>
              ))}
            </ul>
          </>
        )}
      </div>
      {lessons && (
        <p data-testid="close-lessons" className="text-xs">
          {lessons.items.length > 0
            ? t('close.lessons').replace('{n}', String(lessons.items.length))
              .replace('{x}', lessons.items.slice(0, 3).map((l) => l.title).join('; '))
            : lessons.none_reason
              ? t('close.lessonsNone').replace('{x}', lessons.none_reason)
              : t('close.lessonsOpen')}
        </p>
      )}
    </div>
  )
}
