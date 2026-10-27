/**
 * One needs-info request, as its own container.
 *
 * Everything on the card belongs to this one question: the documents that
 * explain it, the answer, and the documents behind that answer. Parallel
 * questions are parallel cards, so nothing can be misread as belonging to a
 * different one.
 *
 * Three states, and two different acts: somebody writes the answer (the asking
 * department or the author, Sales or PM; a record, it does not close anything),
 * and the side that asked, or PM, decides the point is settled. Splitting them
 * keeps the person who needed the information in charge of when they have
 * enough of it. The question stays the asking side's task (2026-10-14).
 */
import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { btnSm } from '../common/buttonStyles'
import { toastError } from '../../lib/apiError'
import { changesApi } from '../../api/changes'
import AttachmentDropzone from './AttachmentDropzone'
import { AttachmentRow } from './AttachmentRow'
import { t } from '../../i18n/cmLabels'
import { formatDate, formatCalendarDate } from '../../lib/format'
import AnswerForm from './scoping/AnswerForm'
import CustomerCopy from './scoping/CustomerCopy'
import type { Attachment, ChangeConcern } from '../../types/change'

export default function NeedsInfoCard({
  changeId, concern: c, attachments, canAnswer, canSettle, editable, onChanged, origin,
  askingSide, structured = false, confirmerName,
}: {
  changeId: number
  concern: ChangeConcern
  /** Every attachment on the change; the card takes only its own. */
  attachments: Attachment[]
  /** The asking department (or the author), Sales or PM: may write and
   *  rewrite the answer while the question is open. */
  canAnswer: boolean
  /** Who the question waits on, in words: its department, else its author. */
  askingSide?: string
  /** The asking side or a PM: may declare the point settled. */
  canSettle: boolean
  editable: boolean
  onChanged: () => void
  /** Where the question came from — a meeting decision, typically. */
  origin?: string
  /** C33 (SCOPING_V2): the structured question (what, part, who answers,
   *  what it changes) with the Confirmed / Assumed answer form. */
  structured?: boolean
  /** Who confirms an Assumed answer by default (Sales contact, else lead). */
  confirmerName?: string | null
}) {
  const [answer, setAnswer] = useState(c.answer_note ?? '')
  const [settling, setSettling] = useState(false)
  const [settleNote, setSettleNote] = useState('')
  const [addingDoc, setAddingDoc] = useState(false)
  // One collapse behaviour everywhere: settled questions start as a line, live
  // ones start open — and either can be toggled to the other.
  // an open confirm item keeps the card open: the confirmer acts on it
  const [expanded, setExpanded] = useState(c.is_open || !!c.can_confirm)

  const mine = attachments.filter((a) => a.concern_id === c.id)
  const answerDocs = mine.filter((a) => a.kind === 'info_response')
  const questionDocs = mine.filter((a) => a.kind !== 'info_response')
  const solved = !c.is_open
  // Answered is a fact with a timestamp — the same signal the backend and the
  // wait banner key off, so all three agree on what "answered" means.
  const answered = c.answered_at != null || !!c.answer_note

  const makeCheck = useMutation({
    mutationFn: () => changesApi.setConcernType(changeId, c.id, { flag_type: 'check' }),
    onSuccess: onChanged,
    onError: (e: unknown) => { toastError(e, 'Could not make it a check item') },
  })
  const postAnswer = useMutation({
    mutationFn: (note: string) => changesApi.answerConcern(changeId, c.id, note.trim()),
    onSuccess: onChanged,
    onError: (e: unknown) => { toastError(e, 'Could not record the answer') },
  })
  const settle = useMutation({
    mutationFn: (note: string) => changesApi.withdrawConcern(changeId, c.id, note.trim()),
    onSuccess: () => { setSettling(false); setSettleNote(''); onChanged() },
    onError: (e: unknown) => { toastError(e, 'Could not close the question') },
  })


  // "Solved by <name>": the person who settled it, never the note text.
  const solverName = c.withdrawn_by_name
    ?? (c.withdrawn_by != null && c.withdrawn_by === c.raised_by ? c.raised_by_name : null)
  const solvedByLine = solverName ? `${t('concern.solvedByName')} ${solverName}` : t('concern.solvedPlain')

  const state = !c.is_open ? 'solved' : c.answered_at != null || !!c.answer_note ? 'answered' : 'open'
  const SUMMARY_DOT: Record<string, string> = {
    open: 'text-amber-400', answered: 'text-sky-400', solved: 'text-slate-500',
  }

  if (!expanded) {
    // The same one-liner for every state: the dot carries where it stands, the
    // text carries what it is about.
    const trailing = solved
      ? `${solvedByLine}${c.resolution_note ? `: ${c.resolution_note}` : ''}`
      : c.answer_note
    return (
      <button type="button" data-testid={`needs-info-summary-${c.id}`}
        onClick={() => setExpanded(true)}
        className="w-full flex items-baseline gap-2 rounded-lg border border-slate-700 bg-slate-800/40 px-3 py-1.5 text-left hover:bg-slate-800">
        <span aria-hidden="true" className={`h-2 w-2 flex-shrink-0 rounded-full bg-current ${SUMMARY_DOT[state]}`} />
        <span className="text-sm text-slate-400 truncate">{c.note}</span>
        {trailing && (
          <span className="text-xs text-slate-500 truncate flex-shrink-0">
            {' · '}{trailing}
          </span>
        )}
        <span className="ml-auto text-xs text-slate-600 flex-shrink-0">
          {t('scoping.showDetails')}
        </span>
      </button>
    )
  }

  const STATE_STYLE: Record<string, string> = {
    open: 'bg-amber-900/70 text-amber-200',
    answered: 'bg-sky-900/70 text-sky-200',
    solved: 'bg-slate-700 text-slate-300',
  }
  const STATE_LABEL: Record<string, string> = {
    open: 'concern.awaitingAnswer',
    answered: 'concern.awaitingClosure',
    solved: 'concern.solved',
  }

  return (
    <article data-testid={`needs-info-card-${c.id}`}
      className={`rounded-lg border p-4 space-y-3 ${
        solved
          ? 'border-slate-700 bg-slate-800/40 text-slate-400'
          : answered
            ? 'border-sky-800/60 bg-sky-950/20'
            : 'border-amber-700/60 bg-amber-950/20'}`}>
      <header className="flex items-center gap-2 flex-wrap">
        <span data-testid={`needs-info-state-${c.id}`}
          className={`inline-flex items-center rounded px-1.5 py-0 text-[11px] leading-tight font-medium ${STATE_STYLE[state]}`}>
          {t(STATE_LABEL[state])}
        </span>
        <span className="text-xs text-slate-500" data-testid={`needs-info-asker-${c.id}`}>
          {t('concern.asked')} {c.raised_by_name ?? `#${c.raised_by}`}
          {/* The asker's role: a question from Quality reads differently than
              one from Logistics, so the hat stands next to the name. */}
          {(c.raised_by_departments?.length ?? 0) > 0
            && ` (${c.raised_by_departments!.join(', ')})`}
          {' · '}{formatDate(c.raised_at)}
          {origin && ` · ${origin}`}
        </span>
        <button type="button" data-testid={`needs-info-collapse-${c.id}`}
          onClick={() => setExpanded(false)}
          className="ml-auto text-xs text-slate-500 hover:text-slate-300">
          {t('bucket.collapse')}
        </button>
      </header>

      {/* The question: its text, then the files that ARE the question — the
          slide deck that was sent, the drawing it refers to. No heading between
          them, because they are one thing. */}
      <div className="space-y-1" data-testid={`needs-info-question-${c.id}`}>
        <p className={`text-sm whitespace-pre-wrap ${solved ? '' : 'text-slate-100'}`}>{c.note}</p>
        {structured && (c.check_what || c.answer_from || c.scope_effect) && (
          <p className="text-[11px] text-slate-400" data-testid={`needs-info-structure-${c.id}`}>
            {[c.check_what ? t(`flag.what.${c.check_what}`) : null,
              c.part_number ?? (c.check_what ? t('flag.wholeChange') : null),
              c.answer_from ? `${t('flag.answerFrom')} ${t(`flag.from.${c.answer_from}`)}` : null,
              c.scope_effect ? `${t('flag.scopeEffect')} ${c.scope_effect}` : null,
            ].filter(Boolean).join(' · ')}
          </p>
        )}
        {structured && !solved && c.customer_copy && (canAnswer || c.can_answer) && (
          <CustomerCopy text={c.customer_copy} testId={`needs-info-copy-${c.id}`} />
        )}
        {structured && !solved && editable && c.can_switch && (
          <button type="button" data-testid={`needs-info-make-check-${c.id}`}
            className="text-xs text-sky-300 hover:text-sky-200" disabled={makeCheck.isPending}
            title={t('flag.scopeTest')}
            onClick={() => makeCheck.mutate()}>
            {t('flag.makeCheck')}
          </button>
        )}
        {questionDocs.length > 0 && (
          <ul className="text-sm rounded border border-slate-700/60 bg-slate-900/30 px-2 py-1">
            {questionDocs.map((a) => (
              <AttachmentRow key={a.id} changeId={changeId} attachment={a} />
            ))}
          </ul>
        )}
        {/* Anyone on the team may add what explains the question. */}
        {!solved && editable && (
          addingDoc ? (
            <AttachmentDropzone changeId={changeId} kind="info_request" concernId={c.id}
              compact label={t('attach.requestSlot')}
              onUploaded={() => { setAddingDoc(false); onChanged() }} />
          ) : (
            <button type="button" data-testid={`needs-info-add-doc-${c.id}`}
              className="text-xs text-sky-300 hover:text-sky-200"
              onClick={() => setAddingDoc(true)}>
              {t('concern.addDoc')}
            </button>
          )
        )}
      </div>

      {/* The answer, as one block: what was said and what came with it, under a
          single label — never the text here and its files somewhere else. */}
      <div className="border-t border-slate-700/60 pt-2 space-y-2"
        data-testid={`needs-info-answer-block-${c.id}`}>
        <p className="text-[11px] uppercase tracking-wide text-slate-500">
          {t('concern.answer')}
        </p>
        {c.answer_kind && (
          <p className="text-xs" data-testid={`needs-info-answer-kind-${c.id}`}>
            {c.answer_kind === 'assumed' ? (
              <span className="text-amber-200">
                {t('answer.assumedLine')
                  .replace('{v}', `${c.assumed_value ?? ''}${c.assumed_unit ? ` ${c.assumed_unit}` : ''}`)
                  .replace('{r}', c.assumed_risk ?? '-')}
                {' · '}
                {t('answer.confirmLine').replace('{who}', c.confirm_by_name ?? '-')
                  .replace('{d}', c.confirm_due ? formatCalendarDate(c.confirm_due) : '-')}
              </span>
            ) : (
              <span className="text-emerald-300">
                {t('answer.confirmedLine').replace('{ref}', c.answer_ref ?? t('concern.answerDocs'))}
              </span>
            )}
          </p>
        )}
        {/* The confirm item: its named confirmer, or who may answer, in any
            live status (the backend's can_confirm), question open or closed. */}
        {structured && c.answer_kind === 'assumed' && !c.confirmed_at
          && (c.can_confirm ?? (editable && (canAnswer || c.can_answer))) && (
          <AnswerForm changeId={changeId} concern={c} attachments={attachments}
            confirming onDone={onChanged} />
        )}
        {answered && (
          <p className="text-sm" data-testid={`needs-info-answer-${c.id}`}>
            {c.answer_note}
            <span className="block text-xs text-slate-500">
              {t('concern.answeredBy')} {c.answered_by_name ?? (c.answered_by != null ? `#${c.answered_by}` : '-')}
              {c.answered_at && ` · ${formatDate(c.answered_at)}`}
            </span>
          </p>
        )}
        {answerDocs.length > 0 && (
          <ul className="text-sm rounded border border-slate-700/60 bg-slate-900/30 px-2 py-1">
            {answerDocs.map((a) => (
              <AttachmentRow key={a.id} changeId={changeId} attachment={a} />
            ))}
          </ul>
        )}
        {!answered && answerDocs.length === 0 && !editable && (
          <p className="text-xs text-slate-600">{t('concern.noAnswerYet')}</p>
        )}

        {!solved && editable && !canAnswer && (
          <p className="text-[11px] text-slate-500" data-testid={`needs-info-answer-readonly-${c.id}`}>
            {t('concern.salesAnswersHint').replace(
              '{x}', askingSide ?? c.asking_department_name ?? c.raised_by_name ?? `#${c.raised_by}`)}
          </p>
        )}
        {!solved && editable && canAnswer && structured && !c.answer_kind && (
          <AnswerForm changeId={changeId} concern={c} attachments={attachments}
            confirmerName={confirmerName} onDone={onChanged} />
        )}
        {!solved && editable && canAnswer && !structured && (
          <>
            <textarea value={answer} rows={2}
              data-testid={`needs-info-answer-note-${c.id}`}
              onChange={(e) => setAnswer(e.target.value)}
              placeholder={t('concern.answerPlaceholder')} aria-label={t('concern.answer')}
              className="w-full bg-slate-900 border border-slate-600 rounded px-2 py-1 text-xs text-slate-100 disabled:opacity-50" />
            <div className="flex flex-wrap items-center gap-2">
              <button type="button" data-testid={`needs-info-answer-submit-${c.id}`}
                className={btnSm.primary}
                disabled={!answer.trim() || postAnswer.isPending}
                onClick={() => postAnswer.mutate(answer)}>
                {answered ? t('concern.updateAnswer') : t('concern.submitAnswer')}
              </button>
              <AttachmentDropzone changeId={changeId} kind="info_response" concernId={c.id}
                compact label={t('attach.responseSlot')} onUploaded={onChanged} />
            </div>
            <p className="text-[11px] text-slate-500">{t('concern.answerHint')}</p>
          </>
        )}
      </div>

      {solved ? (
        <p className="text-sm border-t border-slate-700 pt-2" data-testid={`needs-info-resolution-${c.id}`}>
          <span className="text-slate-500" data-testid={`needs-info-solved-by-${c.id}`}>
            {solvedByLine}{c.withdrawn_at ? ` · ${formatDate(c.withdrawn_at)}` : ''}
          </span>
          {c.resolution_note && <span className="block">{c.resolution_note}</span>}
        </p>
      ) : editable && !canSettle ? (
        <p className="border-t border-slate-700/60 pt-2 text-[11px] text-slate-500"
          data-testid={`needs-info-settle-readonly-${c.id}`}>
          {t('concern.closerHint')}
        </p>
      ) : editable && (
        // Closing belongs to whoever needed the information — or to PM.
        <div className="border-t border-slate-700/60 pt-2 space-y-2">
          {settling ? (
            <div className="flex flex-wrap items-center gap-2">
              <input value={settleNote} onChange={(e) => setSettleNote(e.target.value)}
                data-testid={`needs-info-settle-note-${c.id}`}
                placeholder={t('concern.settleNote')} aria-label={t('concern.settleNote')}
                className="flex-1 min-w-[12rem] bg-slate-900 border border-slate-600 rounded px-2 py-1 text-xs text-slate-100" />
              <button type="button" data-testid={`needs-info-settle-confirm-${c.id}`}
                className={btnSm.secondary}
                disabled={!settleNote.trim() || settle.isPending}
                onClick={() => settle.mutate(settleNote)}>
                {t('concern.markSolved')}
              </button>
              <button type="button" className="text-xs text-slate-400 hover:text-slate-200 px-1"
                onClick={() => { setSettling(false); setSettleNote('') }}>
                {t('common.cancel')}
              </button>
            </div>
          ) : (
            <button type="button" data-testid={`needs-info-settle-${c.id}`}
              className={btnSm.secondary}
              onClick={() => { setSettling(true); setSettleNote(c.answer_note ?? '') }}>
              {t('concern.markSolved')}
            </button>
          )}
        </div>
      )}
    </article>
  )
}
