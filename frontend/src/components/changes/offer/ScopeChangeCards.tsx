/**
 * The scope change card (ECR-solid spec §6 [R3]): from 'quoted' on the
 * customer adds or changes something. Three steps, an owner each:
 * requested (Sales: P/N, what, by when, the customer's mail) -> re-costed
 * (the lead accepts with the departments to re-cost, or refuses; each
 * department marks its part done) -> accepted (the next offer or supplement
 * carries it; the customer's answer settles it). No prices on the card: every
 * viewer reads it.
 */
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { changesApi } from '../../../api/changes'
import { toastError } from '../../../lib/apiError'
import { formatCalendarDate } from '../../../lib/format'
import { t } from '../../../i18n/cmLabels'
import DateInput from '../../gantt/DateInput'
import { buttonClass } from '../../common/buttonStyles'
import type { Attachment, ScopeChangeCard } from '../../../types/change'
import { inputCls, sectionLabel } from './offerFormat'

const fill = (k: string, v: Record<string, string | number>) =>
  Object.entries(v).reduce((acc, [kk, vv]) => acc.split(`{${kk}}`).join(String(vv)), t(k))

const OPEN = new Set(['requested', 'recosting', 'ready', 'offered'])
const STEP: Record<string, number> = { requested: 1, recosting: 2, ready: 2, offered: 3, accepted: 3 }

export interface ScopeChangeCardsProps {
  changeId: number
  status: string
  /** Sales or the run team: "Customer wants to add or change something". */
  canRequest: boolean
  /** The run team decides a requested card. */
  mayDecide: boolean
  isSales: boolean
  myDepartmentIds: number[]
  /** The routed departments (preticked on accept). */
  routed: { id: number; name: string }[]
  attachments: Attachment[]
}

export const scopeKey = (id: number) => ['change', id, 'scope-changes']

export default function ScopeChangeCards(props: ScopeChangeCardsProps) {
  const { changeId, status, canRequest } = props
  const { data: cards = [] } = useQuery({
    queryKey: scopeKey(changeId),
    queryFn: () => changesApi.scopeChanges(changeId),
  })
  const [open, setOpen] = useState(false)
  const inWindow = ['quoted', 'approved', 'in_implementation', 'in_validation'].includes(status)
  if (cards.length === 0 && !(canRequest && inWindow)) return null
  return (
    <section data-testid="scope-changes" className="space-y-2 rounded-lg border border-slate-700 bg-slate-900/50 p-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className={sectionLabel}>{t('sc.title')}</span>
        {canRequest && inWindow && (
          <button type="button" data-testid="scope-request-open" onClick={() => setOpen((o) => !o)}
            aria-expanded={open} className={buttonClass('secondary', 'sm', 'ml-auto')}>
            {t('sc.request')}
          </button>
        )}
      </div>
      {open && <RequestForm {...props} onDone={() => setOpen(false)} />}
      {cards.map((c) => <Card key={c.id} card={c} {...props} />)}
    </section>
  )
}

function useCardMutation<V>(changeId: number, fn: (v: V) => Promise<ScopeChangeCard[]>, onDone?: () => void) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: fn,
    onSuccess: (data) => {
      qc.setQueryData(scopeKey(changeId), data)
      qc.invalidateQueries({ queryKey: ['change', changeId] })
      qc.invalidateQueries({ queryKey: ['change-my-actions', changeId] })
      onDone?.()
    },
    onError: (e: unknown) => toastError(e, t('sc.error')),
  })
}

