/**
 * ECR-solid C15: one "Book hours" dialog for the whole life of a change.
 * Department (yours), hours, the day worked (today back 21 days), for a
 * colleague (Belk for the toolmakers), the lead's Coordination row. Opened
 * with `confirm` at a department's last action it comes prefilled with what
 * is left of the department's estimate and names it ("your estimate: 6 h");
 * skipped is "not booked", never 0.
 */
import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import Dialog from '../../common/Dialog'
import Button from '../../common/Button'
import DateInput from '../../gantt/DateInput'
import { hoursApi, hoursKey, type HoursIn } from '../../../api/hours'
import { readNumberInput, todayIso } from '../../../lib/format'
import { toastError } from '../../../lib/apiError'
import { inputCls } from '../offer/offerFormat'
import { t } from '../../../i18n/cmLabels'

const minusDays = (iso: string, n: number) => {
  const d = new Date(`${iso}T12:00:00Z`)
  d.setUTCDate(d.getUTCDate() - n)
  return d.toISOString().slice(0, 10)
}

/** Why the booking cannot be sent yet, or null. */
export function bookBlocked(deptId: number | null, hours: string, workDate: string,
  today: string = todayIso(), backdate = 21): string | null {
  if (deptId == null) return t('hours.pickDept')
  const h = readNumberInput(hours).value
  if (h == null || !(h > 0)) return t('hours.hoursAbove0')
  if (h > 24) return t('hours.max24')
  if (!workDate) return t('hours.pickDate')
  if (workDate > today) return t('hours.noFuture')
  if (workDate < minusDays(today, backdate)) return t('hours.tooOld').replace('{n}', String(backdate))
  return null
}

export default function BookHoursDialog({ changeId, open, onClose, departments, myDepartmentIds,
  initialDepartmentId = null, confirm = false }: {
  changeId: number
  open: boolean
  onClose: () => void
  departments: { id: number; name: string }[]
  myDepartmentIds: number[]
  initialDepartmentId?: number | null
  /** the one prefilled confirm at the department's last action */
  confirm?: boolean
}) {
  const qc = useQueryClient()
  const { data: state } = useQuery({ queryKey: hoursKey(changeId), queryFn: () => hoursApi.get(changeId), enabled: open })
  const mine = departments.filter((d) => myDepartmentIds.includes(d.id))
  const [deptId, setDeptId] = useState<number | null>(null)
  const [hours, setHours] = useState('')
  const [workDate, setWorkDate] = useState(todayIso())
  const [forWhom, setForWhom] = useState('')
  const [coordination, setCoordination] = useState(false)
  const [note, setNote] = useState('')
  const [prefilled, setPrefilled] = useState<number | null>(null)
  const pre = state?.mine?.find((m) => m.department_id === deptId)

  useEffect(() => {
    if (!open) return
    setDeptId(initialDepartmentId ?? (mine.length === 1 ? mine[0].id : null))
    setHours(''); setWorkDate(todayIso()); setForWhom(''); setCoordination(false); setNote('')
    setPrefilled(null)
  }, [open]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    // the confirm comes prefilled with what is left of the estimate
    if (open && confirm && pre?.prefill_hours && prefilled == null) {
      setHours(String(pre.prefill_hours)); setPrefilled(pre.prefill_hours)
    }
  }, [open, confirm, pre?.prefill_hours]) // eslint-disable-line react-hooks/exhaustive-deps

  const save = useMutation({
    mutationFn: (body: HoursIn) => hoursApi.book(changeId, body),
    onSuccess: (data) => {
      qc.setQueryData(hoursKey(changeId), data)
      qc.invalidateQueries({ queryKey: ['change', changeId, 'impl-bookings'] })
      qc.invalidateQueries({ queryKey: ['change', changeId, 'impl-state'] })
      onClose()
    },
    onError: (e: unknown) => toastError(e, t('hours.error')),
  })
  const blocked = bookBlocked(deptId, hours, workDate, todayIso(), state?.backdate_days ?? 21)
  const h = readNumberInput(hours).value
  const submit = () => {
    if (blocked || deptId == null || h == null) return
    save.mutate({
      department_id: deptId, hours: h, work_date: workDate,
      ...(forWhom.trim() ? { booked_for: forWhom.trim() } : {}),
      ...(coordination ? { coordination: true } : {}),
      ...(note.trim() ? { note: note.trim() } : {}),
      // a confirmed estimate stays 'estimate' only while the number is the prefill
      source: prefilled != null && h === prefilled ? 'estimate' : 'typed',
    })
  }
  return (
    <Dialog open={open} onClose={onClose} title={t(confirm ? 'hours.confirmTitle' : 'hours.title')}
      closeOnBackdrop={false}
      footer={(
        <>
          <Button onClick={onClose}>{t(confirm ? 'hours.skip' : 'common.cancel')}</Button>
          <Button variant="primary" disabled={!!blocked || save.isPending || state?.window_open === false}
            onClick={submit}>{t('hours.book')}</Button>
        </>
      )}>
      <div data-testid="book-hours" className="space-y-2 text-sm">
        {state?.window_open === false && (
          <p data-testid="book-hours-closed" className="text-xs text-amber-300">{t('hours.windowClosed')}</p>
        )}
        {confirm && (
          <p className="text-xs text-slate-300">{t('hours.confirmIntro')}</p>
        )}
        <label className="block text-xs text-slate-400">{t('hours.department')}
          <select data-testid="book-hours-dept" value={deptId ?? ''} className={`${inputCls} mt-0.5 w-full`}
            onChange={(e) => { setDeptId(e.target.value ? Number(e.target.value) : null); setPrefilled(null) }}>
            <option value="">{t('hours.pickDept')}</option>
            {mine.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
          </select>
        </label>
        {pre?.source_label && (
          <p data-testid="book-hours-source" className="text-[11px] text-sky-300">{pre.source_label}</p>
        )}
        <div className="flex flex-wrap items-end gap-2">
          <label className="text-xs text-slate-400">{t('hours.hours')}
            <input data-testid="book-hours-hours" inputMode="decimal" value={hours}
              onChange={(e) => setHours(e.target.value)} className={`${inputCls} mt-0.5 block w-24`} />
          </label>
          <label className="text-xs text-slate-400">{t('hours.workDate')}
            <span className="mt-0.5 block w-36">
              <DateInput aria-label={t('hours.workDate')} value={workDate} commitOnChange
                max={todayIso()} min={minusDays(todayIso(), state?.backdate_days ?? 21)}
                onChange={setWorkDate} className={`${inputCls} w-full`} />
            </span>
          </label>
        </div>
        <label className="block text-xs text-slate-400">{t('hours.forColleague')}
          <input data-testid="book-hours-for" value={forWhom} onChange={(e) => setForWhom(e.target.value)}
            placeholder={t('hours.forColleagueHint')} className={`${inputCls} mt-0.5 w-full`} />
        </label>
        {state?.can_coordinate && (
          <label className="flex items-center gap-2 text-xs text-slate-300">
            <input type="checkbox" data-testid="book-hours-coordination" checked={coordination}
              onChange={(e) => setCoordination(e.target.checked)} />
            {t('hours.coordination')}
          </label>
        )}
        <input data-testid="book-hours-note" value={note} onChange={(e) => setNote(e.target.value)}
          placeholder={t('hours.note')} aria-label={t('hours.note')} className={`${inputCls} w-full`} />
        {blocked && (hours || deptId != null) && (
          <p data-testid="book-hours-blocked" className="text-[11px] text-slate-400">{blocked}</p>
        )}
      </div>
    </Dialog>
  )
}
