/**
 * Spec §4 "Check items first" and C8 "Blocked? Ask a question", on top of a
 * department's assessment bucket (switch ASSESSMENT_V2).
 *
 * - "Checks for Process: 3": the check items scoping gave this department,
 *   each with its raise text, what to check and who raised it. The
 *   department closes each inline, nothing preselected: Answered (a number
 *   with its unit, or a reference), Not relevant (checklist row, drawing
 *   reference, outside our scope + who, same as #n) or Assumed (value + unit,
 *   risk if wrong). Open items hold this department's own submit (HARD #10).
 *   The raiser or the lead may reopen a closed one.
 * - Questions this department asked from its assessment: who answers, the
 *   answer when it came, Close when the answer settles it. They hold only this
 *   department's submit too.
 */
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { btnSm } from '../../common/buttonStyles'
import { toastError } from '../../../lib/apiError'
import { changesApi } from '../../../api/changes'
import { t } from '../../../i18n/cmLabels'
import { formatCalendarDate } from '../../../lib/format'
import CustomerCopy from '../scoping/CustomerCopy'
import AnswerForm from '../scoping/AnswerForm'
import {
  CHECK_WHAT, type AnswerFrom, type Attachment, type ChangeConcern, type CheckWhat,
} from '../../../types/change'

const input = 'bg-slate-900 border border-slate-600 rounded px-2 py-1 text-xs text-slate-100'
type Outcome = '' | 'answered' | 'not_relevant' | 'assumed'
type Basis = '' | 'checklist_row' | 'drawing_ref' | 'outside_scope' | 'same_as'

export const ownsCheck = (c: ChangeConcern, deptId: number) =>
  c.kind === 'needs_info' && c.flag_type === 'check'
  && (c.department_id === deptId || (c.co_department_ids ?? []).includes(deptId))

/** A typed question this department asked (C8). A hold from before C8
 *  (flag_type null) stays in the department's concern strip, answered by a
 *  proposal with its document, as the backend still treats it. */
export const asksFrom = (c: ChangeConcern, deptId: number) =>
  c.kind === 'needs_info' && c.flag_type === 'question' && c.department_id === deptId

export default function AssessmentChecks({
  changeId, departmentId, departmentName, concerns, editable, onChanged,
  attachments = [], confirmerName = null,
}: {
  /** The change's attachments: an answerer picks the filed customer mail. */
  attachments?: Attachment[]
  /** Who confirms an Assumed answer by default (Sales contact, else lead). */
  confirmerName?: string | null
  changeId: number
  departmentId: number
  departmentName: string
  concerns: ChangeConcern[]
  /** The viewer works for this department and the assessment is open. */
  editable: boolean
  onChanged?: () => void
}) {
  const qc = useQueryClient()
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ['change', changeId, 'concerns'] })
    qc.invalidateQueries({ queryKey: ['change', changeId] })
    onChanged?.()
  }
  const checks = concerns.filter((c) => ownsCheck(c, departmentId))
  const open = checks.filter((c) => c.is_open)
  const closed = checks.filter((c) => !c.is_open)
  const questions = concerns.filter((c) => asksFrom(c, departmentId) && c.is_open)
  const others = concerns.filter((c) => c.kind === 'needs_info')
  if (!checks.length && !questions.length && !editable) return null

  return (
    <div className="space-y-2" data-testid={`achk-${departmentId}`}>
      {checks.length > 0 && (
        <div className="rounded border border-amber-800/60 bg-amber-950/20 p-2 space-y-2">
          <p className="text-xs font-semibold text-amber-200" data-testid={`achk-title-${departmentId}`}>
            {t('achk.title').replace('{d}', departmentName).replace('{n}', String(open.length))}
          </p>
          {open.length > 0 && editable && (
            <p className="text-[11px] text-amber-300/80">{t('achk.holds')}</p>
          )}
          {open.map((c) => (
            <CheckRow key={c.id} changeId={changeId} departmentId={departmentId} c={c}
              others={others.filter((o) => o.id !== c.id)} onDone={refresh} />
          ))}
          {closed.map((c) => (
            <ClosedCheck key={c.id} changeId={changeId} c={c} onDone={refresh}
              attachments={attachments} />
          ))}
        </div>
      )}
      {questions.map((q) => (
        <QuestionRow key={q.id} changeId={changeId} q={q} editable={editable} onDone={refresh}
          attachments={attachments} confirmerName={confirmerName} />
      ))}
      {editable && <AskQuestion changeId={changeId} departmentId={departmentId} onDone={refresh} />}
    </div>
  )
}

