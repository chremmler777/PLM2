/**
 * HARD #7 on the Scoping tab (spec §0 "Customer flip", §3 "Internal").
 *
 * PpapDecisionCard: on an internal change, Quality answers "Parameters /
 * tool / material / cycle time changed on any part?". Nothing preselected.
 * No: the basis (control plan / process sheet / customer spec) and its
 * reference. Yes: the parts; it makes a customer notification task for Sales
 * (the change becomes a customer change). Everyone else reads who owes it.
 *
 * CustomerFlipCard: the change became a customer change; the Sales owner
 * answers "notification only" (a filed customer mail or a reference) or
 * "offer needed" (the quote deadline). Proceed waits for it.
 */
import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { btnSm } from '../../common/buttonStyles'
import { toastError } from '../../../lib/apiError'
import { changesApi } from '../../../api/changes'
import { t } from '../../../i18n/cmLabels'
import { formatDate } from '../../../lib/format'
import DateInput from '../../gantt/DateInput'
import type { Attachment, ChangeRequest, ImpactedItem } from '../../../types/change'

const input = 'bg-slate-900 border border-slate-600 rounded px-2 py-1 text-xs text-slate-100'
const BASES = ['control_plan', 'process_sheet', 'customer_spec'] as const

type Change = ChangeRequest & { impacted_items?: ImpactedItem[] }

