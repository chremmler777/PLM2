/**
 * The Mother plant tab (spec 2026-09-25 §14). For a change engineered and
 * sold by the mother plant it replaces Assessments, Costing and Offer:
 *
 *  1. What the mother plant sent: plant, their reference, SOP, their
 *     documents and their timing file (MS Project XML).
 *  2. Inform the team: the PM picks the departments (default: the
 *     physical-part routing), sends, and each department answers "Read and
 *     understood", optionally with a note back.
 *
 * Every rule lives in the backend (GET/POST /changes/{id}/mother-plant...);
 * the tab shows what the answer allows.
 */
import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { API_BASE_URL } from '../../../api/client'
import { changesApi } from '../../../api/changes'
import { motherPlantApi, motherPlantKey, type MotherPlantState } from '../../../api/motherPlant'
import { formatCalendarDate, formatDate, formatDateTime } from '../../../lib/format'
import type { ChangeRequest } from '../../../types/change'
import { t } from '../../../i18n/cmLabels'
import { plantText } from '../../../lib/plantName'
import { Check } from 'lucide-react'
import { btnPrimary, btnSm } from '../../common/buttonStyles'
import { toastError } from '../../../lib/apiError'

const card = 'rounded-lg border border-slate-700 bg-slate-800 p-4'
const primary = btnPrimary
const small = btnSm.secondary

export interface MotherPlantTabProps {
  change: ChangeRequest
  departments: { id: number; name: string; is_active?: boolean }[]
}

export default function MotherPlantTab({ change, departments }: MotherPlantTabProps) {
  const qc = useQueryClient()
  const id = change.id
  const { data: state, isError } = useQuery({
    queryKey: motherPlantKey(id), queryFn: () => motherPlantApi.get(id),
  })
  const refresh = (next?: MotherPlantState) => {
    if (next) qc.setQueryData(motherPlantKey(id), next)
    qc.invalidateQueries({ queryKey: ['change', id] })
    qc.invalidateQueries({ queryKey: ['change-my-actions', id] })
  }

  if (isError) return <p className="text-sm text-red-300">{plantText('mp.loadError', change.mother_plant_name)}</p>
  if (!state) return <p className="text-sm text-slate-400">Loading…</p>

  return (
    <div className="space-y-4" data-testid="mother-plant-tab">
      <Source change={change} state={state} onUploaded={() => refresh()} />
      <InformTeam change={change} state={state} departments={departments} onDone={refresh} />
    </div>
  )
}

function Source({ change, state, onUploaded }: {
  change: ChangeRequest; state: MotherPlantState; onUploaded: () => void
}) {
  const qc = useQueryClient()
  const upload = useMutation({
    mutationFn: ({ file, kind }: { file: File; kind: 'general' | 'mother_plant_timing' }) =>
      changesApi.uploadAttachment(change.id, file, { kind }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: motherPlantKey(change.id) })
      onUploaded()
      toast.success('File attached')
    },
    onError: (e: unknown) => toastError(e, 'Could not attach the file'),
  })
  const href = (aid: number) => `${API_BASE_URL}/v1/changes/${change.id}/attachments/${aid}/download`
  // Their timing seeds the plan at approval; after that it is a record.
  const timingOpen = ['captured', 'scoping'].includes(change.status)
  return (
    <section className={card} data-testid="mother-plant-source">
      <h3 className="text-xs uppercase tracking-wide text-slate-400">{plantText('mp.from', state.mother_plant_name)}</h3>
      <dl className="mt-2 grid gap-x-6 gap-y-2 text-sm sm:grid-cols-3">
        <div>
          <dt className="text-xs text-slate-400">{t('mp.plantLabel')}</dt>
          <dd className="text-slate-100">{state.mother_plant_name ?? '-'}</dd>
        </div>
        <div>
          <dt className="text-xs text-slate-400">Their reference</dt>
          <dd className="font-mono text-slate-100">{state.mother_plant_ref ?? '-'}</dd>
        </div>
        <div>
          <dt className="text-xs text-slate-400">SOP</dt>
          <dd className="text-slate-100" data-testid="mother-plant-sop-date">
            {formatCalendarDate(state.mother_plant_sop)}
            <span className="ml-2 text-xs text-slate-400">
              {change.release_due_date ? 'is the release deadline' : 'becomes the release deadline at approval'}
            </span>
          </dd>
        </div>
      </dl>

      <div className="mt-4 grid gap-4 sm:grid-cols-2">
        <div>
          <p className="text-xs text-slate-400">Their documents</p>
          {state.documents.length === 0 ? (
            <p className="mt-1 text-sm text-slate-400">No documents yet.</p>
          ) : (
            <ul className="mt-1 space-y-0.5 text-sm">
              {state.documents.map((d) => (
                <li key={d.id}>
                  <a className="text-sky-300 hover:underline" href={href(d.id)} download={d.filename}>{d.filename}</a>
                  <span className="ml-2 text-xs text-slate-400">{formatDate(d.created_at)}{d.uploaded_by_name ? `, ${d.uploaded_by_name}` : ''}</span>
                </li>
              ))}
            </ul>
          )}
          <label className="mt-2 inline-block cursor-pointer text-xs text-sky-300 hover:underline">
            Add a document
            <input type="file" className="hidden" aria-label={plantText('mp.addDocument', state.mother_plant_name)}
              onChange={(e) => { const f = e.target.files?.[0]; if (f) upload.mutate({ file: f, kind: 'general' }); e.target.value = '' }} />
          </label>
        </div>
        <div>
          <p className="text-xs text-slate-400">Their timing (MS Project)</p>
          {state.timing_attachment ? (
            <p className="mt-1 text-sm">
              <a className="text-sky-300 hover:underline" href={href(state.timing_attachment.id)}
                download={state.timing_attachment.filename} data-testid="mother-plant-timing-file">
                {state.timing_attachment.filename}
              </a>
              <span className="ml-2 text-xs text-slate-400">
                {['captured', 'scoping'].includes(change.status) ? 'seeds the detailed plan at approval' : 'the detailed plan started from it'}
              </span>
            </p>
          ) : (
            <p className="mt-1 text-sm text-slate-400">
              No timing file. The detailed plan starts from the SOP milestone.
            </p>
          )}
          {timingOpen && (
            <label className="mt-2 inline-block cursor-pointer text-xs text-sky-300 hover:underline">
              {state.timing_attachment ? 'Replace the timing file' : 'Attach their timing (.xml)'}
              <input type="file" accept=".xml,application/xml,text/xml" className="hidden"
                aria-label={plantText('mp.attachTiming', state.mother_plant_name)}
                onChange={(e) => { const f = e.target.files?.[0]; if (f) upload.mutate({ file: f, kind: 'mother_plant_timing' }); e.target.value = '' }} />
            </label>
          )}
        </div>
      </div>
    </section>
  )
}

