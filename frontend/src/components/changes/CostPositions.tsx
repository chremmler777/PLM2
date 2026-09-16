/**
 * The costing table — what a department books against a change, line by line.
 *
 * One table per department. The first rows are standing: the two answers every
 * department owes (assessment effort, implementation support) and, for
 * Tooling, the part weight. Every further line is a category from the
 * department's own list, and the category says what the line is:
 *
 *   own time     — hours, valued at the department's rate in the summation
 *   estimate     — money, a house number
 *   vendor quote — money, read from the favourite of the offers under the line
 *
 * A quoted line carries its vendors as sub-rows with one star among them. The
 * favourite is not decoration: it is the offer the line's price and lead time
 * are read from, so a line without one is a line nobody has costed yet, and it
 * says so.
 *
 * The department writes its own lines during costing; PM may fix them. Sales,
 * the lead and admins read. Sales has nothing to fill in here — they get the
 * picture and put a price on it later.
 */
import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { changesApi } from '../../api/changes'
import AttachmentDropzone from './AttachmentDropzone'
import { AttachmentRow } from './AttachmentRow'
import { t } from '../../i18n/cmLabels'
import { TOOL_ENGINEER_DEPARTMENT } from '../../lib/departments'
import type {
  CostCategory, CostEntryType, CostPosition, CostPositionKind, CostPositionPricing,
  CostingOffer, LeadTimeUnit,
} from '../../types/change'

const UNITS: LeadTimeUnit[] = ['calendar_days', 'business_days']

/** Calendar days unless somebody says otherwise — the safer reading of a bare number. */
const DEFAULT_UNIT: LeadTimeUnit = 'calendar_days'

