/**
 * Adding a department after the routing was built.
 *
 * Someone was forgotten, or something turned out to be impacted after all.
 * The backend already carries this as a routing deviation: the department is
 * put on the hook at once, the change lead approves or rejects (4-eyes), and
 * costing waits for that decision. This panel is the button and the banner
 * for it; the rules live in `change_routing_service.py`.
 */
import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { changesApi } from '../../api/changes'
import ReasonDialog from './ReasonDialog'
import { t } from '../../i18n/cmLabels'
import type { ChangeRouting, DeviationRequest } from '../../types/change'

type Letter = 'R' | 'A' | 'S' | 'C'
const LETTERS: Letter[] = ['R', 'A', 'S', 'C']

interface Props {
  changeId: number
  routing: ChangeRouting | undefined
  departments: { id: number; name: string; is_active?: boolean }[]
  /** Departments already on the assessment board — not offered again. */
  routedIds: number[]
  /** The stage the new row lands on: the assessment stage, so its task fires now. */
  stageOrder: number
  /** Lead, PM or admin while the change is in assessment. */
  canAdd: boolean
  /** Mirrors the backend 4-eyes rule; computed by the caller. */
  canDecide: boolean
}

function AddDepartmentDialog({ open, candidates, onSubmit, onClose }: {
  open: boolean
  candidates: { id: number; name: string }[]
  onSubmit: (body: Pick<DeviationRequest, 'department_id' | 'rasic_letter' | 'reason'>) => void
  onClose: () => void
}) {
  const [departmentId, setDepartmentId] = useState<number | ''>('')
  const [letter, setLetter] = useState<Letter>('R')
  const [reason, setReason] = useState('')
  if (!open) return null
  const ready = departmentId !== '' && reason.trim().length > 0
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50" role="dialog"
      data-testid="add-department-dialog">
      <div className="bg-slate-800 rounded-xl shadow-xl w-full max-w-md p-5 space-y-3">
        <h3 className="text-base font-semibold text-slate-100">{t('routingDev.addTitle')}</h3>
        {candidates.length === 0 ? (
          <p className="text-sm text-slate-400">{t('routingDev.noneLeft')}</p>
        ) : (
          <>
            <label className="block text-sm text-slate-400">
              {t('routingDev.department')}
              <select data-testid="add-department-select"
                className="mt-1 w-full border border-slate-600 bg-slate-900 text-slate-100 rounded-lg p-2 text-sm"
                value={departmentId}
                onChange={(e) => setDepartmentId(e.target.value === '' ? '' : Number(e.target.value))}>
                <option value="">—</option>
                {candidates.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
              </select>
            </label>
            <fieldset>
              <legend className="text-sm text-slate-400 mb-1">{t('routingDev.role')}</legend>
              <div className="space-y-1">
                {LETTERS.map((l) => (
                  <label key={l} className="flex items-center gap-2 text-sm text-slate-200">
                    <input type="radio" name="rasic" value={l} checked={letter === l}
                      onChange={() => setLetter(l)} />
                    {t(`routingDev.letter.${l}`)}
                  </label>
                ))}
              </div>
            </fieldset>
            <label className="block text-sm text-slate-400">
              {t('routingDev.reason')}
              <textarea data-testid="add-department-reason"
                className="mt-1 w-full border border-slate-600 bg-slate-900 text-slate-100 rounded-lg p-2 text-sm min-h-[70px]"
                value={reason} onChange={(e) => setReason(e.target.value)} />
            </label>
            <p className="text-xs text-slate-500">{t('routingDev.leadHint')}</p>
            <p className="text-xs text-amber-300/80">{t('routingDev.templateHint')}</p>
          </>
        )}
        <div className="flex justify-end gap-2 pt-1">
          <button type="button"
            className="px-3 py-1.5 text-sm border border-slate-600 text-slate-300 hover:bg-slate-700 rounded-lg"
            onClick={onClose}>Cancel</button>
          {candidates.length > 0 && (
            <button type="button" data-testid="add-department-submit"
              className="px-3 py-1.5 text-sm rounded-lg text-white bg-sky-600 hover:bg-sky-500 disabled:opacity-50"
              disabled={!ready}
              onClick={() => {
                onSubmit({ department_id: departmentId as number, rasic_letter: letter, reason: reason.trim() })
                setDepartmentId(''); setLetter('R'); setReason('')
              }}>{t('routingDev.add')}</button>
          )}
        </div>
      </div>
    </div>
  )
}

