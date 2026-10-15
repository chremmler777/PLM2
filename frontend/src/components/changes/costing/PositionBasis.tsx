/**
 * Spec §4 costing positions (C25, ASSESSMENT_V2): what an external number
 * stands on, under its row.
 *
 * - Estimate: its reference (an earlier tool, the supplier's figure and its
 *   date), or "Same as" a part and what differs. Shown as "estimated" on the
 *   offer and the approval.
 * - Vendor quote: each offer's quote number, date and validity; finalize
 *   wants the number and the quote file on the counted offer.
 * - A quote that came in after an offer or approval on the estimate: "Quote
 *   vs your estimate: within +5 % / above by x", nothing preselected. Served
 *   per position (can_check_estimate) in any status from then on, also when
 *   the costing window is closed; with no quote recorded yet the same form
 *   takes the supplier, its quote number and the amount (one step).
 */
import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { btnSm } from '../../common/buttonStyles'
import { toastError } from '../../../lib/apiError'
import { changesApi } from '../../../api/changes'
import { t } from '../../../i18n/cmLabels'
import type { CostPosition, CostingOffer } from '../../../types/change'

const input = 'bg-slate-900 border border-slate-600 rounded px-2 py-1 text-xs text-slate-100'

/** The words of an external line's basis, for the row and read-only views. */
export function basisWords(p: CostPosition): string | null {
  if (p.kind !== 'external') return null
  if (p.basis === 'quote') return null
  if (p.basis === 'same_as' && p.basis_part_number) {
    return t('basis.sameAsWords').replace('{p}', p.basis_part_number)
      .replace('{d}', p.basis_differs ?? '')
  }
  return p.basis_ref ? t('basis.estimateWords').replace('{r}', p.basis_ref) : null
}

export function PositionBasis({ changeId, position: p, editable, onChanged, impactedParts = [] }: {
  changeId: number; position: CostPosition; editable: boolean; onChanged: () => void
  /** Parts a "same as" may point at (the change's impacted parts and their tools). */
  impactedParts?: { id: number; number: string }[]
}) {
  const [mode, setMode] = useState<'estimate' | 'same_as'>(p.basis === 'same_as' ? 'same_as' : 'estimate')
  const [ref, setRef] = useState(p.basis_ref ?? '')
  const [partId, setPartId] = useState<number | ''>(p.basis_part_id ?? '')
  const [differs, setDiffers] = useState(p.basis_differs ?? '')
  const [verdict, setVerdict] = useState<'' | 'within' | 'above'>('')
  const [over, setOver] = useState('')
  const [vendor, setVendor] = useState('')
  const [quoteRef, setQuoteRef] = useState('')
  const [amount, setAmount] = useState('')
  // no quote recorded yet: the one that came in goes with the comparison
  const recordsQuote = p.estimate_check !== 'pending'
  const save = useMutation({
    mutationFn: () => changesApi.updateCostPosition(changeId, p.id, mode === 'estimate'
      ? { basis: 'estimate', basis_ref: ref.trim() || null }
      : { basis: 'same_as', basis_part_id: partId === '' ? null : partId,
          basis_differs: differs.trim() || null }),
    onSuccess: onChanged,
    onError: (e: unknown) => { toastError(e, t('basis.failed')) },
  })
  const check = useMutation({
    mutationFn: () => changesApi.checkEstimate(changeId, p.id, {
      verdict: verdict as 'within' | 'above', ...(verdict === 'above' ? { over: Number(over) } : {}),
      ...(recordsQuote ? { vendor_name: vendor.trim(), quote_ref: quoteRef.trim(),
        cost: Number(amount) } : {}) }),
    onSuccess: onChanged,
    onError: (e: unknown) => { toastError(e, t('basis.failed')) },
  })
  if (p.kind !== 'external') return null
  const words = basisWords(p)
  return (
    <div className="space-y-1 text-xs" data-testid={`basis-${p.id}`}>
      {p.estimated && (
        <span className="mr-2 rounded bg-amber-900/60 px-1.5 text-amber-100" data-testid={`basis-estimated-${p.id}`}>
          {t('basis.estimated')}</span>
      )}
      {words && <span className="text-slate-400">{words}</span>}
      {p.basis !== 'quote' && editable && (
        <div className="flex flex-wrap items-center gap-2">
          <select className={input} value={mode} aria-label={t('basis.pick')}
            data-testid={`basis-mode-${p.id}`}
            onChange={(e) => setMode(e.target.value as 'estimate' | 'same_as')}>
            <option value="estimate">{t('basis.estimate')}</option>
            <option value="same_as">{t('basis.sameAs')}</option>
          </select>
          {mode === 'estimate' ? (
            <input className={`${input} flex-1 min-w-[12rem]`} value={ref}
              data-testid={`basis-ref-${p.id}`} aria-label={t('basis.refLabel')}
              placeholder={t('basis.refPlaceholder')} onChange={(e) => setRef(e.target.value)} />
          ) : (
            <>
              <select className={input} value={partId} aria-label={t('basis.part')}
                onChange={(e) => setPartId(e.target.value ? Number(e.target.value) : '')}>
                <option value="">{t('basis.part')}</option>
                {impactedParts.map((x) => <option key={x.id} value={x.id}>{x.number}</option>)}
              </select>
              <input className={`${input} flex-1 min-w-[12rem]`} value={differs}
                aria-label={t('basis.differs')} placeholder={t('basis.differs')}
                onChange={(e) => setDiffers(e.target.value)} />
            </>
          )}
          <button type="button" className={btnSm.secondary} data-testid={`basis-save-${p.id}`}
            disabled={save.isPending || (mode === 'estimate' ? ref.trim().length < 5
              : partId === '' || differs.trim().length < 5)}
            onClick={() => save.mutate()}>{t('basis.save')}</button>
        </div>
      )}
      {p.basis === 'quote' && (p.offers ?? []).map((o) => (
        <QuoteRef key={o.id} changeId={changeId} offer={o} editable={editable} onChanged={onChanged} />
      ))}
      {p.can_check_estimate && (
        <div className="flex flex-wrap items-center gap-2 rounded border border-amber-700/60 bg-amber-950/30 p-1.5"
          data-testid={`estcheck-${p.id}`}>
          {recordsQuote && (
            <>
              <span className="text-amber-200">{t('basis.quoteIn')}</span>
              <input className={`${input} w-28`} value={vendor} aria-label={t('basis.vendor')}
                placeholder={t('basis.vendor')} data-testid={`estcheck-vendor-${p.id}`}
                onChange={(e) => setVendor(e.target.value)} />
              <input className={`${input} w-28`} value={quoteRef} aria-label={t('basis.quoteRef')}
                placeholder={t('basis.quoteRef')} data-testid={`estcheck-ref-${p.id}`}
                onChange={(e) => setQuoteRef(e.target.value)} />
              <input type="number" min={0} className={`${input} w-24`} value={amount}
                aria-label={t('basis.amount')} placeholder={t('basis.amount')}
                data-testid={`estcheck-amount-${p.id}`} onChange={(e) => setAmount(e.target.value)} />
            </>
          )}
          <span className="text-amber-200">{t('basis.checkAsk')}</span>
          {(['within', 'above'] as const).map((v) => (
            <label key={v} className="inline-flex items-center gap-1 text-slate-200">
              <input type="radio" name={`estcheck-${p.id}`} checked={verdict === v}
                data-testid={`estcheck-${p.id}-${v}`} onChange={() => setVerdict(v)} />
              {t(`basis.check.${v}`)}
            </label>
          ))}
          {verdict === 'above' && (
            <input type="number" min={0} className={`${input} w-24`} value={over}
              aria-label={t('basis.overBy')} placeholder={t('basis.overBy')}
              data-testid={`estcheck-over-${p.id}`} onChange={(e) => setOver(e.target.value)} />
          )}
          <button type="button" className={btnSm.primary} data-testid={`estcheck-save-${p.id}`}
            disabled={!verdict || (verdict === 'above' && !(Number(over) > 0)) || check.isPending
              || (recordsQuote && (!vendor.trim() || quoteRef.trim().length < 5 || amount === ''))}
            onClick={() => check.mutate()}>{t('basis.save')}</button>
        </div>
      )}
      {p.estimate_check === 'above' && (
        <span className="text-amber-200">{t('basis.above').replace('{x}', String(p.estimate_over ?? ''))}</span>
      )}
      {p.estimate_check === 'settled' && (
        <span className="text-slate-400">{t('basis.settled').replace('{x}', String(p.estimate_over ?? ''))}</span>
      )}
    </div>
  )
}

