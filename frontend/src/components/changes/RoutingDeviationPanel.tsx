/**
 * Adding a department after the routing was built.
 *
 * Someone was forgotten, or something turned out to be impacted after all.
 * The backend already carries this as a routing deviation: the department is
 * put on the hook at once, the change lead approves or rejects (4-eyes), and
 * costing waits for that decision. This panel is the button and the banner
 * for it; the rules live in `change_routing_service.py`.
 */
import { useId, useRef, useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { Plus } from 'lucide-react'
import { changesApi } from '../../api/changes'
import ReasonDialog from './ReasonDialog'
import PendingRemovalChip from './PendingRemovalChip'
import Dialog from '../common/Dialog'
import Button from '../common/Button'
import FieldGroup from '../common/FieldGroup'
import { btnSm } from '../common/buttonStyles'
import { toastError } from '../../lib/apiError'
import { useAuth } from '../../contexts/AuthContext'
import { deviationWaitKey } from '../../lib/scopingRules'
import { t } from '../../i18n/cmLabels'
import type { ChangeRouting, DeviationRequest } from '../../types/change'

// I (informed): notified only, no task, never waited on (backend TASK_LETTERS).
type Letter = 'R' | 'A' | 'S' | 'C' | 'I'
const LETTERS: Letter[] = ['R', 'A', 'S', 'C', 'I']

const fieldCls =
  'mt-1 w-full rounded-lg border border-slate-600 bg-slate-900 p-2 text-sm text-slate-100 focus:border-sky-500 focus:outline-none'

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
  /** The change lead, so the wait line names who decides: the lead, or the
   *  Project Manager when the lead proposed it. Omitted: the old wording. */
  leadId?: number | null
}

