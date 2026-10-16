/**
 * ECR-solid C15: hours on this change, booked against the estimate, per
 * department ("not booked" where a department has an estimate and no
 * booking, never 0), the bookings, and the Book hours button.
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { hoursApi, hoursKey, requestBookHours } from '../../../api/hours'
import { formatCalendarDate } from '../../../lib/format'
import { toastError } from '../../../lib/apiError'
import { btnSm } from '../../common/buttonStyles'
import { t } from '../../../i18n/cmLabels'

const h = (n?: number | null) => (n == null ? '-' : `${Math.round(n * 100) / 100} h`)

export default function HoursCard({ changeId, canBook }: { changeId: number; canBook: boolean }) {
  const qc = useQueryClient()
  const { data: state } = useQuery({ queryKey: hoursKey(changeId), queryFn: () => hoursApi.get(changeId) })
  const remove = useMutation({
    mutationFn: (id: number) => hoursApi.remove(changeId, id),
    onSuccess: (data) => qc.setQueryData(hoursKey(changeId), data),
    onError: (e: unknown) => toastError(e, t('hours.error')),
  })
  if (!state || !Array.isArray(state.departments)) return null
  const open = state.window_open
  return (
    <section data-testid="hours-card" className="space-y-2 rounded-xl border border-slate-700 bg-slate-800/60 px-4 py-3">
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="text-sm font-semibold text-slate-100">{t('hours.cardTitle')}</h3>
        <span data-testid="hours-total" className="text-xs text-slate-400">
          {t('hours.total').replace('{b}', h(state.total_booked)).replace('{e}', h(state.total_estimate))}
        </span>
        {canBook && open && (
          <button type="button" data-testid="hours-book" onClick={() => requestBookHours()}
            className={`ml-auto ${btnSm.secondary}`}>{t('hours.title')}</button>
        )}
      </div>
      {state.departments.length > 0 && (
        <ul className="grid gap-1 sm:grid-cols-2">
          {state.departments.map((d) => (
            <li key={d.department_id} data-testid={`hours-dept-${d.department_id}`}
              className="flex items-center gap-2 text-xs text-slate-300">
              <span className="min-w-0 flex-1 truncate">{d.department_name}</span>
              <span className="tabular-nums">{t('hours.bookedOf').replace('{b}', h(d.booked_hours)).replace('{e}', h(d.estimate_hours))}</span>
              {d.not_booked && (
                <span data-testid={`hours-not-booked-${d.department_id}`}
                  className="rounded border border-amber-800 px-1 text-[10px] text-amber-300">{t('hours.notBooked')}</span>
              )}
            </li>
          ))}
        </ul>
      )}
      {(state.bookings ?? []).length > 0 && (
        <ul className="space-y-0.5 border-t border-slate-700 pt-1.5">
          {state.bookings.slice(0, 12).map((b) => (
            <li key={b.id} data-testid={`hours-booking-${b.id}`} className="flex flex-wrap items-baseline gap-2 text-[11px] text-slate-300">
              <span className="tabular-nums text-slate-100">{h(b.hours)}</span>
              <span>{b.department_name}{b.activity === 'coordination' ? `, ${t('hours.coordinationShort')}` : ''}</span>
              <span className="text-slate-400">{formatCalendarDate(b.work_date)}</span>
              {b.booked_for && <span className="text-slate-400">{t('hours.forName').replace('{n}', b.booked_for)}</span>}
              {b.source === 'estimate' && <span className="text-sky-300">{t('hours.confirmedEstimate')}</span>}
              <span className="text-slate-500">{b.booked_by_name}</span>
              {b.can_delete && open && (
                <button type="button" data-testid={`hours-delete-${b.id}`} disabled={remove.isPending}
                  onClick={() => remove.mutate(b.id)}
                  className="text-slate-400 underline decoration-dotted hover:text-red-300">{t('hours.delete')}</button>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
