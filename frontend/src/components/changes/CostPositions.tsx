/**
 * The costing table — what a department books against a change, line by line.
 *
 * One table per department. The first rows are standing: the two answers every
 * department owes (assessment effort, implementation support) and, for
 * Tooling, the part weight. Every further line is a category from the
 * department's own list, and the category says what the line is:
 *
 *   own time     — hours, valued at the cost sheet's effective labour rate
 *                  (department, optional position, costing plant)
 *   machine time — machine hours x the machine class rate of the cost sheet
 *   sampling     — trials x the sampling price of the class
 *   estimate     — money, a house number
 *   vendor quote — money, read from the favourite of the offers under the line
 *
 * Every priced line says where its rate comes from ("Cost sheet v2, Tool
 * Engineer, Engineer, 21,50 USD/h"): the snapshot taken when the line was
 * costed. A line the sheet has no rate for says "No rate in the cost sheet"
 * and is not counted: never priced at 0.
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
import { useRef, useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { Star, X } from 'lucide-react'
import { changesApi } from '../../api/changes'
import { costSheetMachinesApi } from '../../api/costSheetMachines'
import ConfirmDialog from '../common/ConfirmDialog'
import { btnIcon, btnSm } from '../common/buttonStyles'
import { toastError } from '../../lib/apiError'
import AttachmentDropzone from './AttachmentDropzone'
import { AttachmentRow } from './AttachmentRow'
import { t } from '../../i18n/cmLabels'
import { TOOL_ENGINEER_DEPARTMENT } from '../../lib/departments'
import { formatHours, formatMoney, formatNumber } from '../../lib/format'
import type {
  CostCategory, CostEntryType, CostPosition, CostPositionKind, CostPositionPricing,
  CostingContext, CostingOffer, LeadTimeUnit,
} from '../../types/change'

const UNITS: LeadTimeUnit[] = ['calendar_days', 'business_days']

/** Calendar days unless somebody says otherwise — the safer reading of a bare number. */
const DEFAULT_UNIT: LeadTimeUnit = 'calendar_days'

/**
 * A dialog opened from inside a table cell still inherits the cell's text
 * styles (right-aligned, nowrap) through the DOM; this resets them.
 */
const DialogHost = ({ children }: { children: React.ReactNode }) => (
  <div className="contents text-left whitespace-normal normal-case tracking-normal font-normal">{children}</div>
)

const num = (s: string): number | null => (s.trim() === '' ? null : Number(s))

/** Money with its currency; a plain amount while the currency is not known
    (never a guessed "EUR"). */
const money = (v: number | null | undefined, currency: string | null | undefined): string =>
  currency ? formatMoney(v, currency) : formatNumber(v, { min: 2, max: 2 })

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
    return quotedTotal(p, pricedOffer(p))
  }
  if (p.effective_cost != null) return p.effective_cost
  return p.est_cost ?? null
}

/** Partial quotes on the line: always counted, summed. */
export const partsOf = (p: CostPosition): CostingOffer[] =>
  (p.offers ?? []).filter((o) => o.is_partial)
/** Full quotes on the line: alternatives, one of them counts. */
export const alternativesOf = (p: CostPosition): CostingOffer[] =>
  (p.offers ?? []).filter((o) => !o.is_partial)

const offerCost = (o: CostingOffer): number =>
  o.cost + (o.shipping_included ? 0 : o.shipping_cost ?? 0)

/** Parts add up; the alternative that counts comes on top. Null when nothing
    is quoted, or when alternatives exist and none counts yet. */