function InformTeam({ change, state, departments, onDone }: {
  change: ChangeRequest; state: MotherPlantState
  departments: { id: number; name: string; is_active?: boolean }[]
  onDone: (s?: MotherPlantState) => void
}) {
  const informed = useMemo(() => new Set(state.receipts.map((r) => r.department_id)), [state.receipts])
  const [picked, setPicked] = useState<Set<number>>(new Set())
  const [message, setMessage] = useState('')
  // The scoping record says who is informed: its departments are the
  // default. Without one, the physical-part routing is.
  const { data: meetings = [] } = useQuery({
    queryKey: ['change-meetings', change.id],
    queryFn: () => changesApi.listMeetings(change.id),
    enabled: change.status === 'scoping',
  })
  const scoped = meetings[meetings.length - 1]?.selected_department_ids ?? []
  const fromScoping = scoped.length > 0
  const defaults = fromScoping ? scoped : state.default_department_ids
  // Pre-pick the default list once, minus the departments already informed.
  const defaultsKey = defaults.join(',')
  useEffect(() => {
    setPicked(new Set(defaults.filter((d) => !informed.has(d))))
  }, [defaultsKey]) // eslint-disable-line react-hooks/exhaustive-deps

  const send = useMutation({
    mutationFn: () => motherPlantApi.sendInfo(change.id, { department_ids: [...picked], message: message.trim() || undefined }),
    onSuccess: (s) => { toast.success('Information sent to the team'); setMessage(''); setPicked(new Set()); onDone(s) },
    onError: (e: unknown) => toastError(e, 'Could not send the information'),
  })
  const active = departments.filter((d) => d.is_active !== false && !informed.has(d.id))
    .sort((a, b) => a.name.localeCompare(b.name))
  const toggle = (did: number) => setPicked((prev) => {
    const next = new Set(prev)
    if (next.has(did)) next.delete(did); else next.add(did)
    return next
  })
  const done = state.receipts.filter((r) => r.acknowledged_at).length

  return (
    <section className={card} data-testid="mother-plant-inform">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-xs uppercase tracking-wide text-slate-400">Inform the team</h3>
        {state.receipts.length > 0 && (
          <span className="text-xs text-slate-400" data-testid="mother-plant-receipt-count">
            {done} of {state.receipts.length} read and understood
          </span>
        )}
      </div>
      <p className="mt-1 text-sm text-slate-300">
        {state.receipts.length === 0
          ? plantText('mp.infoHint', change.mother_plant_name)
          : 'Each informed department confirms "Read and understood". Open confirmations do not hold the change.'}
      </p>

      {state.receipts.length > 0 && (
        <table className="mt-3 w-full text-sm" data-testid="mother-plant-receipts">
          <thead>
            <tr className="text-left text-xs text-slate-400">
              <th className="py-1 pr-3 font-normal">Department</th>
              <th className="py-1 pr-3 font-normal">Sent</th>
              <th className="py-1 pr-3 font-normal">Read and understood</th>
              <th className="py-1 font-normal">Note back</th>
            </tr>
          </thead>
          <tbody>
            {state.receipts.map((r) => (
              <ReceiptRow key={r.id} changeId={change.id} receipt={r}
                mine={state.my_open_receipt_ids.includes(r.id)} onDone={onDone}
                ended={ENDED.includes(change.status)} />
            ))}
          </tbody>
        </table>
      )}

      {state.can_send && active.length > 0 && (
        <div className="mt-4 border-t border-slate-700 pt-3 space-y-2" data-testid="mother-plant-send">
          <p className="text-xs text-slate-400">
            {state.receipts.length > 0 ? 'Inform another department'
              : fromScoping ? 'Departments to inform (preselected: the scoping record)'
                : 'Departments to inform (preselected: the physical-part routing)'}
          </p>
          <div className="flex flex-wrap gap-x-4 gap-y-1.5">
            {active.map((d) => (
              <label key={d.id} className="flex items-center gap-1.5 text-sm text-slate-200">
                <input type="checkbox" checked={picked.has(d.id)} onChange={() => toggle(d.id)} />
                {d.name}
              </label>
            ))}
          </div>
          <textarea aria-label="Message to the team" rows={2} maxLength={2000}
            className="w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm"
            placeholder="What changed and what each team has to do (optional)"
            value={message} onChange={(e) => setMessage(e.target.value)} />
          <button type="button" className={primary} data-testid="mother-plant-send-button"
            disabled={picked.size === 0 || send.isPending} onClick={() => send.mutate()}>
            Send information to {picked.size} department{picked.size === 1 ? '' : 's'}
          </button>
        </div>
      )}
      {!state.can_send && state.receipts.length === 0 && (
        <p className="mt-3 text-sm text-slate-400">Project Management sends the information to the team.</p>
      )}
    </section>
  )
}