const errDetail = (e: unknown): string | undefined =>
  (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail

const num = (s: string): number | null => (s.trim() === '' ? null : Number(s))

/** The tag reads as a label: the served one when the list is at hand, the
    coded one for known keys, else the key itself. */
export const tagLabel = (tag: string, items?: CostCategory[]): string => {
  const served = items?.find((i) => i.key === tag)?.label_en
  if (served) return served
  const label = t(`costtag.${tag}`)
  return label === `costtag.${tag}` ? tag : label
}

/** "10 business days" — the number is meaningless without the unit. */
export const leadTimeText = (days: number, unit?: LeadTimeUnit | null): string =>
  `${days} ${t(`costpos.unitShort.${unit ?? DEFAULT_UNIT}`)}`

/**
 * What the position is worth. For quoted external work that is the favourite
 * offer, price plus whatever freight it does not include — the department's vote
 * is what the money is read from, not a figure entered somewhere else.
 */
export function effectiveOf(p: CostPosition): number | null {
  if (p.kind === 'external' && p.pricing === 'quote') {
    const fav = (p.offers ?? []).find((o) => o.favorite)
    if (fav) return fav.cost + (fav.shipping_included ? 0 : fav.shipping_cost ?? 0)
    return p.effective_cost ?? null
  }
  if (p.effective_cost != null) return p.effective_cost
  return p.est_cost ?? null
}

/** Sales' binding pick, once there is one. */
export const chosenOf = (p: CostPosition): CostingOffer | undefined =>
  (p.offers ?? []).find((o) => o.chosen)

/** The department's recommendation. */
export const favoriteOf = (p: CostPosition): CostingOffer | undefined =>
  (p.offers ?? []).find((o) => o.favorite)

/** True when Sales bought something other than what the department recommended. */
export function decisionDivergesOf(p: CostPosition): boolean {
  const chosen = chosenOf(p)
  const fav = favoriteOf(p)
  return !!chosen && !!fav && chosen.id !== fav.id
}

const offerCost = (o: CostingOffer): number =>
  o.cost + (o.shipping_included ? 0 : o.shipping_cost ?? 0)

/**
 * What the position is worth once Sales has decided. The department's own block
 * keeps reading its favourite (that is its vote, and it stays visible); the
 * wrap-up Sales quotes off reads the offer Sales actually chose.
 */
export function salesEffectiveOf(p: CostPosition): number | null {
  if (p.kind === 'external' && p.pricing === 'quote') {
    const chosen = chosenOf(p)
    if (chosen) return offerCost(chosen)
  }
  return effectiveOf(p)
}

/** The offer a quoted position is read from: the favourite, or a lone offer
    (which needs no vote to be the answer). Several offers without a vote
    give nothing — the department has not finished the job. */
const pricedOffer = (p: CostPosition): CostingOffer | undefined => {
  const offers = p.offers ?? []
  return offers.find((o) => o.favorite) ?? (offers.length === 1 ? offers[0] : undefined)
}

/** The same rule for time: the priced offer's lead time is the position's. */
export function leadTimeOf(p: CostPosition): { days: number; unit: LeadTimeUnit } | null {
  if (p.kind === 'external' && p.pricing === 'quote') {
    const fav = pricedOffer(p)
    if (fav?.lead_time_days != null) {
      return { days: fav.lead_time_days, unit: fav.lead_time_unit ?? DEFAULT_UNIT }
    }
  }
  if (p.lead_time_days == null) return null
  return { days: p.lead_time_days, unit: p.lead_time_unit ?? DEFAULT_UNIT }
}

const fieldCls =
  'bg-slate-900 border border-slate-600 rounded px-2 py-1 text-sm text-slate-100'

/** The unit belongs to the number, so it is drawn as part of the same field. */
function UnitSelect({ testId, value, onChange }: {
  testId: string; value: LeadTimeUnit; onChange: (u: LeadTimeUnit) => void
}) {
  return (
    <select data-testid={testId} value={value} aria-label={t('costpos.unit')}
      onChange={(e) => onChange(e.target.value as LeadTimeUnit)}
      className={`${fieldCls} w-32`}>
      {UNITS.map((u) => (
        <option key={u} value={u}>{t(`costpos.unit.${u}`)}</option>
      ))}
    </select>
  )
}

function OfferRow({
  changeId, positionId, offer, editable, onChanged,
}: {
  changeId: number; positionId: number; offer: CostingOffer
  editable: boolean; onChanged: () => void
}) {
  const qc = useQueryClient()
  const [vendor, setVendor] = useState(offer.vendor_name)
  const [cost, setCost] = useState(String(offer.cost))
  const [included, setIncluded] = useState(!!offer.shipping_included)
  const [ship, setShip] = useState(offer.shipping_cost != null ? String(offer.shipping_cost) : '')
  const [lead, setLead] = useState(offer.lead_time_days != null ? String(offer.lead_time_days) : '')
  const [unit, setUnit] = useState<LeadTimeUnit>(offer.lead_time_unit ?? DEFAULT_UNIT)

  const save = useMutation({
    mutationFn: () => changesApi.updateCostingOffer(changeId, offer.id, {
      vendor_name: vendor, cost: Number(cost) || 0,
      shipping_included: included,
      shipping_cost: included ? null : num(ship),
      lead_time_days: num(lead), lead_time_unit: unit,
    }),
    onSuccess: () => { toast.success(t('costpos.saved')); onChanged() },
    onError: (e: unknown) => toast.error(errDetail(e) ?? 'Could not save the offer'),
  })

  // The vote is exclusive, so the sibling stars go dark the moment this one
  // lights up — the server does the same thing to the record.
  const favorite = useMutation({
    mutationFn: () => changesApi.updateCostingOffer(changeId, offer.id, { favorite: true }),
    onMutate: () => {
      qc.setQueryData<CostPosition[]>(['costing-positions', changeId], (old) =>
        (old ?? []).map((p) => p.id !== positionId ? p : {
          ...p,
          offers: (p.offers ?? []).map((o) => ({ ...o, favorite: o.id === offer.id })),
        }))
    },
    onSuccess: onChanged,
    onError: (e: unknown) => {
      toast.error(errDetail(e) ?? 'Could not set the favourite')
      onChanged()
    },
  })

  const remove = useMutation({
    mutationFn: () => changesApi.deleteCostingOffer(changeId, offer.id),
    onSuccess: onChanged,
    onError: (e: unknown) => toast.error(errDetail(e) ?? 'Could not delete the offer'),
  })

  const dirty = vendor !== offer.vendor_name
    || Number(cost) !== offer.cost
    || included !== !!offer.shipping_included
    || (!included && num(ship) !== (offer.shipping_cost ?? null))
    || num(lead) !== (offer.lead_time_days ?? null)
    || unit !== (offer.lead_time_unit ?? DEFAULT_UNIT)

  return (
    <li data-testid={`offer-row-${offer.id}`}
      // The chosen offer is the one the position's figures come from, so it is
      // lit rather than merely starred.
      className={`flex flex-wrap items-center gap-2 py-1.5 border-t border-slate-700/60 first:border-t-0 ${
        offer.favorite ? 'bg-amber-950/20 border-l-2 border-l-amber-500 pl-2' : ''}`}>
      {editable ? (
        <button type="button" data-testid={`offer-fav-${offer.id}`}
          title={t('costpos.favoriteHint')} aria-pressed={!!offer.favorite}
          onClick={() => { if (!offer.favorite) favorite.mutate() }}
          className={`text-sm leading-none ${offer.favorite ? 'text-amber-300' : 'text-slate-600 hover:text-slate-400'}`}>
          {offer.favorite ? '★' : '☆'}
        </button>
      ) : (
        <span data-testid={`offer-fav-${offer.id}`} title={t('costpos.favorite')}
          className={`text-sm leading-none ${offer.favorite ? 'text-amber-300' : 'text-slate-600'}`}>
          {offer.favorite ? '★' : '☆'}
        </span>
      )}

      {editable ? (
        <>
          <input data-testid={`offer-vendor-${offer.id}`} value={vendor}
            aria-label={t('costpos.vendor')} placeholder={t('costpos.vendor')}
            onChange={(e) => setVendor(e.target.value)} className={`${fieldCls} w-36`} />
          <input data-testid={`offer-cost-${offer.id}`} type="number" step="0.01" value={cost}
            aria-label={t('costpos.cost')}
            onChange={(e) => setCost(e.target.value)} className={`${fieldCls} w-24 tabular-nums`} />
          <label className="flex items-center gap-1 text-xs text-slate-400">
            <input type="checkbox" data-testid={`offer-shipping-included-${offer.id}`}
              checked={included} onChange={(e) => setIncluded(e.target.checked)} />
            {t('costpos.shippingIncluded')}
          </label>
          {!included && (
            <span className="flex items-center gap-1 text-xs text-slate-400">
              <input data-testid={`offer-shipping-cost-${offer.id}`} type="number" step="0.01"
                value={ship} aria-label={t('costpos.shipping')}
                onChange={(e) => setShip(e.target.value)} className={`${fieldCls} w-20 tabular-nums`} />
              {t('costpos.shippingSeparate')}
            </span>
          )}
          <input data-testid={`offer-lead-${offer.id}`} type="number" min={0} value={lead}
            aria-label={t('costpos.leadTime')} placeholder={t('costpos.leadTime')}
            onChange={(e) => setLead(e.target.value)} className={`${fieldCls} w-20 tabular-nums`} />
          <UnitSelect testId={`offer-unit-${offer.id}`} value={unit} onChange={setUnit} />
          <button type="button" data-testid={`offer-save-${offer.id}`}
            disabled={!dirty || save.isPending} onClick={() => save.mutate()}
            className="bg-sky-600 hover:bg-sky-500 text-white px-2 py-1 rounded text-xs disabled:opacity-50">
            {t('common.save')}
          </button>
          <button type="button" data-testid={`offer-delete-${offer.id}`}
            onClick={() => remove.mutate()} title={t('costpos.delete')}
            className="text-slate-500 hover:text-red-300 text-xs">✕</button>
        </>
      ) : (
        <>
          <span data-testid={`offer-vendor-${offer.id}`} className="text-slate-200 text-sm">
            {offer.vendor_name}
          </span>
          <span data-testid={`offer-cost-${offer.id}`} className="text-slate-300 text-sm tabular-nums">
            {offer.cost.toFixed(2)}
          </span>
          <span data-testid={`offer-shipping-${offer.id}`} className="text-xs text-slate-400">
            {t('costpos.shipping')}: {offer.shipping_included
              ? t('costpos.shippingIncluded')
              : `${(offer.shipping_cost ?? 0).toFixed(2)} ${t('costpos.shippingSeparate')}`}
          </span>
          {offer.lead_time_days != null && (
            <span data-testid={`offer-lead-${offer.id}`} className="text-xs text-slate-400">
              {leadTimeText(offer.lead_time_days, offer.lead_time_unit)}
            </span>
          )}
        </>
      )}

      {/* The written offer itself lives with the row that quotes it. */}
      <span className="w-full pl-5 space-y-1">
        {(offer.attachments ?? []).length > 0 && (
          <ul className="text-sm">
            {(offer.attachments ?? []).map((att) => (
              <AttachmentRow key={att.id} changeId={changeId} attachment={att} />
            ))}
          </ul>
        )}
        {editable && (
          <AttachmentDropzone changeId={changeId} compact kind="vendor_quote"
            costingOfferId={offer.id} label={t('costpos.quoteDoc')}
            onUploaded={onChanged} />
        )}
      </span>
    </li>
  )
}

function NewOfferForm({ changeId, positionId, onAdded }: {
  changeId: number; positionId: number; onAdded: () => void
}) {
  const [vendor, setVendor] = useState('')
  const [cost, setCost] = useState('')
  const [included, setIncluded] = useState(false)
  const [ship, setShip] = useState('')
  const [lead, setLead] = useState('')
  const [unit, setUnit] = useState<LeadTimeUnit>(DEFAULT_UNIT)
  const add = useMutation({
    mutationFn: () => changesApi.addCostingOffer(changeId, positionId, {
      vendor_name: vendor.trim(), cost: Number(cost) || 0,
      shipping_included: included, shipping_cost: included ? null : num(ship),
      lead_time_days: num(lead), lead_time_unit: unit,
    }),
    onSuccess: () => {
      setVendor(''); setCost(''); setShip(''); setLead(''); setIncluded(false)
      onAdded()
    },
    onError: (e: unknown) => toast.error(errDetail(e) ?? 'Could not add the offer'),
  })
  return (
    <div data-testid={`offer-new-${positionId}`}
      className="flex flex-wrap items-center gap-2 pt-1.5 border-t border-slate-700/60">
      <input data-testid={`offer-new-vendor-${positionId}`} value={vendor}
        aria-label={t('costpos.vendor')} placeholder={t('costpos.vendor')}
        onChange={(e) => setVendor(e.target.value)} className={`${fieldCls} w-36`} />
      <input data-testid={`offer-new-cost-${positionId}`} type="number" step="0.01" value={cost}
        aria-label={t('costpos.cost')} placeholder={t('costpos.cost')}
        onChange={(e) => setCost(e.target.value)} className={`${fieldCls} w-24 tabular-nums`} />
      <label className="flex items-center gap-1 text-xs text-slate-400">
        <input type="checkbox" data-testid={`offer-new-shipping-included-${positionId}`}
          checked={included} onChange={(e) => setIncluded(e.target.checked)} />
        {t('costpos.shippingIncluded')}
      </label>
      {!included && (
        <input data-testid={`offer-new-shipping-cost-${positionId}`} type="number" step="0.01"
          value={ship} aria-label={t('costpos.shipping')} placeholder={t('costpos.shipping')}
          onChange={(e) => setShip(e.target.value)} className={`${fieldCls} w-24 tabular-nums`} />
      )}
      <input data-testid={`offer-new-lead-${positionId}`} type="number" min={0} value={lead}
        aria-label={t('costpos.leadTime')} placeholder={t('costpos.leadTime')}
        onChange={(e) => setLead(e.target.value)} className={`${fieldCls} w-20 tabular-nums`} />
      <UnitSelect testId={`offer-new-unit-${positionId}`} value={unit} onChange={setUnit} />
      <button type="button" data-testid={`offer-add-${positionId}`}
        disabled={vendor.trim() === '' || add.isPending} onClick={() => add.mutate()}
        className="bg-sky-600 hover:bg-sky-500 text-white px-2 py-1 rounded text-xs disabled:opacity-50">
        {t('costpos.addOffer')}
      </button>
    </div>
  )
}


const cellCls = 'px-2 py-1.5 align-top'
const numCls = 'tabular-nums text-right'
const money = (v: number) => v.toFixed(2)

type LineType = 'time' | 'estimate' | 'quote'
const lineTypeOf = (p: CostPosition): LineType =>
  p.kind === 'external' ? (p.pricing === 'quote' ? 'quote' : 'estimate') : 'time'

/** A position row: reads as one line; edits in place; a quoted line opens its vendors. */
function PositionRow({ changeId, position, editable, index, categories, onChanged }: {
  changeId: number; position: CostPosition; editable: boolean; index: number
  categories: CostCategory[]; onChanged: () => void
}) {
  const p = position
  const [editing, setEditing] = useState(false)
  const [label, setLabel] = useState(p.label)
  const [hours, setHours] = useState(p.hours != null ? String(p.hours) : '')
  const [est, setEst] = useState(p.est_cost != null ? String(p.est_cost) : '')
  const [lead, setLead] = useState(p.lead_time_days != null ? String(p.lead_time_days) : '')
  const [unit, setUnit] = useState<LeadTimeUnit>(p.lead_time_unit ?? DEFAULT_UNIT)
  const [notes, setNotes] = useState(p.notes ?? '')

  const type = lineTypeOf(p)
  const isExternal = p.kind === 'external'
  const isQuote = type === 'quote'
  const cost = effectiveOf(p)
  const time = leadTimeOf(p)
  // With several offers and no vote the line has no price; a single offer
  // is the answer by itself (the backend prices it the same way).
  const needsFavorite = isQuote && (p.offers ?? []).length > 1
    && !(p.offers ?? []).some((o) => o.favorite)
  const chosen = chosenOf(p)
  const diverges = decisionDivergesOf(p)
  const offerCount = (p.offers ?? []).length

  const save = useMutation({
    mutationFn: () => changesApi.updateCostPosition(changeId, p.id, {
      label: label.trim(), hours: num(hours),
      est_cost: type === 'estimate' ? num(est) : null,
      lead_time_days: num(lead), lead_time_unit: unit,
      notes: notes.trim() || null,
    }),
    onSuccess: () => { toast.success(t('costpos.saved')); setEditing(false); onChanged() },
    onError: (e: unknown) => toast.error(errDetail(e) ?? 'Could not save the position'),
  })
  const remove = useMutation({
    mutationFn: () => changesApi.deleteCostPosition(changeId, p.id),
    onSuccess: onChanged,
    onError: (e: unknown) => toast.error(errDetail(e) ?? 'Could not delete the position'),
  })

  const amount = (
    <span data-testid={`costpos-cost-${p.id}`} className="text-slate-200 tabular-nums">
      {type === 'time'
        ? (p.hours != null ? `${p.hours} h` : '—')
        : <>
            {cost != null ? money(cost) : '—'}
            {p.hours != null && ` + ${p.hours} h`}
          </>}
    </span>
  )

  return (
    <>
      <tr data-testid={`costpos-row-${p.id}`}
        className={`border-t border-slate-700/70 ${editing ? 'bg-slate-800/60' : ''}`}>
        <td className={`${cellCls} text-slate-500 tabular-nums w-8`}>{index}</td>
        <td className={cellCls}>
          {p.tag ? (
            <span data-testid={`costpos-tag-${p.id}`} className="text-slate-200">
              {tagLabel(p.tag, categories)}
            </span>
          ) : <span className="text-slate-600">—</span>}
        </td>
        <td className={`${cellCls} min-w-[12rem]`}>
          {editing ? (
            <input data-testid={`costpos-edit-label-${p.id}`} value={label}
              aria-label={t('costpos.label')} autoFocus
              onChange={(e) => setLabel(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Escape') setEditing(false) }}
              className={`${fieldCls} w-full`} />
          ) : (
            <>
              <span data-testid={`costpos-label-${p.id}`} className="text-slate-100">{p.label}</span>
              {p.notes && <span className="block text-xs text-slate-500 whitespace-pre-wrap">{p.notes}</span>}
              {chosen && (
                <span data-testid={`costpos-chosen-${p.id}`}
                  className={`block text-xs ${diverges ? 'text-amber-300' : 'text-slate-400'}`}>
                  {t('vendor.salesChose')}: {chosen.vendor_name}
                  {diverges && ` (${t('vendor.againstRecommendation')})`}
                  {chosen.chosen_reason && (
                    <span className="block text-slate-500">{chosen.chosen_reason}</span>
                  )}
                </span>
              )}
            </>
          )}
        </td>
        <td className={`${cellCls} whitespace-nowrap`}>
          <span data-testid={`costpos-kind-${p.id}`} className="text-xs text-slate-400">
            {t(`costpos.type.${type}`)}
            <span className="sr-only"> · {t(`costpos.kind.${p.kind}`)}{isExternal && p.pricing ? ` · ${t(`costpos.pricing.${p.pricing}`)}` : ''}</span>
          </span>
          {isQuote && offerCount > 0 && (
            <span className="block text-[11px] text-slate-500">
              {offerCount === 1 ? t('costpos.offerCount1') : t('costpos.offersCount').replace('{n}', String(offerCount))}
            </span>
          )}
        </td>
        <td className={`${cellCls} ${numCls} whitespace-nowrap`}>
          {editing ? (
            <span className="inline-flex flex-col gap-1 items-end">
              {type === 'estimate' && (
                <input data-testid={`costpos-edit-est-${p.id}`} type="number" step="0.01" value={est}
                  aria-label={t('costpos.estCost')} placeholder={t('costpos.estCost')}
                  onChange={(e) => setEst(e.target.value)} className={`${fieldCls} w-28 tabular-nums`} />
              )}
              <input data-testid={`costpos-edit-hours-${p.id}`} type="number" step="0.5" value={hours}
                aria-label={isExternal ? t('costpos.ownTime') : t('costpos.hours')}
                placeholder={isExternal ? t('costpos.ownTime') : t('costpos.hours')}
                onChange={(e) => setHours(e.target.value)} className={`${fieldCls} w-28 tabular-nums`} />
            </span>
          ) : (
            <>
              {amount}
              {needsFavorite && (
                <span data-testid={`costpos-needs-favorite-${p.id}`}
                  className="block text-xs text-amber-300">★ {t('costpos.pickFavorite')}</span>
              )}
            </>
          )}
        </td>
        <td className={`${cellCls} whitespace-nowrap`}>
          {editing && !isQuote ? (
            <span className="inline-flex items-center gap-1">
              <input data-testid={`costpos-edit-lead-${p.id}`} type="number" min={0} value={lead}
                aria-label={t('costpos.leadTime')} placeholder={t('costpos.leadTime')}
                onChange={(e) => setLead(e.target.value)} className={`${fieldCls} w-16 tabular-nums`} />
              <UnitSelect testId={`costpos-edit-unit-${p.id}`} value={unit} onChange={setUnit} />
            </span>
          ) : time ? (
            <span data-testid={`costpos-lead-${p.id}`} className="text-xs text-slate-400">
              {leadTimeText(time.days, time.unit)}
            </span>
          ) : null}
        </td>
        <td className={`${cellCls} whitespace-nowrap text-right`}>
          {editable && (editing ? (
            <span className="inline-flex items-center gap-2">
              <button type="button" data-testid={`costpos-save-${p.id}`}
                disabled={label.trim() === '' || save.isPending} onClick={() => save.mutate()}
                className="bg-sky-600 hover:bg-sky-500 text-white px-2 py-1 rounded text-xs disabled:opacity-50 active:scale-[0.98]">
                {t('common.save')}
              </button>
              <button type="button" className="text-xs text-slate-400 hover:text-slate-200"
                onClick={() => setEditing(false)}>{t('costpos.cancelEdit')}</button>
            </span>
          ) : (
            <span className="inline-flex items-center gap-2 text-xs">
              <button type="button" data-testid={`costpos-edit-${p.id}`}
                onClick={() => setEditing(true)}
                className="text-slate-400 hover:text-slate-200">{t('costpos.edit')}</button>
              <button type="button" data-testid={`costpos-delete-${p.id}`}
                onClick={() => remove.mutate()} title={t('costpos.delete')}
                className="text-slate-500 hover:text-red-300">✕</button>
            </span>
          ))}
        </td>
      </tr>
      {editing && (
        <tr className="bg-slate-800/60">
          <td />
          <td colSpan={6} className={`${cellCls} pt-0`}>
            <input data-testid={`costpos-edit-notes-${p.id}`} value={notes}
              aria-label={t('costpos.notes')} placeholder={t('costpos.notes')}
              onChange={(e) => setNotes(e.target.value)} className={`${fieldCls} w-full`} />
          </td>
        </tr>
      )}
      {/* Quoted work carries its vendors with it — one row per offer, one star
          among them. */}
      {isQuote && (
        <tr data-testid={`costpos-offers-${p.id}`} className="bg-slate-900/40">
          <td />
          <td colSpan={6} className={`${cellCls} pt-0 pb-2`}>
            <p className="text-[11px] uppercase tracking-wide text-slate-500">{t('costpos.offers')}</p>
            {offerCount === 0 ? (
              <p className="text-xs text-slate-600">{t('costpos.noOffers')}</p>
            ) : (
              <ul>
                {(p.offers ?? []).map((o) => (
                  <OfferRow key={o.id} changeId={changeId} positionId={p.id} offer={o}
                    editable={editable} onChanged={onChanged} />
                ))}
              </ul>
            )}
            {editable && <NewOfferForm changeId={changeId} positionId={p.id} onAdded={onChanged} />}
          </td>
        </tr>
      )}
    </>
  )
}

/** The two standing effort answers, and the title each one files itself under. */
const EFFORT_FIELDS: { kind: CostPositionKind; labelKey: string; rowKey: string; descKey: string }[] = [
  { kind: 'internal_effort', labelKey: 'costpos.internalEffortField',
    rowKey: 'costpos.internalEffortRow', descKey: 'costpos.internalEffortDesc' },
  { kind: 'support_effort', labelKey: 'costpos.supportEffortField',
    rowKey: 'costpos.supportEffortRow', descKey: 'costpos.supportEffortDesc' },
]

/**
 * A standing row. It is a row, not a line anybody has to think about adding:
 * filling it the first time creates the position behind it (with the fixed
 * title as its label), and every save after that edits that one.
 */
function EffortRow({
  changeId, departmentId, kind, labelKey, rowKey, descKey, position, editable, index, onChanged,
}: {
  changeId: number; departmentId: number
  kind: CostPositionKind; labelKey: string; rowKey: string; descKey: string
  position?: CostPosition
  editable: boolean; index: number; onChanged: () => void
}) {
  const [hours, setHours] = useState(position?.hours != null ? String(position.hours) : '')
  const save = useMutation({
    mutationFn: () => position
      ? changesApi.updateCostPosition(changeId, position.id, { hours: num(hours) })
      : changesApi.createCostPosition(changeId, {
        department_id: departmentId, label: t(labelKey), kind, hours: num(hours),
      }),
    onSuccess: () => { toast.success(t('costpos.saved')); onChanged() },
    onError: (e: unknown) => toast.error(errDetail(e) ?? 'Could not save the effort'),
  })
  const dirty = num(hours) !== (position?.hours ?? null)
  const commit = () => { if (dirty && !save.isPending) save.mutate() }
  return (
    <tr className="border-t border-slate-700/70">
      <td className={`${cellCls} text-slate-500 tabular-nums w-8`}>{index}</td>
      <td className={cellCls}>
        <span className="text-slate-200">{t(rowKey)}</span>
        <span className="ml-1.5 rounded bg-slate-700/70 text-slate-400 px-1 py-0 text-[10px]">
          {t('costpos.standing')}
        </span>
      </td>
      <td className={`${cellCls} text-slate-400 text-xs`}>{t(descKey)}</td>
      <td className={`${cellCls} text-xs text-slate-400 whitespace-nowrap`}>{t('costpos.type.time')}</td>
      <td className={`${cellCls} ${numCls} whitespace-nowrap`}>
        {editable ? (
          <span className="inline-flex items-center gap-1.5">
            <label htmlFor={`effort-${kind}-${departmentId}`} className="sr-only">{t(labelKey)}</label>
            <input id={`effort-${kind}-${departmentId}`}
              data-testid={`costpos-effort-${kind}-${departmentId}`}
              type="number" step="0.5" min={0} value={hours}
              onChange={(e) => setHours(e.target.value)}
              onBlur={commit}
              onKeyDown={(e) => { if (e.key === 'Enter') commit() }}
              className={`${fieldCls} w-20 tabular-nums text-right`} />
            <span className="text-xs text-slate-500">h</span>
            <button type="button" data-testid={`costpos-effort-save-${kind}-${departmentId}`}
              disabled={!dirty || save.isPending} onClick={commit}
              className="bg-sky-600 hover:bg-sky-500 text-white px-2 py-1 rounded text-xs disabled:opacity-50">
              {t('common.save')}
            </button>
          </span>
        ) : (
          <span data-testid={`costpos-effort-value-${kind}-${departmentId}`}
            className="tabular-nums text-slate-200">
            {position?.hours != null ? position.hours : '—'}
          </span>
        )}
      </td>
      <td className={cellCls} />
      <td className={cellCls} />
    </tr>
  )
}

/** Tooling's standing row: what the part will weigh. An estimate, and it says so. */
function PartWeightRow({ changeId, departmentId, weightG, editable, index, onSaved }: {
  changeId: number; departmentId: number
  weightG: number | null | undefined
  editable: boolean; index: number; onSaved: () => void
}) {
  const [grams, setGrams] = useState(weightG != null ? String(weightG) : '')
  const save = useMutation({
    mutationFn: () => changesApi.setWeightEstimate(changeId, num(grams)),
    onSuccess: () => { toast.success(t('costpos.partWeightSaved')); onSaved() },
    onError: (e: unknown) => toast.error(errDetail(e) ?? 'Could not save the weight'),
  })
  const dirty = num(grams) !== (weightG ?? null)
  const commit = () => { if (dirty && !save.isPending) save.mutate() }
  return (
    <tr className="border-t border-slate-700/70">
      <td className={`${cellCls} text-slate-500 tabular-nums w-8`}>{index}</td>
      <td className={cellCls}>
        <span className="text-slate-200">{t('costpos.partWeightRow')}</span>
        <span className="ml-1.5 rounded bg-slate-700/70 text-slate-400 px-1 py-0 text-[10px]">
          {t('costpos.standing')}
        </span>
      </td>
      <td className={`${cellCls} text-slate-400 text-xs`}>{t('costpos.partWeightDesc')}</td>
      <td className={`${cellCls} text-xs text-slate-400 whitespace-nowrap`}>{t('costpos.type.weight')}</td>
      <td className={`${cellCls} ${numCls} whitespace-nowrap`}>
        {editable ? (
          <span className="inline-flex items-center gap-1.5">
            <label htmlFor={`part-weight-${departmentId}`} className="sr-only">{t('costpos.partWeightField')}</label>
            <input id={`part-weight-${departmentId}`}
              data-testid={`costpos-weight-${departmentId}`}
              type="number" step="1" min={0} value={grams}
              onChange={(e) => setGrams(e.target.value)}
              onBlur={commit}
              onKeyDown={(e) => { if (e.key === 'Enter') commit() }}
              className={`${fieldCls} w-20 tabular-nums text-right`} />
            <span className="text-xs text-slate-500">g</span>
            <button type="button" data-testid={`costpos-weight-save-${departmentId}`}
              disabled={!dirty || save.isPending} onClick={commit}
              className="bg-sky-600 hover:bg-sky-500 text-white px-2 py-1 rounded text-xs disabled:opacity-50">
              {t('common.save')}
            </button>
          </span>
        ) : (
          <span data-testid={`costpos-weight-value-${departmentId}`} className="tabular-nums text-slate-200">
            {weightG != null ? weightG : '—'}
          </span>
        )}
      </td>
      <td className={cellCls} />
      <td className={cellCls} />
    </tr>
  )
}

const ADD_CATEGORY = '__add_category'

/**
 * The add line at the foot of the table. Step by step: the category decides
 * what the line is (own hours, or money as estimate or vendor quote), then the
 * description, then the amount. Enter saves and clears for the next line.
 */
function AddLine({ changeId, departmentId, categories, onAdded, onCategoriesChanged }: {
  changeId: number; departmentId: number; categories: CostCategory[]
  onAdded: () => void; onCategoriesChanged: () => void
}) {
  const [tag, setTag] = useState('')
  const [label, setLabel] = useState('')
  const [pricing, setPricing] = useState<CostPositionPricing>('estimate')
  const [hours, setHours] = useState('')
  const [est, setEst] = useState('')
  const [lead, setLead] = useState('')
  const [unit, setUnit] = useState<LeadTimeUnit>(DEFAULT_UNIT)
  // "+ Add own category…" opens a two-field line: name and what it is.
  const [newCat, setNewCat] = useState<{ label: string; type: CostEntryType } | null>(null)

  const category = categories.find((c) => c.key === tag)
  const entryType: CostEntryType = category?.entry_type ?? 'money'
  const isTime = entryType === 'time'
  const isQuote = !isTime && pricing === 'quote'
  const lineType: LineType = isTime ? 'time' : pricing

  const reset = () => { setLabel(''); setHours(''); setEst(''); setLead('') }
  const add = useMutation({
    mutationFn: () => changesApi.createCostPosition(changeId, {
      department_id: departmentId,
      label: label.trim(),
      tag: tag || null,
      kind: isTime ? 'own_time' : 'external',
      pricing: isTime ? 'estimate' : pricing,
      hours: num(hours),
      est_cost: lineType === 'estimate' ? num(est) : null,
      lead_time_days: num(lead), lead_time_unit: unit,
    }),
    onSuccess: () => { reset(); onAdded() },
    onError: (e: unknown) => toast.error(errDetail(e) ?? 'Could not add the position'),
  })
  const createCategory = useMutation({
    mutationFn: (c: { label: string; type: CostEntryType }) =>
      changesApi.createCostCategory(departmentId, c.label.trim(), c.type),
    onSuccess: (row) => { onCategoriesChanged(); setTag(row.key); setNewCat(null); toast.success(t('costpos.categoryAdded')) },
    onError: (e: unknown) => toast.error(errDetail(e) ?? 'Could not add the category'),
  })
  const deleteCategory = useMutation({
    mutationFn: (id: number) => changesApi.deleteCostCategory(id),
    onSuccess: () => { onCategoriesChanged(); setTag(''); toast.success(t('costpos.categoryDeleted')) },
    onError: (e: unknown) => toast.error(errDetail(e) ?? 'Could not remove the category'),
  })

  const ready = label.trim() !== '' && !add.isPending
  const submitOnEnter = (e: React.KeyboardEvent) => { if (e.key === 'Enter' && ready) add.mutate() }
  const own = categories.filter((c) => c.extra && c.custom_id == null)
  const custom = categories.filter((c) => c.custom_id != null)
  const common = categories.filter((c) => !c.extra)
  const option = (c: CostCategory) => (
    <option key={c.key} value={c.key}>
      {tagLabel(c.key, categories)}{c.entry_type === 'time' ? ' · h' : ''}
    </option>
  )

  return (
    <>
      <tr data-testid={`costpos-new-${departmentId}`} className="border-t border-slate-600 bg-slate-800/40">
        <td className={`${cellCls} text-slate-500`}>+</td>
        <td className={cellCls}>
          <select data-testid={`costpos-new-tag-${departmentId}`}
            value={newCat !== null ? ADD_CATEGORY : tag} aria-label={t('costpos.tag')}
            onChange={(e) => {
              if (e.target.value === ADD_CATEGORY) { setNewCat({ label: '', type: 'money' }); return }
              setNewCat(null); setTag(e.target.value)
            }}
            className={`${fieldCls} w-44`}>
            <option value="">{t('costpos.pickCategory')}</option>
            {own.length > 0 && <optgroup label={t('costpos.tag')}>{own.map(option)}</optgroup>}
            {custom.length > 0 && <optgroup label={t('costpos.categoryHint').split(':')[0]}>{custom.map(option)}</optgroup>}
            {common.map(option)}
            <option value={ADD_CATEGORY}>{t('costpos.addCategory')}</option>
          </select>
          {category?.custom_id != null && (
            <button type="button" data-testid={`costpos-category-delete-${departmentId}`}
              title={t('costpos.categoryHint')} disabled={deleteCategory.isPending}
              onClick={() => deleteCategory.mutate(category.custom_id as number)}
              className="block mt-1 text-[11px] text-red-300 hover:text-red-200 underline decoration-dotted">
              {t('costpos.deleteCategory')}
            </button>
          )}
        </td>
        <td className={`${cellCls} min-w-[12rem]`}>
          <input data-testid={`costpos-new-label-${departmentId}`} value={label}
            aria-label={t('costpos.label')} placeholder={t('costpos.descPlaceholder')}
            onChange={(e) => setLabel(e.target.value)} onKeyDown={submitOnEnter}
            className={`${fieldCls} w-full`} />
        </td>
        <td className={`${cellCls} whitespace-nowrap`}>
          {isTime ? (
            <span className="text-xs text-slate-400">{t('costpos.type.time')}</span>
          ) : (
            <select data-testid={`costpos-new-pricing-${departmentId}`} value={pricing}
              aria-label={t('costpos.pricing')}
              onChange={(e) => setPricing(e.target.value as CostPositionPricing)}
              className={`${fieldCls} w-40`}>
              <option value="estimate">{t('costpos.type.estimate')}</option>
              <option value="quote">{t('costpos.type.quote')}</option>
            </select>
          )}
        </td>
        <td className={`${cellCls} ${numCls} whitespace-nowrap`}>
          <span className="inline-flex flex-col gap-1 items-end">
            {lineType === 'estimate' && (
              <input data-testid={`costpos-new-est-${departmentId}`} type="number" step="0.01"
                value={est} aria-label={t('costpos.estCost')} placeholder={t('costpos.cost')}
                onChange={(e) => setEst(e.target.value)} onKeyDown={submitOnEnter}
                className={`${fieldCls} w-28 tabular-nums text-right`} />
            )}
            {/* Money lines take the department's own time around the vendor too;
                a time line IS the hours. */}
            <input data-testid={`costpos-new-hours-${departmentId}`} type="number" step="0.5"
              value={hours} aria-label={isTime ? t('costpos.hours') : t('costpos.ownTime')}
              placeholder={isTime ? t('costpos.hours') : t('costpos.ownTime')}
              onChange={(e) => setHours(e.target.value)} onKeyDown={submitOnEnter}
              className={`${fieldCls} w-28 tabular-nums text-right`} />
          </span>
        </td>
        <td className={`${cellCls} whitespace-nowrap`}>
          {!isQuote && (
            <span className="inline-flex items-center gap-1">
              <input data-testid={`costpos-new-lead-${departmentId}`} type="number" min={0} value={lead}
                aria-label={t('costpos.leadTime')} placeholder={t('summation.days')}
                onChange={(e) => setLead(e.target.value)} onKeyDown={submitOnEnter}
                className={`${fieldCls} w-16 tabular-nums`} />
              <UnitSelect testId={`costpos-new-unit-${departmentId}`} value={unit} onChange={setUnit} />
            </span>
          )}
        </td>
        <td className={`${cellCls} text-right whitespace-nowrap`}>
          <button type="button" data-testid={`costpos-add-${departmentId}`}
            disabled={!ready} onClick={() => add.mutate()}
            className="bg-sky-600 hover:bg-sky-500 text-white px-2.5 py-1 rounded text-xs disabled:opacity-50 active:scale-[0.98]">
            {t('costpos.addLine')}
          </button>
        </td>
      </tr>
      {newCat !== null && (
        <tr className="bg-slate-800/40">
          <td />
          <td colSpan={6} className={`${cellCls} pt-0`}>
            <span className="inline-flex flex-wrap items-center gap-2">
              <input data-testid={`costpos-new-category-${departmentId}`} value={newCat.label} autoFocus
                aria-label={t('costpos.newCategoryLabel')} placeholder={t('costpos.newCategoryLabel')}
                onChange={(e) => setNewCat({ ...newCat, label: e.target.value })}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && newCat.label.trim()) createCategory.mutate(newCat)
                  if (e.key === 'Escape') setNewCat(null)
                }}
                className={`${fieldCls} w-48`} />
              <select data-testid={`costpos-new-category-type-${departmentId}`} value={newCat.type}
                aria-label={t('costpos.categoryType')}
                onChange={(e) => setNewCat({ ...newCat, type: e.target.value as CostEntryType })}
                className={`${fieldCls} w-40`}>
                <option value="money">{t('costpos.type.estimate')} / {t('costpos.type.quote')}</option>
                <option value="time">{t('costpos.type.time')}</option>
              </select>
              <button type="button" data-testid={`costpos-new-category-save-${departmentId}`}
                disabled={!newCat.label.trim() || createCategory.isPending}
                onClick={() => createCategory.mutate(newCat)}
                className="bg-sky-600 hover:bg-sky-500 text-white px-2 py-1 rounded text-xs disabled:opacity-50">
                {t('costpos.saveCategory')}
              </button>
              <button type="button" className="text-xs text-slate-400 hover:text-slate-200"
                onClick={() => setNewCat(null)}>{t('common.cancel')}</button>
              <span className="text-[11px] text-slate-500">{t('costpos.categoryHint')}</span>
            </span>
          </td>
        </tr>
      )}
    </>
  )
}