function quotedTotal(p: CostPosition, alternative: CostingOffer | undefined): number | null {
  const offers = p.offers ?? []
  if (offers.length === 0) return null
  if (alternativesOf(p).length > 0 && !alternative) return null
  return partsOf(p).reduce((s, o) => s + offerCost(o), 0) + (alternative ? offerCost(alternative) : 0)
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

/**
 * What the position is worth once Sales has decided. The department's own block
 * keeps reading its favourite (that is its vote, and it stays visible); the
 * wrap-up Sales quotes off reads the offer Sales actually chose.
 */
export function salesEffectiveOf(p: CostPosition): number | null {
  if (p.kind === 'external' && p.pricing === 'quote') {
    const chosen = chosenOf(p)
    if (chosen) return quotedTotal(p, chosen)
  }
  return effectiveOf(p)
}

/** The alternative a quoted position is read from: the favourite, or a lone
    alternative (which needs no vote to be the answer). Several alternatives
    without a vote give nothing — the department has not finished the job. */
const pricedOffer = (p: CostPosition): CostingOffer | undefined => {
  const alts = alternativesOf(p)
  return alts.find((o) => o.favorite) ?? (alts.length === 1 ? alts[0] : undefined)
}

const calendarDays = (o: CostingOffer): number =>
  o.lead_time_days == null ? 0
    : (o.lead_time_unit ?? DEFAULT_UNIT) === 'business_days' ? Math.ceil(o.lead_time_days * 7 / 5) : o.lead_time_days

/** The same rule for time: the slowest of what is counted (parts plus the
    priced alternative) is the position's lead time. */
export function leadTimeOf(p: CostPosition): { days: number; unit: LeadTimeUnit } | null {
  if (p.kind === 'external' && p.pricing === 'quote') {
    const alt = pricedOffer(p)
    const dated = [...partsOf(p), ...(alt ? [alt] : [])].filter((o) => o.lead_time_days != null)
    if (dated.length > 0) {
      const slowest = dated.reduce((a, b) => (calendarDays(b) > calendarDays(a) ? b : a))
      return { days: slowest.lead_time_days as number, unit: slowest.lead_time_unit ?? DEFAULT_UNIT }
    }
  }
  if (p.lead_time_days == null) return null
  return { days: p.lead_time_days, unit: p.lead_time_unit ?? DEFAULT_UNIT }
}

const fieldCls =
  'bg-slate-900 border border-slate-600 rounded px-2 py-1 text-sm text-slate-100'

/** The Suppliers master data, offered under every vendor field. */
function useSuppliers() {
  return useQuery({
    queryKey: ['suppliers'],
    queryFn: () => changesApi.listSuppliers(),
    staleTime: 5 * 60 * 1000,
    retry: false,
  })
}

/**
 * Vendor name with the Suppliers list behind it. A name that is not in the
 * list yet becomes a supplier the moment the row is saved, so the next person
 * finds it in the dropdown — the same habit as the department's own
 * categories, but on the master data everyone shares.
 */
function VendorField({ testId, value, onChange, placeholder, className }: {
  testId: string; value: string; onChange: (v: string) => void
  placeholder?: string; className?: string
}) {
  const { data: suppliers = [] } = useSuppliers()
  const listId = `${testId}-list`
  return (
    <>
      <input data-testid={testId} value={value} list={listId}
        aria-label={t('costpos.vendor')} placeholder={placeholder ?? t('costpos.vendor')}
        title={t('costpos.vendorHint')} autoComplete="off"
        onChange={(e) => onChange(e.target.value)}
        className={className ?? `${fieldCls} w-36`} />
      <datalist id={listId}>
        {suppliers.filter((s) => s.is_active !== false).map((s) => (
          <option key={s.id} value={s.name} />
        ))}
      </datalist>
    </>
  )
}

/** Store a vendor name the Suppliers list does not know yet. Best effort: a
    failure (name too short, no rights) must never block the row's save. */
async function ensureVendor(qc: ReturnType<typeof useQueryClient>, name: string) {
  const n = name.trim()
  if (n.length < 2) return
  const known = qc.getQueryData<{ id: number; name: string }[]>(['suppliers']) ?? []
  if (known.some((s) => s.name.toLowerCase() === n.toLowerCase())) return
  try {
    await changesApi.createSupplier(n)
    qc.invalidateQueries({ queryKey: ['suppliers'] })
  } catch {
    /* already there under another spelling, or not ours to add — the row is saved either way */
  }
}

/** The unit belongs to the number, so it is drawn as part of the same field. */
function UnitSelect({ testId, value, onChange }: {
  testId: string; value: LeadTimeUnit; onChange: (u: LeadTimeUnit) => void
}) {
  return (
    <select data-testid={testId} value={value} aria-label={t('costpos.unit')}
      onChange={(e) => onChange(e.target.value as LeadTimeUnit)}
      className={`${fieldCls} w-28`}>
      {UNITS.map((u) => (
        <option key={u} value={u}>{t(`costpos.unit.${u}`)}</option>
      ))}
    </select>
  )
}

/** Full quote (alternative) or partial quote (part): the one fact that decides
    whether the offer competes or adds up. */
function ScopeToggle({ testId, partial, onChange }: {
  testId: string; partial: boolean; onChange: (partial: boolean) => void
}) {
  return (
    <span data-testid={testId} role="group" aria-label={t('costpos.scopeHint')} title={t('costpos.scopeHint')}
      className="inline-flex rounded-md border border-slate-600 overflow-hidden divide-x divide-slate-600">
      {([false, true] as const).map((v) => (
        <button key={String(v)} type="button" data-testid={`${testId}-${v ? 'partial' : 'full'}`}
          aria-pressed={partial === v} onClick={() => onChange(v)}
          className={`px-2 h-6 text-[11px] whitespace-nowrap ${
            partial === v ? 'bg-slate-600 text-slate-100' : 'bg-slate-900 text-slate-500 hover:text-slate-200'}`}>
          {t(v ? 'costpos.scope.partial' : 'costpos.scope.full')}
        </button>
      ))}
    </span>
  )
}

function OfferRow({
  changeId, positionId, offer, currency, editable, onChanged,
}: {
  changeId: number; positionId: number; offer: CostingOffer
  /** The position's currency; offers carry none of their own. */
  currency: string | null
  editable: boolean; onChanged: () => void
}) {
  const qc = useQueryClient()
  const [vendor, setVendor] = useState(offer.vendor_name)
  const [cost, setCost] = useState(String(offer.cost))
  const [included, setIncluded] = useState(!!offer.shipping_included)
  const [ship, setShip] = useState(offer.shipping_cost != null ? String(offer.shipping_cost) : '')
  const [lead, setLead] = useState(offer.lead_time_days != null ? String(offer.lead_time_days) : '')
  const [unit, setUnit] = useState<LeadTimeUnit>(offer.lead_time_unit ?? DEFAULT_UNIT)
  const [partial, setPartial] = useState(!!offer.is_partial)

  const save = useMutation({
    mutationFn: async () => {
      await ensureVendor(qc, vendor)
      return changesApi.updateCostingOffer(changeId, offer.id, {
        vendor_name: vendor, cost: Number(cost) || 0,
        shipping_included: included,
        shipping_cost: included ? null : num(ship),
        lead_time_days: num(lead), lead_time_unit: unit,
        is_partial: partial,
      })
    },
    onSuccess: () => { toast.success(t('costpos.saved')); onChanged() },
    onError: (e: unknown) => toastError(e, 'Could not save the offer'),
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
      toastError(e, 'Could not set the favorite')
      onChanged()
    },
  })

  const remove = useMutation({
    mutationFn: () => changesApi.deleteCostingOffer(changeId, offer.id),
    onSuccess: onChanged,
  })
  const [confirmDelete, setConfirmDelete] = useState(false)
  const vendorName = offer.vendor_name.trim() || t('costpos.vendor')

  const dirty = vendor !== offer.vendor_name
    || Number(cost) !== offer.cost
    || included !== !!offer.shipping_included
    || (!included && num(ship) !== (offer.shipping_cost ?? null))
    || num(lead) !== (offer.lead_time_days ?? null)
    || unit !== (offer.lead_time_unit ?? DEFAULT_UNIT)
    || partial !== !!offer.is_partial

  const counted = !!offer.is_partial || !!offer.favorite
  return (
    <li data-testid={`offer-row-${offer.id}`}
      // What is counted is lit: a part always, an alternative when starred.
      className={`flex flex-wrap items-center gap-2 py-1.5 border-t border-slate-700/60 first:border-t-0 ${
        counted ? 'bg-amber-950/20 border-l border-l-amber-500 pl-2' : ''}`}>
      {/* A part is always counted, so it carries no star — the star is the
          choice among alternatives. */}
      {offer.is_partial ? (
        <span data-testid={`offer-part-${offer.id}`} title={t('costpos.scopeHint')}
          className="rounded bg-slate-700 text-slate-300 px-1 py-0 text-[11px] leading-tight">
          {t('costpos.partBadge')}
        </span>
      ) : editable ? (
        <button type="button" data-testid={`offer-fav-${offer.id}`}
          title={t('costpos.favoriteHint')} aria-pressed={!!offer.favorite}
          aria-label={`${t('costpos.favorite')}: ${vendorName}`}
          onClick={() => { if (!offer.favorite) favorite.mutate() }}
          className={`inline-flex h-6 w-6 items-center justify-center rounded focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400 ${
            offer.favorite ? 'text-amber-300' : 'text-slate-500 hover:text-slate-300'}`}>
          <Star aria-hidden="true" size={14} fill={offer.favorite ? 'currentColor' : 'none'} />
        </button>
      ) : (
        <span data-testid={`offer-fav-${offer.id}`} title={t('costpos.favorite')}
          className={`inline-flex h-6 w-6 items-center justify-center ${offer.favorite ? 'text-amber-300' : 'text-slate-600'}`}>
          <Star aria-hidden="true" size={14} fill={offer.favorite ? 'currentColor' : 'none'} />
          <span className="sr-only">{offer.favorite ? t('costpos.favorite') : ''}</span>
        </span>
      )}

      {editable ? (
        <>
          <VendorField testId={`offer-vendor-${offer.id}`} value={vendor} onChange={setVendor} />
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
          <ScopeToggle testId={`offer-scope-${offer.id}`} partial={partial} onChange={setPartial} />
          <button type="button" data-testid={`offer-save-${offer.id}`}
            disabled={!dirty || save.isPending} onClick={() => save.mutate()}
            className={btnSm.primary}>
            {t('common.save')}
          </button>
          <button type="button" data-testid={`offer-delete-${offer.id}`}
            onClick={() => setConfirmDelete(true)} title={t('costpos.delete')}
            aria-label={`Delete the offer from ${vendorName}`}
            className={`${btnIcon} h-7 w-7 hover:text-red-300`}>
            <X aria-hidden="true" size={14} />
          </button>
          <DialogHost><ConfirmDialog open={confirmDelete} danger
            title={`Delete the offer from ${vendorName}?`}
            body="The offer and its attached quote leave this cost line. If it was the favorite, the line needs a new pick before it has a price."
            confirmLabel="Delete offer" errorFallback="Could not delete the offer"
            onConfirm={() => remove.mutateAsync()} onClose={() => setConfirmDelete(false)}
            data-testid={`offer-delete-confirm-${offer.id}`} /></DialogHost>
        </>
      ) : (
        <>
          <span data-testid={`offer-vendor-${offer.id}`} className="text-slate-200 text-sm">
            {offer.vendor_name}
          </span>
          <span data-testid={`offer-cost-${offer.id}`} className="text-slate-300 text-sm tabular-nums">
            {money(offer.cost, currency)}
          </span>
          <span data-testid={`offer-shipping-${offer.id}`} className="text-xs text-slate-400">
            {t('costpos.shipping')}: {offer.shipping_included
              ? t('costpos.shippingIncluded')
              : `${money(offer.shipping_cost ?? 0, currency)} ${t('costpos.shippingSeparate')}`}
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
  const [partial, setPartial] = useState(false)
  const qc = useQueryClient()
  const add = useMutation({
    mutationFn: async () => {
      await ensureVendor(qc, vendor)
      return changesApi.addCostingOffer(changeId, positionId, {
        vendor_name: vendor.trim(), cost: Number(cost) || 0,
        shipping_included: included, shipping_cost: included ? null : num(ship),
        lead_time_days: num(lead), lead_time_unit: unit,
        is_partial: partial,
      })
    },
    onSuccess: () => {
      setVendor(''); setCost(''); setShip(''); setLead(''); setIncluded(false); setPartial(false)
      onAdded()
    },
    onError: (e: unknown) => toastError(e, 'Could not add the offer'),
  })
  return (
    <div data-testid={`offer-new-${positionId}`}
      className="flex flex-wrap items-center gap-2 pt-1.5 border-t border-slate-700/60">
      <VendorField testId={`offer-new-vendor-${positionId}`} value={vendor} onChange={setVendor} />
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
      <ScopeToggle testId={`offer-new-scope-${positionId}`} partial={partial} onChange={setPartial} />
      <button type="button" data-testid={`offer-add-${positionId}`}
        disabled={vendor.trim() === '' || add.isPending} onClick={() => add.mutate()}
        className={btnSm.secondary}>
        {t('costpos.addOffer')}
      </button>
    </div>
  )
}


const cellCls = 'px-2 py-1.5 align-top'
const numCls = 'tabular-nums text-right'

type LineType = 'time' | 'estimate' | 'quote' | 'machine' | 'sampling'
const lineTypeOf = (p: CostPosition): LineType =>
  p.kind === 'machine_time' ? 'machine'
    : p.kind === 'sampling' ? 'sampling'
      : p.kind === 'external' ? (p.pricing === 'quote' ? 'quote' : 'estimate') : 'time'

/** What the line's rate multiplies: trials on a sampling line, hours else. */
const quantityOf = (p: CostPosition): number =>
  p.kind === 'sampling' ? (p.trials ?? 0) : (p.hours ?? 0)

/**
 * Where the line's rate comes from, under its description: the cost sheet
 * version, department, position and rate ("Cost sheet v2, Tool Engineer,
 * Engineer, 21,50 USD/h"), or the missing-rate state.
 */
function RateNote({ p }: { p: CostPosition }) {
  if (p.rate_missing) {
    return (
      <span data-testid={`costpos-norate-${p.id}`} title={t('costpos.noRateHint')}
        className="mt-0.5 inline-flex items-center gap-1 rounded bg-amber-950/60 border border-amber-800/60 px-1.5 py-0 text-[11px] text-amber-200">
        {t('costpos.noRate')}
      </span>
    )
  }
  if (p.rate == null || !p.rate_label) return null
  // A money line without own hours has nothing the rate would price.
  if (p.kind === 'external' && quantityOf(p) <= 0) return null
  return (
    <span data-testid={`costpos-rate-${p.id}`}
      className="block text-[11px] text-slate-500 tabular-nums">
      {p.rate_label}
    </span>
  )
}

/** An old line (before its currency was recorded): the amount is read in
 * the costing plant's currency, and that is said, never silently. */
function CurrencyUnrecorded({ p }: { p: CostPosition }) {
  if (!p.currency_unrecorded || !p.currency) return null
  // only a money amount is read in the plant's currency: hours and trials
  // are priced at the rate, in the rate's own currency
  if (!(p.est_cost || p.effective_cost)) return null
  return (
    <span data-testid={`costpos-currency-unrecorded-${p.id}`}
      className="mt-0.5 block text-[11px] text-amber-300">
      {t('costpos.currencyUnrecorded').replace('{cur}', p.currency)}
    </span>
  )
}

/** hours (trials) x rate, in the line's currency; "not counted" without a rate. */
function LineValue({ p }: { p: CostPosition }) {
  if (quantityOf(p) <= 0) return null
  if (p.rate_missing) {
    return <span className="block text-[11px] text-amber-300">{t('costpos.notCounted')}</span>
  }
  if (p.line_value == null) return null
  return (
    <span data-testid={`costpos-value-${p.id}`} className="block text-xs text-slate-300 tabular-nums">
      {money(p.line_value, p.rate_currency ?? p.currency)}
    </span>
  )
}

/** The org's machine classes; the change's class is the default. */
function MachineClassSelect({ testId, value, ctx, onChange }: {
  testId: string; value: number | null; ctx?: CostingContext; onChange: (v: number | null) => void
}) {
  const classes = ctx?.machine_classes ?? []
  return (
    <select data-testid={testId} value={value ?? ''} aria-label={t('costpos.machineClass')}
      title={t('costpos.machineClass')}
      onChange={(e) => onChange(e.target.value === '' ? null : Number(e.target.value))}
      className={`${fieldCls} w-32 text-xs`}>
      <option value="">{t('costpos.machineClassPick')}</option>
      {classes.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
    </select>
  )
}

/** A named MachineDB press at the costing plant, narrowed to the class's
 * tonnage band when a class is picked. Its own cost sheet rate beats the
 * class rate; "Any machine" prices on the class. Hidden when the plant has
 * no synced machines. */
function MachineSelect({ testId, value, classId, ctx, onChange }: {
  testId: string; value: number | null; classId: number | null; ctx?: CostingContext
  onChange: (v: number | null) => void
}) {
  const plantId = ctx?.plant_id ?? null
  // the version that prices this change (valid on its creation date), so
  // "own rate" means an own rate there, not in today's version
  const versionId = ctx?.current_version?.id ?? null
  const q = useQuery({
    queryKey: ['cost-sheet', 'machines', 'pick', versionId],
    // all of the org's machines: the line's own machine stays listed even
    // when it is inactive now or sits at another plant
    queryFn: () => costSheetMachinesApi.list({ version_id: versionId }),
    enabled: plantId != null, staleTime: 60_000, retry: false,
  })
  const cls = ctx?.machine_classes.find((c) => c.id === classId)
  const inBand = (t: number | null) => !cls || (t != null
    && (cls.tonnage_min == null || t > cls.tonnage_min)
    && (cls.tonnage_max == null || t <= cls.tonnage_max))
  const machines = (q.data?.machines ?? []).filter((m) => m.id === value
    || (m.plant_id === plantId && m.active && inBand(m.clamping_force_t)))
  if (plantId == null || (machines.length === 0 && value == null)) return null
  return (
    <select data-testid={testId} value={value ?? ''} aria-label={t('costpos.machine')}
      title={t('costpos.machine')}
      onChange={(e) => onChange(e.target.value === '' ? null : Number(e.target.value))}
      className={`${fieldCls} w-44 text-xs`}>
      <option value="">{t('costpos.machineAny')}</option>
      {machines.map((m) => (
        <option key={m.id} value={m.id}>
          {m.internal_name}{m.clamping_force_t != null ? ` · ${formatNumber(m.clamping_force_t, { max: 0 })} t` : ''}
          {m.hourly_rate != null ? ` · ${t('costpos.ownRate')}` : ''}
          {m.active ? '' : ` (${t('costpos.machineInactive')})`}
        </option>
      ))}
    </select>
  )
}

/** A position row: reads as one line; edits in place; a quoted line opens its vendors. */
function PositionRow({ changeId, position, editable, index, categories, onChanged, ctx }: {
  changeId: number; position: CostPosition; editable: boolean; index: number
  categories: CostCategory[]; onChanged: () => void; ctx?: CostingContext
}) {
  const p = position
  const [editing, setEditing] = useState(false)
  const [classId, setClassId] = useState<number | null>(p.machine_class_id ?? null)
  const [machineId, setMachineId] = useState<number | null>(p.machine_id ?? null)
  const [trials, setTrials] = useState(p.trials != null ? String(p.trials) : '')
  const [label, setLabel] = useState(p.label)
  const [hours, setHours] = useState(p.hours != null ? String(p.hours) : '')
  const [est, setEst] = useState(p.est_cost != null ? String(p.est_cost) : '')
  const [vendor, setVendor] = useState(p.vendor_name ?? '')
  const [lead, setLead] = useState(p.lead_time_days != null ? String(p.lead_time_days) : '')
  const [unit, setUnit] = useState<LeadTimeUnit>(p.lead_time_unit ?? DEFAULT_UNIT)
  const [notes, setNotes] = useState(p.notes ?? '')
  const qc = useQueryClient()

  const type = lineTypeOf(p)
  const isExternal = p.kind === 'external'
  const isQuote = type === 'quote'
  const isMachine = type === 'machine' || type === 'sampling'
  const cost = effectiveOf(p)
  const time = leadTimeOf(p)
  // With several offers and no vote the line has no price; a single offer
  // is the answer by itself (the backend prices it the same way).
  const needsFavorite = isQuote && alternativesOf(p).length > 1
    && !alternativesOf(p).some((o) => o.favorite)
  const chosen = chosenOf(p)
  const diverges = decisionDivergesOf(p)
  const offerCount = (p.offers ?? []).length

  const save = useMutation({
    mutationFn: async () => {
      if (type === 'estimate') await ensureVendor(qc, vendor)
      return changesApi.updateCostPosition(changeId, p.id, {
        label: label.trim(),
        hours: type === 'sampling' ? null : num(hours),
        est_cost: type === 'estimate' ? num(est) : null,
        vendor_name: type === 'estimate' ? (vendor.trim() || null) : null,
        lead_time_days: num(lead), lead_time_unit: unit,
        notes: notes.trim() || null,
        ...(isMachine
          ? { machine_class_id: classId, machine_id: machineId,
              trials: type === 'sampling' ? num(trials) : null }
          : {}),
      })
    },
    onSuccess: () => { toast.success(t('costpos.saved')); setEditing(false); onChanged() },
    onError: (e: unknown) => toastError(e, 'Could not save the position'),
  })
  const remove = useMutation({
    mutationFn: () => changesApi.deleteCostPosition(changeId, p.id),
    onSuccess: onChanged,
  })
  const [confirmDelete, setConfirmDelete] = useState(false)

  const cur = p.currency ?? ctx?.currency ?? null
  const amount = (
    <span data-testid={`costpos-cost-${p.id}`} className="text-slate-200 tabular-nums">
      {type === 'time' || type === 'machine'
        ? formatHours(p.hours)
        : type === 'sampling'
          ? (p.trials != null ? `${p.trials} ${t('costpos.trialsShort')}` : '-')
          : cost != null
            ? <>{money(cost, cur)}{p.hours != null && ` + ${formatHours(p.hours)}`}</>
            : formatHours(p.hours)}
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
          ) : <span className="text-slate-600">-</span>}
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
              <RateNote p={p} />
              <CurrencyUnrecorded p={p} />
              {type === 'estimate' && p.vendor_name && (
                <span data-testid={`costpos-vendor-${p.id}`} className="block text-xs text-slate-400">
                  {t('costpos.vendor')}: {p.vendor_name}
                </span>
              )}
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
            {isMachine && p.machine_class && (
              <span className="block text-[11px] text-slate-500">
                {p.machine_class}{p.machine_class_from_change ? ` (${t('costpos.classFromChange')})` : ''}
              </span>
            )}
            {isMachine && p.machine_name && (
              <span data-testid={`costpos-machine-${p.id}`} className="block text-[11px] text-slate-400">
                {p.machine_name}{p.machine_rate_own ? ` (${t('costpos.ownRate')})` : ''}
              </span>
            )}
            <span className="sr-only"> · {t(`costpos.kind.${p.kind}`)}{isExternal && p.pricing ? ` · ${t(`costpos.pricing.${p.pricing}`)}` : ''}</span>
          </span>
          {isQuote && offerCount > 0 && (
            <span className="block text-[11px] text-slate-500" data-testid={`costpos-offer-summary-${p.id}`}>
              {partsOf(p).length > 0
                ? `${partsOf(p).length} ${t('costpos.partsSum')}${alternativesOf(p).length > 0
                  ? ` + ${alternativesOf(p).length} ${t('costpos.altSum')}` : ''}`
                : offerCount === 1 ? t('costpos.offerCount1') : t('costpos.offersCount').replace('{n}', String(offerCount))}
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
              {type === 'sampling' ? (
                <input data-testid={`costpos-edit-trials-${p.id}`} type="number" step="1" min={0}
                  value={trials} aria-label={t('costpos.trials')} placeholder={t('costpos.trials')}
                  onChange={(e) => setTrials(e.target.value)} className={`${fieldCls} w-28 tabular-nums`} />
              ) : (
                <input data-testid={`costpos-edit-hours-${p.id}`} type="number" step="0.5" value={hours}
                  aria-label={type === 'machine' ? t('costpos.machineHours') : isExternal ? t('costpos.ownTime') : t('costpos.hours')}
                  placeholder={type === 'machine' ? t('costpos.machineHours') : isExternal ? t('costpos.ownTime') : t('costpos.hours')}
                  onChange={(e) => setHours(e.target.value)} className={`${fieldCls} w-28 tabular-nums`} />
              )}
              {isMachine ? (
                <>
                  <MachineClassSelect testId={`costpos-edit-class-${p.id}`} value={classId} ctx={ctx}
                    onChange={setClassId} />
                  <MachineSelect testId={`costpos-edit-machine-${p.id}`} value={machineId}
                    classId={classId ?? ctx?.effective_machine_class_id ?? null} ctx={ctx}
                    onChange={setMachineId} />
                </>
              ) : null}
            </span>
          ) : (
            <>
              {amount}
              <LineValue p={p} />
              {needsFavorite && (
                <span data-testid={`costpos-needs-favorite-${p.id}`}
                  className="flex items-center justify-end gap-1 text-xs text-amber-300">
                  <Star aria-hidden="true" size={12} />{t('costpos.pickFavorite')}
                </span>
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
        <td className={`${cellCls} whitespace-nowrap text-right sticky right-0 bg-slate-800`}>
          {editable && (editing ? (
            <span className="inline-flex items-center gap-2">
              <button type="button" data-testid={`costpos-save-${p.id}`}
                disabled={label.trim() === '' || save.isPending} onClick={() => save.mutate()}
                className={btnSm.primary}>
                {t('common.save')}
              </button>
              <button type="button" className={btnSm.ghost}
                onClick={() => setEditing(false)}>{t('costpos.cancelEdit')}</button>
            </span>
          ) : (
            <span className="inline-flex items-center gap-1 text-xs">
              <button type="button" data-testid={`costpos-edit-${p.id}`}
                onClick={() => setEditing(true)} aria-label={`${t('costpos.edit')}: ${p.label}`}
                className={btnSm.ghost}>{t('costpos.edit')}</button>
              <button type="button" data-testid={`costpos-delete-${p.id}`}
                onClick={() => setConfirmDelete(true)} title={t('costpos.delete')}
                aria-label={`Delete cost line: ${p.label}`}
                className={`${btnIcon} h-7 w-7 hover:text-red-300`}>
                <X aria-hidden="true" size={14} />
              </button>
              <DialogHost><ConfirmDialog open={confirmDelete} danger
                title={`Delete cost line "${p.label}"?`}
                body={offerCount > 0
                  ? `The line and its ${offerCount === 1 ? 'vendor offer' : `${offerCount} vendor offers`} leave the costing. This cannot be undone.`
                  : 'The line leaves the costing and the totals. This cannot be undone.'}
                confirmLabel="Delete line" errorFallback="Could not delete the cost line"
                onConfirm={() => remove.mutateAsync()} onClose={() => setConfirmDelete(false)}
                data-testid={`costpos-delete-confirm-${p.id}`} /></DialogHost>
            </span>
          ))}
        </td>
      </tr>
      {editing && (
        <tr className="bg-slate-800/60">
          <td />
          <td colSpan={6} className={`${cellCls} pt-0 flex flex-wrap gap-2`}>
            {type === 'estimate' && (
              <VendorField testId={`costpos-edit-vendor-${p.id}`} value={vendor} onChange={setVendor}
                placeholder={t('costpos.vendorOptional')} />
            )}
            <input data-testid={`costpos-edit-notes-${p.id}`} value={notes}
              aria-label={t('costpos.notes')} placeholder={t('costpos.notes')}
              onChange={(e) => setNotes(e.target.value)} className={`${fieldCls} flex-1 min-w-[10rem]`} />
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
                    currency={cur} editable={editable} onChanged={onChanged} />
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
  editable: boolean; index: number; onChanged: () => void; ctx?: CostingContext
}) {
  const [hours, setHours] = useState(position?.hours != null ? String(position.hours) : '')
  // Blur and the Save click (or Enter, then blur) arrive in the same moment,
  // and isPending is only true after a render. One save at a time: a change
  // made while one is out (a second hours commit, a labour position pick) is
  // queued, the latest of each wins, and it goes out when the save settles.
  // A create answers with the new position's id; from then on every save of
  // this row (queued or new, until the row remounts on the listed position)
  // is an edit of that id, never a second create.
  type Patch = { hours?: true; labour_position?: string | null }
  const inFlight = useRef(false)
  const queued = useRef<Patch | null>(null)
  const createdId = useRef<number | null>(null)
  const targetId = () => position?.id ?? createdId.current
  const hoursRef = useRef(hours)
  hoursRef.current = hours
  // The hours the save in flight sent: a queued hours commit of the same
  // number has nothing left to say.
  const sentHours = useRef<string | null>(null)
  // The hours the server holds for this row, as far as this row knows.
  const savedHours = useRef<number | null>(position?.hours ?? null)
  const body = (p: Patch) => ({
    ...(p.hours ? { hours: num(hoursRef.current) } : {}),
    ...('labour_position' in p ? { labour_position: p.labour_position ?? null } : {}),
  })
  const save = useMutation({
    mutationFn: (p: Patch) => {
      const id = targetId()
      return id != null
        ? changesApi.updateCostPosition(changeId, id, body(p))
        : changesApi.createCostPosition(changeId, {
          department_id: departmentId, label: t(labelKey), kind, hours: num(hoursRef.current),
        })
    },
    onSuccess: (res: unknown) => {
      toast.success(t('costpos.saved'))
      if (targetId() == null) {
        const id = (res as { id?: number } | undefined)?.id
        if (id != null) createdId.current = id
      }
      if (sentHours.current !== null) savedHours.current = num(sentHours.current)
      inFlight.current = false
      let q = queued.current
      queued.current = null
      // A queued hours commit that matches what the server now holds has
      // nothing to say, also after a position-only save (nothing sent then).
      if (q?.hours && num(hoursRef.current) === savedHours.current) {
        q = 'labour_position' in q ? { labour_position: q.labour_position } : null
      }
      if (q) run(q)
      else onChanged()
    },
    onError: (e: unknown) => {
      inFlight.current = false
      toastError(e, 'Could not save the effort')
      const q = queued.current
      queued.current = null
      // What is still queued goes out (as an edit when there is a position to
      // edit); otherwise the row reloads what the server holds.
      if (q && targetId() != null) run(q)
      else onChanged()
    },
  })
  const dirty = num(hours) !== (position?.hours ?? null)
  const run = (p: Patch) => {
    if (inFlight.current) {
      queued.current = { ...queued.current, ...p }
      return
    }
    inFlight.current = true
    sentHours.current = p.hours || targetId() == null ? hoursRef.current : null
    save.mutate(p)
  }
  // Compared with what the server holds now (after a create, before the row
  // remounts, that is the created position's hours, not "nothing").
  const commit = () => {
    if (inFlight.current || num(hoursRef.current) !== savedHours.current) run({ hours: true })
  }
  return (
    <tr className="border-t border-slate-700/70">
      <td className={`${cellCls} text-slate-500 tabular-nums w-8`}>{index}</td>
      <td className={cellCls}>
        <span className="text-slate-200">{t(rowKey)}</span>
        <span className="ml-1.5 rounded bg-slate-700/70 text-slate-400 px-1 py-0 text-[11px]">
          {t('costpos.standing')}
        </span>
      </td>
      <td className={`${cellCls} text-slate-400 text-xs`}>
        {t(descKey)}
        {position && <RateNote p={position} />}
      </td>
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
              className={btnSm.secondary}>
              {t('common.save')}
            </button>
          </span>
        ) : (
          <span data-testid={`costpos-effort-value-${kind}-${departmentId}`}
            className="tabular-nums text-slate-200">
            {position?.hours != null ? position.hours : '-'}
          </span>
        )}
        {position && <LineValue p={position} />}
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
    onError: (e: unknown) => toastError(e, 'Could not save the weight'),
  })
  const dirty = num(grams) !== (weightG ?? null)
  const commit = () => { if (dirty && !save.isPending) save.mutate() }
  return (
    <tr className="border-t border-slate-700/70">
      <td className={`${cellCls} text-slate-500 tabular-nums w-8`}>{index}</td>
      <td className={cellCls}>
        <span className="text-slate-200">{t('costpos.partWeightRow')}</span>
        <span className="ml-1.5 rounded bg-slate-700/70 text-slate-400 px-1 py-0 text-[11px]">
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
              className={btnSm.secondary}>
              {t('common.save')}
            </button>
          </span>
        ) : (
          <span data-testid={`costpos-weight-value-${departmentId}`} className="tabular-nums text-slate-200">
            {weightG != null ? weightG : '-'}
          </span>
        )}
      </td>
      <td className={cellCls} />
      <td className={cellCls} />
    </tr>
  )
}

const ADD_CATEGORY = '__add_category'
/** Categories the cost sheet kinds replace for new lines (see AddLine). */
const HIDDEN_CATEGORIES = new Set(['sampling'])
/** The cost-sheet kinds, offered in the category list under their own group. */
const MACHINE_TIME = '__machine_time'
const SAMPLING = '__sampling'

/**
 * The add line at the foot of the table. Step by step: the category decides
 * what the line is (own hours, or money as estimate or vendor quote), then the
 * description, then the amount. Enter saves and clears for the next line.
 */
function AddLine({ changeId, departmentId, categories, onAdded, onCategoriesChanged, ctx }: {
  changeId: number; departmentId: number; categories: CostCategory[]
  onAdded: () => void; onCategoriesChanged: () => void; ctx?: CostingContext
}) {
  const [tag, setTag] = useState('')
  const [label, setLabel] = useState('')
  const [pricing, setPricing] = useState<CostPositionPricing>('estimate')
  const [hours, setHours] = useState('')
  const [est, setEst] = useState('')
  const [vendor, setVendor] = useState('')
  const [lead, setLead] = useState('')
  const [unit, setUnit] = useState<LeadTimeUnit>(DEFAULT_UNIT)
  const qc = useQueryClient()
  // "+ Add own category…" opens a two-field line: name and what it is.
  const [newCat, setNewCat] = useState<{ label: string; type: CostEntryType } | null>(null)

  const [trials, setTrials] = useState('')
  const [classId, setClassId] = useState<number | null>(null)
  const [machineId, setMachineId] = useState<number | null>(null)
  const isMachine = tag === MACHINE_TIME
  const isSampling = tag === SAMPLING
  const isSheetKind = isMachine || isSampling
  const category = isSheetKind ? undefined : categories.find((c) => c.key === tag)
  const entryType: CostEntryType = category?.entry_type ?? 'money'
  const isTime = !isSheetKind && entryType === 'time'
  const isQuote = !isTime && !isSheetKind && pricing === 'quote'
  const lineType: LineType = isMachine ? 'machine' : isSampling ? 'sampling' : isTime ? 'time' : pricing
  // A machine line defaults to the change's class (own or from the tool's tonnage).
  const effectiveClass = classId ?? ctx?.effective_machine_class_id ?? null

  const reset = () => {
    setLabel(''); setHours(''); setEst(''); setVendor(''); setLead(''); setTrials('')
  }
  const add = useMutation({
    mutationFn: async () => {
      if (lineType === 'estimate') await ensureVendor(qc, vendor)
      if (isSheetKind) {
        return changesApi.createCostPosition(changeId, {
          department_id: departmentId, label: label.trim(),
          kind: isMachine ? 'machine_time' : 'sampling', pricing: 'estimate',
          hours: isMachine ? num(hours) : null,
          trials: isSampling ? num(trials) : null,
          // A named machine brings its own class unless one was picked.
          machine_class_id: machineId != null ? classId : effectiveClass,
          machine_id: machineId,
          lead_time_days: num(lead), lead_time_unit: unit,
        })
      }
      return changesApi.createCostPosition(changeId, {
        department_id: departmentId,
        label: label.trim(),
        tag: tag || null,
        kind: isTime ? 'own_time' : 'external',
        pricing: isTime ? 'estimate' : pricing,
        hours: num(hours),
        est_cost: lineType === 'estimate' ? num(est) : null,
        vendor_name: lineType === 'estimate' ? (vendor.trim() || null) : null,
        lead_time_days: num(lead), lead_time_unit: unit,
      })
    },
    onSuccess: () => { reset(); onAdded() },
    onError: (e: unknown) => toastError(e, 'Could not add the position'),
  })
  const createCategory = useMutation({
    mutationFn: (c: { label: string; type: CostEntryType }) =>
      changesApi.createCostCategory(departmentId, c.label.trim(), c.type),
    onSuccess: (row) => { onCategoriesChanged(); setTag(row.key); setNewCat(null); toast.success(t('costpos.categoryAdded')) },
    onError: (e: unknown) => toastError(e, 'Could not add the category'),
  })
  const deleteCategory = useMutation({
    mutationFn: (id: number) => changesApi.deleteCostCategory(id),
    onSuccess: () => { onCategoriesChanged(); setTag(''); toast.success(t('costpos.categoryDeleted')) },
  })
  const [confirmCategory, setConfirmCategory] = useState(false)

  const ready = label.trim() !== '' && !add.isPending
  const submitOnEnter = (e: React.KeyboardEvent) => { if (e.key === 'Enter' && ready) add.mutate() }
  // Sampling is priced from the cost sheet (trials x the class's price), in
  // the group below. The old own-time "Sampling" category would sit next to
  // it under the same name, so it is not offered for new lines; lines that
  // already carry it keep their label.
  const offered = categories.filter((c) => !HIDDEN_CATEGORIES.has(c.key))
  const own = offered.filter((c) => c.extra && c.custom_id == null)
  const custom = offered.filter((c) => c.custom_id != null)
  const common = offered.filter((c) => !c.extra)
  const option = (c: CostCategory) => (
    <option key={c.key} value={c.key}>
      {tagLabel(c.key, categories)}{c.entry_type === 'time' && !tagLabel(c.key, categories).includes('(') ? ' (hours)' : ''}
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
              // A cost-sheet kind names itself until the user says more.
              if ((e.target.value === MACHINE_TIME || e.target.value === SAMPLING) && !label.trim()) {
                setLabel(t(e.target.value === MACHINE_TIME ? 'costpos.type.machine' : 'costpos.type.sampling'))
              }
            }}
            className={`${fieldCls} w-40`}>
            <option value="">{t('costpos.pickCategory')}</option>
            {own.length > 0 && <optgroup label={t('costpos.tag')}>{own.map(option)}</optgroup>}
            {custom.length > 0 && <optgroup label={t('costpos.categoryHint').split(':')[0]}>{custom.map(option)}</optgroup>}
            {common.map(option)}
            <optgroup label={t('costpos.costSheetGroup')}>
              <option value={MACHINE_TIME}>{t('costpos.kind.machine_time')}</option>
              <option value={SAMPLING}>{t('costpos.kind.sampling')}</option>
            </optgroup>
            <option value={ADD_CATEGORY}>{t('costpos.addCategory')}</option>
          </select>
          {category?.custom_id != null && (
            <>
              <button type="button" data-testid={`costpos-category-delete-${departmentId}`}
                title={t('costpos.categoryHint')} disabled={deleteCategory.isPending}
                onClick={() => setConfirmCategory(true)}
                className="block mt-1 text-[11px] text-red-300 hover:text-red-200 underline decoration-dotted">
                {t('costpos.deleteCategory')}
              </button>
              <DialogHost><ConfirmDialog open={confirmCategory} danger
                title={`Remove the category "${tagLabel(category.key, categories)}"?`}
                body="It leaves your department's category list. Lines that already use it keep it."
                confirmLabel="Remove category" errorFallback="Could not remove the category"
                onConfirm={() => deleteCategory.mutateAsync(category.custom_id as number)}
                onClose={() => setConfirmCategory(false)}
                data-testid={`costpos-category-delete-confirm-${departmentId}`} /></DialogHost>
            </>
          )}
        </td>
        <td className={`${cellCls} min-w-[9rem]`}>
          <span className="inline-flex flex-col gap-1 w-full">
            <input data-testid={`costpos-new-label-${departmentId}`} value={label}
              aria-label={t('costpos.label')} placeholder={t('costpos.descPlaceholder')}
              onChange={(e) => setLabel(e.target.value)} onKeyDown={submitOnEnter}
              className={`${fieldCls} w-full`} />
            {/* An estimated external line says who gave the number; a quoted
                one names its vendors on the offers below it. */}
            {lineType === 'estimate' && (
              <VendorField testId={`costpos-new-vendor-${departmentId}`} value={vendor}
                onChange={setVendor} placeholder={t('costpos.vendorOptional')}
                className={`${fieldCls} w-full`} />
            )}
          </span>
        </td>
        <td className={`${cellCls} whitespace-nowrap`}>
          {isSheetKind ? (
            <span className="inline-flex flex-col gap-1">
              <span className="text-xs text-slate-400">{t(`costpos.type.${lineType}`)}</span>
              <MachineClassSelect testId={`costpos-new-class-${departmentId}`} value={effectiveClass}
                ctx={ctx} onChange={setClassId} />
              <MachineSelect testId={`costpos-new-machine-${departmentId}`} value={machineId}
                classId={effectiveClass} ctx={ctx} onChange={setMachineId} />
            </span>
          ) : isTime ? (
            <span className="inline-flex flex-col gap-1">
              <span className="text-xs text-slate-400">{t('costpos.type.time')}</span>
            </span>
          ) : (
            // Two buttons, not a dropdown: a house number or a vendor's written
            // offer is the one choice on a money line, and it should be seen.
            <span data-testid={`costpos-new-pricing-${departmentId}`} role="group"
              aria-label={t('costpos.pricing')}
              className="inline-flex rounded-md border border-slate-600 overflow-hidden divide-x divide-slate-600">
              {(['estimate', 'quote'] as CostPositionPricing[]).map((v) => (
                <button key={v} type="button"
                  data-testid={`costpos-new-pricing-${departmentId}-${v}`}
                  aria-pressed={pricing === v} onClick={() => setPricing(v)}
                  className={`px-2.5 h-7 text-xs whitespace-nowrap transition-colors ${
                    pricing === v ? 'bg-sky-700 text-white' : 'bg-slate-900 text-slate-400 hover:text-slate-200'}`}>
                  {t(`costpos.pricingShort.${v}`)}
                </button>
              ))}
            </span>
          )}
        </td>
        <td className={`${cellCls} ${numCls} whitespace-nowrap`}>
          <span className="inline-flex flex-col gap-1 items-end">
            {lineType === 'estimate' && (
              <input data-testid={`costpos-new-est-${departmentId}`} type="number" step="0.01"
                value={est} aria-label={t('costpos.estCost')} placeholder={t('costpos.cost')}
                onChange={(e) => setEst(e.target.value)} onKeyDown={submitOnEnter}
                className={`${fieldCls} w-24 tabular-nums text-right`} />
            )}
            {/* Money lines take the department's own time around the vendor too;
                a time line IS the hours; a sampling line counts trials. */}
            {isSampling ? (
              <input data-testid={`costpos-new-trials-${departmentId}`} type="number" step="1" min={0}
                value={trials} aria-label={t('costpos.trials')} placeholder={t('costpos.trials')}
                onChange={(e) => setTrials(e.target.value)} onKeyDown={submitOnEnter}
                className={`${fieldCls} w-24 tabular-nums text-right`} />
            ) : (
              <input data-testid={`costpos-new-hours-${departmentId}`} type="number" step="0.5"
                value={hours}
                aria-label={isMachine ? t('costpos.machineHours') : isTime ? t('costpos.hours') : t('costpos.ownTime')}
                placeholder={isMachine ? t('costpos.machineHours') : isTime ? t('costpos.hours') : t('costpos.ownTime')}
                onChange={(e) => setHours(e.target.value)} onKeyDown={submitOnEnter}
                className={`${fieldCls} w-24 tabular-nums text-right`} />
            )}
          </span>
        </td>
        <td className={`${cellCls} whitespace-nowrap`}>
          {!isQuote && (
            <span className="inline-flex items-center gap-1">
              <input data-testid={`costpos-new-lead-${departmentId}`} type="number" min={0} value={lead}
                aria-label={t('costpos.leadTime')} placeholder={t('summation.days')}
                onChange={(e) => setLead(e.target.value)} onKeyDown={submitOnEnter}
                className={`${fieldCls} w-14 tabular-nums`} />
              <UnitSelect testId={`costpos-new-unit-${departmentId}`} value={unit} onChange={setUnit} />
            </span>
          )}
        </td>
        <td className={`${cellCls} text-right whitespace-nowrap sticky right-0 bg-slate-800`}>
          <button type="button" data-testid={`costpos-add-${departmentId}`}
            disabled={!ready} onClick={() => add.mutate()}
            className={btnSm.primary}>
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
                className={btnSm.secondary}>
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
  const { data: ctx } = useQuery({
    queryKey: ['costing-context', changeId],
    queryFn: () => changesApi.costingContext(changeId),
    retry: false,
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
  // The department's total, per currency (never added across currencies):
  // money lines plus every priced hours/trials value. Lines without a rate
  // are counted out loud, not as 0.
  const byCurrency = new Map<string, number>()
  const addTo = (cur: string, v: number) => byCurrency.set(cur, (byCurrency.get(cur) ?? 0) + v)
  for (const p of mine) {
    const cur = p.currency ?? ctx?.currency ?? ''
    const type = lineTypeOf(p)
    if (type === 'estimate' || type === 'quote') {
      const c = effectiveOf(p)
      if (c != null) addTo(cur, c)
    }
    if (p.line_value != null && quantityOf(p) > 0) addTo(p.rate_currency ?? cur, p.line_value)
  }
  const unpriced = mine.filter((p) => p.rate_missing).length
  const totalHours = mine.reduce((s, p) => s + (p.kind === 'machine_time' || p.kind === 'sampling' ? 0 : (p.hours ?? 0)), 0)
  const totals = [...byCurrency.entries()]

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
                  position={bound} editable={editable} index={i + 1} onChanged={invalidate}
                  ctx={ctx} />
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
                editable={editable} index={standingCount + i + 1} onChanged={invalidate} ctx={ctx} />
            ))}
          </tbody>
          <tfoot>
            {editable && (
              <AddLine changeId={changeId} departmentId={departmentId} categories={categories}
                ctx={ctx} onAdded={invalidate}
                onCategoriesChanged={() => qc.invalidateQueries({ queryKey: ['costing-tags', departmentId] })} />
            )}
            <tr className="border-t border-slate-600">
              <td />
              <td colSpan={3} className={`${cellCls} text-xs uppercase tracking-wide text-slate-500`}>
                {t('costpos.total')}
              </td>
              <td className={`${cellCls} ${numCls} text-slate-100 whitespace-nowrap`}
                data-testid={`costpos-total-${departmentId}`}>
                {totals.length === 0
                  ? money(0, ctx?.currency)
                  : totals.map(([cur, v]) => (
                    <span key={cur || '-'} className="block">{money(v, cur)}</span>
                  ))}
                {totalHours > 0 && (
                  <span className="block text-xs text-slate-400">{formatHours(totalHours)}</span>
                )}
                {unpriced > 0 && (
                  <span data-testid={`costpos-unpriced-${departmentId}`}
                    className="block text-[11px] text-amber-300" title={t('costpos.noRateHint')}>
                    {t('costpos.unpricedInTotal').replace('{n}', String(unpriced))}
                  </span>
                )}
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
