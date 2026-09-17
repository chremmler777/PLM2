/**
 * "Not our responsibility": a routed department declining the assessment.
 *
 * The room put the department on the hook at scoping; the department, looking
 * at the actual change, says it is not theirs. That is a routing deviation
 * (reletter to C — consulted, no answer owed) with a reason, decided by the
 * change lead through the same 4-eyes panel as an added department. Naming
 * who should own it instead files the add in the same step.
 */
import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { changesApi } from '../../api/changes'
import { t } from '../../i18n/cmLabels'

interface Props {
  changeId: number
  departmentId: number
  stageOrder: number
  /** Departments not yet routed — offered as "who instead". */
  candidates: { id: number; name: string }[]
  onClose: () => void
}

export default function NotResponsibleDialog({
  changeId, departmentId, stageOrder, candidates, onClose,
}: Props) {
  const qc = useQueryClient()
  const [reason, setReason] = useState('')
  const [instead, setInstead] = useState<number | ''>('')
  const decline = useMutation({
    mutationFn: async () => {
      const why = reason.trim()
      await changesApi.postDeviation(changeId, {
        op: 'reletter', department_id: departmentId, rasic_letter: 'C', reason: why,
      })
      if (instead !== '') {
        await changesApi.postDeviation(changeId, {
          op: 'add', department_id: instead, rasic_letter: 'R', stage_order: stageOrder,
          reason: why,
        })
      }
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['change-routing', changeId] })
      qc.invalidateQueries({ queryKey: ['change', changeId] })
      toast.success(t('notResp.sent'))
      onClose()
    },
    onError: (e: Error & { response?: { data?: { detail?: string } } }) =>
      toast.error(e.response?.data?.detail ?? t('routingDev.failed')),
  })
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50" role="dialog"
      data-testid="not-responsible-dialog">
      <div className="bg-slate-800 rounded-xl shadow-xl w-full max-w-md p-5 space-y-3">
        <h3 className="text-base font-semibold text-slate-100">{t('notResp.title')}</h3>
        <p className="text-xs text-amber-200/90 rounded-lg border border-amber-700/60 bg-amber-950/40 px-3 py-2">
          {t('notResp.effect')}
        </p>
        <label className="block text-sm text-slate-400">
          {t('notResp.reason')}
          <textarea data-testid="not-responsible-reason" autoFocus
            className="mt-1 w-full border border-slate-600 bg-slate-900 text-slate-100 rounded-lg p-2 text-sm min-h-[70px]"
            value={reason} onChange={(e) => setReason(e.target.value)} />
        </label>
        <label className="block text-sm text-slate-400">
          {t('notResp.whoInstead')}
          <select data-testid="not-responsible-instead"
            className="mt-1 w-full border border-slate-600 bg-slate-900 text-slate-100 rounded-lg p-2 text-sm"
            value={instead}
            onChange={(e) => setInstead(e.target.value === '' ? '' : Number(e.target.value))}>
            <option value="">{t('notResp.nobody')}</option>
            {candidates.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
          </select>
        </label>
        <div className="flex justify-end gap-2 pt-1">
          <button type="button"
            className="px-3 py-1.5 text-sm border border-slate-600 text-slate-300 hover:bg-slate-700 rounded-lg"
            onClick={onClose}>{t('common.cancel')}</button>
          <button type="button" data-testid="not-responsible-submit"
            className="px-3 py-1.5 text-sm rounded-lg text-white bg-red-700 hover:bg-red-600 disabled:opacity-50"
            disabled={!reason.trim() || decline.isPending}
            onClick={() => decline.mutate()}>{t('notResp.submit')}</button>
        </div>
      </div>
    </div>
  )
}