/** After the change ended an open confirmation is history, not a to-do. */
const ENDED = ['released', 'closed', 'rejected', 'cancelled']

function ReceiptRow({ changeId, receipt: r, mine, onDone, ended = false }: {
  changeId: number; receipt: MotherPlantState['receipts'][number]; mine: boolean
  onDone: (s?: MotherPlantState) => void
  ended?: boolean
}) {
  const [note, setNote] = useState('')
  const ack = useMutation({
    mutationFn: () => motherPlantApi.acknowledge(changeId, r.id, note.trim() || undefined),
    onSuccess: (s) => { toast.success(`${r.department_name ?? 'Department'}: read and understood`); onDone(s) },
    onError: (e: unknown) => toastError(e, 'Could not confirm'),
  })
  return (
    <tr className="border-t border-slate-700/60 align-top" data-testid={`mother-plant-receipt-${r.department_id}`}>
      <td className="py-1.5 pr-3 text-slate-100">{r.department_name ?? `#${r.department_id}`}</td>
      <td className="py-1.5 pr-3 text-xs text-slate-400">{formatDate(r.sent_at)}{r.sent_by_name ? `, ${r.sent_by_name}` : ''}</td>
      <td className="py-1.5 pr-3">
        {r.acknowledged_at ? (
          <span className="inline-flex flex-wrap items-center gap-1 text-emerald-300">
            <Check aria-hidden="true" size={14} />{r.acknowledged_by_name ?? ''}
            <span className="text-xs text-slate-400">{formatDateTime(r.acknowledged_at)}</span>
          </span>
        ) : ended ? (
          <span className="text-xs text-slate-400" data-testid={`mother-plant-receipt-unconfirmed-${r.department_id}`}>not confirmed</span>
        ) : mine ? (
          <div className="flex flex-wrap items-center gap-2">
            <input aria-label={`Note back from ${r.department_name ?? 'department'}`} maxLength={2000}
              className="w-56 rounded-md border border-slate-700 bg-slate-900 px-2 py-1 text-xs"
              placeholder="Note back (optional)" value={note} onChange={(e) => setNote(e.target.value)} />
            <button type="button" className={small} disabled={ack.isPending} onClick={() => ack.mutate()}
              data-testid={`mother-plant-ack-${r.department_id}`}>
              Read and understood
            </button>
          </div>
        ) : (
          <span className="text-amber-300/90">open</span>
        )}
      </td>
      <td className="py-1.5 text-xs text-slate-300">{r.note ?? ''}</td>
    </tr>
  )
}