function RequestForm({ changeId, attachments, onDone }: ScopeChangeCardsProps & { onDone: () => void }) {
  const [part, setPart] = useState('')
  const [what, setWhat] = useState('')
  const [by, setBy] = useState('')
  const [mail, setMail] = useState('')
  const [ref, setRef] = useState('')
  const mails = attachments.filter((a) => ['customer_email', 'customer_file', 'general'].includes(a.kind ?? 'general'))
    .sort((a, b) => b.created_at.localeCompare(a.created_at))
  const save = useCardMutation(changeId, () => changesApi.requestScopeChange(changeId, {
    what: what.trim(), ...(part.trim() ? { part_number: part.trim() } : {}),
    ...(by ? { expects_by: by } : {}),
    ...(mail ? { attachment_id: Number(mail) } : { ref: ref.trim() }),
  }), onDone)
  const ok = what.trim().length >= 5 && (!!mail || ref.trim().length >= 5)
  return (
    <div data-testid="scope-request-form" className="grid gap-2 rounded border border-slate-700 p-2 sm:grid-cols-[auto_minmax(0,1fr)]">
      <label className="self-center text-xs text-slate-400" htmlFor={`scope-part-${changeId}`}>{t('sc.part')}</label>
      <input id={`scope-part-${changeId}`} data-testid="scope-part" value={part} onChange={(e) => setPart(e.target.value)}
        placeholder="886.198" className={inputCls} />
      <label className="self-center text-xs text-slate-400" htmlFor={`scope-what-${changeId}`}>{t('sc.what')}</label>
      <textarea id={`scope-what-${changeId}`} rows={2} data-testid="scope-what" value={what}
        onChange={(e) => setWhat(e.target.value)} placeholder={t('sc.whatPlaceholder')} className={inputCls} />
      <label className="self-center text-xs text-slate-400" htmlFor={`scope-by-${changeId}`}>{t('sc.expectsBy')}</label>
      <DateInput id={`scope-by-${changeId}`} value={by} commitOnChange onChange={setBy} className={`${inputCls} w-44`} />
      <label className="self-center text-xs text-slate-400" htmlFor={`scope-mail-${changeId}`}>{t('sc.mail')}</label>
      <div className="flex flex-wrap gap-2">
        <select id={`scope-mail-${changeId}`} data-testid="scope-mail" value={mail}
          onChange={(e) => setMail(e.target.value)} className={`${inputCls} min-w-0 flex-1`}>
          <option value="">{t('cust.pickMail')}</option>
          {mails.map((m) => <option key={m.id} value={m.id}>{m.filename}</option>)}
        </select>
        <input data-testid="scope-ref" value={ref} disabled={!!mail} onChange={(e) => setRef(e.target.value)}
          aria-label={t('sc.ref')} placeholder={t('sc.ref')} className={`${inputCls} min-w-0 flex-1`} />
      </div>
      <div className="flex justify-end sm:col-span-2">
        <button type="button" data-testid="scope-request-save" disabled={!ok || save.isPending}
          onClick={() => save.mutate(undefined)} className={buttonClass('primary', 'sm')}>
          {t('sc.requestSave')}
        </button>
      </div>
    </div>
  )
}

