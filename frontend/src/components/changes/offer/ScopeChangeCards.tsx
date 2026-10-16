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
import EvidencePick, { pickBody, pickNeedsTick } from './EvidencePick'
import CustomerCopy from '../scoping/CustomerCopy'

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
  const [fromCustomer, setFromCustomer] = useState(false)
  const save = useCardMutation(changeId, () => changesApi.requestScopeChange(changeId, {
    what: what.trim(), ...(part.trim() ? { part_number: part.trim() } : {}),
    ...(by ? { expects_by: by } : {}),
    ...(mail ? pickBody(attachments, mail) : { ref: ref.trim() }),
  }), onDone)
  const ok = what.trim().length >= 5
    && (mail ? (!pickNeedsTick(attachments, mail) || fromCustomer) : ref.trim().length >= 5)
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
        <EvidencePick id={`scope-mail-${changeId}`} testId="scope-mail" label={t('sc.mail')}
          attachments={attachments} value={mail} onChange={setMail}
          fromCustomer={fromCustomer} onFromCustomer={setFromCustomer} />
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

function Card({ card, changeId, status, canRequest, mayDecide, isSales, myDepartmentIds, routed, attachments }: ScopeChangeCardsProps & { card: ScopeChangeCard }) {
  const [picked, setPicked] = useState<number[]>(routed.map((r) => r.id))
  const [note, setNote] = useState('')
  const [toldRef, setToldRef] = useState('')
  const decide = useCardMutation(changeId, (v: { decision: 'accept' | 'refuse' | 'new_change' }) =>
    changesApi.decideScopeChange(changeId, card.id, {
      decision: v.decision, ...(v.decision === 'accept' ? { department_ids: picked } : {}),
      ...(note.trim() ? { note: note.trim() } : {}),
    }))
  const recosted = useCardMutation(changeId, (v: { d: number; note?: string }) =>
    changesApi.scopeRecosted(changeId, card.id, v.d, v.note), () => { setNoCostFor(null); setNoCost('') })
  // R4: re-costed means the costing moved; else "no cost impact" and why
  const [noCostFor, setNoCostFor] = useState<number | null>(null)
  const [noCost, setNoCost] = useState('')
  const told = useCardMutation(changeId, () => changesApi.scopeTold(changeId, card.id, toldRef.trim()))
  // §6 step 1: missing info is a question to the customer (Sales owns it)
  const [askOpen, setAskOpen] = useState(false)
  const [askText, setAskText] = useState('')
  const ask = useCardMutation(changeId, () => changesApi.scopeAsk(changeId, card.id, askText.trim()),
    () => { setAskOpen(false); setAskText('') })
  const [answer, setAnswer] = useState('')
  const [ansMail, setAnsMail] = useState('')
  const [ansRef, setAnsRef] = useState('')
  const [ansFromCustomer, setAnsFromCustomer] = useState(false)
  const fileAnswer = useCardMutation(changeId, () => changesApi.scopeAnswer(changeId, card.id, {
    answer: answer.trim(), ...(ansMail ? pickBody(attachments, ansMail) : { ref: ansRef.trim() }),
  }))
  const answerOk = answer.trim().length >= 2
    && (ansMail ? (!pickNeedsTick(attachments, ansMail) || ansFromCustomer) : ansRef.trim().length >= 5)
  const question = card.question
  const questionOpen = !!question?.open
  const step = STEP[card.status]
  const postApproval = ['approved', 'in_implementation', 'in_validation'].includes(status)
  return (
    <div data-testid={`scope-card-${card.id}`} className={`space-y-1.5 rounded border p-2 text-xs ${OPEN.has(card.status)
      ? 'border-amber-900/70 bg-amber-950/10' : 'border-slate-700 bg-slate-900/30'}`}>
      <div className="flex flex-wrap items-baseline gap-2">
        <span className="font-medium text-slate-100">#{card.id}{card.part_number ? ` ${card.part_number}` : ''}</span>
        <span className="text-slate-300">{card.what}</span>
        <span data-testid={`scope-status-${card.id}`} className="ml-auto rounded border border-slate-600 px-1.5 text-[11px] text-slate-300">
          {t(card.status === 'ready' && card.no_cost ? 'sc.status.readyNoCost' : `sc.status.${card.status}`)}{card.kind !== 'customer' ? ` · ${t(`sc.kind.${card.kind}`)}` : ''}
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
        <p className="text-sky-200">{card.no_cost ? t('sc.readyNoCost')
          : postApproval ? t('sc.readySupplement') : t('sc.readyOffer')}</p>
      )}
      {card.status === 'accepted' && card.told_at && !card.offer_id && (
        <p className="text-slate-400">{fill('sc.noCostDone', { d: formatCalendarDate(card.told_at), ref: card.told_ref ?? '' })}</p>
      )}
      {question && (
        <div data-testid={`scope-question-${card.id}`} className="space-y-1">
          <p className={questionOpen ? 'text-amber-200' : 'text-slate-400'}>
            {fill('sc.question', { who: question.by_name ?? '-', q: question.text })}
          </p>
          {questionOpen && <p className="text-[11px] text-slate-500">{t('sc.questionWaits')}</p>}
          {!questionOpen && question.answer && (
            <p className="text-slate-300">{fill('sc.answered', { ref: question.ref ?? '', a: question.answer })}</p>
          )}
          {questionOpen && isSales && question.customer_copy && (
            <CustomerCopy text={question.customer_copy} testId={`scope-question-copy-${card.id}`} />
          )}
          {questionOpen && isSales && (
            <div className="grid gap-2 sm:grid-cols-[auto_minmax(0,1fr)]">
              <label className="self-center text-xs text-slate-400" htmlFor={`scope-answer-${card.id}`}>{t('sc.answer')}</label>
              <input id={`scope-answer-${card.id}`} data-testid={`scope-answer-${card.id}`} value={answer}
                onChange={(e) => setAnswer(e.target.value)} className={inputCls} />
              <label className="self-center text-xs text-slate-400" htmlFor={`scope-answer-mail-${card.id}`}>{t('sc.mail')}</label>
              <div className="flex flex-wrap gap-2">
                <EvidencePick id={`scope-answer-mail-${card.id}`} testId={`scope-answer-mail-${card.id}`} label={t('sc.mail')}
                  attachments={attachments} value={ansMail} onChange={setAnsMail}
                  fromCustomer={ansFromCustomer} onFromCustomer={setAnsFromCustomer} />
                <input data-testid={`scope-answer-ref-${card.id}`} value={ansRef} disabled={!!ansMail}
                  onChange={(e) => setAnsRef(e.target.value)} aria-label={t('sc.ref')} placeholder={t('sc.ref')}
                  className={`${inputCls} min-w-0 flex-1`} />
              </div>
              <div className="flex justify-end sm:col-span-2">
                <button type="button" data-testid={`scope-answer-save-${card.id}`} disabled={!answerOk || fileAnswer.isPending}
                  onClick={() => fileAnswer.mutate(undefined)} className={buttonClass('primary', 'sm')}>
                  {t('sc.answerSave')}
                </button>
              </div>
            </div>
          )}
        </div>
      )}
      {card.status === 'requested' && !questionOpen && (mayDecide || canRequest) && (
        <div className="space-y-1">
          <button type="button" data-testid={`scope-ask-open-${card.id}`} aria-expanded={askOpen}
            onClick={() => setAskOpen((o) => !o)} className="text-[11px] text-sky-300 underline">
            {t('sc.ask')}
          </button>
          {askOpen && (
            <div className="flex flex-wrap gap-2">
              <input value={askText} onChange={(e) => setAskText(e.target.value)} data-testid={`scope-ask-text-${card.id}`}
                aria-label={t('sc.askText')} placeholder={t('sc.askText')} className={`${inputCls} min-w-0 flex-1`} />
              <button type="button" data-testid={`scope-ask-save-${card.id}`}
                disabled={ask.isPending || askText.trim().length < 10}
                onClick={() => ask.mutate(undefined)} className={buttonClass('secondary', 'sm')}>
                {t('sc.askSave')}
              </button>
            </div>
          )}
        </div>
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
            <button type="button" data-testid={`scope-accept-${card.id}`} disabled={decide.isPending || picked.length === 0 || questionOpen}
              title={questionOpen ? t('sc.questionWaits') : undefined}
              onClick={() => decide.mutate({ decision: 'accept' })} className={buttonClass('primary', 'sm')}>
              {t('sc.accept')}
            </button>
          </div>
        </div>
      )}

      {card.status === 'recosting' && card.departments.filter((d) => !d.done && myDepartmentIds.includes(d.id)).map((d) => (
        <div key={d.id} className="space-y-1">
          <div className="flex flex-wrap items-center gap-2">
            <button type="button" data-testid={`scope-recosted-${card.id}-${d.id}`} disabled={recosted.isPending}
              onClick={() => recosted.mutate({ d: d.id })} className={buttonClass('primary', 'sm')}>
              {fill('sc.recosted', { dept: d.name })}
            </button>
            <button type="button" data-testid={`scope-nocost-open-${card.id}-${d.id}`} aria-expanded={noCostFor === d.id}
              onClick={() => setNoCostFor((x) => (x === d.id ? null : d.id))} className={buttonClass('secondary', 'sm')}>
              {t('sc.noCost')}
            </button>
            <span className="text-[11px] text-slate-500">{t('sc.recostedHelp')}</span>
          </div>
          {noCostFor === d.id && (
            <div className="flex flex-wrap gap-2">
              <input value={noCost} onChange={(e) => setNoCost(e.target.value)} data-testid={`scope-nocost-note-${card.id}-${d.id}`}
                aria-label={t('sc.noCostWhy')} placeholder={t('sc.noCostWhy')} className={`${inputCls} min-w-0 flex-1`} />
              <button type="button" data-testid={`scope-nocost-${card.id}-${d.id}`}
                disabled={recosted.isPending || noCost.trim().length < 15}
                onClick={() => recosted.mutate({ d: d.id, note: noCost.trim() })} className={buttonClass('primary', 'sm')}>
                {fill('sc.noCostConfirm', { dept: d.name })}
              </button>
            </div>
          )}
        </div>
      ))}

      {card.status === 'ready' && card.no_cost && isSales && (
        <div className="flex flex-wrap gap-2">
          <input value={toldRef} onChange={(e) => setToldRef(e.target.value)} data-testid={`scope-nocost-ref-${card.id}`}
            aria-label={t('sc.noCostRef')} placeholder={t('sc.noCostRef')} className={`${inputCls} min-w-0 flex-1`} />
          <button type="button" data-testid={`scope-nocost-told-${card.id}`} disabled={told.isPending || toldRef.trim().length < 5}
            onClick={() => told.mutate(undefined)} className={buttonClass('primary', 'sm')}>
            {t('sc.noCostTold')}
          </button>
        </div>
      )}
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
