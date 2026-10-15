/**
 * Start at risk (ECR-solid spec §7a; P8: urgent only, switch START_AT_RISK).
 * Sales (or the run team) files the customer's go-ahead; Quality adds one
 * line of quality risks; a Project Management member (second: an admin)
 * approves it, never the one who asked. The change is then approved with the
 * price open until the customer accepts an offer or the money is absorbed.
 * No prices on the card.
 */
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import client from '../../../api/client'
import { toastError } from '../../../lib/apiError'
import { formatCalendarDate } from '../../../lib/format'
import { t } from '../../../i18n/cmLabels'
import { buttonClass } from '../../common/buttonStyles'
import type { Attachment } from '../../../types/change'
import { inputCls, sectionLabel } from './offerFormat'
import EvidencePick, { pickBody, pickNeedsTick } from './EvidencePick'

export interface StartAtRiskState {
  available: boolean
  refusal?: string | null
  evidence?: string | null
  requested_by?: number | null
  requested_by_name?: string | null
  requested_at?: string | null
  /** The ask can be decided now (no refusal stands in the way). */
  decidable?: boolean
  quality_note?: string | null
  quality_by_name?: string | null
  approved_by_name?: string | null
  approved_at?: string | null
  price_open?: boolean
}

export const sarApi = {
  get: (id: number) => client.get<StartAtRiskState>(`/v1/changes/${id}/start-at-risk`).then((r) => r.data),
  request: (id: number, body: { attachment_id?: number; from_customer?: boolean; ref?: string }) =>
    client.post<StartAtRiskState>(`/v1/changes/${id}/start-at-risk`, body).then((r) => r.data),
  quality: (id: number, note: string) =>
    client.post<StartAtRiskState>(`/v1/changes/${id}/start-at-risk/quality`, { note }).then((r) => r.data),
  approve: (id: number) =>
    client.post<StartAtRiskState>(`/v1/changes/${id}/start-at-risk/approve`, {}).then((r) => r.data),
  refuse: (id: number, note: string) =>
    client.post<StartAtRiskState>(`/v1/changes/${id}/start-at-risk/refuse`, { note }).then((r) => r.data),
}

const fill = (k: string, v: Record<string, string>) =>
  Object.entries(v).reduce((acc, [kk, vv]) => acc.split(`{${kk}}`).join(vv), t(k))

export interface StartAtRiskCardProps {
  changeId: number
  canAsk: boolean
  isQuality: boolean
  /** A Project Management member or an admin. */
  canApprove: boolean
  userId: number | null
  attachments: Attachment[]
}