function AddDepartmentDialog({ open, candidates, pending = false, onSubmit, onClose }: {
  open: boolean
  candidates: { id: number; name: string }[]
  pending?: boolean
  onSubmit: (body: Pick<DeviationRequest, 'department_id' | 'rasic_letter' | 'reason'>) => void
  onClose: () => void
}) {
  const [departmentId, setDepartmentId] = useState<number | ''>('')
  const [letter, setLetter] = useState<Letter>('R')
  const [reason, setReason] = useState('')
  const selectId = useId()
  const reasonId = useId()
  const selectRef = useRef<HTMLSelectElement>(null)
  const ready = departmentId !== '' && reason.trim().length > 0
  const close = () => { setDepartmentId(''); setLetter('R'); setReason(''); onClose() }
  return (
    <Dialog open={open} onClose={close} title={t('routingDev.addTitle')} busy={pending}
      closeOnBackdrop={false} data-testid="add-department-dialog"
      initialFocus={selectRef as React.RefObject<HTMLElement>}
      footer={(
        <>
          <Button onClick={close} disabled={pending}>Cancel</Button>
          {candidates.length > 0 && (
            <Button variant="primary" data-testid="add-department-submit"
              disabled={!ready} loading={pending}
              onClick={() => {
                onSubmit({ department_id: departmentId as number, rasic_letter: letter, reason: reason.trim() })
                setDepartmentId(''); setLetter('R'); setReason('')
              }}>{t('routingDev.add')}</Button>
          )}
        </>
      )}>
      {candidates.length === 0 ? (
        <p className="text-sm text-slate-400">{t('routingDev.noneLeft')}</p>
      ) : (
        <div className="space-y-3">
          <div>
            <label htmlFor={selectId} className="block text-sm text-slate-300">{t('routingDev.department')}</label>
            <select id={selectId} ref={selectRef} data-testid="add-department-select"
              className={fieldCls} value={departmentId}
              onChange={(e) => setDepartmentId(e.target.value === '' ? '' : Number(e.target.value))}>
              <option value="">Choose a department</option>
              {candidates.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
            </select>
          </div>
          <FieldGroup legend={<span className="text-sm text-slate-300">{t('routingDev.role')}</span>}>
            <div className="space-y-1">
              {LETTERS.map((l) => (
                <label key={l} className="flex cursor-pointer items-center gap-2 text-sm text-slate-200">
                  <input type="radio" name="rasic" value={l} checked={letter === l}
                    className="accent-sky-500" onChange={() => setLetter(l)} />
                  {t(`routingDev.letter.${l}`)}
                </label>
              ))}
            </div>
          </FieldGroup>
          <div>
            <label htmlFor={reasonId} className="block text-sm text-slate-300">{t('routingDev.reason')}</label>
            <textarea id={reasonId} data-testid="add-department-reason"
              className={`${fieldCls} min-h-[70px]`}
              value={reason} onChange={(e) => setReason(e.target.value)} />
          </div>
          <p className="text-xs text-slate-400">{t('routingDev.leadHint')}</p>
          <p className="text-xs text-amber-300/90">{t('routingDev.templateHint')}</p>
        </div>
      )}
    </Dialog>
  )
}

export default function RoutingDeviationPanel({
  changeId, routing, departments, routedIds, stageOrder, canAdd, canDecide, leadId,
}: Props) {
  const qc = useQueryClient()
  const { userId } = useAuth()
  const [addOpen, setAddOpen] = useState(false)
  const [rejectOpen, setRejectOpen] = useState(false)
  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ['change-routing', changeId] })
    qc.invalidateQueries({ queryKey: ['change', changeId] })
    qc.invalidateQueries({ queryKey: ['change-my-actions', changeId] })
  }
  const fail = (e: unknown) => { toastError(e, t('routingDev.failed')) }

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
  // The rows this deviation asks to take off: still on the routing (owed)
  // until the decision.
  const removals = pending ? (routing?.stages ?? []).flatMap((s) => s.departments
    .filter((d) => d.pending_removal)
    .map((d) => ({ ...d, stage_order: s.stage_order }))) : []
  const nameOf = (id: number) => departments.find((d) => d.id === id)?.name ?? `#${id}`
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
          {removals.length > 0 && (
            <ul className="mt-2 space-y-1" data-testid="routing-deviation-removals">
              {removals.map((d) => (
                <li key={`${d.department_id}-${d.stage_order}`}
                  data-testid={`routing-removal-${d.department_id}-${d.stage_order}`}
                  className="flex flex-wrap items-center gap-2 text-amber-100">
                  <span className="font-medium">{nameOf(d.department_id)}</span>
                  <span className="text-xs text-amber-200/70">{d.rasic_letter}</span>
                  <PendingRemovalChip />
                </li>
              ))}
            </ul>
          )}
          <p className="text-amber-200/80 text-xs mt-1">{t('routingDev.pendingBody')}</p>
          <div className="mt-2 flex items-center gap-2">
            {canDecide ? (
              <>
                <button type="button" data-testid="routing-deviation-approve"
                  className={btnSm.primary} aria-busy={approve.isPending || undefined}
                  disabled={approve.isPending}
                  onClick={() => approve.mutate()}>{t('routingDev.approve')}</button>
                <button type="button" data-testid="routing-deviation-reject"
                  className={`${btnSm.secondary} text-red-300 hover:text-red-200 hover:border-red-700`}
                  onClick={() => setRejectOpen(true)}>{t('routingDev.reject')}</button>
              </>
            ) : (
              <span className="text-xs text-amber-200/70" data-testid="routing-deviation-waiting">
                {t(deviationWaitKey(routing?.deviation_proposed_by, leadId, userId))}
              </span>
            )}
          </div>
        </div>
      )}

      {canAdd && (
        <div className="flex justify-end">
          <button type="button" data-testid="add-department-button"
            className={btnSm.secondary}
            disabled={pending}
            title={pending ? t('routingDev.addBlocked') : undefined}
            onClick={() => setAddOpen(true)}>
            <Plus aria-hidden="true" size={14} />{t('routingDev.add')}
          </button>
        </div>
      )}

      <AddDepartmentDialog open={addOpen} candidates={candidates} pending={propose.isPending}
        onClose={() => setAddOpen(false)}
        onSubmit={(body) => propose.mutate({ op: 'add', stage_order: stageOrder, ...body })} />
      <ReasonDialog open={rejectOpen} danger
        title={t('routingDev.rejectTitle')} label={t('routingDev.rejectLabel')}
        submitLabel={t('routingDev.reject')} warning={t('routingDev.rejectWarning')}
        onSubmit={(reason) => reject.mutate(reason)} onClose={() => setRejectOpen(false)} />
    </div>
  )
}
