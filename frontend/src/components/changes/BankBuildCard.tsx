/**
 * How an approved change actually reaches the line — and when the customer
 * hears about it.
 *
 * Stage 7 of the process map splits one decision across two desks. Scheduling
 * picks between a running change (the new state runs in on the fly) and a
 * planned scrap (the remaining bank is written off and rebuilt), and sketches
 * the plan. Planned scrap costs money, and that money is the customer's: the
 * additional scrap quote is part of the decision, not an afterthought, so the
 * price field is required the moment scrap is chosen.
 *
 * Publishing is deliberately a second, separate act by Sales. The plan is an
 * internal decision until somebody puts it in front of the customer, and the
 * card says which of the two it currently is rather than letting an unpublished
 * plan look finished.
 *
 * Everyone who can see the implementation tab sees this card; only the writers
 * get controls. A read-only viewer gets the same facts in the same order.
 */
import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { changesApi } from '../../api/changes'
import { t } from '../../i18n/cmLabels'
import type { BankBuildMode, ChangeRequest } from '../../types/change'
import { formatDate, formatMoney } from '../../lib/format'
import { toastError } from '../../lib/apiError'
import { plantName } from '../../lib/plantName'
import { btnSm } from '../common/buttonStyles'

const MODES: BankBuildMode[] = ['running_change', 'planned_scrap']

const onDay = (iso?: string | null) => formatDate(iso)

interface Props {
  change: Pick<ChangeRequest,
    'id' | 'status' | 'bank_build_mode' | 'bank_build_note' | 'scrap_quote_price' | 'scrap_price_set'
    | 'bank_build_set_by_name' | 'bank_build_set_at'
    | 'plan_published_by_name' | 'plan_published_at'> & { mother_plant_name?: string | null }
  /** Scheduling / PM / change lead / admin — the page derives it. */
  canSetMode?: boolean
  /** Sales / change lead / admin. */
  canPublish?: boolean
  /** Inside the Timing tab the tab's own card publishes the validated plan. */
  hidePublish?: boolean
  /**
   * A change from the mother plant: nothing is published to a customer, the
   * mother plant hears about the validated timing instead. The intro says so
   * and the publish block stays hidden.
   */
  motherPlant?: boolean
}