export default function StartAtRiskCard({ changeId, canAsk, isQuality, canApprove, userId, attachments }: StartAtRiskCardProps) {
  const qc = useQueryClient()
  const key = ['change', changeId, 'start-at-risk']
  const { data: s } = useQuery({ queryKey: key, queryFn: () => sarApi.get(changeId) })
  const [mail, setMail] = useState('')
  const [fromCustomer, setFromCustomer] = useState(false)
  const [ref, setRef] = useState('')
  const [note, setNote] = useState('')
  const done = (data: StartAtRiskState) => {
    qc.setQueryData(key, data)
    qc.invalidateQueries({ queryKey: ['change', changeId] })
    qc.invalidateQueries({ queryKey: ['change-my-actions', changeId] })
  }
  const onError = (e: unknown) => toastError(e, t('sar.error'))
  const ask = useMutation({
    mutationFn: () => sarApi.request(changeId, mail ? pickBody(attachments, mail) : { ref: ref.trim() }),
    onSuccess: done, onError,
  })
  const quality = useMutation({ mutationFn: () => sarApi.quality(changeId, note.trim()), onSuccess: done, onError })
  const approve = useMutation({ mutationFn: () => sarApi.approve(changeId), onSuccess: done, onError })
  const [why, setWhy] = useState('')
  const [refusing, setRefusing] = useState(false)
  const refuse = useMutation({
    mutationFn: () => sarApi.refuse(changeId, why.trim()),
    onSuccess: (d) => { setRefusing(false); setWhy(''); done(d) }, onError,
  })
  if (!s) return null
  if (s.approved_at) {
    return (
      <p data-testid="sar-started" className="rounded-lg border border-amber-800 bg-amber-950/30 px-3 py-2 text-xs text-amber-100">
        {fill('sar.started', { d: formatCalendarDate(s.approved_at), who: s.approved_by_name ?? '-',
          q: s.quality_note ?? '-' })}
        {s.price_open ? ` ${t('sar.priceOpen')}` : ''}
      </p>
    )
  }
  if (!s.available && !s.requested_at) return null
  const askOk = mail ? (!pickNeedsTick(attachments, mail) || fromCustomer) : ref.trim().length >= 5
  return (
    <section data-testid="sar-card" className="space-y-2 rounded-lg border border-amber-900/70 bg-amber-950/10 p-3 text-xs">
      <div className={sectionLabel}>{t('sar.title')}</div>
      <p className="text-slate-400">{t('sar.help')}</p>
      {!s.requested_at && canAsk && (
        <div className="flex flex-wrap gap-2">
          <EvidencePick testId="sar-mail" label={t('sar.goAhead')} attachments={attachments}
            value={mail} onChange={setMail} fromCustomer={fromCustomer} onFromCustomer={setFromCustomer} />
          <input data-testid="sar-ref" value={ref} disabled={!!mail} onChange={(e) => setRef(e.target.value)}
            aria-label={t('sar.goAhead')} placeholder={t('sar.goAhead')} className={`${inputCls} min-w-0 flex-1`} />
          <button type="button" data-testid="sar-ask" disabled={ask.isPending || !askOk}
            onClick={() => ask.mutate()} className={buttonClass('primary', 'sm')}>{t('sar.ask')}</button>
        </div>
      )}
      {s.requested_at && (
        <p data-testid="sar-requested" className="text-slate-300">
          {fill('sar.requested', { who: s.requested_by_name ?? '-', d: formatCalendarDate(s.requested_at), e: s.evidence ?? '' })}
        </p>
      )}
      {s.requested_at && !s.quality_note && (isQuality ? (
        <div className="flex flex-wrap gap-2">
          <input data-testid="sar-quality-note" value={note} onChange={(e) => setNote(e.target.value)}
            aria-label={t('sar.qualityNote')} placeholder={t('sar.qualityNote')} className={`${inputCls} min-w-0 flex-1`} />
          <button type="button" data-testid="sar-quality-save" disabled={quality.isPending || note.trim().length < 10}
            onClick={() => quality.mutate()} className={buttonClass('primary', 'sm')}>{t('sar.qualitySave')}</button>
        </div>
      ) : <p className="text-amber-200">{t('sar.waitQuality')}</p>)}
      {s.quality_note && (
        <p data-testid="sar-quality" className="text-slate-300">{fill('sar.qualityLine', { who: s.quality_by_name ?? '-', q: s.quality_note })}</p>
      )}
      {s.requested_at && s.quality_note && !s.decidable && s.refusal && (
        // nothing to decide any more (e.g. the customer accepted): say why
        <p data-testid="sar-moot" className="text-slate-400">{s.refusal}</p>
      )}
      {s.requested_at && s.quality_note && s.decidable && (canApprove && userId !== s.requested_by ? (
        <div className="space-y-1">
          <div className="flex flex-wrap gap-2">
            <button type="button" data-testid="sar-approve" disabled={approve.isPending}
              onClick={() => approve.mutate()} className={buttonClass('primary', 'sm')}>{t('sar.approve')}</button>
            <button type="button" data-testid="sar-refuse-open" aria-expanded={refusing}
              onClick={() => setRefusing((r) => !r)} className={buttonClass('secondary', 'sm')}>{t('sar.refuse')}</button>
          </div>
          {refusing && (
            <div className="flex flex-wrap gap-2">
              <input data-testid="sar-refuse-note" value={why} onChange={(e) => setWhy(e.target.value)}
                aria-label={t('sar.refuseWhy')} placeholder={t('sar.refuseWhy')} className={`${inputCls} min-w-0 flex-1`} />
              <button type="button" data-testid="sar-refuse" disabled={refuse.isPending || why.trim().length < 10}
                onClick={() => refuse.mutate()} className={buttonClass('danger', 'sm')}>{t('sar.refuse')}</button>
            </div>
          )}
        </div>
      ) : <p className="text-amber-200">{t('sar.waitPm')}</p>)}
    </section>
  )
}