function Card({ card, changeId, status, mayDecide, isSales, myDepartmentIds, routed }: ScopeChangeCardsProps & { card: ScopeChangeCard }) {
  const [picked, setPicked] = useState<number[]>(routed.map((r) => r.id))
  const [note, setNote] = useState('')
  const [toldRef, setToldRef] = useState('')
  const decide = useCardMutation(changeId, (v: { decision: 'accept' | 'refuse' | 'new_change' }) =>
    changesApi.decideScopeChange(changeId, card.id, {
      decision: v.decision, ...(v.decision === 'accept' ? { department_ids: picked } : {}),
      ...(note.trim() ? { note: note.trim() } : {}),
    }))
  const recosted = useCardMutation(changeId, (d: number) => changesApi.scopeRecosted(changeId, card.id, d))
  const told = useCardMutation(changeId, () => changesApi.scopeTold(changeId, card.id, toldRef.trim()))
  const step = STEP[card.status]
  const postApproval = ['approved', 'in_implementation', 'in_validation'].includes(status)
  return (
    <div data-testid={`scope-card-${card.id}`} className={`space-y-1.5 rounded border p-2 text-xs ${OPEN.has(card.status)
      ? 'border-amber-900/70 bg-amber-950/10' : 'border-slate-700 bg-slate-900/30'}`}>
      <div className="flex flex-wrap items-baseline gap-2">
        <span className="font-medium text-slate-100">#{card.id}{card.part_number ? ` ${card.part_number}` : ''}</span>
        <span className="text-slate-300">{card.what}</span>
        <span data-testid={`scope-status-${card.id}`} className="ml-auto rounded border border-slate-600 px-1.5 text-[11px] text-slate-300">
          {t(`sc.status.${card.status}`)}{card.kind !== 'customer' ? ` · ${t(`sc.kind.${card.kind}`)}` : ''}
        </span>
      </div>
      {step && (
        <ol className="flex flex-wrap gap-3 text-[11px] text-slate-400">
          {[1, 2, 3].map((n) => (
            <li key={n} className={n === step ? 'font-medium text-amber-200' : n < step ? 'text-emerald-300' : ''}>
              {n}. {t(`sc.step${n}`)}
            </li>
          ))}
        </ol>
      )}
      <p className="text-[11px] text-slate-500">
        {fill('sc.meta', { who: card.requested_by_name ?? '-', d: formatCalendarDate(card.requested_at) })}
        {card.expects_by ? ` · ${fill('sc.expects', { d: formatCalendarDate(card.expects_by) })}` : ''}
        {card.evidence_ref ? ` · ${card.evidence_ref}` : ''}
      </p>
      {card.status === 'recosting' && card.waiting_for.length > 0 && (
        <p data-testid={`scope-waiting-${card.id}`} className="text-amber-200">
          {fill('sc.waiting', { list: card.waiting_for.join(', '),
            d: card.recost_due ? formatCalendarDate(card.recost_due) : '-' })}
        </p>
      )}
      {card.status === 'ready' && (
        <p className="text-sky-200">{postApproval ? t('sc.readySupplement') : t('sc.readyOffer')}</p>
      )}
      {card.status === 'refused' && (
        <p className="text-slate-400">{fill('sc.refusedBy', { who: card.decided_by_name ?? '-', why: card.decision_note ?? '' })}
          {card.told_at ? ` · ${fill('sc.toldOn', { d: formatCalendarDate(card.told_at), ref: card.told_ref ?? '' })}` : ''}</p>
      )}
      {card.status === 'moved' && card.new_change_id && (
        <Link to={`/changes/${card.new_change_id}`} className="text-sky-300 underline">{t('sc.movedLink')}</Link>
      )}

      {card.status === 'requested' && mayDecide && (
        <div data-testid={`scope-decide-${card.id}`} className="space-y-1 rounded border border-slate-700 p-2">
          <p className="text-slate-400">{t('sc.pickDepartments')}</p>
          <div className="flex flex-wrap gap-3">
            {routed.map((r) => (
              <label key={r.id} className="flex items-center gap-1 text-slate-200">
                <input type="checkbox" data-testid={`scope-dept-${card.id}-${r.id}`} checked={picked.includes(r.id)}
                  onChange={(e) => setPicked((p) => e.target.checked ? [...p, r.id] : p.filter((x) => x !== r.id))} />
                {r.name}
              </label>
            ))}
          </div>
          <input value={note} onChange={(e) => setNote(e.target.value)} data-testid={`scope-note-${card.id}`}
            aria-label={t('sc.note')} placeholder={t('sc.note')} className={`${inputCls} w-full`} />
          <div className="flex flex-wrap justify-end gap-2">
            {postApproval && card.part_number && (
              <button type="button" data-testid={`scope-new-${card.id}`} disabled={decide.isPending}
                onClick={() => decide.mutate({ decision: 'new_change' })} className={buttonClass('secondary', 'sm')}>
                {t('sc.newChange')}
              </button>
            )}
            <button type="button" data-testid={`scope-refuse-${card.id}`} disabled={decide.isPending || note.trim().length < 5}
              onClick={() => decide.mutate({ decision: 'refuse' })} className={buttonClass('secondary', 'sm')}>
              {t('sc.refuse')}
            </button>
            <button type="button" data-testid={`scope-accept-${card.id}`} disabled={decide.isPending || picked.length === 0}
              onClick={() => decide.mutate({ decision: 'accept' })} className={buttonClass('primary', 'sm')}>
              {t('sc.accept')}
            </button>
          </div>
        </div>
      )}

      {card.status === 'recosting' && card.departments.filter((d) => !d.done && myDepartmentIds.includes(d.id)).map((d) => (
        <button key={d.id} type="button" data-testid={`scope-recosted-${card.id}-${d.id}`} disabled={recosted.isPending}
          onClick={() => recosted.mutate(d.id)} className={buttonClass('primary', 'sm')}>
          {fill('sc.recosted', { dept: d.name })}
        </button>
      ))}

      {card.status === 'refused' && !card.told_at && isSales && (
        <div className="flex flex-wrap gap-2">
          <input value={toldRef} onChange={(e) => setToldRef(e.target.value)} data-testid={`scope-told-ref-${card.id}`}
            aria-label={t('sc.toldRef')} placeholder={t('sc.toldRef')} className={`${inputCls} min-w-0 flex-1`} />
          <button type="button" data-testid={`scope-told-${card.id}`} disabled={told.isPending || toldRef.trim().length < 5}
            onClick={() => told.mutate(undefined)} className={buttonClass('primary', 'sm')}>
            {t('sc.told')}
          </button>
        </div>
      )}
    </div>
  )
}