function QuoteRef({ changeId, offer: o, editable, onChanged }: {
  changeId: number; offer: CostingOffer; editable: boolean; onChanged: () => void
}) {
  const [ref, setRef] = useState(o.quote_ref ?? '')
  const [on, setOn] = useState(o.quoted_on ?? '')
  const [until, setUntil] = useState(o.valid_until ?? '')
  const save = useMutation({
    mutationFn: () => changesApi.updateCostingOffer(changeId, o.id, {
      quote_ref: ref.trim() || null, quoted_on: on || null, valid_until: until || null }),
    onSuccess: onChanged,
    onError: (e: unknown) => { toastError(e, t('basis.failed')) },
  })
  const filed = (o.attachments ?? []).length > 0
  if (!editable) {
    return (
      <p className="text-slate-400">{o.vendor_name}: {o.quote_ref ?? t('basis.noQuoteRef')}
        {o.valid_until ? ` · ${t('basis.validUntil')} ${o.valid_until}` : ''}
        {filed ? '' : ` · ${t('basis.noFile')}`}</p>
    )
  }
  return (
    <div className="flex flex-wrap items-center gap-2" data-testid={`quoteref-${o.id}`}>
      <span className="text-slate-300">{o.vendor_name}</span>
      <input className={`${input} w-32`} value={ref} placeholder={t('basis.quoteRef')}
        aria-label={t('basis.quoteRef')} data-testid={`quoteref-ref-${o.id}`}
        onChange={(e) => setRef(e.target.value)} />
      <label className="text-slate-500">{t('basis.quotedOn')}
        <input type="date" className={`${input} ml-1`} value={on} onChange={(e) => setOn(e.target.value)} /></label>
      <label className="text-slate-500">{t('basis.validUntil')}
        <input type="date" className={`${input} ml-1`} value={until} onChange={(e) => setUntil(e.target.value)} /></label>
      <button type="button" className={btnSm.secondary} data-testid={`quoteref-save-${o.id}`}
        disabled={save.isPending || ref.trim().length < 3} onClick={() => save.mutate()}>
        {t('basis.save')}</button>
      {!filed && <span className="text-amber-300">{t('basis.noFile')}</span>}
    </div>
  )
}
