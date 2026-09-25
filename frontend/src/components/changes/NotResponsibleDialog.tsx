/**
 * "Not our responsibility": a routed department declining the assessment.
 *
 * The room put the department on the hook at scoping; the department, looking
 * at the actual change, says it is not theirs. That is a routing deviation
 * (reletter to C — consulted, no answer owed) with a reason, decided by the
 * change lead through the same 4-eyes panel as an added department. Naming
 * who should own it instead files the add in the same step.
 */
import { useId, useRef, useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { TriangleAlert } from 'lucide-react'
import { changesApi } from '../../api/changes'
import Dialog from '../common/Dialog'
import Button from '../common/Button'
import { toastError } from '../../lib/apiError'
import { t } from '../../i18n/cmLabels'

const fieldCls =
  'mt-1 w-full rounded-lg border border-slate-600 bg-slate-900 p-2 text-sm text-slate-100 focus:border-sky-500 focus:outline-none'

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
  const reasonId = useId()
  const insteadId = useId()
  const reasonRef = useRef<HTMLTextAreaElement>(null)
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
      qc.invalidateQueries({ queryKey: ['change-my-actions', changeId] })
      toast.success(t('notResp.sent'))
      onClose()
    },
    onError: (e: unknown) => { toastError(e, t('routingDev.failed')) },
  })
  return (
    <Dialog open onClose={onClose} title={t('notResp.title')} busy={decline.isPending}
      closeOnBackdrop={false} data-testid="not-responsible-dialog"
      initialFocus={reasonRef as React.RefObject<HTMLElement>}
      footer={(
        <>
          <Button onClick={onClose} disabled={decline.isPending}>{t('common.cancel')}</Button>
          <Button variant="danger" data-testid="not-responsible-submit"
            disabled={!reason.trim()} loading={decline.isPending}
            onClick={() => decline.mutate()}>{t('notResp.submit')}</Button>
        </>
      )}>
      <div className="space-y-3">
        <p className="flex items-start gap-2 rounded-lg border border-amber-700/60 bg-amber-950/40 px-3 py-2 text-xs text-amber-200">
          <TriangleAlert aria-hidden="true" size={14} className="mt-0.5 shrink-0 text-amber-300" />
          <span>{t('notResp.effect')}</span>
        </p>
        <div>
          <label htmlFor={reasonId} className="block text-sm text-slate-300">{t('notResp.reason')}</label>
          <textarea id={reasonId} ref={reasonRef} data-testid="not-responsible-reason"
            className={`${fieldCls} min-h-[70px]`}
            value={reason} onChange={(e) => setReason(e.target.value)} />
        </div>
        <div>
          <label htmlFor={insteadId} className="block text-sm text-slate-300">{t('notResp.whoInstead')}</label>
          <select id={insteadId} data-testid="not-responsible-instead" className={fieldCls}
            value={instead}
            onChange={(e) => setInstead(e.target.value === '' ? '' : Number(e.target.value))}>
            <option value="">{t('notResp.nobody')}</option>
            {candidates.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
          </select>
        </div>
      </div>
    </Dialog>
  )
}
