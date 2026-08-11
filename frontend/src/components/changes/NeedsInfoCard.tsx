/**
 * One needs-info request, as its own container.
 *
 * Every element on the card belongs to this one question: the documents that
 * explain it, the answer, and the documents behind that answer. Parallel
 * requests are parallel cards — nothing is shared, so nothing can be misread as
 * belonging to a different question. A settled card mutes itself and keeps the
 * resolution on show, so a stack reads as "these two are done, this one waits".
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
  changeId, concern: c, attachments, canAnswer, isAuthor, editable, onChanged,
}: {
  changeId: number
  concern: ChangeConcern
  /** Every attachment on the change; the card takes only its own. */
  attachments: Attachment[]
  /** Sales may answer and settle the question. */
  canAnswer: boolean
  isAuthor: boolean
  editable: boolean
  onChanged: () => void
}) {
  const [answer, setAnswer] = useState('')
  const [addingDoc, setAddingDoc] = useState(false)
  const mine = attachments.filter((a) => a.concern_id === c.id)
  const answerDocs = mine.filter((a) => a.kind === 'info_response')
  const questionDocs = mine.filter((a) => a.kind !== 'info_response')
  const solved = !c.is_open
  const mayAnswer = editable && (canAnswer || isAuthor)

  const solve = useMutation({
    mutationFn: (note: string) => changesApi.withdrawConcern(changeId, c.id, note.trim()),
    onSuccess: () => { setAnswer(''); onChanged() },
    onError: (e: unknown) => toast.error(errDetail(e) ?? 'Could not settle the question'),
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

  return (
    <article data-testid={`needs-info-card-${c.id}`}
      className={`rounded-lg border p-4 space-y-3 ${
        solved
          ? 'border-slate-700 bg-slate-800/40 text-slate-400'
          : 'border-amber-700/60 bg-amber-950/20'}`}>
      <header className="flex items-center gap-2 flex-wrap">
        <span data-testid={`needs-info-state-${c.id}`}
          className={`inline-flex items-center rounded px-1.5 py-0 text-[10px] leading-tight font-medium ${
            solved ? 'bg-slate-700 text-slate-300' : 'bg-amber-900/70 text-amber-200'}`}>
          {solved ? t('concern.solved') : t('concern.awaitingAnswer')}
        </span>
        <span className="text-xs text-slate-500">
          {t('concern.asked')} {c.raised_by_name ?? `#${c.raised_by}`}
          {' · '}{new Date(c.raised_at).toLocaleDateString()}
        </span>
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

      {solved ? (
        c.resolution_note && (
          <div className="border-t border-slate-700 pt-2 space-y-1">
            <p className="text-sm" data-testid={`needs-info-answer-${c.id}`}>
              <span className="text-slate-500">{t('concern.answer')}: </span>
              {c.resolution_note}
            </p>
            {answerDocs.length > 0 && docList(answerDocs, t('concern.answerDocs'))}
          </div>
        )
      ) : (
        <div className="border-t border-amber-800/40 pt-2 space-y-2">
          {answerDocs.length > 0 && docList(answerDocs, t('concern.answerDocs'))}
          <textarea value={answer} rows={2}
            data-testid={`needs-info-answer-note-${c.id}`}
            disabled={!mayAnswer}
            onChange={(e) => setAnswer(e.target.value)}
            placeholder={t('concern.answerPlaceholder')} aria-label={t('concern.answer')}
            className="w-full bg-slate-900 border border-slate-600 rounded px-2 py-1 text-xs text-slate-100 disabled:opacity-50" />
          <div className="flex flex-wrap items-center gap-2">
            <button type="button" data-testid={`needs-info-solve-${c.id}`}
              className="bg-sky-600 hover:bg-sky-500 text-white px-2.5 py-1 rounded text-xs disabled:opacity-50 disabled:cursor-not-allowed"
              disabled={!mayAnswer || !answer.trim() || solve.isPending}
              title={mayAnswer ? undefined : t('concern.authorOrSales')}
              onClick={() => solve.mutate(answer)}>
              {t('concern.markSolved')}
            </button>
            <AttachmentDropzone changeId={changeId} kind="info_response" concernId={c.id}
              compact label={t('attach.responseSlot')} onUploaded={onChanged} />
          </div>
          <p className="text-[11px] text-slate-500">{t('concern.answerHint')}</p>
        </div>
      )}
    </article>
  )
}
