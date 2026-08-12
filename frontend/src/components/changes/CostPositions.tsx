/**
 * Cost positions — what a department actually books against a change.
 *
 * Two questions every department owes are always the same — how long the
 * assessment took, and how much support the implementation will need — so they
 * stand in the block as two labelled fields. Nobody should have to know that
 * "spent time" hides behind an add-form's kind picker; the first time a field is
 * filled it creates its position, and after that it edits it.
 *
 * Everything else is an external position: money the department has to spend
 * outside, plus the own time it costs to run the vendor.
 *
 * External money is either a house number or real vendor offers, and then the
 * department picks its favourite. The favourite is not decoration: it is the
 * offer the position's price and lead time are read from, so a position without
 * one is a position nobody has costed yet, and it says so.
 *
 * The department writes its own positions during costing. PM, Sales, the lead
 * and admins read them; Sales especially has nothing to fill in here — they get
 * the picture and put a price on it later.
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
  CostPosition, CostPositionKind, CostPositionPricing, CostingOffer, LeadTimeUnit,
} from '../../types/change'

const UNITS: LeadTimeUnit[] = ['calendar_days', 'business_days']

/** Calendar days unless somebody says otherwise — the safer reading of a bare number. */
const DEFAULT_UNIT: LeadTimeUnit = 'calendar_days'

