/**
 * The answer form of a scoping question (C33, spec §0 "Answer form").
 *
 * Nothing is preselected: the answerer says how sure the answer is.
 * - Confirmed: evidence. A customer question only by the customer's mail
 *   (picked from the mails filed on the change) or the customer's document
 *   uploaded into the question; anything else also by a reference.
 * - Assumed: the value as a number with its unit (or "n/a"), the risk if it
 *   is wrong; the Sales contact (else the lead) confirms it within 5 working
 *   days. The assumption goes to the scoping record and creates their task.
 *
 * Also used, with `confirming`, to confirm an open assumption later: the
 * evidence half only.
 */
import { useId, useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { btnSm } from '../../common/buttonStyles'
import { toastError } from '../../../lib/apiError'
import { changesApi } from '../../../api/changes'
import { t } from '../../../i18n/cmLabels'
import AttachmentDropzone from '../AttachmentDropzone'
import ConfirmDialog from '../../common/ConfirmDialog'
import { CONFIRM_EVIDENCE_REQUIRED } from '../../../lib/scopingRules'
import type { AnswerForm as AnswerBody, Attachment, ChangeConcern } from '../../../types/change'

const input = 'bg-slate-900 border border-slate-600 rounded px-2 py-1 text-xs text-slate-100'

export default function AnswerForm({
  changeId, concern: c, attachments, confirmerName, onDone, confirming = false,
}: {
  changeId: number
  concern: ChangeConcern
  /** Every attachment on the change: the filed customer mails are picked from it. */
  attachments: Attachment[]
  /** Who confirms an assumption by default (the Sales contact, else the lead). */
  confirmerName?: string | null
  onDone: () => void
  /** Confirm an open assumption (evidence only) instead of answering. */
  confirming?: boolean
}) {
  const nameId = useId()
  const [kind, setKind] = useState<'' | 'confirmed' | 'assumed'>(confirming ? 'confirmed' : '')
  const [ref, setRef] = useState('')
  const [mailId, setMailId] = useState<number | ''>('')
  const [note, setNote] = useState('')
  const [value, setValue] = useState('')
  const [unit, setUnit] = useState('')
  const [risk, setRisk] = useState('')
  const [askNoFile, setAskNoFile] = useState(false)
  const customer = c.answer_from === 'customer'
  const mails = attachments.filter((a) => a.kind === 'customer_email')
    .sort((a, b) => b.created_at.localeCompare(a.created_at))
  // a customer question: only the customer's own document filed on it
  const docKind = customer ? 'customer_file' : 'info_response'
  const docs = attachments.filter((a) => a.concern_id === c.id
    && (a.kind === 'customer_file' || (!customer && a.kind === 'info_response')))
  const na = ['n/a', 'na'].includes(value.trim().toLowerCase())

  const save = useMutation({
    mutationFn: () => {
      if (confirming) {
        return changesApi.confirmConcern(changeId, c.id, {
          ...(ref.trim() ? { ref: ref.trim() } : {}),
          ...(mailId !== '' ? { mail_id: mailId } : {}),
        })
      }
      const body: AnswerBody = kind === 'confirmed'
        ? { answer_kind: 'confirmed', ...(ref.trim() ? { ref: ref.trim() } : {}),
            ...(mailId !== '' ? { mail_id: mailId } : {}) }
        : { answer_kind: 'assumed', assumed_value: value.trim(),
            ...(na ? {} : { assumed_unit: unit.trim() }), assumed_risk: risk.trim() }
      return changesApi.answerConcernForm(changeId, c.id, {
        ...body, ...(note.trim() ? { note: note.trim() } : {}) })
    },
    onSuccess: () => {
      setKind(confirming ? 'confirmed' : ''); setRef(''); setMailId(''); setNote('')
      setValue(''); setUnit(''); setRisk('')
      onDone()
    },
    onError: (e: unknown) => { toastError(e, 'Could not save the answer') },
  })

  // What still stops the save, in words (the backend says the same).
  const evidence = mailId !== '' || docs.length > 0 || (!customer && ref.trim().length >= 5)
  // 2026-10-28: no proof is a warning (asked once on Save), not a must;
  // the answer or a reference in words carries it then
  const noProof = kind === 'confirmed' && !confirming && !evidence && !CONFIRM_EVIDENCE_REQUIRED
  // nothing filed: no picked mail, no document on the question
  const noFile = kind === 'confirmed' && !confirming && mailId === '' && docs.length === 0
  const missing = kind === ''
    ? [t('answer.pick')]
    : kind === 'confirmed'
      ? (evidence ? []
        : noProof ? (note.trim() || ref.trim() ? [] : [t('answer.inWords')])
          : [customer ? t('answer.mail') : t('answer.ref')])
      : [
          ...(value.trim() && (na || /\d/.test(value)) ? [] : [t('answer.value')]),
          ...(na || unit.trim() ? [] : [t('answer.unit')]),
          ...(risk.trim().length >= 5 ? [] : [t('answer.risk')]),
        ]

  return (
    <div className="space-y-2" data-testid={`answer-form-${c.id}`}>
      {!confirming && (
        <fieldset className="flex flex-wrap items-center gap-3 text-xs">
          <legend className="sr-only">{t('answer.pick')}</legend>
          <span className="text-slate-400">{t('answer.pick')}</span>
          {(['confirmed', 'assumed'] as const).map((k) => (
            <label key={k} className="flex items-center gap-1.5 cursor-pointer">
              <input type="radio" name={`answer-kind-${nameId}`} checked={kind === k}
                data-testid={`answer-kind-${k}-${c.id}`} onChange={() => setKind(k)} />
              <span className="text-slate-200">{t(`answer.${k}`)}</span>
            </label>
          ))}
        </fieldset>
      )}
      {kind === 'confirmed' && (
        <div className="space-y-1.5">
          {customer && CONFIRM_EVIDENCE_REQUIRED && (
            <p className="text-[11px] text-amber-300/90" data-testid={`answer-customer-rule-${c.id}`}>
              {t('answer.customerRule')}
            </p>
          )}
          <div className="flex flex-wrap items-center gap-2">
            {mails.length > 0 ? (
              <select value={mailId} aria-label={t('answer.mail')} data-testid={`answer-mail-${c.id}`}
                onChange={(e) => setMailId(e.target.value ? Number(e.target.value) : '')}
                className={`${input} max-w-[18rem]`}>
                <option value="">{t('answer.mailPick')}</option>
                {mails.map((m) => <option key={m.id} value={m.id}>{m.filename}</option>)}
              </select>
            ) : customer && (
              <span className="text-[11px] text-slate-500">{t('answer.noMails')}</span>
            )}
            {!customer && (
              <input value={ref} onChange={(e) => setRef(e.target.value)}
                aria-label={t('answer.ref')} placeholder={t('answer.refPlaceholder')}
                data-testid={`answer-ref-${c.id}`} className={`${input} flex-1 min-w-[12rem]`} />
            )}
          </div>
        </div>
      )}
      {kind === 'assumed' && (
        <div className="space-y-1.5">
          <div className="flex flex-wrap items-center gap-2">
            <input value={value} onChange={(e) => setValue(e.target.value)}
              aria-label={t('answer.value')} placeholder={t('answer.valuePlaceholder')}
              data-testid={`answer-value-${c.id}`} className={`${input} w-28`} />
            <input value={unit} onChange={(e) => setUnit(e.target.value)} disabled={na}
              aria-label={t('answer.unit')} placeholder={t('answer.unit')}
              data-testid={`answer-unit-${c.id}`} className={`${input} w-24 disabled:opacity-40`} />
            <input value={risk} onChange={(e) => setRisk(e.target.value)}
              aria-label={t('answer.risk')} placeholder={t('answer.risk')}
              data-testid={`answer-risk-${c.id}`} className={`${input} flex-1 min-w-[12rem]`} />
          </div>
          <p className="text-[11px] text-slate-500" data-testid={`answer-confirm-by-${c.id}`}>
            {t('answer.confirmBy').replace('{who}', confirmerName || t('answer.salesOwner'))
              .replace('{d}', '+5 wd')}
          </p>
        </div>
      )}
      {/* a closed question takes no more documents: the filed mail or a
          reference confirms it then. Assumed takes them too (2026-10-28:
          more info behind the assumption) */}
      {kind !== '' && c.is_open && (
        <AttachmentDropzone changeId={changeId} kind={docKind} concernId={c.id}
          compact label={t(customer ? 'answer.customerDocSlot' : 'answer.ourDocSlot')}
          onUploaded={onDone} />
      )}
      {noProof && (
        <p role="note" className="text-[11px] text-amber-300/90" data-testid={`answer-no-proof-${c.id}`}>
          {t(customer ? 'answer.noProofCustomer' : 'answer.noProof')}
        </p>
      )}
      {kind !== '' && !confirming && (
        <input value={note} onChange={(e) => setNote(e.target.value)}
          aria-label={t('answer.note')} placeholder={t(noProof ? 'answer.inWords' : 'answer.note')}
          className={`${input} w-full`} />
      )}
      {kind !== '' && (
        <div className="flex flex-wrap items-center gap-2">
          <button type="button" className={btnSm.primary} data-testid={`answer-save-${c.id}`}
            disabled={missing.length > 0 || save.isPending}
            onClick={() => (noFile ? setAskNoFile(true) : save.mutate())}>
            {confirming ? t('answer.confirmNow') : t('answer.save')}
          </button>
          {/* 2026-10-28: Confirmed with no file or mail attached is asked once */}
          <ConfirmDialog open={askNoFile} data-testid={`answer-no-file-${c.id}`}
            title={t('answer.noFileTitle')}
            body={t(customer ? 'answer.noProofCustomer' : 'answer.noProof')}
            confirmLabel={t('answer.saveAnyway')} cancelLabel={t('answer.back')}
            pending={save.isPending}
            onConfirm={() => save.mutateAsync()} onClose={() => setAskNoFile(false)} />
          {missing.length > 0 && (
            <span className="text-[11px] text-slate-500" data-testid={`answer-missing-${c.id}`}>
              {t('flag.missing').replace('{x}', missing.join(', '))}
            </span>
          )}
        </div>
      )}
    </div>
  )
}
