/**
 * One needs-info request, as its own container.
 *
 * Everything on the card belongs to this one question: the documents that
 * explain it, the answer, and the documents behind that answer. Parallel
 * questions are parallel cards, so nothing can be misread as belonging to a
 * different one.
 *
 * Three states, and two different acts: Sales writes the answer (a record of
 * what the customer said — it does not close anything), and the side that asked
 * — or PM — decides the point is settled. Splitting them keeps the person who
 * needed the information in charge of when they have enough of it.
 */
import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { toast } from 'sonner'
import { changesApi } from '../../api/changes'
import AttachmentDropzone from './AttachmentDropzone'
import { AttachmentRow } from './AttachmentRow'
import { t } from '../../i18n/cmLabels'
import type { Attachment, ChangeConcern } from '../../types/change'

const errDetail = (e: unknown): string | undefined =>
  (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail

export default function NeedsInfoCard({
  changeId, concern: c, attachments, canAnswer, canSettle, editable, onChanged, origin,
}: {
  changeId: number
  concern: ChangeConcern
  /** Every attachment on the change; the card takes only its own. */
  attachments: Attachment[]
  /** Sales: may write and rewrite the answer while the question is open. */
  canAnswer: boolean
  /** The asking side or a PM: may declare the point settled. */
  canSettle: boolean
  editable: boolean
  onChanged: () => void
  /** Where the question came from — a meeting decision, typically. */
  origin?: string
}) {
  const [answer, setAnswer] = useState(c.answer_note ?? '')
  const [settling, setSettling] = useState(false)
  const [settleNote, setSettleNote] = useState('')
  const [addingDoc, setAddingDoc] = useState(false)
  // A settled question is history: one line until asked to open.
  const [expanded, setExpanded] = useState(false)

  const mine = attachments.filter((a) => a.concern_id === c.id)
  const answerDocs = mine.filter((a) => a.kind === 'info_response')
  const questionDocs = mine.filter((a) => a.kind !== 'info_response')
  const solved = !c.is_open
  const answered = !!c.answer_note

  const postAnswer = useMutation({
    mutationFn: (note: string) => changesApi.answerConcern(changeId, c.id, note.trim()),
    onSuccess: onChanged,
    onError: (e: unknown) => toast.error(errDetail(e) ?? 'Could not record the answer'),
  })
  const settle = useMutation({
    mutationFn: (note: string) => changesApi.withdrawConcern(changeId, c.id, note.trim()),
    onSuccess: () => { setSettling(false); setSettleNote(''); onChanged() },
    onError: (e: unknown) => toast.error(errDetail(e) ?? 'Could not close the question'),
  })

  const docList = (docs: Attachment[], label: string) => (
    <div>
      <p className="text-[11px] uppercase tracking-wide text-slate-500 mb-0.5">{label}</p>
      {docs.length === 0 ? (
        <p className="text-xs text-slate-600">{t('concern.noDocs')}</p>
      ) : (
        <ul className="text-sm">
          {docs.map((a) => (
            <AttachmentRow key={a.id} changeId={changeId} attachment={a} />
          ))}
        </ul>
      )}
    </div>
  )

  if (solved && !expanded) {
    return (
      <button type="button" data-testid={`needs-info-summary-${c.id}`}
        onClick={() => setExpanded(true)}
        className="w-full flex items-baseline gap-2 rounded-lg border border-slate-700 bg-slate-800/40 px-3 py-1.5 text-left hover:bg-slate-800">
        <span aria-hidden className="text-slate-600 flex-shrink-0">●</span>
        <span className="text-sm text-slate-400 truncate">{c.note}</span>
        {c.resolution_note && (
          <span className="text-xs text-slate-500 truncate flex-shrink-0">
            — {t('concern.solvedBy')} {c.resolution_note}
          </span>
        )}
        <span className="ml-auto text-xs text-slate-600 flex-shrink-0">
          {t('scoping.showDetails')}
        </span>
      </button>
    )
  }

  const state = solved ? 'solved' : answered ? 'answered' : 'open'
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
          className={`inline-flex items-center rounded px-1.5 py-0 text-[10px] leading-tight font-medium ${STATE_STYLE[state]}`}>
          {t(STATE_LABEL[state])}
        </span>
        <span className="text-xs text-slate-500">
          {t('concern.asked')} {c.raised_by_name ?? `#${c.raised_by}`}
          {' · '}{new Date(c.raised_at).toLocaleDateString()}
          {origin && ` · ${origin}`}
        </span>
        {solved && (
          <button type="button" onClick={() => setExpanded(false)}
            className="ml-auto text-xs text-slate-500 hover:text-slate-300">
            {t('bucket.collapse')}
          </button>
        )}
      </header>

      <p className={`text-sm ${solved ? '' : 'text-slate-100'}`}>{c.note}</p>

      <div className="space-y-1">
        {docList(questionDocs, t('concern.questionDocs'))}
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

      {/* The answer of record, and — for Sales — the means to write or revise it. */}
      <div className="border-t border-slate-700/60 pt-2 space-y-2">
        {answered && (
          <p className="text-sm" data-testid={`needs-info-answer-${c.id}`}>
            <span className="text-slate-500">{t('concern.answer')}: </span>
            {c.answer_note}
            <span className="block text-xs text-slate-500">
              {t('concern.answeredBy')} {c.answered_by_name ?? (c.answered_by != null ? `#${c.answered_by}` : '—')}
              {c.answered_at && ` · ${new Date(c.answered_at).toLocaleDateString()}`}
            </span>
          </p>
        )}
        {answerDocs.length > 0 && docList(answerDocs, t('concern.answerDocs'))}

        {!solved && editable && (
          <>
            <textarea value={answer} rows={2}
              data-testid={`needs-info-answer-note-${c.id}`}
              disabled={!canAnswer}
              onChange={(e) => setAnswer(e.target.value)}
              placeholder={t('concern.answerPlaceholder')} aria-label={t('concern.answer')}
              className="w-full bg-slate-900 border border-slate-600 rounded px-2 py-1 text-xs text-slate-100 disabled:opacity-50" />
            <div className="flex flex-wrap items-center gap-2">
              <button type="button" data-testid={`needs-info-answer-submit-${c.id}`}
                className="bg-sky-600 hover:bg-sky-500 text-white px-2.5 py-1 rounded text-xs disabled:opacity-50 disabled:cursor-not-allowed"
                disabled={!canAnswer || !answer.trim() || postAnswer.isPending}
                title={canAnswer ? undefined : t('concern.salesAnswers')}
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
        c.resolution_note && (
          <p className="text-sm border-t border-slate-700 pt-2" data-testid={`needs-info-resolution-${c.id}`}>
            <span className="text-slate-500">{t('concern.solvedBy')} </span>
            {c.resolution_note}
          </p>
        )
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
                className="bg-emerald-700 hover:bg-emerald-600 text-white px-2.5 py-1 rounded text-xs disabled:opacity-50"
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
              className="bg-emerald-700 hover:bg-emerald-600 text-white px-2.5 py-1 rounded text-xs disabled:opacity-50 disabled:cursor-not-allowed"
              disabled={!canSettle}
              title={canSettle ? undefined : t('concern.closerOnly')}
              onClick={() => { setSettling(true); setSettleNote(c.answer_note ?? '') }}>
              {t('concern.markSolved')}
            </button>
          )}
        </div>
      )}
    </article>
  )
}