export default function CostPositions({
  changeId, departmentId, editable, departmentName, partWeightG,
}: {
  changeId: number
  departmentId: number
  /** The department's own members during costing (and PM). Everyone else reads. */
  editable: boolean
  /** Told by name, because the weight question belongs to Tooling alone. */
  departmentName?: string
  /** The change's current weight estimate, when there is one. */
  partWeightG?: number | null
}) {
  const qc = useQueryClient()
  const { data: positions } = useQuery({
    queryKey: ['costing-positions', changeId],
    queryFn: () => changesApi.listCostPositions(changeId),
  })
  const { data: tags } = useQuery({
    queryKey: ['costing-tags', departmentId],
    queryFn: () => changesApi.costingTags(departmentId),
  })
  const categories = tags?.items ?? []
  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ['costing-positions', changeId] })
    qc.invalidateQueries({ queryKey: ['change-summation', changeId] })
  }
  const mine = (positions ?? []).filter((p) => p.department_id === departmentId)
  // Each standing row binds to THE position of its kind. A department that
  // somehow has two keeps the extras in the list below rather than losing them.
  const boundIds = new Set(
    EFFORT_FIELDS.map(({ kind }) => mine.find((p) => p.kind === kind)?.id)
      .filter((id): id is number => id != null))
  const listed = mine.filter((p) => !boundIds.has(p.id))
  const isToolEngineer = departmentName === TOOL_ENGINEER_DEPARTMENT
  const weightSaved = () => {
    qc.invalidateQueries({ queryKey: ['change', changeId] })
    qc.invalidateQueries({ queryKey: ['change-summation', changeId] })
  }
  const standingCount = EFFORT_FIELDS.length + (isToolEngineer ? 1 : 0)
  const totalMoney = listed.reduce((s, p) => s + (lineTypeOf(p) === 'time' ? 0 : (effectiveOf(p) ?? 0)), 0)
  const totalHours = mine.reduce((s, p) => s + (p.hours ?? 0), 0)

  return (
    <div data-testid={`costpos-section-${departmentId}`} className="space-y-1">
      <div className="overflow-x-auto -mx-1">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-[11px] uppercase tracking-wide text-slate-500">
              <th className={`${cellCls} text-left font-normal w-8`}>{t('costpos.col.n')}</th>
              <th className={`${cellCls} text-left font-normal`}>{t('costpos.col.category')}</th>
              <th className={`${cellCls} text-left font-normal`}>{t('costpos.col.description')}</th>
              <th className={`${cellCls} text-left font-normal`}>{t('costpos.col.type')}</th>
              <th className={`${cellCls} text-right font-normal`}>{t('costpos.col.amount')}</th>
              <th className={`${cellCls} text-left font-normal whitespace-nowrap`}>{t('costpos.col.leadTime')}</th>
              <th className={cellCls} />
            </tr>
          </thead>
          <tbody data-testid={`costpos-effort-${departmentId}`}>
            {EFFORT_FIELDS.map(({ kind, labelKey, rowKey, descKey }, i) => {
              const bound = mine.find((p) => p.kind === kind)
              return (
                // Keyed on the position it binds to, so the row remounts once
                // that position arrives and shows the saved number.
                <EffortRow key={`${kind}-${bound?.id ?? 'new'}`}
                  changeId={changeId} departmentId={departmentId}
                  kind={kind} labelKey={labelKey} rowKey={rowKey} descKey={descKey}
                  position={bound} editable={editable} index={i + 1} onChanged={invalidate} />
              )
            })}
            {isToolEngineer && (
              <PartWeightRow key={`weight-${partWeightG ?? 'new'}`}
                changeId={changeId} departmentId={departmentId}
                weightG={partWeightG} editable={editable} index={standingCount}
                onSaved={weightSaved} />
            )}
          </tbody>
          <tbody data-testid={`costpos-list-${departmentId}`}>
            {listed.length === 0 ? (
              <tr className="border-t border-slate-700/70">
                <td />
                <td colSpan={6} className={`${cellCls} text-xs text-slate-600`}
                  data-testid={`costpos-empty-${departmentId}`}>
                  {t('costpos.noExternal')}
                </td>
              </tr>
            ) : listed.map((p, i) => (
              <PositionRow key={p.id} changeId={changeId} position={p} categories={categories}
                editable={editable} index={standingCount + i + 1} onChanged={invalidate} />
            ))}
          </tbody>
          <tfoot>
            {editable && (
              <AddLine changeId={changeId} departmentId={departmentId} categories={categories}
                onAdded={invalidate}
                onCategoriesChanged={() => qc.invalidateQueries({ queryKey: ['costing-tags', departmentId] })} />
            )}
            <tr className="border-t border-slate-600">
              <td />
              <td colSpan={3} className={`${cellCls} text-xs uppercase tracking-wide text-slate-500`}>
                {t('costpos.total')}
              </td>
              <td className={`${cellCls} ${numCls} text-slate-100 whitespace-nowrap`}
                data-testid={`costpos-total-${departmentId}`}>
                {money(totalMoney)}{totalHours > 0 && ` + ${totalHours} h`}
              </td>
              <td colSpan={2} />
            </tr>
          </tfoot>
        </table>
      </div>
      {!editable && (
        <p className="text-xs text-slate-600" data-testid={`costpos-readonly-${departmentId}`}>
          {t('costpos.readOnly')}
        </p>
      )}
    </div>
  )
}