export default function BankBuildCard({
  change, canSetMode = false, canPublish = false, hidePublish: hide = false, motherPlant = false,
}: Props) {
  const hidePublish = hide || motherPlant
  const qc = useQueryClient()
  const [mode, setMode] = useState<BankBuildMode | null>(change.bank_build_mode ?? null)
  const [note, setNote] = useState(change.bank_build_note ?? '')
  const [price, setPrice] = useState(
    change.scrap_quote_price != null ? String(change.scrap_quote_price) : '')
  // The price is sent only when the user touched it: a viewer who may not
  // read prices gets null here, and saving that back must not wipe (or be
  // refused for) the quote on record. The backend keeps the stored price
  // when none is sent.
  const [priceEdited, setPriceEdited] = useState(false)
  const priceHidden = change.scrap_quote_price == null && !!change.scrap_price_set
  const priceOnRecord = change.bank_build_mode === 'planned_scrap'
    && (change.scrap_quote_price != null || !!change.scrap_price_set)

  const published = !!change.plan_published_at
  // The backend only accepts the decision while the change sits at `approved`;
  // later the card is the record of what was decided.
  const editable = canSetMode && change.status === 'approved'
  const priceValue = Number(price.trim())
  const priceOk = price.trim() !== '' && !Number.isNaN(priceValue)
  const missingPrice = mode === 'planned_scrap' && !priceOk && (priceEdited || !priceOnRecord)

  const invalidate = () => qc.invalidateQueries({ queryKey: ['change', change.id] })

  const save = useMutation({
    mutationFn: () => changesApi.setBankBuild(change.id, {
      mode: mode as BankBuildMode,
      ...(note.trim() !== '' ? { note: note.trim() } : {}),
      ...(mode === 'planned_scrap' && priceEdited && priceOk ? { scrap_quote_price: priceValue } : {}),
    }),
    onSuccess: invalidate,
    onError: (e: unknown) => toastError(e, 'Could not save the bank-build plan'),
  })

  const publish = useMutation({
    mutationFn: () => changesApi.publishBankBuildPlan(change.id),
    onSuccess: invalidate,
    onError: (e: unknown) => toastError(e, 'Could not publish the plan'),
  })

  return (
    <section data-testid="bank-build-card"
      className="rounded-lg border border-slate-700 bg-slate-800 p-3 space-y-3 text-sm">
      <div>
        <span className="font-medium text-slate-100">{t('bankbuild.title')}</span>
        <p className="text-xs text-slate-400 mt-0.5" data-testid="bank-build-intro">
          {motherPlant
            ? `How does the change reach the line? Scheduling decides; ${plantName(change.mother_plant_name)} hears about it with the validated timing.`
            : t('bankbuild.intro')}
        </p>
      </div>

      {editable ? (
        <div className="space-y-3">
          <div className="space-y-2">
            {MODES.map((m) => (
              <label key={m} className="flex gap-2 items-start cursor-pointer">
                <input type="radio" name="bank-build-mode" className="mt-1"
                  data-testid={`bank-build-mode-${m}`}
                  checked={mode === m} onChange={() => setMode(m)} />
                <span>
                  <span className="text-slate-100">{t(`bankbuild.mode.${m}`)}</span>
                  <span className="block text-xs text-slate-400">
                    {t(`bankbuild.mode.${m}.hint`)}
                  </span>
                </span>
              </label>
            ))}
          </div>

          {/* Scrap is the expensive branch, so the price it costs the customer
              appears with it and blocks the save until it is named. */}
          {mode === 'planned_scrap' && (
            <div>
              <label className="block text-xs text-slate-400 mb-1">
                {t('bankbuild.scrapPrice')}
              </label>
              <input type="number" data-testid="bank-build-scrap-price"
                value={price} onChange={(e) => { setPrice(e.target.value); setPriceEdited(true) }}
                placeholder={priceHidden ? t('bankbuild.scrapPriceHidden') : undefined}
                className="bg-slate-900 border border-slate-600 rounded px-2 py-1 text-slate-100 w-40" />
              <p data-testid="bank-build-scrap-hint" className="text-xs text-amber-300 mt-1">
                {t('bankbuild.scrapPriceHint')}
              </p>
            </div>
          )}

          <div>
            <label className="block text-xs text-slate-400 mb-1">{t('bankbuild.note')}</label>
            <textarea data-testid="bank-build-note" rows={3}
              placeholder={t('bankbuild.notePlaceholder')}
              value={note} onChange={(e) => setNote(e.target.value)}
              className="w-full bg-slate-900 border border-slate-600 rounded px-2 py-1 text-slate-100" />
          </div>

          <div className="flex items-center gap-2 flex-wrap">
            <button type="button" data-testid="bank-build-save"
              disabled={!mode || missingPrice || save.isPending}
              onClick={() => save.mutate()}
              className={btnSm.primary}>
              {save.isPending ? t('saving') : t('save')}
            </button>
            {missingPrice && (
              <span data-testid="bank-build-need-price" className="text-xs text-amber-300">
                {t('bankbuild.needPrice')}
              </span>
            )}
          </div>
        </div>
      ) : (
        <div data-testid="bank-build-readonly" className="space-y-1">
          <p className="text-slate-100">
            {change.bank_build_mode
              ? t(`bankbuild.mode.${change.bank_build_mode}`)
              : t('bankbuild.noMode')}
          </p>
          {change.bank_build_mode === 'planned_scrap' && (
            <p className="text-xs text-slate-400">
              {t('bankbuild.scrapPrice')}: {priceHidden
                ? <span data-testid="bank-build-price-hidden">{t('bankbuild.scrapPriceHidden')}</span>
                : formatMoney(change.scrap_quote_price)}
            </p>
          )}
          {change.bank_build_note && (
            <p className="text-xs text-slate-300 whitespace-pre-wrap">{change.bank_build_note}</p>
          )}
          {change.bank_build_set_at && (
            <p className="text-xs text-slate-400">
              {t('bankbuild.setBy')
                .replace('{x}', change.bank_build_set_by_name ?? '-')
                .replace('{d}', onDay(change.bank_build_set_at))}
            </p>
          )}
          {!canSetMode && <p className="text-xs text-slate-400">{t('bankbuild.readOnly')}</p>}
        </div>
      )}

      {/* Internal decision or customer-facing plan — never ambiguous. */}
      {!hidePublish && <div className="border-t border-slate-700 pt-2 space-y-2">
        <p data-testid="bank-build-publish-state"
          className={published ? 'text-xs text-emerald-300' : 'text-xs text-amber-300'}>
          {published
            ? t('bankbuild.published')
              .replace('{x}', change.plan_published_by_name ?? '-')
              .replace('{d}', onDay(change.plan_published_at))
            : t('bankbuild.unpublished')}
        </p>
        {canPublish && !published && (
          <div className="flex items-center gap-2 flex-wrap">
            <button type="button" data-testid="bank-build-publish"
              disabled={!change.bank_build_mode || publish.isPending}
              onClick={() => publish.mutate()}
              className={btnSm.primary}>
              {t('bankbuild.publish')}
            </button>
            {!change.bank_build_mode && (
              <span data-testid="bank-build-publish-blocked" className="text-xs text-slate-400">
                {t('bankbuild.publishNeedsMode')}
              </span>
            )}
          </div>
        )}
      </div>}
    </section>
  )
}