function Head({ c }: { c: ChangeConcern }) {
  return (
    <p className="text-xs text-slate-200">
      <span className="text-slate-500">#{c.id} </span>{c.note}
      <span className="text-slate-500">
        {' · '}{t(`flag.what.${c.check_what ?? 'other'}`)}
        {c.part_number ? ` · ${c.part_number}` : ''}
        {c.raised_by_name ? ` · ${t('flag.byRaiser').replace('{x}', c.raised_by_name)}` : ''}
        {/* R5: an open check item names its due (the department's assessment due) */}
        {c.is_open && c.owner_due ? ` · ${t('flag.due').replace('{d}', formatCalendarDate(c.owner_due))}` : ''}
      </span>
    </p>
  )
}

function CheckRow({ changeId, departmentId, c, others, onDone }: {
  changeId: number; departmentId: number; c: ChangeConcern
  others: ChangeConcern[]; onDone: () => void
}) {
  const [outcome, setOutcome] = useState<Outcome>('')
  const [value, setValue] = useState('')
  const [unit, setUnit] = useState('')
  const [ref, setRef] = useState('')
  const [basis, setBasis] = useState<Basis>('')
  const [row, setRow] = useState('')
  const [who, setWho] = useState('')
  const [sameAs, setSameAs] = useState<number | ''>('')
  const [risk, setRisk] = useState('')
  const { data: rows = [] } = useQuery({
    queryKey: ['assessment-checklist', departmentId],
    queryFn: () => changesApi.assessmentChecklist(departmentId),
    enabled: basis === 'checklist_row',
  })
  const save = useMutation({
    mutationFn: () => changesApi.closeCheck(changeId, c.id, {
      outcome: outcome as Exclude<Outcome, ''>,
      ...(value.trim() ? { value: value.trim() } : {}),
      ...(unit.trim() ? { unit: unit.trim() } : {}),
      ...(ref.trim() ? { ref: ref.trim() } : {}),
      ...(outcome === 'not_relevant' ? { basis: basis || undefined } : {}),
      ...(basis === 'checklist_row' && row ? { checklist_key: row } : {}),
      ...(basis === 'outside_scope' ? { who: who.trim() } : {}),
      ...(basis === 'same_as' && sameAs !== '' ? { same_as_id: sameAs } : {}),
      ...(outcome === 'assumed' ? { assumed_risk: risk.trim() } : {}),
    }),
    onSuccess: onDone,
    onError: (e: unknown) => { toastError(e, t('achk.saveFailed')) },
  })
  // What still stops the save, in words (the backend says the same).
  const missing = !outcome ? t('achk.missingOutcome')
    : outcome === 'answered' && !(value.trim() && unit.trim()) && ref.trim().length < 5
      ? t('achk.missingEvidence')
      : outcome === 'not_relevant' && (!basis
          || (basis === 'checklist_row' && !row)
          || (basis === 'drawing_ref' && ref.trim().length < 5)
          || (basis === 'outside_scope' && who.trim().length < 3)
          || (basis === 'same_as' && sameAs === ''))
        ? t('achk.missingBasis')
        : outcome === 'assumed' && (!value.trim() || risk.trim().length < 5)
          ? t('achk.missingAssumed') : null
  return (
    <div className="rounded bg-slate-900/50 p-2 space-y-1.5" data-testid={`achk-item-${c.id}`}>
      <Head c={c} />
      {c.can_check && (
        <>
          <div role="radiogroup" aria-label={t('achk.found')} className="flex flex-wrap gap-3 text-xs">
            {(['answered', 'not_relevant', 'assumed'] as const).map((o) => (
              <label key={o} className="inline-flex items-center gap-1 text-slate-200">
                <input type="radio" name={`achk-o-${c.id}`} checked={outcome === o}
                  data-testid={`achk-outcome-${c.id}-${o}`}
                  onChange={() => setOutcome(o)} />
                {t(`achk.outcome.${o}`)}
              </label>
            ))}
          </div>
          {(outcome === 'answered' || outcome === 'assumed') && (
            <div className="flex flex-wrap gap-2 items-center">
              <input className={`${input} w-24`} value={value} aria-label={t('answer.value')}
                data-testid={`achk-value-${c.id}`}
                placeholder={t('answer.valuePlaceholder')} onChange={(e) => setValue(e.target.value)} />
              <input className={`${input} w-20`} value={unit} aria-label={t('answer.unit')}
                data-testid={`achk-unit-${c.id}`}
                placeholder={t('answer.unit')} onChange={(e) => setUnit(e.target.value)} />
              {outcome === 'answered' && (
                <input className={`${input} flex-1 min-w-[10rem]`} value={ref}
                  aria-label={t('answer.ref')} data-testid={`achk-ref-${c.id}`}
                  placeholder={t('achk.refPlaceholder')} onChange={(e) => setRef(e.target.value)} />
              )}
            </div>
          )}
          {outcome === 'assumed' && (
            <input className={`${input} w-full`} value={risk} aria-label={t('answer.risk')}
              data-testid={`achk-risk-${c.id}`}
              placeholder={t('answer.risk')} onChange={(e) => setRisk(e.target.value)} />
          )}
          {outcome === 'not_relevant' && (
            <div className="flex flex-wrap gap-2 items-center">
              <select className={input} value={basis} aria-label={t('achk.why')}
                data-testid={`achk-basis-${c.id}`}
                onChange={(e) => setBasis(e.target.value as Basis)}>
                <option value="">{t('achk.why')}</option>
                {(['checklist_row', 'drawing_ref', 'outside_scope', 'same_as'] as const).map((b) => (
                  <option key={b} value={b}>{t(`achk.basis.${b}`)}</option>
                ))}
              </select>
              {basis === 'checklist_row' && (
                <select className={input} value={row} aria-label={t('achk.basis.checklist_row')}
                  onChange={(e) => setRow(e.target.value)}>
                  <option value="">…</option>
                  {rows.map((r) => <option key={r.key} value={r.key}>{r.label_en}</option>)}
                </select>
              )}
              {basis === 'drawing_ref' && (
                <input className={`${input} flex-1`} value={ref} placeholder="DRW-4471 rev C"
                  aria-label={t('achk.basis.drawing_ref')} onChange={(e) => setRef(e.target.value)} />
              )}
              {basis === 'outside_scope' && (
                <input className={`${input} flex-1`} value={who} placeholder={t('achk.whoOwns')}
                  aria-label={t('achk.whoOwns')} onChange={(e) => setWho(e.target.value)} />
              )}
              {basis === 'same_as' && (
                <select className={input} value={sameAs} aria-label={t('achk.basis.same_as')}
                  onChange={(e) => setSameAs(e.target.value ? Number(e.target.value) : '')}>
                  <option value="">…</option>
                  {others.map((o) => <option key={o.id} value={o.id}>#{o.id} {o.note}</option>)}
                </select>
              )}
            </div>
          )}
          <div className="flex items-center gap-2">
            <button type="button" className={btnSm.primary} disabled={!!missing || save.isPending}
              data-testid={`achk-save-${c.id}`} onClick={() => save.mutate()}>
              {t('achk.save')}
            </button>
            {missing && outcome && <span className="text-[11px] text-slate-400">{missing}</span>}
          </div>
        </>
      )}
    </div>
  )
}

function ClosedCheck({ changeId, c, onDone, attachments }: {
  changeId: number; c: ChangeConcern; onDone: () => void; attachments: Attachment[]
}) {
  const [reopening, setReopening] = useState(false)
  const [reason, setReason] = useState('')
  const reopen = useMutation({
    mutationFn: () => changesApi.reopenCheck(changeId, c.id, reason.trim()),
    onSuccess: () => { setReopening(false); setReason(''); onDone() },
    onError: (e: unknown) => { toastError(e, t('achk.saveFailed')) },
  })
  return (
    <div className="text-xs text-slate-400" data-testid={`achk-closed-${c.id}`}>
      <span className="text-emerald-300">✓ </span>#{c.id} {c.note}
      {c.resolution_note && <span>: {c.resolution_note}</span>}
      {c.withdrawn_by_name && <span className="text-slate-500"> ({c.withdrawn_by_name})</span>}
      {c.can_reopen && !reopening && (
        <button type="button" className="ml-2 underline text-slate-300"
          data-testid={`achk-reopen-${c.id}`} onClick={() => setReopening(true)}>
          {t('achk.reopen')}
        </button>
      )}
      {reopening && (
        <span className="ml-2 inline-flex gap-1">
          <input className={input} value={reason} placeholder={t('achk.reopenWhy')}
            aria-label={t('achk.reopenWhy')} onChange={(e) => setReason(e.target.value)} />
          <button type="button" className={btnSm.secondary} disabled={reason.trim().length < 5}
            onClick={() => reopen.mutate()}>{t('achk.reopen')}</button>
        </span>
      )}
      {/* A3-01: an Assumed check item leaves a confirm item; its named
          confirmer (default the Sales contact) confirms it here, in any live
          status (the backend's can_confirm). */}
      {c.answer_kind === 'assumed' && !c.confirmed_at && (
        <p className="text-amber-200" data-testid={`achk-confirmline-${c.id}`}>
          {t('answer.confirmLine').replace('{who}', c.confirm_by_name ?? '-')
            .replace('{d}', c.confirm_due ? formatCalendarDate(c.confirm_due) : '-')}
        </p>
      )}
      {c.answer_kind === 'assumed' && !c.confirmed_at && c.can_confirm && (
        <div className="mt-1" data-testid={`achk-confirm-${c.id}`}>
          <AnswerForm changeId={changeId} concern={c} attachments={attachments}
            confirming onDone={onDone} />
        </div>
      )}
    </div>
  )
}

function QuestionRow({ changeId, q, editable, onDone, attachments, confirmerName }: {
  changeId: number; q: ChangeConcern; editable: boolean; onDone: () => void
  attachments: Attachment[]; confirmerName: string | null
}) {
  const [note, setNote] = useState('')
  const close = useMutation({
    mutationFn: () => changesApi.withdrawConcern(changeId, q.id, note.trim()),
    onSuccess: () => { setNote(''); onDone() },
    onError: (e: unknown) => { toastError(e, t('achk.saveFailed')) },
  })
  const answer = q.answer_kind === 'assumed'
    ? `${t('answer.assumed')}: ${q.assumed_value ?? ''} ${q.assumed_unit ?? ''}`.trim()
    : q.answer_kind === 'confirmed' ? `${t('answer.confirmed')}: ${q.answer_ref ?? ''}`
      : q.answer_note
  const outside = q.answer_from === 'customer' || q.answer_from === 'supplier'
  const passOn = outside && !!q.can_answer && !q.answered_at && !editable
  return (
    <div className="rounded border border-sky-800/60 bg-sky-950/20 p-2 space-y-1" data-testid={`achk-q-${q.id}`}>
      {/* A3-13: worded by viewer: the asker reads its own question, the
          answerer who asks it, anybody else both */}
      <p className="text-xs text-sky-200 font-semibold" data-testid={`achk-qhead-${q.id}`}>
        {editable
          ? t('achk.question').replace('{who}', t(`flag.from.${q.answer_from ?? 'our_team'}`))
          : q.can_answer && !q.answered_at
            // a customer/supplier question: the heading names who is asked,
            // the step line below what the viewer does (Christoph 2026-10-30)
            ? (outside ? t(`achk.questionTo.${q.answer_from}`)
              : t('achk.asksYou').replace('{d}', q.asking_department_name ?? q.raised_by_name ?? ''))
              + (q.answer_due ? `: ${t('achk.answerBy').replace('{d}', formatCalendarDate(q.answer_due))}` : '')
            : t('achk.asks').replace('{d}', q.asking_department_name ?? q.raised_by_name ?? '')
              .replace('{who}', t(`flag.from.${q.answer_from ?? 'our_team'}`))}
      </p>
      <Head c={q} />
      {q.answered_at ? (
        <p className="text-xs text-slate-200">{t('achk.answer')}: {answer}
          {q.answered_by_name && <span className="text-slate-500"> ({q.answered_by_name})</span>}</p>
      ) : passOn ? (
        <p className="text-xs text-slate-300" data-testid={`achk-qstep-${q.id}`}>
          {t(`achk.passOn.${q.answer_from}`)
            .replace('{d}', q.asking_department_name ?? q.raised_by_name ?? '')}
        </p>
      ) : (
        <p className="text-xs text-slate-400">{t(editable ? 'achk.waiting' : 'achk.waitingOther')}</p>
      )}
      {q.customer_copy && <CustomerCopy text={q.customer_copy} testId={`achk-copy-${q.id}`} />}
      {/* Sales, PM or the asking department answer here (C8): Confirmed or
          Assumed, as for any question. */}
      {q.can_answer && !q.answered_at && (
        <div data-testid={`achk-answer-${q.id}`}>
          <AnswerForm changeId={changeId} concern={q} attachments={attachments}
            confirmerName={confirmerName} onDone={onDone} />
        </div>
      )}
      {editable && (
        <div className="flex gap-2 items-center">
          <input className={`${input} flex-1`} value={note} placeholder={t('achk.closeNote')}
            aria-label={t('achk.closeNote')} data-testid={`achk-qnote-${q.id}`}
            onChange={(e) => setNote(e.target.value)} />
          <button type="button" className={btnSm.secondary} disabled={!note.trim() || close.isPending}
            data-testid={`achk-qclose-${q.id}`} onClick={() => close.mutate()}>
            {t('achk.closeQuestion')}
          </button>
        </div>
      )}
    </div>
  )
}

function AskQuestion({ changeId, departmentId, onDone }: {
  changeId: number; departmentId: number; onDone: () => void
}) {
  const [opened, setOpened] = useState(false)
  const [note, setNote] = useState('')
  const [what, setWhat] = useState<CheckWhat | ''>('')
  const [from, setFrom] = useState<AnswerFrom | ''>('')
  const ask = useMutation({
    mutationFn: () => changesApi.raiseConcern(changeId, {
      kind: 'needs_info', note: note.trim(), department_id: departmentId,
      flag_type: 'question', check_what: what as CheckWhat, answer_from: from as AnswerFrom,
    }),
    onSuccess: () => { setOpened(false); setNote(''); setWhat(''); setFrom(''); onDone() },
    onError: (e: unknown) => { toastError(e, t('achk.saveFailed')) },
  })
  if (!opened) {
    return (
      <button type="button" className="text-xs underline text-sky-300"
        data-testid={`achk-ask-${departmentId}`} onClick={() => setOpened(true)}>
        {t('achk.ask')}
      </button>
    )
  }
  return (
    <div className="rounded border border-slate-700 p-2 space-y-1.5" data-testid={`achk-askform-${departmentId}`}>
      <p className="text-[11px] text-slate-400">{t('achk.askHint')}</p>
      <input className={`${input} w-full`} value={note} placeholder={t('achk.askPlaceholder')}
        aria-label={t('achk.askPlaceholder')} data-testid={`achk-asknote-${departmentId}`}
        onChange={(e) => setNote(e.target.value)} />
      <div className="flex flex-wrap gap-2">
        <select className={input} value={what} aria-label={t('flag.checkWhat')}
          data-testid={`achk-askwhat-${departmentId}`}
          onChange={(e) => setWhat(e.target.value as CheckWhat)}>
          <option value="">{t('flag.checkWhat')}</option>
          {CHECK_WHAT.map((w) => <option key={w} value={w}>{t(`flag.what.${w}`)}</option>)}
        </select>
        <select className={input} value={from} aria-label={t('flag.answerFrom')}
          data-testid={`achk-askfrom-${departmentId}`}
          onChange={(e) => setFrom(e.target.value as AnswerFrom)}>
          <option value="">{t('flag.answerFrom')}</option>
          {(['customer', 'our_team', 'supplier'] as const).map((f) => (
            <option key={f} value={f}>{t(`flag.from.${f}`)}</option>
          ))}
        </select>
        <button type="button" className={btnSm.primary}
          disabled={!note.trim() || !what || !from || ask.isPending}
          data-testid={`achk-asksend-${departmentId}`} onClick={() => ask.mutate()}>
          {t('flag.addQuestion')}
        </button>
        <button type="button" className={btnSm.secondary} onClick={() => setOpened(false)}>
          {t('achk.cancel')}
        </button>
      </div>
    </div>
  )
}