const errDetail = (e: unknown): string | undefined =>
  (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail

const num = (s: string): number | null => (s.trim() === '' ? null : Number(s))

/** The tag reads as a label when it is one of the known keys, else as itself. */
export const tagLabel = (tag: string): string => {
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

/** The same rule for time: the favourite offer's lead time is the position's. */
export function leadTimeOf(p: CostPosition): { days: number; unit: LeadTimeUnit } | null {
  if (p.kind === 'external' && p.pricing === 'quote') {
    const fav = (p.offers ?? []).find((o) => o.favorite)
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

function PositionRow({ changeId, position, editable, onChanged }: {
  changeId: number; position: CostPosition; editable: boolean; onChanged: () => void
}) {
  const p = position
  const [editing, setEditing] = useState(false)
  const [label, setLabel] = useState(p.label)
  const [hours, setHours] = useState(p.hours != null ? String(p.hours) : '')
  const [est, setEst] = useState(p.est_cost != null ? String(p.est_cost) : '')
  const [lead, setLead] = useState(p.lead_time_days != null ? String(p.lead_time_days) : '')
  const [unit, setUnit] = useState<LeadTimeUnit>(p.lead_time_unit ?? DEFAULT_UNIT)
  const [notes, setNotes] = useState(p.notes ?? '')

  const isExternal = p.kind === 'external'
  const isQuote = isExternal && p.pricing === 'quote'
  const cost = effectiveOf(p)
  const time = leadTimeOf(p)
  // A quoted position with nobody's vote on it has no price and no date — the
  // department has collected offers and not finished the job.
  const needsFavorite = isQuote && !(p.offers ?? []).some((o) => o.favorite)

  const save = useMutation({
    mutationFn: () => changesApi.updateCostPosition(changeId, p.id, {
      label: label.trim(), hours: num(hours),
      est_cost: isQuote ? null : num(est),
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

  return (
    <li data-testid={`costpos-row-${p.id}`}
      className="rounded border border-slate-700 bg-slate-900/40 px-2 py-1.5 space-y-1.5">
      <div className="flex flex-wrap items-center gap-2">
        <span data-testid={`costpos-label-${p.id}`} className="text-slate-100 text-sm">
          {p.label}
        </span>
        {p.tag && (
          <span data-testid={`costpos-tag-${p.id}`}
            className="rounded bg-slate-700 text-slate-300 px-1.5 py-0 text-[10px] leading-tight">
            {tagLabel(p.tag)}
          </span>
        )}
        <span data-testid={`costpos-kind-${p.id}`} className="text-[11px] text-slate-500">
          {t(`costpos.kind.${p.kind}`)}
          {isExternal && p.pricing ? ` · ${t(`costpos.pricing.${p.pricing}`)}` : ''}
        </span>
        <span className="ml-auto flex items-center gap-3 text-xs">
          {time && (
            <span data-testid={`costpos-lead-${p.id}`} className="text-slate-400">
              {leadTimeText(time.days, time.unit)}
            </span>
          )}
          {/* Money and own time read as one figure: what it costs to buy and
              what it costs us to run. */}
          <span data-testid={`costpos-cost-${p.id}`} className="text-slate-300 tabular-nums">
            {cost != null ? cost.toFixed(2) : '—'}
            {p.hours != null && ` + ${p.hours} h`}
          </span>
          {editable && (
            <>
              <button type="button" data-testid={`costpos-edit-${p.id}`}
                onClick={() => setEditing((v) => !v)}
                className="text-slate-400 hover:text-slate-200">
                {t('costpos.edit')}
              </button>
              <button type="button" data-testid={`costpos-delete-${p.id}`}
                onClick={() => remove.mutate()} title={t('costpos.delete')}
                className="text-slate-500 hover:text-red-300">✕</button>
            </>
          )}
        </span>
      </div>

      {needsFavorite && (
        <p data-testid={`costpos-needs-favorite-${p.id}`}
          className="text-xs text-amber-300">
          ★ {t('costpos.pickFavorite')}
        </p>
      )}

      {p.notes && !editing && (
        <p className="text-xs text-slate-500 whitespace-pre-wrap">{p.notes}</p>
      )}

      {editable && editing && (
        <div data-testid={`costpos-editor-${p.id}`} className="flex flex-wrap items-center gap-2">
          <input data-testid={`costpos-edit-label-${p.id}`} value={label}
            aria-label={t('costpos.label')}
            onChange={(e) => setLabel(e.target.value)} className={`${fieldCls} w-48`} />
          {/* External work costs the department time too — coordination, trials. */}
          <input data-testid={`costpos-edit-hours-${p.id}`} type="number" step="0.5" value={hours}
            aria-label={isExternal ? t('costpos.ownTime') : t('costpos.hours')}
            placeholder={isExternal ? t('costpos.ownTime') : t('costpos.hours')}
            onChange={(e) => setHours(e.target.value)} className={`${fieldCls} w-28 tabular-nums`} />
          {!isQuote && (
            <input data-testid={`costpos-edit-est-${p.id}`} type="number" step="0.01" value={est}
              aria-label={t('costpos.estCost')} placeholder={t('costpos.estCost')}
              onChange={(e) => setEst(e.target.value)} className={`${fieldCls} w-28 tabular-nums`} />
          )}
          <input data-testid={`costpos-edit-lead-${p.id}`} type="number" min={0} value={lead}
            aria-label={t('costpos.leadTime')} placeholder={t('costpos.leadTime')}
            onChange={(e) => setLead(e.target.value)} className={`${fieldCls} w-24 tabular-nums`} />
          <UnitSelect testId={`costpos-edit-unit-${p.id}`} value={unit} onChange={setUnit} />
          <input data-testid={`costpos-edit-notes-${p.id}`} value={notes}
            aria-label={t('costpos.notes')} placeholder={t('costpos.notes')}
            onChange={(e) => setNotes(e.target.value)} className={`${fieldCls} flex-1 min-w-[8rem]`} />
          <button type="button" data-testid={`costpos-save-${p.id}`}
            disabled={label.trim() === '' || save.isPending} onClick={() => save.mutate()}
            className="bg-sky-600 hover:bg-sky-500 text-white px-2 py-1 rounded text-xs disabled:opacity-50">
            {t('common.save')}
          </button>
        </div>
      )}

      {/* Quoted external work carries its vendors with it — one row per offer,
          one star among them. */}
      {isQuote && (
        <div data-testid={`costpos-offers-${p.id}`} className="pl-2">
          <p className="text-[11px] uppercase tracking-wide text-slate-500">
            {t('costpos.offers')}
          </p>
          {(p.offers ?? []).length === 0 ? (
            <p className="text-xs text-slate-600">{t('costpos.noOffers')}</p>
          ) : (
            <ul>
              {(p.offers ?? []).map((o) => (
                <OfferRow key={o.id} changeId={changeId} positionId={p.id} offer={o}
                  editable={editable} onChanged={onChanged} />
              ))}
            </ul>
          )}
          {editable && (
            <NewOfferForm changeId={changeId} positionId={p.id} onAdded={onChanged} />
          )}
        </div>
      )}
    </li>
  )
}

/** The two standing effort answers, and the title each one files itself under. */
const EFFORT_FIELDS: { kind: CostPositionKind; labelKey: string }[] = [
  { kind: 'internal_effort', labelKey: 'costpos.internalEffortField' },
  { kind: 'support_effort', labelKey: 'costpos.supportEffortField' },
]

/**
 * One standing effort field. It is a field, not a position anybody has to think
 * about adding: filling it the first time creates the position behind it (with
 * the fixed title as its label), and every save after that edits that one.
 */
function EffortField({
  changeId, departmentId, kind, labelKey, position, editable, onChanged,
}: {
  changeId: number; departmentId: number
  kind: CostPositionKind; labelKey: string
  /** The department's position of this kind, once there is one. */
  position?: CostPosition
  editable: boolean; onChanged: () => void
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

  if (!editable) {
    return (
      <div className="flex items-baseline gap-2 text-sm">
        <span className="text-slate-400">{t(labelKey)}</span>
        <span data-testid={`costpos-effort-value-${kind}-${departmentId}`}
          className="tabular-nums text-slate-200">
          {position?.hours != null ? position.hours : '—'}
        </span>
      </div>
    )
  }
  return (
    <div className="flex flex-wrap items-center gap-2">
      <label htmlFor={`effort-${kind}-${departmentId}`} className="text-sm text-slate-300">
        {t(labelKey)}
      </label>
      <input id={`effort-${kind}-${departmentId}`}
        data-testid={`costpos-effort-${kind}-${departmentId}`}
        type="number" step="0.5" min={0} value={hours}
        onChange={(e) => setHours(e.target.value)}
        // Leaving the field is the ordinary way to save it; the button is for
        // people who want to see something happen.
        onBlur={commit}
        className={`${fieldCls} w-24 tabular-nums`} />
      <button type="button" data-testid={`costpos-effort-save-${kind}-${departmentId}`}
        disabled={!dirty || save.isPending} onClick={commit}
        className="bg-sky-600 hover:bg-sky-500 text-white px-2 py-1 rounded text-xs disabled:opacity-50">
        {t('common.save')}
      </button>
    </div>
  )
}

/**
 * What the part will weigh, quoted by Tooling while they cost the change.
 *
 * It stands next to the effort answers because it is the same kind of thing: a
 * question the department owes every time, not a position anybody adds. It is
 * an estimate and the label says so — the validated figure comes later from
 * somewhere else entirely, and this field never writes it.
 */
function PartWeightField({ changeId, departmentId, weightG, editable, onSaved }: {
  changeId: number; departmentId: number
  weightG: number | null | undefined
  editable: boolean; onSaved: () => void
}) {
  const [grams, setGrams] = useState(weightG != null ? String(weightG) : '')
  const save = useMutation({
    mutationFn: () => changesApi.setWeightEstimate(changeId, num(grams)),
    onSuccess: () => { toast.success(t('costpos.partWeightSaved')); onSaved() },
    onError: (e: unknown) => toast.error(errDetail(e) ?? 'Could not save the weight'),
  })
  const dirty = num(grams) !== (weightG ?? null)
  const commit = () => { if (dirty && !save.isPending) save.mutate() }

  if (!editable) {
    return (
      <div className="flex items-baseline gap-2 text-sm">
        <span className="text-slate-400">{t('costpos.partWeightField')}</span>
        <span data-testid={`costpos-weight-value-${departmentId}`}
          className="tabular-nums text-slate-200">
          {weightG != null ? weightG : '—'}
        </span>
      </div>
    )
  }
  return (
    <div className="flex flex-wrap items-center gap-2">
      <label htmlFor={`part-weight-${departmentId}`} className="text-sm text-slate-300">
        {t('costpos.partWeightField')}
      </label>
      <input id={`part-weight-${departmentId}`}
        data-testid={`costpos-weight-${departmentId}`}
        type="number" step="1" min={0} value={grams}
        onChange={(e) => setGrams(e.target.value)}
        // Same habit as the effort fields: leaving the box is what saves it.
        onBlur={commit}
        className={`${fieldCls} w-28 tabular-nums`} />
      <button type="button" data-testid={`costpos-weight-save-${departmentId}`}
        disabled={!dirty || save.isPending} onClick={commit}
        className="bg-sky-600 hover:bg-sky-500 text-white px-2 py-1 rounded text-xs disabled:opacity-50">
        {t('common.save')}
      </button>
    </div>
  )
}

/**
 * Adding a position means adding an external one — the two effort answers have
 * their own standing fields above, so the kind is not a question any more.
 */
function NewPositionForm({ changeId, departmentId, onAdded }: {
  changeId: number; departmentId: number; onAdded: () => void
}) {
  const [label, setLabel] = useState('')
  const [tag, setTag] = useState('')
  const [freeTag, setFreeTag] = useState('')
  const [pricing, setPricing] = useState<CostPositionPricing>('estimate')
  const [hours, setHours] = useState('')
  const [est, setEst] = useState('')
  const [lead, setLead] = useState('')
  const [unit, setUnit] = useState<LeadTimeUnit>(DEFAULT_UNIT)

  const { data: tags } = useQuery({
    queryKey: ['costing-tags', departmentId],
    queryFn: () => changesApi.costingTags(departmentId),
  })

  const isQuote = pricing === 'quote'

  const add = useMutation({
    mutationFn: () => changesApi.createCostPosition(changeId, {
      department_id: departmentId,
      label: label.trim(),
      tag: (tag === '__free' ? freeTag.trim() : tag) || null,
      kind: 'external',
      pricing,
      hours: num(hours),
      est_cost: isQuote ? null : num(est),
      lead_time_days: num(lead), lead_time_unit: unit,
    }),
    onSuccess: () => {
      setLabel(''); setTag(''); setFreeTag(''); setHours(''); setEst(''); setLead('')
      onAdded()
    },
    onError: (e: unknown) => toast.error(errDetail(e) ?? 'Could not add the position'),
  })

  return (
    <div data-testid={`costpos-new-${departmentId}`}
      className="flex flex-wrap items-center gap-2 rounded border border-slate-700 bg-slate-900/30 px-2 py-2">
      <input data-testid={`costpos-new-label-${departmentId}`} value={label}
        aria-label={t('costpos.label')} placeholder={t('costpos.labelPlaceholder')}
        onChange={(e) => setLabel(e.target.value)} className={`${fieldCls} w-48`} />

      <select data-testid={`costpos-new-tag-${departmentId}`} value={tag}
        aria-label={t('costpos.tag')}
        onChange={(e) => setTag(e.target.value)} className={`${fieldCls} w-40`}>
        <option value="">{t('costpos.tagNone')}</option>
        {(tags?.items ?? []).map((item) => (
          <option key={item.key} value={item.key}>{tagLabel(item.key)}</option>
        ))}
        {/* The list never covers everything — a department may name its own. */}
        <option value="__free">{t('costpos.tagFree')}</option>
      </select>
      {tag === '__free' && (
        <input data-testid={`costpos-new-tag-free-${departmentId}`} value={freeTag}
          aria-label={t('costpos.tag')} placeholder={t('costpos.tagFree')}
          onChange={(e) => setFreeTag(e.target.value)} className={`${fieldCls} w-40`} />
      )}

      {/* External work takes the department's own time around the vendor —
          coordination, trials — and that is not the vendor's price. */}
      <input data-testid={`costpos-new-hours-${departmentId}`} type="number" step="0.5"
        value={hours} aria-label={t('costpos.ownTime')} placeholder={t('costpos.ownTime')}
        onChange={(e) => setHours(e.target.value)} className={`${fieldCls} w-28 tabular-nums`} />
      <select data-testid={`costpos-new-pricing-${departmentId}`} value={pricing}
        aria-label={t('costpos.pricing')}
        onChange={(e) => setPricing(e.target.value as CostPositionPricing)}
        className={`${fieldCls} w-32`}>
        <option value="estimate">{t('costpos.pricing.estimate')}</option>
        <option value="quote">{t('costpos.pricing.quote')}</option>
      </select>
      {!isQuote && (
        <input data-testid={`costpos-new-est-${departmentId}`} type="number" step="0.01"
          value={est} aria-label={t('costpos.estCost')} placeholder={t('costpos.estCost')}
          onChange={(e) => setEst(e.target.value)} className={`${fieldCls} w-28 tabular-nums`} />
      )}
      <input data-testid={`costpos-new-lead-${departmentId}`} type="number" min={0} value={lead}
        aria-label={t('costpos.leadTime')} placeholder={t('costpos.leadTime')}
        onChange={(e) => setLead(e.target.value)} className={`${fieldCls} w-24 tabular-nums`} />
      <UnitSelect testId={`costpos-new-unit-${departmentId}`} value={unit} onChange={setUnit} />

      <button type="button" data-testid={`costpos-add-${departmentId}`}
        disabled={label.trim() === '' || add.isPending} onClick={() => add.mutate()}
        className="bg-sky-600 hover:bg-sky-500 text-white px-2.5 py-1 rounded text-xs disabled:opacity-50">
        {t('costpos.addExternal')}
      </button>
    </div>
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
  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ['costing-positions', changeId] })
    qc.invalidateQueries({ queryKey: ['change-summation', changeId] })
  }
  const mine = (positions ?? []).filter((p) => p.department_id === departmentId)
  // Each standing field binds to THE position of its kind. A department that
  // somehow has two keeps the extras in the list below rather than losing them.
  const boundIds = new Set(
    EFFORT_FIELDS.map(({ kind }) => mine.find((p) => p.kind === kind)?.id)
      .filter((id): id is number => id != null))
  const listed = mine.filter((p) => !boundIds.has(p.id))
  // The weight lives on the change, not on a position, so saving it refreshes
  // the change and the wrap-up that reads it — the positions are untouched.
  const isToolEngineer = departmentName === TOOL_ENGINEER_DEPARTMENT
  const weightSaved = () => {
    qc.invalidateQueries({ queryKey: ['change', changeId] })
    qc.invalidateQueries({ queryKey: ['change-summation', changeId] })
  }

  return (
    <div data-testid={`costpos-section-${departmentId}`} className="space-y-3">
      {/* The two answers every department owes, in front of them from the
          moment the block opens. */}
      <div data-testid={`costpos-effort-${departmentId}`} className="space-y-1.5">
        <p className="text-[11px] uppercase tracking-wide text-slate-500">
          {t('costpos.effortTitle')}
        </p>
        {EFFORT_FIELDS.map(({ kind, labelKey }) => {
          const bound = mine.find((p) => p.kind === kind)
          return (
            // Keyed on the position it binds to, so the field remounts once that
            // position arrives and shows the saved number instead of the empty
            // box it started as.
            <EffortField key={`${kind}-${bound?.id ?? 'new'}`}
              changeId={changeId} departmentId={departmentId}
              kind={kind} labelKey={labelKey} position={bound}
              editable={editable} onChanged={invalidate} />
          )
        })}
        {/* Tooling is the department that can answer this one, so it is asked
            here and nowhere else. */}
        {isToolEngineer && (
          <PartWeightField key={`weight-${partWeightG ?? 'new'}`}
            changeId={changeId} departmentId={departmentId}
            weightG={partWeightG} editable={editable} onSaved={weightSaved} />
        )}
      </div>

      <div className="space-y-2">
        <p className="text-[11px] uppercase tracking-wide text-slate-500">
          {t('costpos.externalTitle')}
        </p>
        {listed.length === 0 ? (
          <p className="text-xs text-slate-600" data-testid={`costpos-empty-${departmentId}`}>
            {t('costpos.noExternal')}
          </p>
        ) : (
          <ul className="space-y-1.5" data-testid={`costpos-list-${departmentId}`}>
            {listed.map((p) => (
              <PositionRow key={p.id} changeId={changeId} position={p}
                editable={editable} onChanged={invalidate} />
            ))}
          </ul>
        )}
        {editable ? (
          <NewPositionForm changeId={changeId} departmentId={departmentId} onAdded={invalidate} />
        ) : (
          <p className="text-xs text-slate-600" data-testid={`costpos-readonly-${departmentId}`}>
            {t('costpos.readOnly')}
          </p>
        )}
      </div>
    </div>
  )
}
