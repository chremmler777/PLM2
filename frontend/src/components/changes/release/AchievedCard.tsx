/**
 * ECR-solid §11: an internal change closes with what it achieved, beside
 * the target it was raised with (§2 "what is wrong today" -> target), and
 * where that number comes from. The lead, Project Management or an admin
 * enter it in validation or once released; closing without it is a soft
 * rule ("Achieved value not entered") the run team may override.
 */
import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { changesApi } from '../../../api/changes'
import type { ChangeDetail } from '../../../types/change'
import { readNumberInput } from '../../../lib/format'
import { toastError } from '../../../lib/apiError'
import { inputCls } from '../offer/offerFormat'
import { btnSm } from '../../common/buttonStyles'
import { t } from '../../../i18n/cmLabels'
import { refOk } from '../validation/MeasurementForm'

/** Shown for an internal change with a target, from validation on. */
export const achievedApplies = (c: Pick<ChangeDetail, 'customer_relevant' | 'target_value' | 'status' | 'release_v2'>) =>
  c.release_v2 !== false && c.customer_relevant === false && c.target_value != null
  && ['in_validation', 'released', 'closed'].includes(c.status)

export default function AchievedCard({ change, canEdit }: { change: ChangeDetail; canEdit: boolean }) {
  const qc = useQueryClient()
  const [value, setValue] = useState('')
  const [ref, setRef] = useState('')
  const unit = change.problem_unit ? ` ${change.problem_unit}` : ''
  const read = readNumberInput(value)
  const save = useMutation({
    mutationFn: () => changesApi.recordAchieved(change.id, { value: read.value!, ref: ref.trim() }),
    onSuccess: () => {
      setValue(''); setRef('')
      qc.invalidateQueries({ queryKey: ['change', change.id] })
    },
    onError: (e: unknown) => toastError(e, t('achieved.error')),
  })
  const editable = canEdit && ['in_validation', 'released'].includes(change.status)
  return (
    <div data-testid="achieved-card" className="space-y-1.5 rounded-lg border border-slate-700 bg-slate-900/40 p-3">
      <div className="text-xs font-medium text-slate-200">{t('achieved.title')}</div>
      <p className="text-[11px] text-slate-400">
        {t('achieved.target').replace('{t}', `${change.target_value}${unit}`)
          .replace('{p}', change.problem_value != null ? `${change.problem_value}${unit}` : '-')}
      </p>
      {change.achieved_value != null && (
        <p data-testid="achieved-recorded" className="text-xs text-emerald-200">
          {t('achieved.recorded').replace('{v}', `${change.achieved_value}${unit}`)
            .replace('{t}', `${change.target_value}${unit}`).replace('{ref}', change.achieved_ref ?? '-')}
        </p>
      )}
      {editable && (
        <div className="flex flex-wrap items-center gap-2">
          <input data-testid="achieved-value" inputMode="decimal" value={value} onChange={(e) => setValue(e.target.value)}
            aria-label={t('achieved.value')} placeholder={`${t('achieved.value')}${unit}`} className={`${inputCls} w-32`} />
          <input data-testid="achieved-ref" value={ref} onChange={(e) => setRef(e.target.value)}
            aria-label={t('achieved.ref')} placeholder={t('achieved.ref')} className={`${inputCls} min-w-[12rem] flex-1`} />
          <button type="button" data-testid="achieved-save"
            disabled={read.value == null || !refOk(ref) || save.isPending}
            onClick={() => save.mutate()} className={btnSm.primary}>
            {t('achieved.save')}
          </button>
        </div>
      )}
    </div>
  )
}

/** §10-§11: the header line of the concessions in force. */
export function ConcessionLine({ change }: { change: Pick<ChangeDetail, 'active_concessions'> }) {
  const rows = change.active_concessions ?? []
  if (!rows.length) return null
  return (
    <p data-testid="concession-line" className="text-xs font-medium text-emerald-200">
      {rows.map((c) => c.text).join(' · ')}
    </p>
  )
}
