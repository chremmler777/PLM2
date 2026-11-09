/**
 * Christoph 2026-11-08: "a correction possibility if time was booked: a popup
 * table to delete or change the efforts". The department's bookings on this
 * change: date, person, hours, phase, note; inline edit (hours, day worked,
 * note) and delete with an inline red confirm row. Who may: the booker, the
 * department (members, manager) or an admin (the backend's can_edit). After
 * a correction the costing section, totals and the standing effort rows
 * refetch (invalidateCosting).
 */
import { Fragment, useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import Dialog from '../../common/Dialog'
import Button from '../../common/Button'
import DateInput from '../../gantt/DateInput'
import { btnSm } from '../../common/buttonStyles'
import { hoursApi, hoursKey, requestBookHours, type HoursBooking, type HoursPatch } from '../../../api/hours'
import { formatCalendarDate, readNumberInput, todayIso } from '../../../lib/format'
import { toastError } from '../../../lib/apiError'
import { invalidateCosting } from '../../../lib/invalidateCosting'
import { STATUS_LABELS } from '../../../lib/changeStatus'
import { inputCls } from '../offer/offerFormat'
import { t } from '../../../i18n/cmLabels'

const fmtH = (n?: number | null) => (n == null ? '-' : `${Math.round(n * 100) / 100} h`)

export function phaseLabel(b: Pick<HoursBooking, 'phase' | 'activity'>): string {
  const p = b.phase ?? ''
  const base = p === 'assessment' || p === 'costing' ? t(`hours.phase.${p}`)
    : (STATUS_LABELS as Record<string, string>)[p] ?? (p ? p.replace(/_/g, ' ') : '-')
  return b.activity === 'coordination' ? `${base}, ${t('hours.coordinationShort')}` : base
}

const minusDays = (iso: string, n: number) => {
  const d = new Date(`${iso}T12:00:00Z`)
  d.setUTCDate(d.getUTCDate() - n)
  return d.toISOString().slice(0, 10)
}

/** Why an edit cannot be saved yet, or null. */
export function editBlocked(hours: string, workDate: string, original: string | null | undefined,
  today: string = todayIso(), backdate = 21): string | null {
  const h = readNumberInput(hours).value
  if (h == null || !(h > 0)) return t('hours.hoursAbove0')
  if (h > 24) return t('hours.max24')
  if (!workDate) return t('hours.pickDate')
  if (workDate !== (original ?? '')) {
    if (workDate > today) return t('hours.noFuture')
    if (workDate < minusDays(today, backdate)) return t('hours.tooOld').replace('{n}', String(backdate))
  }
  return null
}

export default function BookingsDialog({ changeId, open, onClose, departmentId = null, departments }: {
  changeId: number
  open: boolean
  onClose: () => void
  /** the department opened from; the picker can widen it to all */
  departmentId?: number | null
  departments: { id: number; name: string }[]
}) {
  const qc = useQueryClient()
  const { data: state } = useQuery({
    queryKey: hoursKey(changeId), queryFn: () => hoursApi.get(changeId), enabled: open,
  })
  const [dept, setDept] = useState<number | null>(departmentId)
  const [editing, setEditing] = useState<number | null>(null)
  const [confirming, setConfirming] = useState<number | null>(null)
  const [hours, setHours] = useState('')
  const [workDate, setWorkDate] = useState('')
  const [note, setNote] = useState('')
  useEffect(() => {
    if (!open) return
    setDept(departmentId); setEditing(null); setConfirming(null)
  }, [open, departmentId])

  const done = (data: Awaited<ReturnType<typeof hoursApi.get>>) => {
    qc.setQueryData(hoursKey(changeId), data)
    invalidateCosting(qc, changeId)
  }
  const update = useMutation({
    mutationFn: ({ id, body }: { id: number; body: HoursPatch }) => hoursApi.update(changeId, id, body),
    onSuccess: (data) => { done(data); setEditing(null); toast.success(t('hours.corrected')) },
    onError: (e: unknown) => toastError(e, t('hours.correctError')),
  })
  const remove = useMutation({
    mutationFn: (id: number) => hoursApi.remove(changeId, id),
    onSuccess: (data) => { done(data); setConfirming(null); toast.success(t('hours.deleted')) },
    onError: (e: unknown) => toastError(e, t('hours.correctError')),
  })

  const all = state?.bookings ?? []
  const rows = dept == null ? all : all.filter((b) => b.department_id === dept)
  const sum = rows.reduce((a, b) => a + (b.hours ?? 0), 0)
  const windowOpen = state?.window_open !== false
  const backdate = state?.backdate_days ?? 21
  // the departments with bookings, plus the one opened from
  const deptOptions = [...new Map([
    ...all.map((b) => [b.department_id, b.department_name ?? String(b.department_id)] as const),
    ...departments.filter((d) => d.id === departmentId).map((d) => [d.id, d.name] as const),
  ]).entries()].sort((a, b) => a[1].localeCompare(b[1]))

  const startEdit = (b: HoursBooking) => {
    setConfirming(null); setEditing(b.id)
    setHours(String(b.hours)); setWorkDate(b.work_date ?? ''); setNote(b.note ?? '')
  }
  const editing_ = rows.find((b) => b.id === editing)
  const blocked = editing_ ? editBlocked(hours, workDate, editing_.work_date, todayIso(), backdate) : null
  const saveEdit = (b: HoursBooking) => {
    const h = readNumberInput(hours).value
    if (blocked || h == null) return
    const body: HoursPatch = {}
    if (h !== b.hours) body.hours = h
    if (workDate !== (b.work_date ?? '')) body.work_date = workDate
    if (note.trim() !== (b.note ?? '')) body.note = note.trim()
    if (Object.keys(body).length === 0) { setEditing(null); return }
    update.mutate({ id: b.id, body })
  }
  const busy = update.isPending || remove.isPending
  const th = 'px-2 py-1.5 text-left text-[11px] font-medium uppercase tracking-wide text-slate-400'
  const td = 'px-2 py-1.5 align-middle'

  return (
    <Dialog open={open} onClose={onClose} size="xl" closeOnBackdrop={false}
      title={t('hours.correctTitle')} description={t('hours.correctIntro')}
      data-testid="bookings-dialog"
      footer={(
        <>
          {windowOpen && (
            <Button onClick={() => { onClose(); requestBookHours(dept != null ? { departmentId: dept } : {}) }}>
              {t('hours.title')}
            </Button>
          )}
          <Button variant="primary" onClick={onClose}>{t('common.close')}</Button>
        </>
      )}>
      <div className="space-y-2 text-sm">
        <div className="flex flex-wrap items-center gap-2">
          <label className="text-xs text-slate-400" htmlFor="bookings-dept">{t('hours.department')}</label>
          <select id="bookings-dept" data-testid="bookings-dept" value={dept ?? ''}
            onChange={(e) => { setDept(e.target.value ? Number(e.target.value) : null); setEditing(null); setConfirming(null) }}
            className={`${inputCls} w-56`}>
            <option value="">{t('hours.allDepts')}</option>
            {deptOptions.map(([id, name]) => <option key={id} value={id}>{name}</option>)}
          </select>
          <span data-testid="bookings-sum" className="ml-auto text-xs tabular-nums text-slate-300">
            {t('hours.sum').replace('{h}', fmtH(sum))}
          </span>
        </div>
        {!windowOpen && (
          <p className="text-xs text-amber-300">{t('hours.windowClosed')}</p>
        )}
        {rows.length === 0 ? (
          <p data-testid="bookings-empty" className="py-4 text-center text-xs text-slate-400">{t('hours.none')}</p>
        ) : (
          <div className="overflow-x-auto rounded-lg border border-slate-700">
            <table className="w-full text-xs text-slate-200">
              <thead className="bg-slate-800/80">
                <tr>
                  <th className={th}>{t('hours.colDate')}</th>
                  <th className={th}>{t('hours.colPerson')}</th>
                  {dept == null && <th className={th}>{t('hours.department')}</th>}
                  <th className={`${th} text-right`}>{t('hours.hours')}</th>
                  <th className={th}>{t('hours.colPhase')}</th>
                  <th className={th}>{t('hours.colNote')}</th>
                  <th className={th}><span className="sr-only">{t('hours.correct')}</span></th>
                </tr>
              </thead>
              <tbody>
                {rows.map((b) => {
                  const isEdit = editing === b.id
                  const may = !!(b.can_edit ?? b.can_delete) && windowOpen
                  return (
                    <Fragment key={b.id}>
                      <tr data-testid={`booking-row-${b.id}`}
                        className={`border-t border-slate-700/70 ${isEdit ? 'bg-slate-800/70' : ''} ${confirming === b.id ? 'bg-red-950/30' : ''}`}>
                        <td className={`${td} whitespace-nowrap`}>
                          {isEdit ? (
                            <span className="block w-36">
                              <DateInput aria-label={t('hours.workDate')} value={workDate} commitOnChange
                                max={todayIso()} min={minusDays(todayIso(), backdate)}
                                onChange={setWorkDate} className={`${inputCls} w-full`} />
                            </span>
                          ) : <span className="tabular-nums">{formatCalendarDate(b.work_date)}</span>}
                        </td>
                        <td className={td}>
                          <span>{b.booked_by_name ?? '-'}</span>
                          {b.booked_for && (
                            <span className="ml-1 text-slate-400">{t('hours.forName').replace('{n}', b.booked_for)}</span>
                          )}
                        </td>
                        {dept == null && <td className={`${td} text-slate-300`}>{b.department_name}</td>}
                        <td className={`${td} text-right`}>
                          {isEdit ? (
                            <input data-testid={`booking-hours-${b.id}`} inputMode="decimal" value={hours}
                              aria-label={t('hours.hours')}
                              onChange={(e) => setHours(e.target.value)}
                              onKeyDown={(e) => { if (e.key === 'Enter') saveEdit(b) }}
                              className={`${inputCls} w-20 text-right tabular-nums`} />
                          ) : (
                            <span className="tabular-nums text-slate-100">{fmtH(b.hours)}</span>
                          )}
                        </td>
                        <td className={`${td} whitespace-nowrap text-slate-300`}>
                          {phaseLabel(b)}
                          {b.source === 'estimate' && (
                            <span className="ml-1 text-[11px] text-sky-300">{t('hours.confirmedEstimate')}</span>
                          )}
                        </td>
                        <td className={`${td} min-w-[10rem]`}>
                          {isEdit ? (
                            <input data-testid={`booking-note-${b.id}`} value={note} aria-label={t('hours.colNote')}
                              onChange={(e) => setNote(e.target.value)}
                              onKeyDown={(e) => { if (e.key === 'Enter') saveEdit(b) }}
                              className={`${inputCls} w-full`} />
                          ) : <span className="text-slate-300">{b.note ?? ''}</span>}
                        </td>
                        <td className={`${td} whitespace-nowrap text-right`}>
                          {!may ? (
                            <span className="text-[11px] text-slate-500">{t('hours.readOnly')}</span>
                          ) : isEdit ? (
                            <span className="inline-flex gap-1.5">
                              <button type="button" data-testid={`booking-save-${b.id}`}
                                disabled={!!blocked || busy} onClick={() => saveEdit(b)}
                                className={btnSm.primary}>{t('hours.save')}</button>
                              <button type="button" onClick={() => setEditing(null)} disabled={busy}
                                className={btnSm.ghost}>{t('hours.cancel')}</button>
                            </span>
                          ) : (
                            <span className="inline-flex gap-1.5">
                              <button type="button" data-testid={`booking-edit-${b.id}`} disabled={busy}
                                onClick={() => startEdit(b)} className={btnSm.secondary}>{t('hours.edit')}</button>
                              <button type="button" data-testid={`booking-delete-${b.id}`} disabled={busy}
                                onClick={() => { setEditing(null); setConfirming(b.id) }}
                                className="inline-flex h-7 items-center rounded-lg px-2.5 text-xs font-medium text-red-300 hover:bg-red-950/50 hover:text-red-200 disabled:opacity-50">{t('hours.delete')}</button>
                            </span>
                          )}
                        </td>
                      </tr>
                      {isEdit && blocked && (
                        <tr className="bg-slate-800/70">
                          <td colSpan={dept == null ? 7 : 6} data-testid="booking-blocked"
                            className="px-2 pb-1.5 text-[11px] text-amber-300">{blocked}</td>
                        </tr>
                      )}
                      {confirming === b.id && (
                        <tr data-testid={`booking-confirm-${b.id}`} className="bg-red-950/40">
                          <td colSpan={dept == null ? 7 : 6} className="px-2 py-1.5">
                            <div className="flex flex-wrap items-center gap-2 text-xs text-red-100">
                              <span>{t('hours.deleteConfirm').replace('{h}', fmtH(b.hours))
                                .replace('{d}', formatCalendarDate(b.work_date))
                                .replace('{p}', b.booked_by_name ?? '-')}</span>
                              <span className="ml-auto inline-flex gap-1.5">
                                <button type="button" onClick={() => setConfirming(null)} disabled={busy}
                                  className={btnSm.secondary}>{t('hours.keep')}</button>
                                <button type="button" data-testid={`booking-delete-yes-${b.id}`} disabled={busy}
                                  onClick={() => remove.mutate(b.id)} className={btnSm.danger}>{t('hours.delete')}</button>
                              </span>
                            </div>
                          </td>
                        </tr>
                      )}
                    </Fragment>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </Dialog>
  )
}