export default function RoutingDeviationPanel({
  changeId, routing, departments, routedIds, stageOrder, canAdd, canDecide,
}: Props) {
  const qc = useQueryClient()
  const [addOpen, setAddOpen] = useState(false)
  const [rejectOpen, setRejectOpen] = useState(false)
  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ['change-routing', changeId] })
    qc.invalidateQueries({ queryKey: ['change', changeId] })
    qc.invalidateQueries({ queryKey: ['change', changeId, 'my-actions'] })
  }
  const fail = (e: Error & { response?: { data?: { detail?: string } } }) =>
    toast.error(e.response?.data?.detail ?? t('routingDev.failed'))

  const propose = useMutation({
    mutationFn: (body: DeviationRequest) => changesApi.postDeviation(changeId, body),
    onSuccess: () => { invalidate(); toast.success(t('routingDev.proposed')); setAddOpen(false) },
    onError: fail,
  })
  const approve = useMutation({
    mutationFn: () => changesApi.approveDeviation(changeId),
    onSuccess: () => { invalidate(); toast.success(t('routingDev.approved')) },
    onError: fail,
  })
  const reject = useMutation({
    mutationFn: (reason: string) => changesApi.rejectDeviation(changeId, reason),
    onSuccess: () => { invalidate(); toast.success(t('routingDev.rejected')); setRejectOpen(false) },
    onError: fail,
  })

  const pending = routing?.deviation_status === 'pending_approval'
  const candidates = departments
    .filter((d) => d.is_active !== false && !routedIds.includes(d.id))
    .sort((a, b) => a.name.localeCompare(b.name))

  if (!pending && !canAdd) return null

  return (
    <div className="space-y-2" data-testid="routing-deviation-panel">
      {pending && (
        <div className="border border-amber-700 bg-amber-900/30 rounded-lg p-3 text-sm"
          data-testid="routing-deviation-pending">
          <p className="font-medium text-amber-200">{t('routingDev.pendingTitle')}</p>
          {routing?.deviation_note && (
            <p className="text-amber-100/90 mt-1 whitespace-pre-wrap"
              data-testid="routing-deviation-note">{routing.deviation_note}</p>
          )}
          <p className="text-amber-200/80 text-xs mt-1">{t('routingDev.pendingBody')}</p>
          <div className="mt-2 flex items-center gap-2">
            {canDecide ? (
              <>
                <button type="button" data-testid="routing-deviation-approve"
                  className="px-3 py-1 text-xs rounded-lg bg-emerald-700 hover:bg-emerald-600 text-white disabled:opacity-50"
                  disabled={approve.isPending}
                  onClick={() => approve.mutate()}>{t('routingDev.approve')}</button>
                <button type="button" data-testid="routing-deviation-reject"
                  className="px-3 py-1 text-xs rounded-lg border border-red-700 text-red-300 hover:bg-red-900/40"
                  onClick={() => setRejectOpen(true)}>{t('routingDev.reject')}</button>
              </>
            ) : (
              <span className="text-xs text-amber-200/70" data-testid="routing-deviation-waiting">
                {t('routingDev.waitingForLead')}
              </span>
            )}
          </div>
        </div>
      )}

      {canAdd && (
        <div className="flex justify-end">
          <button type="button" data-testid="add-department-button"
            className="text-xs px-2.5 py-1 rounded-lg border border-slate-600 text-slate-300 hover:bg-slate-700 disabled:opacity-50 disabled:cursor-not-allowed"
            disabled={pending}
            title={pending ? t('routingDev.addBlocked') : undefined}
            onClick={() => setAddOpen(true)}>+ {t('routingDev.add')}</button>
        </div>
      )}

      <AddDepartmentDialog open={addOpen} candidates={candidates}
        onClose={() => setAddOpen(false)}
        onSubmit={(body) => propose.mutate({ op: 'add', stage_order: stageOrder, ...body })} />
      <ReasonDialog open={rejectOpen} danger
        title={t('routingDev.rejectTitle')} label={t('routingDev.rejectLabel')}
        submitLabel={t('routingDev.reject')} warning={t('routingDev.rejectWarning')}
        onSubmit={(reason) => reject.mutate(reason)} onClose={() => setRejectOpen(false)} />
    </div>
  )
}