export function PpapDecisionCard({ change, isQuality, editable, onChanged }: {
  change: Change; isQuality: boolean; editable: boolean; onChanged: () => void
}) {
  const [answer, setAnswer] = useState<'' | 'no' | 'yes'>('')
  const [basis, setBasis] = useState<(typeof BASES)[number] | ''>('')
  const [ref, setRef] = useState('')
  const [parts, setParts] = useState<number[]>([])
  const items = change.impacted_items ?? []
  const save = useMutation({
    mutationFn: () => changesApi.ppapDecision(change.id, answer === 'no'
      ? { answer: 'no', basis: basis as string, ref: ref.trim() }
      : { answer: 'yes', part_ids: parts }),
    onSuccess: onChanged,
    onError: (e: unknown) => { toastError(e, 'Could not record the ppap decision') },
  })
  const decided = change.ppap_decision != null
  const missing = answer === '' ? [t('ppap.pickAnswer')]
    : answer === 'no'
      ? [...(basis ? [] : [t('ppap.basis')]), ...(ref.trim().length >= 5 ? [] : [t('answer.ref')])]
      : (parts.length ? [] : [t('ppap.parts')])
  return (
    <div data-testid="ppap-card"
      className={`rounded-lg border p-3 space-y-2 ${decided ? 'border-slate-700 bg-slate-800/40'
        : 'border-amber-700/60 bg-amber-950/20'}`}>
      <p className="text-sm font-medium text-slate-100">{t('ppap.title')}</p>
      <p className="text-xs text-slate-300">{t('ppap.question')}</p>
      {decided ? (
        <p className="text-xs text-slate-300" data-testid="ppap-decided">
          {change.ppap_decision === 'no'
            ? t('ppap.decidedNo').replace('{b}', t(`ppap.basis.${change.ppap_basis}`))
              .replace('{r}', change.ppap_ref ?? '-')
            : t('ppap.decidedYes').replace('{n}', String(change.ppap_part_ids?.length ?? 0))}
          {change.ppap_decided_at && ` · ${formatDate(change.ppap_decided_at)}`}
        </p>
      ) : !isQuality || !editable ? (
        <p className="text-[11px] text-slate-500" data-testid="ppap-owner">{t('ppap.qualityOwes')}</p>
      ) : (
        <div className="space-y-2">
          <fieldset className="flex flex-wrap gap-4 text-xs">
            <legend className="sr-only">{t('ppap.question')}</legend>
            <label className="flex items-center gap-1.5 cursor-pointer">
              <input type="radio" name="ppap-answer" checked={answer === 'no'}
                data-testid="ppap-no" onChange={() => setAnswer('no')} />
              <span className="text-slate-200">{t('ppap.no')}</span>
            </label>
            <label className="flex items-center gap-1.5 cursor-pointer">
              <input type="radio" name="ppap-answer" checked={answer === 'yes'}
                data-testid="ppap-yes" onChange={() => setAnswer('yes')} />
              <span className="text-slate-200">{t('ppap.yes')}</span>
            </label>
          </fieldset>
          {answer === 'no' && (
            <div className="flex flex-wrap gap-2">
              <select value={basis} aria-label={t('ppap.basis')} data-testid="ppap-basis"
                onChange={(e) => setBasis(e.target.value as typeof basis)} className={input}>
                <option value="">{t('ppap.basis')}…</option>
                {BASES.map((b) => <option key={b} value={b}>{t(`ppap.basis.${b}`)}</option>)}
              </select>
              <input value={ref} onChange={(e) => setRef(e.target.value)} data-testid="ppap-ref"
                aria-label={t('answer.ref')} placeholder={t('ppap.refPlaceholder')}
                className={`${input} flex-1 min-w-[12rem]`} />
            </div>
          )}
          {answer === 'yes' && (
            <div className="space-y-1">
              <p className="text-[11px] text-amber-300/90">{t('ppap.yesMeans')}</p>
              {items.map((i) => (
                <label key={i.part_id} className="flex items-center gap-2 text-xs cursor-pointer">
                  <input type="checkbox" checked={parts.includes(i.part_id)}
                    data-testid={`ppap-part-${i.part_id}`}
                    onChange={(e) => setParts(e.target.checked
                      ? [...parts, i.part_id] : parts.filter((p) => p !== i.part_id))} />
                  <span className="text-slate-200">{i.part_number ?? `#${i.part_id}`} {i.part_name ?? ''}</span>
                </label>
              ))}
            </div>
          )}
          {answer !== '' && (
            <div className="flex items-center gap-2">
              <button type="button" className={btnSm.primary} data-testid="ppap-save"
                disabled={missing.length > 0 || save.isPending} onClick={() => save.mutate()}>
                {t('ppap.save')}
              </button>
              {missing.length > 0 && (
                <span className="text-[11px] text-slate-500">
                  {t('flag.missing').replace('{x}', missing.join(', '))}
                </span>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

export function CustomerFlipCard({ change, isSales, editable, attachments, onChanged }: {
  change: Change; isSales: boolean; editable: boolean; attachments: Attachment[]
  onChanged: () => void
}) {
  const [answer, setAnswer] = useState<'' | 'notification' | 'offer'>('')
  const [ref, setRef] = useState('')
  const [mailId, setMailId] = useState<number | ''>('')
  const [deadline, setDeadline] = useState('')
  const mails = attachments.filter((a) => a.kind === 'customer_email')
    .sort((a, b) => b.created_at.localeCompare(a.created_at))
  const save = useMutation({
    mutationFn: () => changesApi.answerCustomerFlip(change.id, answer === 'offer'
      ? { answer: 'offer', quote_deadline: `${deadline}T12:00:00` }
      : { answer: 'notification', ...(mailId !== '' ? { mail_id: mailId } : { ref: ref.trim() }) }),
    onSuccess: onChanged,
    onError: (e: unknown) => { toastError(e, 'Could not record the answer') },
  })
  if (!change.customer_flip_at) return null
  const answered = change.flip_answer != null
  const ready = answer === 'offer' ? !!deadline
    : answer === 'notification' ? (mailId !== '' || ref.trim().length >= 5) : false
  return (
    <div data-testid="flip-card"
      className={`rounded-lg border p-3 space-y-2 ${answered ? 'border-slate-700 bg-slate-800/40'
        : 'border-amber-700/60 bg-amber-950/20'}`}>
      <p className="text-sm font-medium text-slate-100">{t('flip.title')}</p>
      <p className="text-xs text-slate-400">{change.customer_flip_reason}</p>
      {answered ? (
        <p className="text-xs text-slate-300" data-testid="flip-answered">
          {change.flip_answer === 'notification'
            ? t('flip.answeredNotification').replace('{r}', change.flip_ref ?? '-')
            : t('flip.answeredOffer')}
        </p>
      ) : !isSales || !editable ? (
        <p className="text-[11px] text-slate-500" data-testid="flip-owner">
          {t('flip.salesOwes').replace('{x}', change.sales_owner_name ?? 'Sales')}
          {change.sales_owner_id == null && (
            <span className="block text-amber-300/90" data-testid="flip-no-owner">{t('flip.noSalesOwner')}</span>
          )}
        </p>
      ) : (
        <div className="space-y-2">
          <fieldset className="flex flex-wrap gap-4 text-xs">
            <legend className="sr-only">{t('flip.title')}</legend>
            {(['notification', 'offer'] as const).map((k) => (
              <label key={k} className="flex items-center gap-1.5 cursor-pointer">
                <input type="radio" name="flip-answer" checked={answer === k}
                  data-testid={`flip-${k}`} onChange={() => setAnswer(k)} />
                <span className="text-slate-200">{t(`flip.${k}`)}</span>
              </label>
            ))}
          </fieldset>
          {answer === 'notification' && (
            <div className="flex flex-wrap gap-2">
              {mails.length > 0 && (
                <select value={mailId} aria-label={t('answer.mail')} data-testid="flip-mail"
                  onChange={(e) => setMailId(e.target.value ? Number(e.target.value) : '')}
                  className={`${input} max-w-[18rem]`}>
                  <option value="">{t('answer.mailPick')}</option>
                  {mails.map((m) => <option key={m.id} value={m.id}>{m.filename}</option>)}
                </select>
              )}
              {mailId === '' && (
                <input value={ref} onChange={(e) => setRef(e.target.value)} data-testid="flip-ref"
                  aria-label={t('answer.ref')} placeholder={t('answer.refPlaceholder')}
                  className={`${input} flex-1 min-w-[12rem]`} />
              )}
            </div>
          )}
          {answer === 'offer' && (
            <div className="flex items-center gap-2 text-xs">
              <span className="text-slate-400">{t('deadline.quote')}</span>
              <DateInput value={deadline} onChange={setDeadline} aria-label={t('deadline.quote')}
                className={`${input} w-36`} />
            </div>
          )}
          {answer !== '' && (
            <button type="button" className={btnSm.primary} data-testid="flip-save"
              disabled={!ready || save.isPending} onClick={() => save.mutate()}>
              {t('answer.save')}
            </button>
          )}
        </div>
      )}
    </div>
  )
}
