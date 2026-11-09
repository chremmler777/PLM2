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
import { requestBookHours, requestHoursCorrection } from '../../api/hours'
import { COSTING_REFETCH_MS, invalidateCosting } from '../../lib/invalidateCosting'
import { useRef, useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { Send, Star, X } from 'lucide-react'
import { changesApi } from '../../api/changes'
import { costSheetMachinesApi } from '../../api/costSheetMachines'
import ConfirmDialog from '../common/ConfirmDialog'
import { btnIcon, btnSm } from '../common/buttonStyles'
import { toastError } from '../../lib/apiError'
import AttachmentDropzone from './AttachmentDropzone'
import { DownloadIcons } from './AttachmentRow'
import { t } from '../../i18n/cmLabels'
import { PositionBasis } from './costing/PositionBasis'
import { machineClassOriginDetail, machineClassOriginText } from './machineClassOrigin'
import { TOOL_ENGINEER_DEPARTMENT } from '../../lib/departments'
import { formatDate, formatHours, formatMoney, formatNumber } from '../../lib/format'
import type { Attachment } from '../../types/change'
import type {
  CostCategory, CostEntryType, CostPosition, CostPositionKind, CostPositionPricing,
  CostingContext, CostingOffer, LeadTimeUnit, SupplierWait,
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

/** The line's name in the total, led by its category title when it has one
 *  ("Lab Measurement: hgjh"), Christoph 2026-11-09. */
export const titledName = (p: CostPosition, name: string, items?: CostCategory[]): string => {
  if (!p.tag) return name
  const title = tagLabel(p.tag, items).replace(/ \((hours|h)\)$/, '')
  return title && title !== name ? `${title}: ${name}` : name
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
    // the backend's line total counts spare parts as amount x price + transport
    if (p.effective_cost != null && (p.quantity_unit ?? '') === 'pcs') return p.effective_cost
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

/** A lead time in calendar days (what every roll-up compares). */
const calendarOf = (lt: { days: number; unit: LeadTimeUnit }): number =>
  lt.unit === 'business_days' ? Math.ceil(lt.days * 7 / 5) : lt.days

/** Christoph 2026-11-09: a spare part that is not time critical does not set
 *  the lead time (the backend's counts_for_lead_time, same rule). Unanswered
 *  counts: the safe side until the department says. */
export const countsForLeadTime = (p: CostPosition): boolean =>
  p.counts_for_lead_time ?? !(isSpareLine(p) && p.time_critical === false)

export interface LeadSummary {
  /** the longest counted line, calendar days (0 = none) */
  days: number
  leader: CostPosition | null
  /** spare parts left out (not time critical), with their days */
  excluded: { p: CostPosition; days: number }[]
}

/** The department's lead time: the longest line that counts. */
export function leadSummary(lines: CostPosition[]): LeadSummary {
  let days = 0
  let leader: CostPosition | null = null
  const excluded: LeadSummary['excluded'] = []
  for (const p of lines) {
    // the backend's calendar days when served, else read from the offers
    const lt = leadTimeOf(p)
    const d = p.effective_lead_time_calendar_days ?? (lt ? calendarOf(lt) : 0)
    if (!countsForLeadTime(p)) {
      if (d > 0) excluded.push({ p, days: d })
    } else if (d > days) {
      days = d
      leader = p
    }
  }
  return { days, leader, excluded }
}

/** Who sets the lead time: "spare part X, time critical" / "Hitech, tool change". */
export function leaderText(p: CostPosition): string {
  if (isSpareLine(p)) {
    return t(p.time_critical === true ? 'costpos.tc.leaderSpare' : 'costpos.tc.leaderSpareOpen')
      .replace('{name}', spareName(p.label))
  }
  if (p.kind !== 'external') return p.label.replace(/ \(h\)$/, '')
  const vendor = pricedOffer(p)?.vendor_name ?? p.vendor_name
  return [vendor, t('costpos.tc.toolChange')].filter(Boolean).join(', ')
}

/** "spare part not time critical (30 d) excluded", or null when none is. */
export function excludedText(s: LeadSummary): string | null {
  if (!s.excluded.length) return null
  const d = Math.max(...s.excluded.map((x) => x.days))
  return s.excluded.length === 1
    ? t('costpos.tc.excluded').replace('{d}', String(d))
    : t('costpos.tc.excludedMany').replace('{n}', String(s.excluded.length)).replace('{d}', String(d))
}

/** "30 d (spare part X, time critical)" or
 *  "15 d (Hitech, tool change) · spare part not time critical (30 d) excluded". */
export function leadSummaryText(s: LeadSummary): string {
  const head = s.leader && s.days > 0 ? `${s.days} d (${leaderText(s.leader)})` : s.days > 0 ? `${s.days} d` : '-'
  const ex = excludedText(s)
  return ex ? `${head} · ${ex}` : head
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

/** Christoph 2026-11-08: a quoted supplier line as a table, one line per
 *  supplier: Supplier · Status · Quote file · Days · Price · favourite.
 *  An asked shop waits until "Quote received", then its line takes the file,
 *  days, price (and quote no.); the received line shows them, the star picks. */
function SupplierLines({ changeId, position: p, editable, currency, onChanged, estimate = false }: {
  changeId: number; position: CostPosition; editable: boolean
  currency: string | null; onChanged: () => void
  /** the line is priced on an estimate: the estimate row, then the asked shops */
  estimate?: boolean
}) {
  const qc = useQueryClient()
  const { data: waits } = useQuery({
    queryKey: ['change', changeId, 'supplier-waits'],
    queryFn: () => changesApi.listSupplierWaits(changeId),
  })
  const key = (v: string) => v.trim().toLowerCase()
  // a wait without a line belongs to the department's only supplier line
  const { data: allPositions } = useQuery({
    queryKey: ['costing-positions', changeId],
    queryFn: () => changesApi.listCostPositions(changeId),
  })
  // Christoph 2026-11-08: every supplier wait sits in a line's box; one without
  // a line belongs to the department's first external line
  const firstLine = (allPositions ?? []).find((x) => x.department_id === p.department_id
    && x.kind === 'external')
  const asked = (waits ?? []).filter((w) => w.position_id === p.id
    || (w.position_id == null && firstLine?.id === p.id && w.department_id === p.department_id))
  const offers = p.offers ?? []
  // one row per received quote, plus one per asked shop without a quote
  const names: string[] = asked.map((w) => w.vendor_name)
    .filter((v, n, all) => all.findIndex((x) => key(x) === key(v)) === n)
    .filter((v) => !offers.some((o) => key(o.vendor_name) === key(v)))
  const [received, setReceived] = useState<Set<string>>(new Set())
  const [shop, setShop] = useState('')
  const spare = isSpareLine(p)
  const group = lineGroupOf(p)
  const qty = spare && perPieceOf(p) > 0 && p.quantity_unit === 'pcs' ? (p.quantity ?? null) : null
  const [item, setItem] = useState('')
  const [itemQty, setItemQty] = useState('1')
  // Christoph 2026-11-08: several spare parts, each its own line; the add sits under the last one
  const spares = (allPositions ?? []).filter((x) => x.department_id === p.department_id
    && isSpareLine(x))
  const lastSpare = spares.length === 0 || spares[spares.length - 1].id === p.id
  const addItem = useMutation({
    mutationFn: () => changesApi.createCostPosition(changeId, {
      department_id: p.department_id, label: item.trim(), kind: 'external', pricing: 'estimate',
      quantity: num(itemQty) ?? 1, quantity_unit: 'pcs', notes: 'From the assessment: Spare part required',
    }),
    onSuccess: () => { setItem(''); setItemQty('1'); refresh() },
    onError: (e: unknown) => toastError(e, 'Could not add the item'),
  })
  const { data: fcheck } = useQuery({
    queryKey: ['change', changeId, 'finalize-check', p.department_id],
    queryFn: () => changesApi.finalizeCheck(changeId, p.department_id),
    enabled: editable,
  })
  const lineMissing = !!fcheck?.position_ids?.includes(p.id)
  const refresh = () => { invalidateCosting(qc, changeId); onChanged() }
  const iso = (d: Date) => d.toISOString().slice(0, 10)
  // Christoph 2026-11-08: a request states when it was asked and when the quote is expected
  const [askedOn, setAskedOn] = useState(iso(new Date()))
  const [expectedBy, setExpectedBy] = useState('')
  const canAsk = shop.trim().length >= 2 && !!askedOn && !!expectedBy && expectedBy >= askedOn
  const ask = useMutation({
    mutationFn: () => changesApi.startSupplierWait(changeId, {
      department_id: p.department_id, vendor_name: shop.trim(), asked_on: askedOn,
      expected_by: expectedBy, position_id: p.id }),
    onSuccess: () => { setShop(''); setExpectedBy(''); setAskedOn(iso(new Date())); refresh() },
    onError: (e: unknown) => toastError(e, 'Could not record the RFQ'),
  })
  const star = useMutation({
    mutationFn: (id: number) => changesApi.updateCostingOffer(changeId, id, { favorite: true }),
    onSuccess: onChanged,
    onError: (e: unknown) => toastError(e, 'Could not pick the favourite'),
  })
  const th = 'px-2 py-1 text-left text-[11px] font-medium uppercase tracking-wide text-slate-500'
  const td = 'px-2 py-1 text-xs align-middle'
  return (
    <div className={`mt-1 rounded-lg border ${GROUP_STYLE[group].border} bg-slate-800/60 p-2`}
      data-missing={lineMissing ? 'yes' : 'no'} data-group={group}>
    <p className="mb-1 text-xs font-semibold text-slate-200">
      {/* Christoph 2026-11-08: what the box is, in its type colour, before how it is priced */}
      <span data-testid={`supplier-type-${p.id}`}
        className={`mr-2 inline-flex items-center gap-1 rounded px-1.5 text-[11px] font-semibold ${GROUP_STYLE[group].chip}`}>
        {t(GROUP_STYLE[group].labelKey)}</span>
      <span className="mr-2 rounded border border-slate-500 px-1.5 text-[11px] font-semibold text-slate-200">
        {estimate ? t('costpos.bannerEstimate') : t('costpos.bannerQuotes')}</span>
      {offers.filter((x) => !x.is_partial).length > 1 && !offers.some((x) => x.favorite) && (
        <span className="mr-2 rounded bg-red-800 px-1.5 text-[11px] font-semibold text-red-100">{t('costpos.pickFavoriteBanner')}</span>
      )}
      {t('costpos.quotesBox').replace('{w}', String(asked.filter((w) => w.is_open && !offers.some((x) => key(x.vendor_name) === key(w.vendor_name))).length))
        .replace('{r}', String(offers.length))}</p>
    {spare && <SpareAmount changeId={changeId} position={p} editable={editable} onChanged={refresh} />}
    {estimate && !editable && (
      <p className="text-xs text-slate-300">{money(p.est_cost, currency)} · {p.lead_time_days ?? '-'} d · {p.basis_ref ?? ''}</p>
    )}
    <table className="w-full table-fixed" data-testid={`supplier-lines-${p.id}`}>
      {/* Christoph 2026-11-08: fixed column widths */}
      <colgroup>
        <col style={{ width: '13%' }} /><col style={{ width: '19%' }} /><col style={{ width: '22%' }} />
        <col style={{ width: '9%' }} /><col style={{ width: '11%' }} /><col style={{ width: '11%' }} />
        <col style={{ width: '15%' }} />
      </colgroup>
      <thead>
        <tr>
          <th className={th}>{t('costpos.supplier')}</th><th className={th}>{t('costpos.status')}</th>
          <th className={th}>{t('costpos.shopFile')}</th><th className={`${th} text-right`} title={t('costpos.totalDays')}>{t('costpos.daysShort')}</th>
          <th className={`${th} text-right`}>{t(spare ? 'costpos.pricePerPc' : 'costpos.price')}</th>
          <th className={`${th} text-right`}>{t('costpos.transport')}</th><th className={th} />
        </tr>
      </thead>
      <tbody>
        {estimate && (
          <EstimateLine changeId={changeId} position={p} td={td} editable={editable}
            currency={currency} onChanged={refresh} spare={spare} qty={qty} />
        )}
        {names.length === 0 && offers.length === 0 && !estimate && (
          <tr><td className={`${td} text-slate-600`} colSpan={7}>{t('costpos.rfqNone')}</td></tr>
        )}
        {offers.map((o) => (
          <ReceivedLine key={`o${o.id}`} changeId={changeId} positionId={p.id} offer={o} td={td} fileOptional={spare} qty={qty}
            wait={asked.find((w) => key(w.vendor_name) === key(o.vendor_name))}
            editable={editable} currency={currency} onChanged={onChanged}
            onStar={() => star.mutate(o.id)} starring={star.isPending} />
        ))}
        {names.map((n) => {
          const w = asked.find((x) => key(x.vendor_name) === key(n))
          // marked "quote in" elsewhere without the quote: enter it now
          if (w && editable && (received.has(n) || (!w.is_open && w.close_reason === 'received'))) {
            return <ShopQuoteLine key={n} changeId={changeId} positionId={p.id} shop={n} td={td}
              fileOptional={spare} qty={qty} currency={currency} onDone={refresh} onCancel={async () => {
                const r = new Set(received); r.delete(n); setReceived(r)
                try { await changesApi.reopenSupplierWait(changeId, w.id) } catch (e) { toastError(e, 'Could not undo') }
                refresh()
              }} />
          }
          return (
            <tr key={n} data-testid={`supplier-line-${p.id}-${n}`} className="border-t border-slate-700/60">
              <td className={`${td} font-medium text-slate-200`}>{n}</td>
              <td className={td}>
                {w && !w.is_open && editable && w.close_reason !== 'not_received' && (
                  <button type="button" className="mr-1 text-[11px] underline text-slate-400"
                    onClick={async () => { try { await changesApi.reopenSupplierWait(changeId, w.id) } catch (e) { toastError(e, 'Could not undo') } refresh() }}>
                    {t('costpos.undo')}</button>
                )}
                {w && !w.is_open ? (
                  <span className={`rounded px-1.5 font-semibold ${w.close_reason === 'not_received'
                    ? 'bg-red-900/70 text-red-100' : 'bg-slate-700 text-slate-200'}`}>
                    {t(`wait.sup.badge.${w.close_reason ?? 'not_needed'}`)}</span>
                ) : (
                  <span className={`rounded px-1.5 ${w?.overdue ? 'bg-red-900/70 text-red-100' : 'bg-slate-700 text-slate-200'}`}>
                    {t('wait.sup.badge.open')}{w ? ` · ${w.chip}` : ''}</span>
                )}
                {w && <RfqDates w={w} />}
              </td>
              <td className={td} colSpan={5}>
                {editable && w?.is_open && (
                  <button type="button" className={btnSm.secondary} data-testid={`rfq-received-${w.id}`}
                    onClick={async () => {
                      try {
                        if (estimate) await changesApi.updateCostPosition(changeId, p.id, { pricing: 'quote' })
                        await changesApi.closeSupplierWait(changeId, w.id, { reason: 'received' })
                      } catch (e) { toastError(e, 'Could not mark the quote received') }
                      setReceived(new Set([...received, n]))
                      refresh()
                    }}>{t('costpos.quoteReceived')}</button>
                )}
              </td>
            </tr>
          )
        })}
      </tbody>
    </table>
    {editable && (
      // Christoph 2026-11-08: the request is an action, not another quote row:
      // its own strip below the table, the same in every box
      <div data-testid={`rfq-request-${p.id}`}
        className="mt-2 flex flex-wrap items-end gap-x-3 gap-y-2 rounded-md border border-dashed border-slate-600 bg-slate-900/70 px-3 py-2">
        <span className="inline-flex items-center gap-1.5 self-center text-xs font-semibold text-slate-100">
          <Send aria-hidden="true" size={14} className="text-slate-300" />{t('costpos.requestQuote')}</span>
        <label className="flex flex-col gap-0.5 text-[11px] text-slate-300">{t('costpos.supplier')}
          <input value={shop} onChange={(e) => setShop(e.target.value)}
            data-testid={`rfq-shop-new-${p.id}`} placeholder={t('costpos.rfqAddShop')}
            onKeyDown={(e) => { if (e.key === 'Enter' && canAsk) ask.mutate() }}
            className={`${fieldCls} w-48`} /></label>
        <label className="flex flex-col gap-0.5 text-[11px] text-slate-300">{t('wait.sup.askedOn')}
          <input type="date" value={askedOn} max={iso(new Date())} onChange={(e) => setAskedOn(e.target.value)}
            data-testid={`rfq-asked-${p.id}`} className={fieldCls} /></label>
        <label className="flex flex-col gap-0.5 text-[11px] text-slate-300">{t('wait.sup.expectedBy')}
          <input type="date" value={expectedBy} min={askedOn} onChange={(e) => setExpectedBy(e.target.value)}
            data-testid={`rfq-expected-${p.id}`}
            className={`${fieldCls} ${shop.trim().length >= 2 && !expectedBy ? 'border-red-600' : ''}`} /></label>
        <button type="button" data-testid={`rfq-shop-add-${p.id}`}
          className="rounded border border-sky-500 px-2.5 py-1 text-xs font-semibold text-sky-100 hover:bg-sky-900/50 disabled:cursor-not-allowed disabled:opacity-50"
          disabled={!canAsk || ask.isPending} onClick={() => ask.mutate()}>
          {t('costpos.addRequest')}</button>
      </div>
    )}
    {spare && editable && lastSpare && (
      <div className="mt-2 flex flex-wrap items-center gap-2 rounded-md border border-dashed border-slate-600 bg-slate-900/70 px-3 py-2" data-testid={`spare-add-${p.id}`}>
        <input value={item} onChange={(e) => setItem(e.target.value)} placeholder={t('costpos.itemName')}
          data-testid={`spare-new-${p.id}`} className={`${fieldCls} w-64`} />
        <input type="number" step="1" min={1} value={itemQty} onChange={(e) => setItemQty(e.target.value)}
          aria-label={t('costpos.amount')} placeholder={t('costpos.amount')}
          data-testid={`spare-new-qty-${p.id}`} className={`${fieldCls} w-20 tabular-nums text-right`} />
        <span className="text-xs text-slate-400">{t('costpos.pcs')}</span>
        <button type="button" className={btnSm.secondary} data-testid={`spare-new-add-${p.id}`}
          disabled={item.trim().length < 2 || !(Number(itemQty) > 0) || addItem.isPending}
          onClick={() => addItem.mutate()}>{t('costpos.addItem')}</button>
      </div>
    )}
    </div>
  )
}

/** Christoph 2026-11-08: when the quote was asked, and when it is expected
 *  (red + overdue while still waiting past it) or when it came in. */
function RfqDates({ w }: { w: SupplierWait }) {
  const asked = formatDate(w.asked_on)
  const received = !w.is_open && w.close_reason === 'received'
  const late = w.is_open && w.overdue
  return (
    <span className="mt-1 block pb-0.5 text-xs leading-snug text-slate-200 tabular-nums" data-testid={`rfq-dates-${w.id}`}>
      {t('costpos.rfqAsked')} {asked}
      {' · '}
      {received ? (
        <>{t('costpos.rfqReceivedOn')} {w.closed_at ? formatDate(w.closed_at) : '-'}</>
      ) : (
        <span className={late ? 'font-semibold text-red-300' : undefined}>
          {t('costpos.rfqExpected')} {formatDate(w.expected_by)}{late ? ` · ${t('costpos.rfqOverdue')}` : ''}
        </span>
      )}
    </span>
  )
}

/** Christoph 2026-11-08: the filed quote shows its file name (download),
 *  with delete (Yes/No) and replace. */
function QuoteFileCell({ changeId, offerId, file: a, editable, onChanged }: {
  changeId: number; offerId: number; file: Attachment; editable: boolean; onChanged: () => void
}) {
  const [asking, setAsking] = useState(false)
  const del = useMutation({
    mutationFn: () => changesApi.deleteAttachment(changeId, a.id),
    onSuccess: onChanged,
    onError: (e: unknown) => toastError(e, 'Could not delete the file'),
  })
  const replace = useMutation({
    mutationFn: async (f: File) => {
      await changesApi.uploadAttachment(changeId, f, { kind: 'vendor_quote', costingOfferId: offerId })
      await changesApi.deleteAttachment(changeId, a.id)
    },
    onSuccess: onChanged,
    onError: (e: unknown) => toastError(e, 'Could not replace the file'),
  })
  return (
    <span className="inline-flex max-w-full items-center gap-1 overflow-hidden">
      <DownloadIcons changeId={changeId} attachments={[a]} />
      {editable && !asking && (
        <>
          <label className="cursor-pointer text-[11px] text-slate-400 underline hover:text-slate-200"
            title={t('costpos.replaceFile')}>
            {t('costpos.replaceFile')}
            <input type="file" className="sr-only" accept=".pdf,.xlsx,.xls,.doc,.docx,.msg,.eml"
              onChange={(e) => { const f = e.target.files?.[0]; if (f) replace.mutate(f) }} />
          </label>
          <button type="button" aria-label={`Delete ${a.filename}`} title={t('risk.confirmDelete')}
            className="px-1 text-sm leading-none text-red-300 hover:text-red-200" onClick={() => setAsking(true)}>×</button>
        </>
      )}
      {asking && (
        <span className="inline-flex items-center gap-1">
          <span className="text-[11px] text-red-200">{t('risk.confirmDelete')}</span>
          <button type="button" className="rounded bg-red-800 px-1.5 text-[11px] text-white"
            onClick={() => { setAsking(false); del.mutate() }}>{t('risk.yes')}</button>
          <button type="button" className="rounded border border-slate-600 px-1.5 text-[11px] text-slate-200"
            onClick={() => setAsking(false)}>{t('risk.no')}</button>
        </span>
      )}
    </span>
  )
}

/** Christoph 2026-11-08: the estimate as a row of the same supplier table:
 *  vendor, ESTIMATE + what it is based on, days total, price, (transport). */
function EstimateLine({ changeId, position: p, td, editable, currency, onChanged, spare = false, qty = null }: {
  changeId: number; position: CostPosition; td: string; editable: boolean
  currency: string | null; onChanged: () => void
  /** a spare part: the estimate is the catalogue price */
  spare?: boolean
  /** a spare part's amount: the price is per piece */
  qty?: number | null
}) {
  const [vendor, setVendor] = useState(p.vendor_name ?? '')
  const [basis, setBasis] = useState(p.basis_ref ?? '')
  const [days, setDays] = useState(p.lead_time_days != null ? String(p.lead_time_days) : '')
  const [cost, setCost] = useState(p.est_cost != null ? String(p.est_cost) : '')
  const dirty = vendor.trim() !== (p.vendor_name ?? '') || basis.trim() !== (p.basis_ref ?? '')
    || num(days) !== (p.lead_time_days ?? null) || num(cost) !== (p.est_cost ?? null)
  const save = useMutation({
    mutationFn: () => changesApi.updateCostPosition(changeId, p.id, {
      vendor_name: vendor.trim() || null, basis: 'estimate', basis_ref: basis.trim() || null,
      lead_time_days: num(days), lead_time_unit: 'calendar_days', est_cost: num(cost),
    }),
    onSuccess: () => { toast.success(t('costpos.saved')); onChanged() },
    onError: (e: unknown) => toastError(e, 'Could not save the estimate'),
  })
  const noPrice = !(Number(cost) > 0)
  const noDays = !(Number(days) >= 1)
  const noBasis = basis.trim().length < 5
  const missing = noPrice || noDays || noBasis
  const f = `${fieldCls} w-full tabular-nums text-right`
  return (
    <tr data-testid={`estimate-line-${p.id}`} data-missing={missing ? 'yes' : 'no'}
      className={`border-t border-slate-700/60 ${missing ? 'bg-red-950/40 outline outline-1 outline-red-700/70' : ''}`}>
      <td className={td}>
        {editable ? <input value={vendor} onChange={(e) => setVendor(e.target.value)}
          placeholder={t('costpos.vendor')} aria-label={t('costpos.vendor')} className={`${fieldCls} w-full`} />
          : <span className="font-medium text-slate-100">{p.vendor_name ?? '-'}</span>}
      </td>
      <td className={td}>
        <span className="rounded border border-slate-500 px-1.5 text-[11px] font-semibold text-slate-200">{t('costpos.bannerEstimate')}</span>
        {editable ? <input value={basis} onChange={(e) => setBasis(e.target.value)}
          placeholder={t(spare ? 'costpos.spareBasis' : 'costpos.estBasisShort')} title={t('costpos.estBasis')} aria-label={t('costpos.estBasis')}
          className={`${fieldCls} mt-0.5 block w-full ${noBasis ? 'border-red-600' : ''}`} />
          : <span className="ml-1 text-slate-400">{p.basis_ref}</span>}
        {editable && missing && (
          <span className="mt-0.5 block text-[11px] text-red-300">
            {[noPrice && t('costpos.price'), noDays && t('costpos.daysShort'), noBasis && t('costpos.estBasisShort')]
              .filter(Boolean).join(', ')} {t('costpos.missingWord')}</span>
        )}
      </td>
      <td className={`${td} text-slate-500`}>-</td>
      <td className={`${td} text-right`}>
        {editable ? <input type="number" step="1" min={1} value={days} onChange={(e) => setDays(e.target.value)}
          aria-label={t('costpos.totalDays')} title={t('costpos.daysMin')} className={`${f} ${noDays ? 'border-red-600' : ''}`} />
          : (p.lead_time_days ?? '-')}
      </td>
      <td className={`${td} text-right`}>
        {editable ? <input type="number" step="0.01" min={0} value={cost} onChange={(e) => setCost(e.target.value)}
          aria-label={t('costpos.price')} data-testid={`est-cost-${p.id}`} className={`${f} ${noPrice ? 'border-red-600' : ''}`} />
          : money(p.est_cost, currency)}
        <PerPieceNote qty={qty} price={num(cost)} currency={currency} />
      </td>
      {/* an estimate has no transport field: it is in the price */}
      <td className={`${td} text-right text-slate-400`} data-testid={`est-transport-${p.id}`}>{t('costpos.transportInPrice')}</td>
      <td className={`${td} whitespace-nowrap`}>
        {editable && dirty && (
          <button type="button" className={btnSm.primary} data-testid={`est-save-${p.id}`}
            disabled={save.isPending || (days !== '' && noDays)} onClick={() => save.mutate()}>{t('common.save')}</button>
        )}
      </td>
    </tr>
  )
}

/** A received quote, editable in its line (Christoph 2026-11-08): quote no.,
 *  file, days, price, transport (empty = not entered yet, red; 0 = none), favourite. */
function ReceivedLine({ changeId, positionId, offer: o, td, editable, currency, onChanged, onStar, starring, fileOptional = false, qty = null, wait }: {
  changeId: number; positionId: number; offer: CostingOffer; td: string; editable: boolean
  currency: string | null; onChanged: () => void; onStar: () => void; starring: boolean
  fileOptional?: boolean
  /** a spare part's amount: the price is per piece */
  qty?: number | null
  /** the shop's request, when the quote was asked through one */
  wait?: SupplierWait
}) {
  const [ref, setRef] = useState(o.quote_ref ?? '')
  const [days, setDays] = useState(o.lead_time_days != null ? String(o.lead_time_days) : '')
  const [cost, setCost] = useState(String(o.cost ?? ''))
  // Christoph 2026-11-08: "transport none is not ok, mark red but 0 is allowed"
  const stored = shipOf(o)
  const [ship, setShip] = useState(stored != null ? String(stored) : '')
  const shipNum = num(ship)
  const noShip = shipNum == null || !(shipNum >= 0)
  const dirty = ref.trim() !== (o.quote_ref ?? '') || num(days) !== (o.lead_time_days ?? null)
    || Number(cost) !== Number(o.cost) || (shipNum ?? null) !== stored
  const save = useMutation({
    mutationFn: () => changesApi.updateCostingOffer(changeId, o.id, {
      quote_ref: ref.trim() || null, lead_time_days: num(days), lead_time_unit: 'calendar_days',
      cost: Number(cost) || 0,
      ...(noShip ? { shipping_included: true, shipping_cost: null }
        : { shipping_included: false, shipping_cost: shipNum }),
    }),
    onSuccess: () => { toast.success(t('costpos.saved')); onChanged() },
    onError: (e: unknown) => toastError(e, 'Could not save the quote'),
  })
  const files = o.attachments ?? []
  // Christoph 2026-11-08: only the row that misses something is red
  const refThin = (o.quote_ref ?? '').trim().length < 5
  const rowMissing = (!fileOptional && (files.length === 0 || (!!o.favorite && refThin))) || noShip
  const f = `${fieldCls} tabular-nums text-right`
  const [askDel, setAskDel] = useState(false)
  const delOffer = useMutation({
    mutationFn: () => changesApi.deleteCostingOffer(changeId, o.id),
    onSuccess: onChanged,
    onError: (e: unknown) => toastError(e, 'Could not delete the quote'),
  })
  return (
    <>
    <tr data-testid={`supplier-line-${positionId}-${o.vendor_name}`}
      data-missing={rowMissing ? 'yes' : 'no'}
      className={`border-t border-slate-700/60 ${rowMissing ? 'bg-red-950/40 outline outline-1 outline-red-700/70' : ''}`}>
      <td className={`${td} font-medium text-slate-100`}>{o.vendor_name}</td>
      <td className={td}>
        {(o.attachments ?? []).length > 0
          ? <span className="rounded bg-emerald-900/70 px-1.5 text-[11px] font-semibold text-emerald-100">{t('wait.sup.badge.received')}</span>
          : <span className="rounded bg-red-800 px-1.5 text-[11px] font-semibold text-red-100">{t('costpos.openNoFile')}</span>}
        {editable ? <input value={ref} onChange={(e) => setRef(e.target.value)} placeholder={t(fileOptional ? 'costpos.spareRef' : 'costpos.shopRef')}
          aria-label={t('costpos.shopRef')} title={t('costpos.refMin')}
          className={`${fieldCls} mt-0.5 block w-full ${ref.trim().length < 5 ? 'border-red-600' : ''}`} />
          : null}
        {/* say why the row is red, in the row */}
        {files.length === 0 && !fileOptional && <span className="mt-0.5 block text-[11px] text-red-300">{t('costpos.whyNoFile')}</span>}
        {files.length > 0 && o.favorite && refThin && (
          <span className="mt-0.5 block text-[11px] text-red-300">{t('costpos.whyRefShort')}</span>
        )}
        {wait && <RfqDates w={wait} />}
        {noShip && (
          <span className="mt-0.5 block text-[11px] text-red-300" data-testid={`transport-missing-${o.id}`}>
            {t('costpos.transportMissing')}</span>
        )}
        {editable ? null
          : (o.quote_ref ? <span className="ml-1 text-slate-400">#{o.quote_ref}</span> : null)}
      </td>
      <td className={td}>
        {files.map((f0) => (
          <QuoteFileCell key={f0.id} changeId={changeId} offerId={o.id} file={f0}
            editable={editable} onChanged={onChanged} />
        ))}
        {editable && files.length === 0 && (
          <AttachmentDropzone changeId={changeId} compact kind="vendor_quote"
            costingOfferId={o.id} label={t('costpos.shopFile')} onUploaded={onChanged} />
        )}
        {!editable && files.length === 0 && <span className="text-red-300">{t('costpos.noFile')}</span>}
      </td>
      <td className={`${td} text-right`}>
        {editable ? <input type="number" step="1" min={1} value={days} onChange={(e) => setDays(e.target.value)}
          aria-label={t('costpos.totalDays')} title={t('costpos.daysMin')}
          className={`${f} w-full ${!(Number(days) >= 1) ? 'border-red-600' : ''}`} /> : (o.lead_time_days ?? '-')}
      </td>
      <td className={`${td} text-right`}>
        {editable ? <input type="number" step="0.01" min={0} value={cost} onChange={(e) => setCost(e.target.value)}
          aria-label={t('costpos.price')} className={`${f} w-full`} /> : money(o.cost, currency)}
        <PerPieceNote qty={qty} price={num(cost)} currency={currency} />
      </td>
      <td className={`${td} text-right`}>
        {editable ? <input type="number" step="0.01" min={0} value={ship} onChange={(e) => setShip(e.target.value)}
          placeholder={t('costpos.transportPlaceholder')} aria-label={t('costpos.transport')}
          aria-invalid={noShip} className={`${f} w-full ${noShip ? 'border-red-600' : ''}`} />
          : stored == null ? <span className="text-red-300">{t('costpos.missingWord')}</span> : money(stored, currency)}
      </td>
      <td className={`${td} whitespace-nowrap`}>
        {editable && dirty && (
          <button type="button" className={btnSm.primary} disabled={save.isPending || !(Number(days) >= 1)}
            onClick={() => save.mutate()}>{t('common.save')}</button>
        )}
        {o.favorite ? (
          <span data-testid={`supplier-star-${o.id}`} title={t('costpos.favoriteLineHint')}
            className="ml-1 rounded bg-slate-200 px-1.5 text-[11px] font-semibold text-slate-900">★ {t('costpos.favorite')}</span>
        ) : editable ? (
          <button type="button" data-testid={`supplier-star-${o.id}`} disabled={starring}
            title={t('costpos.favoriteLineHint')} onClick={onStar}
            className="ml-1 rounded border border-slate-500 px-1.5 text-[11px] text-slate-200 hover:bg-slate-700">
            ☆ {t('costpos.makeFavorite')}</button>
        ) : null}
        {editable && !askDel && (
          <button type="button" aria-label={`Delete the quote from ${o.vendor_name}`} title={t('costpos.deleteQuote')}
            className="ml-1 px-1 text-sm leading-none text-red-300 hover:text-red-200" onClick={() => setAskDel(true)}>×</button>
        )}
        {o.chosen && (
          <span className="ml-1 rounded bg-violet-800 px-1.5 text-[11px] font-semibold text-violet-100"
            title={o.chosen_reason ?? undefined}>{t('vendor.salesChose')}</span>
        )}
      </td>
    </tr>
    {askDel && (
      <tr className="bg-red-950/50">
        <td colSpan={7} className={`${td} text-red-100`}>
          <span className="inline-flex flex-wrap items-center gap-2">
            {t('costpos.deleteQuoteAsk').replace('{x}', o.vendor_name)}
            <button type="button" data-testid={`supplier-del-yes-${o.id}`}
              className="rounded bg-red-700 px-2 py-0.5 text-[11px] font-semibold text-white hover:bg-red-600"
              onClick={() => { setAskDel(false); delOffer.mutate() }}>{t('costpos.yesDelete')}</button>
            <button type="button" className="rounded border border-slate-500 px-2 py-0.5 text-[11px] text-slate-100"
              onClick={() => setAskDel(false)}>{t('costpos.keepIt')}</button>
          </span>
        </td>
      </tr>
    )}
    </>
  )
}

/** The line of a shop whose quote just came in: file, days, price, quote no. */
function ShopQuoteLine({ changeId, positionId, shop, td, onDone, onCancel, fileOptional = false, qty = null, currency = null }: {
  changeId: number; positionId: number; shop: string; td: string
  onDone: () => void; onCancel: () => void
  /** a spare part may be a catalogue buy: no quote file needed */
  fileOptional?: boolean
  /** a spare part's amount: the price is per piece */
  qty?: number | null
  currency?: string | null
}) {
  const [cost, setCost] = useState('')
  const [days, setDays] = useState('')
  const [ref, setRef] = useState('')
  const [file, setFile] = useState<File | null>(null)
  const [ship, setShip] = useState('')
  const save = useMutation({
    mutationFn: async () => {
      const offer = await changesApi.addCostingOffer(changeId, positionId, {
        vendor_name: shop, cost: Number(cost) || 0,
        // transport is always entered, 0 = none (Christoph 2026-11-08)
        shipping_included: false, shipping_cost: num(ship) ?? 0,
        lead_time_days: num(days), lead_time_unit: 'calendar_days',
        ...(ref.trim() ? { quote_ref: ref.trim() } : {}),
      })
      if (file) await changesApi.uploadAttachment(changeId, file, { kind: 'vendor_quote', costingOfferId: offer.id })
      return offer
    },
    onSuccess: () => { toast.success(t('costpos.shopQuoteSaved').replace('{x}', shop)); onDone() },
    onError: (e: unknown) => toastError(e, 'Could not save the quote'),
  })
  const noShip = num(ship) == null || !(Number(ship) >= 0)
  return (
    <tr data-testid={`shop-quote-${positionId}-${shop}`} className="border-t border-slate-700/60 bg-slate-900/50">
      <td className={`${td} font-medium text-slate-100`}>{shop}</td>
      <td className={td}>
        <input value={ref} onChange={(e) => setRef(e.target.value)} placeholder={t(fileOptional ? 'costpos.spareRef' : 'costpos.shopRef')}
          aria-label={t('costpos.shopRef')} className={`${fieldCls} w-full`} />
        {noShip && (
          <span className="mt-0.5 block text-[11px] text-red-300" data-testid={`shop-transport-missing-${positionId}-${shop}`}>
            {t('costpos.transportMissing')}</span>
        )}
      </td>
      <td className={td}>
        <label className={`cursor-pointer rounded border px-1.5 py-0.5 text-[11px] hover:bg-slate-700/60 ${file || fileOptional
          ? 'border-slate-600 text-slate-200' : 'border-red-600 text-red-200'}`}>
          {file ? file.name : fileOptional ? t('costpos.shopFile') : `${t('costpos.shopFile')} *`}
          <input type="file" className="sr-only" accept=".pdf,.xlsx,.xls,.doc,.docx,.msg,.eml"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
        </label>
      </td>
      <td className={`${td} text-right`}>
        <input type="number" step="1" min={1} value={days} onChange={(e) => setDays(e.target.value)}
          aria-label={t('costpos.totalDays')} title={t('costpos.daysMin')}
          className={`${fieldCls} w-full tabular-nums text-right ${days !== '' && !(Number(days) >= 1) ? 'border-red-600' : ''}`} />
      </td>
      <td className={`${td} text-right`}>
        <input type="number" step="0.01" min={0} value={cost} onChange={(e) => setCost(e.target.value)}
          aria-label={t('costpos.price')} className={`${fieldCls} w-full tabular-nums text-right`} />
        <PerPieceNote qty={qty} price={num(cost)} currency={currency} />
      </td>
      <td className={`${td} text-right`}>
        <input type="number" step="0.01" min={0} value={ship} onChange={(e) => setShip(e.target.value)}
          placeholder={t('costpos.transportPlaceholder')} aria-label={t('costpos.transport')} aria-invalid={noShip}
          className={`${fieldCls} w-full tabular-nums text-right ${noShip ? 'border-red-600' : ''}`} />
      </td>
      <td className={`${td} whitespace-nowrap`}>
        <button type="button" className={btnSm.primary} data-testid={`shop-quote-save-${positionId}-${shop}`}
          disabled={!(Number(cost) > 0) || !(Number(days) >= 1) || (!file && !fileOptional) || noShip || save.isPending}
          title={noShip ? t('costpos.transportMissing') : !file ? t('costpos.fileFirst') : undefined}
          onClick={() => save.mutate()}>{t('common.save')}</button>
        <button type="button" className="ml-1 text-[11px] underline text-slate-400" onClick={onCancel}
          title={t('costpos.undoReceivedHint')}>{t('costpos.undoReceived')}</button>
      </td>
    </tr>
  )
}

/** Christoph 2026-11-08: a line carried from an assessment case shows that
 *  case's documents (inquiry PPT, RFQ, internal change PPT) as downloads. */
function CaseDocs({ changeId, position: p }: { changeId: number; position: CostPosition }) {
  const { data: change } = useQuery({
    queryKey: ['change', changeId],
    queryFn: () => changesApi.get(changeId),
  })
  if (!change || !(p.notes ?? '').startsWith('From the assessment')) return null
  // every assessment row of the department (a department can have two)
  const impacts = (change.assessments ?? []).filter((x) => x.department_id === p.department_id)
    .flatMap((a) => {
      let details: Record<string, unknown> = {}
      try { details = typeof a.details === 'string' ? JSON.parse(a.details) : (a.details ?? {}) } catch { details = {} }
      return (details.impacts as { key?: string; cases?: (string | { id: string; text: string })[] }[] | undefined) ?? []
    })
  // a spare part line is labelled "Spare part: <name>"; its case text may also sit in the notes
  const wants = new Set([p.label, spareName(p.label), (p.notes ?? '').replace(/^From the assessment:\s*/, '')]
    .map((x) => x.trim().toLowerCase()).filter(Boolean))
  let caseId: string | null = null
  let kind = ''
  for (const i of impacts) {
    for (const c of i.cases ?? []) {
      if (typeof c !== 'string' && wants.has(c.text.trim().toLowerCase())) {
        caseId = c.id; kind = i.key === 'modification_internal' ? 'internal' : 'external'
      }
    }
  }
  if (!caseId) return null
  const docs = (change.attachments ?? []).filter((x) => x.case_ref === caseId)
  if (!docs.length) return <span className="block text-[11px] text-red-300">{t('costpos.caseNoDocs')}</span>
  return (
    <span className="block" data-testid={`case-docs-${p.id}`}>
      <span className="mb-0.5 block text-[11px] text-slate-500">
        {t(kind === 'internal' ? 'costpos.caseDocsInternal' : 'costpos.caseDocsExternal')}</span>
      {docs.map((d) => (
        <span key={d.id} className="block">
          {/* neutral: the type colours (teal, sky, violet) name line types only */}
          <span className="mr-1 rounded border border-slate-500 px-1 text-[10px] font-semibold text-slate-200">
            {d.kind === 'rfq' ? t('costpos.docRfq') : t('costpos.docPpt')}</span>
          <DownloadIcons changeId={changeId} attachments={[d]} />
        </span>
      ))}
    </span>
  )
}

/** Old spare part lines carry their item as "Spare part: <name / part no.>";
 *  newer ones (seeded from the assessment, or added below a spare box) carry
 *  the plain name and say what they are in the notes. */
const SPARE_PREFIX = 'Spare part: '

/** The item's name, without the old "Spare part: " prefix. */
export const spareName = (label: string) => label.startsWith(SPARE_PREFIX) ? label.slice(SPARE_PREFIX.length) : label

/** The notes say it is a spare part ("From the assessment: Spare part required"). */
const spareByNotes = (p: CostPosition) => /spare part|ersatzteil/i.test(p.notes ?? '')

/** Christoph 2026-11-08: a spare part line, by its notes, or by the old label prefix. */
export const isSpareLine = (p: CostPosition): boolean =>
  p.kind === 'external' && (spareByNotes(p) || p.label.startsWith(SPARE_PREFIX))

/** Christoph 2026-11-08: the four kinds of line a department costs, each with
 *  its own colour everywhere (section header dot, box chip, box border).
 *  Amber/orange/red never name a type: they only mean "needs attention". */
export type LineGroup = 'time' | 'internal' | 'external' | 'spare'

export const lineGroupOf = (p: CostPosition): LineGroup =>
  p.kind !== 'external' ? 'time'
    : isSpareLine(p) ? 'spare'
      : /internal modification|interne änderung/i.test(p.notes ?? '') ? 'internal' : 'external'

const GROUP_STYLE: Record<LineGroup, { dot: string; chip: string; border: string; labelKey: string }> = {
  time: { dot: 'bg-slate-400', chip: 'bg-slate-700 text-slate-100', border: 'border-slate-600', labelKey: 'costpos.grp.time' },
  internal: { dot: 'bg-teal-400', chip: 'bg-teal-800 text-teal-50', border: 'border-teal-600/80', labelKey: 'costpos.grp.internal' },
  external: { dot: 'bg-sky-400', chip: 'bg-sky-800 text-sky-50', border: 'border-sky-600/80', labelKey: 'costpos.grp.external' },
  spare: { dot: 'bg-violet-400', chip: 'bg-violet-800 text-violet-50', border: 'border-violet-600/80', labelKey: 'costpos.grp.spare' },
}

const TypeDot = ({ group }: { group: LineGroup }) => (
  <span aria-hidden="true" className={`inline-block h-2 w-2 shrink-0 rounded-full ${GROUP_STYLE[group].dot}`} />
)

/** Spare parts are priced per piece: the line counts amount x price (transport once). */
const perPieceOf = (p: CostPosition): number =>
  p.kind === 'external' && p.quantity_unit === 'pcs' && (p.quantity ?? 0) > 0 ? Number(p.quantity) : 1

/** Transport as entered: null = not entered yet (red), 0 = none. */
const shipOf = (o: CostingOffer): number | null =>
  !o.shipping_included && o.shipping_cost != null ? Number(o.shipping_cost) : null

/** An offer's total on its line: amount x price + transport once. */
const offerLineTotal = (p: CostPosition, o: CostingOffer): number =>
  Number(o.cost) * perPieceOf(p) + (shipOf(o) ?? 0)

/** From-to over a set of supplier lines (cheapest to dearest quote), and the favourites' sum. */
function supplierRange(lines: CostPosition[]) {
  let low = 0, high = 0, fav = 0
  let complete = true
  for (const p of lines) {
    if (p.pricing === 'quote') {
      const vals = (p.offers ?? []).filter((o) => !o.is_partial).map((o) => offerLineTotal(p, o))
      if (!vals.length) { complete = false; continue }
      low += Math.min(...vals); high += Math.max(...vals)
      const f = (p.offers ?? []).find((o) => o.favorite)
      if (f) fav += offerLineTotal(p, f); else complete = false
    } else if (p.est_cost) {
      const v = Number(p.est_cost) * perPieceOf(p)
      low += v; high += v; fav += v
    } else complete = false
  }
  return { low, high, fav, complete }
}

/** "10 × 1,000.00 = 10,000.00" under a spare part's per-piece price. */
function PerPieceNote({ qty, price, currency }: { qty: number | null | undefined; price: number | null; currency: string | null }) {
  if (!qty || !(price != null && price > 0)) return null
  return (
    <span className="mt-0.5 block text-right text-[11px] leading-tight tabular-nums text-slate-400" data-testid="per-piece-note">
      <span className="block">{formatNumber(qty)} × {formatNumber(price, { min: 2, max: 2 })}</span>
      <span className="block text-slate-300">= {money(qty * price, currency)}</span>
    </span>
  )
}

/** Christoph 2026-11-08: a spare part line names its item (name or part no.)
 *  and its amount (pcs); the supplier table below prices it like any external line. */
function SpareAmount({ changeId, position: p, editable, onChanged }: {
  changeId: number; position: CostPosition; editable: boolean; onChanged: () => void
}) {
  const [name, setName] = useState(spareName(p.label))
  const [qty, setQty] = useState(p.quantity != null ? String(p.quantity) : '')
  const save = useMutation({
    // the plain name; an old row keeps its prefix only while its notes do not
    // say "spare part" (that prefix is what still marks it as one)
    mutationFn: () => changesApi.updateCostPosition(changeId, p.id, {
      label: spareByNotes(p) ? name.trim() : `${SPARE_PREFIX}${name.trim()}`, quantity: num(qty), quantity_unit: 'pcs' }),
    onSuccess: () => { toast.success(t('costpos.saved')); onChanged() },
    onError: (e: unknown) => toastError(e, 'Could not save the spare part'),
  })
  const badQty = !(Number(qty) > 0)
  const badName = name.trim().length < 2
  const dirty = name.trim() !== spareName(p.label) || num(qty) !== (p.quantity ?? null)
  return (
    <div className="mb-1 flex flex-wrap items-center gap-2 text-xs" data-testid={`spare-amount-${p.id}`}>
      <span className="font-medium text-slate-200">{t('costpos.spareItem')}</span>
      {editable ? (
        <>
          <input value={name} onChange={(e) => setName(e.target.value)} placeholder={t('costpos.itemName')}
            data-testid={`spare-name-${p.id}`}
            className={`${fieldCls} w-64 ${badName ? 'border-red-600' : ''}`} />
          <span className="font-medium text-slate-200">{t('costpos.amount')}</span>
          <input type="number" step="1" min={1} value={qty} onChange={(e) => setQty(e.target.value)}
            data-testid={`spare-qty-${p.id}`}
            className={`${fieldCls} w-20 tabular-nums text-right ${badQty ? 'border-red-600' : ''}`} />
          <span className="text-slate-400">{t('costpos.pcs')}</span>
          {dirty && (
            <button type="button" className={btnSm.primary} data-testid={`spare-save-${p.id}`}
              disabled={badQty || badName || save.isPending} onClick={() => save.mutate()}>
              {t('common.save')}</button>
          )}
          {(badName || badQty) && <span className="text-[11px] text-red-300">
            {[badName && t('costpos.itemName'), badQty && t('costpos.amount')].filter(Boolean).join(', ')} {t('costpos.missingWord')}</span>}
        </>
      ) : <span className="tabular-nums">{spareName(p.label) || '-'} · {p.quantity ?? '-'} {t('costpos.pcs')}</span>}
      <TimeCritical changeId={changeId} position={p} editable={editable} />
    </div>
  )
}

/** Christoph 2026-11-09: "It needs to be identified if spare parts are time
 *  critical or not, that changes the sales timing." Yes: the spare part counts
 *  for the lead time (it may be the time leader); No: it is left out. Red until
 *  answered (Finalize asks for it), neutral once answered. Saves on click. */
function TimeCritical({ changeId, position: p, editable }: {
  changeId: number; position: CostPosition; editable: boolean
}) {
  const qc = useQueryClient()
  const value = p.time_critical ?? null
  const open = value == null
  const save = useMutation({
    mutationFn: (v: boolean) => changesApi.updateCostPosition(changeId, p.id, { time_critical: v }),
    onSuccess: () => { toast.success(t('costpos.tc.saved')); invalidateCosting(qc, changeId) },
    onError: (e: unknown) => toastError(e, 'Could not save time critical'),
  })
  const edge = open ? 'border-red-600' : 'border-slate-500'
  return (
    <span className="inline-flex items-center gap-1.5" data-testid={`spare-tc-${p.id}`}
      data-answered={open ? 'no' : 'yes'}>
      <span className={`font-medium ${open ? 'text-red-300' : 'text-slate-200'}`} title={t('costpos.tc.question')}>
        {t('costpos.tc.label')}</span>
      {editable ? (
        <span role="group" aria-label={`${t('costpos.tc.label')}: ${t('costpos.tc.question')}`}
          className={`inline-flex overflow-hidden rounded border ${edge}`}>
          {([true, false] as const).map((b) => (
            <button key={String(b)} type="button" aria-pressed={value === b}
              data-testid={`spare-tc-${b ? 'yes' : 'no'}-${p.id}`}
              disabled={save.isPending}
              onClick={() => { if (value !== b) save.mutate(b) }}
              className={`px-2 py-0.5 text-[11px] font-medium ${b ? `border-r ${edge}` : ''} ${value === b
                ? 'bg-slate-600 text-white' : 'bg-slate-900 text-slate-300 hover:bg-slate-800'}`}>
              {t(b ? 'costpos.tc.yes' : 'costpos.tc.no')}</button>
          ))}
        </span>
      ) : (
        <span className={open ? 'text-red-300' : 'text-slate-200'}>
          {open ? t('costpos.tc.open') : t(value ? 'costpos.tc.yes' : 'costpos.tc.no')}</span>
      )}
      {open && editable && <span className="text-[11px] text-red-300">{t('costpos.tc.question')}</span>}
    </span>
  )
}

/** Costing effort: the hours booked after the assessment submit, read-only;
 *  corrected through Book hours (red until something is booked). */
function BookedRow({ changeId, position: p, editable }: {
  changeId: number; position: CostPosition; editable: boolean
}) {
  const { data: fc } = useQuery({
    queryKey: ['change', changeId, 'finalize-check', p.department_id],
    queryFn: () => changesApi.finalizeCheck(changeId, p.department_id),
    enabled: editable,
  })
  const missing = !!fc?.items?.some((i) => i.tag === 'book_hours')
  return (
    <div className="flex items-center gap-2 text-xs text-slate-300">
      <span>{t('costpos.bookedHint')}</span>
      {editable && (
        <button type="button" onClick={() => requestBookHours({ departmentId: p.department_id })}
          className={missing
            ? 'inline-flex h-7 items-center rounded-lg border border-red-600 bg-red-900/50 px-2.5 text-xs font-medium text-red-100'
            : btnSm.secondary}>{t('hours.title')}</button>
      )}
      {editable && p.hours != null && (
        <button type="button" onClick={() => requestHoursCorrection({ departmentId: p.department_id })}
          title={t('hours.correctBooked')} className={btnSm.ghost}>{t('hours.correct')}</button>
      )}
    </div>
  )
}

/** Christoph 2026-11-08: an internal case line fills like the external
 *  estimate. 2026-11-09: hours only (no days), same look as the estimate:
 *  ESTIMATE tag, red fields + "... missing" until hours and basis are there;
 *  once filled it reads as text with Edit, editing has Save and Cancel. */
function InternalQuickRow({ changeId, position: p, onChanged }: {
  changeId: number; position: CostPosition; onChanged: () => void
}) {
  const [hours, setHours] = useState(p.hours != null ? String(p.hours) : '')
  const [basis, setBasis] = useState(p.notes ?? '')
  const storedMissing = !((p.hours ?? 0) > 0) || (p.notes ?? '').trim().length < 5
  const [editing, setEditing] = useState(false)
  const dirty = num(hours) !== (p.hours ?? null) || basis.trim() !== (p.notes ?? '')
  const save = useMutation({
    mutationFn: () => changesApi.updateCostPosition(changeId, p.id, {
      hours: num(hours), notes: basis.trim() || null,
    }),
    onSuccess: () => { toast.success(t('costpos.saved')); setEditing(false); onChanged() },
    onError: (e: unknown) => toastError(e, 'Could not save the internal work'),
  })
  const cancel = () => {
    setHours(p.hours != null ? String(p.hours) : ''); setBasis(p.notes ?? ''); setEditing(false)
  }
  const noHours = !(Number(hours) > 0)
  const noBasis = basis.trim().length < 5
  const missing = noHours || noBasis
  const open = editing || storedMissing
  return (
    <div data-testid={`int-row-${p.id}`} data-missing={missing ? 'yes' : 'no'}
      className={`flex flex-wrap items-start gap-2 rounded px-2 py-1.5 ${open && missing
        ? 'bg-red-950/40 outline outline-1 outline-red-700/70' : 'border border-slate-700'}`}>
      <span className="w-36 pt-1 text-xs font-medium text-slate-200">{t('costpos.internalWork')}</span>
      <div className="flex-1 min-w-[12rem]">
        <span className="rounded border border-slate-500 px-1.5 text-[11px] font-semibold text-slate-200">{t('costpos.bannerEstimate')}</span>
        {open ? (
          <input value={basis} onChange={(e) => setBasis(e.target.value)}
            data-testid={`int-basis-${p.id}`} aria-label={t('costpos.estBasis')} title={t('costpos.estBasis')}
            placeholder={t('costpos.estBasisShort')}
            className={`${fieldCls} mt-0.5 block w-full ${noBasis ? 'border-red-600' : ''}`} />
        ) : (
          <span data-testid={`int-basis-text-${p.id}`} className="ml-2 text-sm text-slate-300">{p.notes}</span>
        )}
        {open && missing && (
          <span className="mt-0.5 block text-[11px] text-red-300">
            {[noHours && t('costpos.hours'), noBasis && t('costpos.estBasisShort')]
              .filter(Boolean).join(', ')} {t('costpos.missingWord')}</span>
        )}
      </div>
      {open ? (
        <label className="flex items-center gap-1 pt-5 text-xs text-slate-400">
          <input type="number" step="0.5" min={0} value={hours} onChange={(e) => setHours(e.target.value)}
            data-testid={`int-hours-${p.id}`} aria-label={t('costpos.hours')}
            className={`${fieldCls} w-24 tabular-nums text-right ${noHours ? 'border-red-600' : ''}`} />
          h
        </label>
      ) : (
        <span data-testid={`int-hours-text-${p.id}`} className="w-28 text-right text-sm tabular-nums text-slate-200">
          {formatHours(p.hours ?? 0)}</span>
      )}
      <div className={`flex items-center gap-1 ${open ? 'pt-5' : ''}`}>
        {open ? (
          <>
            <button type="button" className={btnSm.primary} data-testid={`int-save-${p.id}`}
              disabled={!dirty || missing || save.isPending} onClick={() => save.mutate()}>{t('common.save')}</button>
            {editing && (
              <button type="button" className={btnSm.ghost} data-testid={`int-cancel-${p.id}`}
                onClick={cancel}>{t('costpos.cancelEdit')}</button>
            )}
          </>
        ) : (
          <button type="button" className={btnSm.ghost} data-testid={`int-edit-${p.id}`}
            aria-label={`${t('costpos.edit')}: ${p.label}`}
            onClick={() => setEditing(true)}>{t('costpos.edit')}</button>
        )}
      </div>
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
          {(m.has_own_rate ?? m.hourly_rate != null) ? ` · ${t('costpos.ownRate')}` : ''}
          {m.active ? '' : ` (${t('costpos.machineInactive')})`}
        </option>
      ))}
    </select>
  )
}

/** A position row: reads as one line; edits in place; a quoted line opens its vendors. */
function PositionRow({ changeId, position, editable, index, categories, onChanged, ctx,
  v2 = false, basisParts = [] }: {
  changeId: number; position: CostPosition; editable: boolean; index: number
  categories: CostCategory[]; onChanged: () => void; ctx?: CostingContext
  /** ASSESSMENT_V2: the basis sub-row (spec §4, C25). */
  v2?: boolean
  basisParts?: { id: number; number: string }[]
}) {
  const p = position
  // Christoph 2026-11-08: a line missing its price / hours is marked red
  const { data: fcheck } = useQuery({
    queryKey: ['change', changeId, 'finalize-check', p.department_id],
    queryFn: () => changesApi.finalizeCheck(changeId, p.department_id),
    enabled: editable,
  })
  const missing = !!fcheck?.position_ids?.includes(p.id)
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

  const setPricing = useMutation({
    mutationFn: (v: 'estimate' | 'quote') => changesApi.updateCostPosition(changeId, p.id, { pricing: v }),
    onSuccess: onChanged,
    onError: (e: unknown) => toastError(e, 'Could not switch the pricing'),
  })
  const save = useMutation({
    mutationFn: async () => {
      if (type === 'estimate') await ensureVendor(qc, vendor)
      return changesApi.updateCostPosition(changeId, p.id, {
        label: label.trim(),
        hours: type === 'sampling' ? null : num(hours),
        est_cost: type === 'estimate' ? num(est) : null,
        vendor_name: type === 'estimate' ? (vendor.trim() || null) : null,
        lead_time_days: type === 'time' ? null : num(lead), lead_time_unit: unit,
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
      <tr data-testid={`costpos-row-${p.id}`} data-missing={missing ? 'yes' : 'no'}
        title={missing ? t('costpos.lineMissing') : undefined}
        className={`border-t border-slate-700/70 ${editing ? 'bg-slate-800/60' : missing ? 'bg-red-950/40 outline outline-1 outline-red-700/70' : ''}`}>
        <td className={`${cellCls} text-slate-500 tabular-nums w-8`}>{index}</td>
        <td className={cellCls}>
          {p.tag ? (
            <span data-testid={`costpos-tag-${p.id}`} className="text-slate-200">
              {tagLabel(p.tag, categories)}
            </span>
          ) : (p.notes ?? '').startsWith('From the assessment') ? null : <span className="text-slate-600">-</span>}
          <CaseDocs changeId={changeId} position={p} />
        </td>
        <td className={`${cellCls} min-w-[12rem]`}>
          {editing && !(p.notes ?? '').startsWith('From the assessment') ? (
            <input data-testid={`costpos-edit-label-${p.id}`} value={label}
              aria-label={t('costpos.label')} autoFocus
              onChange={(e) => setLabel(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Escape') setEditing(false) }}
              className={`${fieldCls} w-full`} />
          ) : (
            <>
              <span data-testid={`costpos-label-${p.id}`} className="text-slate-100">{isSpareLine(p) ? spareName(p.label) : p.label}</span>
              {p.quantity != null && p.quantity_unit && (
                <span data-testid={`costpos-qty-${p.id}`} className="ml-1.5 text-xs text-slate-400 tabular-nums">
                  {p.quantity} {p.quantity_unit}
                </span>
              )}
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
          {/* Christoph 2026-11-08: a supplier line switches to quotes, one
              per supplier (toolmaker, gauge maker, assembly supplier) */}
          {p.kind === 'external' && editable && (
            <span className="mb-0.5 flex rounded border border-slate-600 overflow-hidden w-fit"
              role="group" aria-label={t('costpos.pricingSwitch')}>
              {(['estimate', 'quote'] as const).map((v) => (
                <button key={v} type="button" data-testid={`costpos-pricing-${v}-${p.id}`}
                  aria-pressed={p.pricing === v}
                  disabled={setPricing.isPending || p.pricing === v}
                  onClick={() => setPricing.mutate(v)}
                  className={`px-1.5 py-0.5 text-[11px] ${p.pricing === v
                    ? 'bg-slate-600 text-white' : 'bg-slate-900 text-slate-400 hover:text-slate-200'}`}>
                  {t(v === 'estimate' ? 'costpos.type.estimate' : 'costpos.supplierQuotes')}
                </button>
              ))}
            </span>
          )}
          <span data-testid={`costpos-kind-${p.id}`} className="text-xs text-slate-400">
            {t(`costpos.type.${type}`)}
            {isMachine && p.machine_class && (
              <span data-testid={`costpos-class-${p.id}`} className="block text-[11px] text-slate-500"
                title={machineClassOriginDetail(p.machine_class_origin) ?? undefined}>
                {p.machine_class}
                {p.machine_class_origin?.kind === 'tool'
                  ? `, ${machineClassOriginText(p.machine_class_origin)}`
                  : p.machine_class_from_change ? ` (${t('costpos.classFromChange')})` : ''}
              </span>
            )}
            {isMachine && !p.machine_class && machineClassOriginText(p.machine_class_origin) && (
              <span data-testid={`costpos-class-${p.id}`} className="block text-[11px] text-amber-300"
                title={machineClassOriginDetail(p.machine_class_origin) ?? undefined}>
                {machineClassOriginText(p.machine_class_origin)}
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
          {/* own time is hours only, no days (Christoph 2026-11-09) */}
          {editing && !isQuote && type !== 'time' ? (
            <span className="inline-flex items-center gap-1">
              <input data-testid={`costpos-edit-lead-${p.id}`} type="number" min={0} value={lead}
                aria-label={t('costpos.leadTime')} placeholder={t('costpos.leadTime')}
                onChange={(e) => setLead(e.target.value)} className={`${fieldCls} w-16 tabular-nums`} />
              <UnitSelect testId={`costpos-edit-unit-${p.id}`} value={unit} onChange={setUnit} />
            </span>
          ) : time ? (
            <span data-testid={`costpos-lead-${p.id}`} className="text-xs text-slate-400">
              {leadTimeText(time.days, time.unit)}
              {!countsForLeadTime(p) && (
                <span className="block text-[11px] text-slate-500" data-testid={`costpos-lead-excluded-${p.id}`}>
                  {t('costpos.tc.notCounted')}</span>
              )}
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
              {/* Christoph 2026-11-08: a carried case line is filled in its rows
                  below (estimate / quotes); Edit only for other lines, and it
                  says what it edits */}
              {((p.notes ?? '').startsWith('From the assessment') || p.notes === 'From the bookings') ? (
                <span className="text-[11px] text-slate-500"
                  title={p.notes === 'From the bookings' ? t('costpos.bookedHint') : t('costpos.carriedHint')}>
                  {p.notes === 'From the bookings' ? t('costpos.fromBookings') : t('costpos.carried')}</span>
              ) : (
                <button type="button" data-testid={`costpos-edit-${p.id}`}
                  onClick={() => setEditing(true)} aria-label={`${t('costpos.edit')}: ${p.label}`}
                  title={t('costpos.editHint')}
                  className={btnSm.ghost}>{t('costpos.edit')}</button>
              )}
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
            {!(p.notes ?? '').startsWith('From the assessment') && <input data-testid={`costpos-edit-notes-${p.id}`} value={notes}
              aria-label={t('costpos.notes')} placeholder={t('costpos.notes')}
              onChange={(e) => setNotes(e.target.value)} className={`${fieldCls} flex-1 min-w-[10rem]`} />}
          </td>
        </tr>
      )}
      {/* Christoph 2026-11-08: an estimated supplier line fills like a quote:
          total cost, days, what it is based on */}
      {p.kind === 'own_time' && p.notes === 'From the bookings' && (
        <tr data-testid={`costpos-costing-effort-${p.id}`} className="bg-slate-900/40">
          <td />
          <td colSpan={6} className={`${cellCls} pt-0 pb-2`}>
            <BookedRow changeId={changeId} position={p} editable={editable} />
          </td>
        </tr>
      )}
      {/* only a line carried from the assessment gets its fill row; a line
          added here has its hours already (Christoph 2026-11-09) */}
      {p.kind === 'own_time' && (p.notes ?? '').startsWith('From the assessment') && editable && !editing && (
        <tr data-testid={`costpos-internal-${p.id}`} className="bg-slate-900/40">
          <td />
          <td colSpan={6} className={`${cellCls} pt-0 pb-2`}>
            <InternalQuickRow changeId={changeId} position={p} onChanged={onChanged} />
          </td>
        </tr>
      )}
      {p.kind === 'external' && !isQuote && (
        <tr data-testid={`costpos-estimate-${p.id}`} className="bg-slate-900/40">
          <td />
          <td colSpan={6} className={`${cellCls} pt-0 pb-2`}>
            <SupplierLines changeId={changeId} position={p} editable={editable}
              currency={cur} onChanged={onChanged} estimate />
          </td>
        </tr>
      )}
      {/* Quoted work carries its vendors with it — one row per offer, one star
          among them. */}
      {isQuote && (
        <tr data-testid={`costpos-offers-${p.id}`} className="bg-slate-900/40">
          <td />
          <td colSpan={6} className={`${cellCls} pt-0 pb-2`}>
            <SupplierLines changeId={changeId} position={p} editable={editable}
              currency={cur} onChanged={onChanged} />
          </td>
        </tr>
      )}
      {v2 && isExternal && editing && !isQuote && (
        <tr className="bg-slate-900/30">
          <td />
          <td colSpan={6} className={`${cellCls} pt-0 pb-2`}>
            <PositionBasis changeId={changeId} position={p} editable={editable}
              onChanged={onChanged} impactedParts={basisParts} />
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

/** Christoph 2026-11-09, the Project Manager's standing rows: "Scoping
 *  effort: time spent" (booked during capture and scoping, instead of the
 *  assessment effort), the costing effort (booked), and "PM time still to
 *  come, estimated" on the support_effort row (required, 0 allowed). */
export const effortFieldsFor = (departmentName?: string) => departmentName !== 'Project Manager'
  ? EFFORT_FIELDS
  : EFFORT_FIELDS.map((f) => f.kind === 'support_effort' ? {
    ...f, labelKey: 'costpos.pmEffortField', rowKey: 'costpos.pmEffortRow', descKey: 'costpos.pmEffortDesc',
  } : f.kind === 'internal_effort' ? {
    // the PM did the scoping, not an assessment: its booked scoping time
    ...f, labelKey: 'costpos.pmScopingField', rowKey: 'costpos.pmScopingRow', descKey: 'costpos.pmScopingDesc',
  } : f)

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
  // Christoph 2026-11-08: red until the department booked its costing hours
  const { data: fc } = useQuery({
    queryKey: ['change', changeId, 'finalize-check', departmentId],
    queryFn: () => changesApi.finalizeCheck(changeId, departmentId),
    enabled: editable && kind === 'internal_effort',
    refetchInterval: COSTING_REFETCH_MS,
  })
  // Christoph 2026-11-09: required like the Costing effort once the
  // assessment is submitted (red + REQUIRED when nothing is booked)
  const bookMissing = kind === 'internal_effort'
    && !!fc?.items?.some((i) => i.tag === 'assessment_hours')
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
  // Christoph 2026-11-08: implementation support is red until its hours are entered (0 allowed)
  const supportMissing = kind === 'support_effort' && position?.hours == null && hours.trim() === ''
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
    <tr className={`border-t border-slate-700/70 ${supportMissing ? 'bg-red-950/40 outline outline-1 outline-red-700/70'
      : bookMissing ? 'bg-red-950/30' : ''}`}
      data-missing={supportMissing || bookMissing ? 'yes' : 'no'}>
      <td className={`${cellCls} text-slate-500 tabular-nums w-8`}>{index}</td>
      <td className={cellCls}>
        <span className="text-slate-200">{t(rowKey)}</span>
        <span className="ml-1.5 rounded bg-slate-700/70 text-slate-400 px-1 py-0 text-[11px]">
          {t('costpos.standing')}
        </span>
        {bookMissing && <span className="ml-1.5 rounded bg-red-800 px-1 text-[11px] font-semibold text-red-100">{t('costpos.required')}</span>}
      </td>
      <td className={`${cellCls} text-slate-400 text-xs`}>
        {t(descKey)}
        {position && <RateNote p={position} />}
      </td>
      <td className={`${cellCls} text-xs text-slate-400 whitespace-nowrap`}>{t('costpos.type.time')}</td>
      <td className={`${cellCls} ${numCls} whitespace-nowrap`}>
        {kind === 'internal_effort' ? (
          // Christoph 2026-11-08: the booked hours, never typed here; add or
          // correct them in Book hours (one place for hours)
          <span className="inline-flex items-center gap-1.5">
            <span data-testid={`costpos-effort-value-${kind}-${departmentId}`}
              className="tabular-nums text-slate-200">
              {position?.hours != null ? `${position.hours} h` : t('costpos.noneBooked')}
            </span>
            {editable && (
              <button type="button" data-testid={`costpos-effort-book-${departmentId}`}
                data-missing={bookMissing ? 'yes' : 'no'}
                title={bookMissing ? t('costpos.bookAssessmentHours') : undefined}
                onClick={() => requestBookHours(rowKey === 'costpos.pmScopingRow'
                  ? { departmentId, scoping: true } : { departmentId, assessment: true })}
                className={bookMissing
                  ? 'inline-flex h-7 items-center rounded-lg border border-red-600 bg-red-900/50 px-2.5 text-xs font-medium text-red-100 hover:bg-red-800/60'
                  : btnSm.secondary}>{t('hours.title')}</button>
            )}
            {editable && position?.hours != null && (
              <button type="button" data-testid={`costpos-effort-correct-${departmentId}`}
                title={t('hours.correctBooked')}
                onClick={() => requestHoursCorrection({ departmentId })}
                className={btnSm.ghost}>{t('hours.correct')}</button>
            )}
          </span>
        ) : editable ? (
          <span className="inline-flex items-center gap-1.5">
            <label htmlFor={`effort-${kind}-${departmentId}`} className="sr-only">{t(labelKey)}</label>
            <input id={`effort-${kind}-${departmentId}`}
              data-testid={`costpos-effort-${kind}-${departmentId}`}
              type="number" step="0.5" min={0} value={hours}
              onChange={(e) => setHours(e.target.value)}
              onBlur={commit}
              onKeyDown={(e) => { if (e.key === 'Enter') commit() }}
              className={`${fieldCls} w-20 tabular-nums text-right ${supportMissing ? 'border-red-600' : ''}`} />
            <span className="text-xs text-slate-500">h</span>
            {supportMissing && <span className="text-[11px] text-red-300">{t('costpos.supportMissing')}</span>}
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

/** Christoph 2026-11-08: costing effort is booked (Book hours) and is
 *  mandatory: the standing row is red until the first costing booking. */
function CostingEffortStanding({ changeId, departmentId, position, editable, index, pm = false }: {
  changeId: number; departmentId: number; position?: CostPosition; editable: boolean; index: number
  /** the Project Manager: its costing effort is what it booked after scoping */
  pm?: boolean
}) {
  const { data: fc } = useQuery({
    queryKey: ['change', changeId, 'finalize-check', departmentId],
    queryFn: () => changesApi.finalizeCheck(changeId, departmentId),
    refetchInterval: COSTING_REFETCH_MS,
    enabled: editable,
  })
  const missing = !!fc?.items?.some((i) => i.tag === 'book_hours')
  return (
    <tr className={`border-t border-slate-700/70 ${missing ? 'bg-red-950/30' : ''}`} data-testid={`costpos-costing-effort-${departmentId}`}>
      <td className={`${cellCls} text-slate-500 tabular-nums w-8`}>{index}</td>
      <td className={cellCls}>
        <span className="text-slate-200">{t('costpos.costingEffortRow')}</span>
        <span className="ml-1.5 rounded bg-slate-700/70 text-slate-400 px-1 py-0 text-[11px]">{t('costpos.standing')}</span>
        {missing && <span className="ml-1.5 rounded bg-red-800 px-1 text-[11px] font-semibold text-red-100">{t('costpos.required')}</span>}
      </td>
      <td className={`${cellCls} text-slate-400 text-xs`} data-testid={`costpos-costing-effort-hint-${departmentId}`}>
        {t(pm ? 'costpos.bookedHintPm' : 'costpos.bookedHint')}
        {position && <RateNote p={position} />}</td>
      <td className={`${cellCls} text-xs text-slate-400 whitespace-nowrap`}>{t('costpos.type.time')}</td>
      <td className={`${cellCls} ${numCls} whitespace-nowrap`}>
        <span className="inline-flex items-center gap-1.5">
          <span className="tabular-nums text-slate-200">
            {position?.hours != null ? `${position.hours} h` : t('costpos.noneBooked')}</span>
          {editable && (
            <button type="button" data-testid={`costpos-costing-book-${departmentId}`}
              onClick={() => requestBookHours({ departmentId })}
              className={missing
                ? 'inline-flex h-7 items-center rounded-lg border border-red-600 bg-red-900/50 px-2.5 text-xs font-medium text-red-100'
                : btnSm.secondary}>{t('hours.title')}</button>
          )}
          {editable && position?.hours != null && (
            <button type="button" data-testid={`costpos-costing-correct-${departmentId}`}
              title={t('hours.correctBooked')}
              onClick={() => requestHoursCorrection({ departmentId })}
              className={btnSm.ghost}>{t('hours.correct')}</button>
          )}
        </span>
        {position && <LineValue p={position} />}
      </td>
      <td className={cellCls} /><td className={cellCls} />
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
              type="number" step="0.1" value={grams}
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
            {weightG != null ? `${weightG > 0 ? '+' : ''}${weightG} g` : '-'}
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
function AddLine({ changeId, departmentId, categories, onAdded, onCategoriesChanged, ctx, v2 = false, onCancel }: {
  changeId: number; departmentId: number; categories: CostCategory[]
  onAdded: () => void; onCategoriesChanged: () => void; ctx?: CostingContext
  /** Christoph 2026-11-08: an add row opened by accident is removed again, filled or not */
  onCancel?: () => void
  /** ASSESSMENT_V2: a money line says how many of what (A3-07). */
  v2?: boolean
}) {
  const [tag, setTag] = useState('')
  const [label, setLabel] = useState('')
  const [qty, setQty] = useState('')
  const [qtyUnit, setQtyUnit] = useState('')
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

  // A3-07 (spec §4 [R3]): a money line (estimate or quote) names its quantity
  const needsQty = v2 && !isTime && !isSheetKind
  const reset = () => {
    setLabel(''); setHours(''); setEst(''); setVendor(''); setLead(''); setTrials('')
    setQty(''); setQtyUnit('')
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
        lead_time_days: isTime ? null : num(lead), lead_time_unit: unit,
        ...(needsQty ? { quantity: num(qty), quantity_unit: qtyUnit.trim() } : {}),
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
    && (!needsQty || ((num(qty) ?? 0) > 0 && qtyUnit.trim() !== ''))
  // Audit P3-1: say what 'Add line' still waits for (the unit was silent)
  const waitsFor = [
    ...(label.trim() === '' ? [t('costpos.label')] : []),
    ...(needsQty && !((num(qty) ?? 0) > 0) ? [t('costpos.quantity')] : []),
    ...(needsQty && qtyUnit.trim() === '' ? [t('costpos.quantityUnit')] : []),
  ]
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
            {needsQty && (
              <span className="inline-flex items-center gap-1">
                <input data-testid={`costpos-new-qty-${departmentId}`} type="number" min={0} step="1"
                  value={qty} aria-label={t('costpos.quantity')} placeholder={t('costpos.quantity')}
                  onChange={(e) => setQty(e.target.value)} onKeyDown={submitOnEnter}
                  className={`${fieldCls} w-16 tabular-nums text-right`} />
                <input data-testid={`costpos-new-qtyunit-${departmentId}`} value={qtyUnit}
                  maxLength={20} aria-label={t('costpos.quantityUnit')}
                  placeholder={t('costpos.quantityUnit')}
                  onChange={(e) => setQtyUnit(e.target.value)} onKeyDown={submitOnEnter}
                  className={`${fieldCls} w-24`} />
              </span>
            )}
            {needsQty && label.trim() !== '' && waitsFor.length > 0 && (
              <span data-testid={`costpos-new-needs-${departmentId}`} className="text-[11px] text-amber-300">
                {t('costpos.qtyRequired')}
              </span>
            )}
            {isQuote && (
              <span data-testid={`costpos-new-quotehint-${departmentId}`} className="text-[11px] text-slate-400">
                {t('costpos.quoteAfterAdd')}
              </span>
            )}
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
          {/* own time is hours only, no days (Christoph 2026-11-09) */}
          {!isQuote && !isTime && (
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
            title={waitsFor.length ? t('costpos.addNeeds').replace('{x}', waitsFor.join(', ')) : undefined}
            className={btnSm.primary}>
            {t('costpos.addLine')}
          </button>
          {onCancel && (
            <button type="button" data-testid={`costpos-add-cancel-${departmentId}`}
              onClick={onCancel} className={`${btnSm.secondary} ml-1`}>{t('costpos.cancelAdd')}</button>
          )}
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

/** One line of the department total: what it is, and its amount. */
function TotalLine({ label, amount, testId }: { label: string; amount: string; testId?: string }) {
  return (
    <>
      <span className="min-w-0 pl-4 text-slate-300">{label}</span>
      <span className="text-right text-slate-100" data-testid={testId}>{amount}</span>
    </>
  )
}

/** A block's heading in the total: type dot, name, block subtotal. */
function TotalGroup({ group, title, sum, testId, label }: {
  group: LineGroup; title: string; sum: string; testId?: string; label?: string
}) {
  return (
    <>
      <span className="mt-2 inline-flex items-center gap-1.5 text-xs font-semibold text-slate-200">
        <TypeDot group={group} />{title}</span>
      <span className="mt-2 text-right text-xs font-semibold text-slate-200" data-testid={testId}>
        {label ? <span className="sr-only">{label}: </span> : null}{sum}</span>
    </>
  )
}

/** Christoph 2026-11-08: a supplier-priced block in the total, line by line:
 *  favourite vendor + price incl. transport (from-to while none is picked), or
 *  the estimate; a spare part as amount x price/pc + transport = total. */
function TotalBlock({ group, lines, currency, rangeText, categories }: {
  group: LineGroup; lines: CostPosition[]; currency: string; rangeText: string
  categories?: CostCategory[]
}) {
  const row = (p: CostPosition): { label: string; amount: string } => {
    const name = titledName(p, group === 'spare' ? spareName(p.label) : p.label, categories)
    const qty = group === 'spare' ? perPieceOf(p) : 1
    const pcs = (price: number) => (group === 'spare' ? `${formatNumber(qty)} × ${money(price, currency)}` : '')
    if (p.pricing === 'quote') {
      const offers = (p.offers ?? []).filter((o) => !o.is_partial)
      const fav = offers.find((o) => o.favorite) ?? (offers.length === 1 ? offers[0] : undefined)
      if (fav) {
        const ship = shipOf(fav)
        const parts = [fav.vendor_name, pcs(Number(fav.cost)),
          ship != null && ship > 0 ? `+ ${t('costpos.transport')} ${money(ship, currency)}` : ''].filter(Boolean)
        return { label: `${name}: ${parts.join(' ')}`, amount: money(offerLineTotal(p, fav), currency) }
      }
      if (offers.length) {
        const vals = offers.map((o) => offerLineTotal(p, o))
        return { label: `${name}: ${offers.length} ${t('costpos.grp.quotesNoFav')}`,
          amount: `${money(Math.min(...vals), currency)} – ${money(Math.max(...vals), currency)}` }
      }
      return { label: `${name}: ${t('costpos.grp.noQuoteYet')}`, amount: '-' }
    }
    if (p.est_cost) {
      const parts = [p.vendor_name ?? t('costpos.type.estimate'), pcs(Number(p.est_cost))].filter(Boolean)
      return { label: `${name}: ${parts.join(' ')}`, amount: money(Number(p.est_cost) * qty, currency) }
    }
    return { label: `${name}: ${t('costpos.grp.noPriceYet')}`, amount: '-' }
  }
  return (
    <>
      {/* one line: no block sum repeating its number */}
      <TotalGroup group={group} title={t(GROUP_STYLE[group].labelKey)} sum={lines.length > 1 ? rangeText : ''} />
      {lines.map((p) => {
        const r = row(p)
        return <TotalLine key={p.id} label={r.label} amount={r.amount} testId={`costpos-total-line-${p.id}`} />
      })}
    </>
  )
}

/** Christoph 2026-11-08: a section of the department's table: the type dot(s)
 *  and name, how many lines, and the section's subtotal on the right. */
function SectionHeader({ testId, title, kinds, subtotal, first = false }: {
  testId: string; title: string
  /** the line types in the section, with their counts (a type with 0 lines is left out) */
  kinds: [LineGroup, number][]
  subtotal?: React.ReactNode
  first?: boolean
}) {
  const shown = kinds.filter(([, c]) => c > 0)
  const count = shown.reduce((a, [, c]) => a + c, 0)
  return (
    <tr data-testid={testId}>
      <td colSpan={4} className={`px-2 ${first ? 'pt-3' : 'pt-8'} pb-1.5 border-b border-slate-600`}>
        <span className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
          <span className="text-sm font-semibold text-slate-100">{title}</span>
          {shown.length === 1 && kinds.length === 1 ? (
            <span className="inline-flex items-center gap-1.5 text-xs text-slate-400">
              <TypeDot group={shown[0][0]} />
              {count === 1 ? t('costpos.grp.line1') : t('costpos.grp.lines').replace('{n}', String(count))}
            </span>
          ) : shown.map(([g, c]) => (
            <span key={g} className="inline-flex items-center gap-1.5 text-xs text-slate-300">
              <TypeDot group={g} />{t(GROUP_STYLE[g].labelKey)} · {c}
            </span>
          ))}
        </span>
      </td>
      <td className={`px-2 ${first ? 'pt-3' : 'pt-8'} pb-1.5 border-b border-slate-600 ${numCls} whitespace-nowrap text-sm text-slate-100`}
        data-testid={`${testId}-subtotal`}>
        {subtotal}
      </td>
      <td colSpan={2} className={`${first ? 'pt-3' : 'pt-8'} pb-1.5 border-b border-slate-600`} />
    </tr>
  )
}

export default function CostPositions({
  changeId, departmentId, editable, departmentName, partWeightG, v2 = false, basisParts = [],
}: {
  /** ASSESSMENT_V2: every external line names its basis (spec §4, C25). */
  v2?: boolean
  /** Parts a "same as" basis may point at. */
  basisParts?: { id: number; number: string }[]
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
    refetchInterval: COSTING_REFETCH_MS,
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
  // A position is an answer too: the change's costing_pending_department_ids
  // moves, and "Your actions" drops its "Enter costs" row (one shared helper).
  const invalidate = () => invalidateCosting(qc, changeId)
  const mine = (positions ?? []).filter((p) => p.department_id === departmentId)
  // Each standing row binds to THE position of its kind. A department that
  // somehow has two keeps the extras in the list below rather than losing them.
  const boundIds = new Set(
    EFFORT_FIELDS.map(({ kind }) => mine.find((p) => p.kind === kind)?.id)
      .filter((id): id is number => id != null))
  // the costing effort (bookings after the assessment) is a standing row
  const costingEffort = mine.find((p) => p.kind === 'own_time' && p.notes === 'From the bookings')
  const listed = mine.filter((p) => !boundIds.has(p.id) && p.id !== costingEffort?.id)
  const isToolEngineer = departmentName === TOOL_ENGINEER_DEPARTMENT
  const weightSaved = () => invalidateCosting(qc, changeId)
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
  // Christoph 2026-11-08: three totals: hours spent so far (booked), the
  // internal work (hours x rate + own money lines), the external range
  const cur0 = ctx?.currency ?? (mine[0]?.currency ?? '')
  // booked so far = assessment effort + costing effort (both sums of the
  // bookings); the costing effort row counted nowhere here (2026-11-09 night:
  // 3 h shown with 5 h booked)
  const spentHours = mine.filter((p) => p.kind === 'internal_effort' || p.id === costingEffort?.id)
    .reduce((n, p) => n + (p.hours ?? 0), 0)
  const internalLines = mine.filter((p) => p.kind !== 'external')
  const internalHours = internalLines.reduce((n, p) => n + (p.kind === 'machine_time' || p.kind === 'sampling' ? 0 : (p.hours ?? 0)), 0)
  const internalMoney = internalLines.reduce((n, p) => n + (p.line_value != null && quantityOf(p) > 0 ? p.line_value : 0), 0)
  // spare parts count amount x price per piece, transport once (Christoph 2026-11-08)
  const { low: extLow, high: extHigh, fav: extFav, complete: extComplete } =
    supplierRange(mine.filter((x) => x.kind === 'external'))
  // Christoph 2026-11-08: fixed sections, in this order: our time, tool
  // change (internal, then external), spare parts, other
  const ownLines = listed.filter((p) => lineGroupOf(p) === 'time')
  const internalChanges = listed.filter((p) => lineGroupOf(p) === 'internal')
  const externalChanges = listed.filter((p) => lineGroupOf(p) === 'external')
  const toolChanges = [...internalChanges, ...externalChanges]
  const spareLines = listed.filter((p) => lineGroupOf(p) === 'spare')
  const rangeText = (lines: CostPosition[]) => {
    const r = supplierRange(lines)
    return r.high === 0 ? '-' : r.low === r.high ? money(r.low, cur0) : `${money(r.low, cur0)} – ${money(r.high, cur0)}`
  }
  const [adding, setAdding] = useState(false)
  const standingRows = EFFORT_FIELDS.length + 1
  let n = standingRows
  const rowOf = (p: CostPosition) => {
    n += 1
    return (
      <PositionRow key={p.id} changeId={changeId} position={p} categories={categories}
        v2={v2} basisParts={basisParts}
        editable={editable} index={n} onChanged={invalidate} ctx={ctx} />
    )
  }
  // the department's lead time: the longest line (favourite quote's days on
  // quoted lines); a spare part that is not time critical is left out
  // (Christoph 2026-11-09, same rule as the backend's roll-ups)
  const lead = leadSummary(mine)
  const unpriced = mine.filter((p) => p.rate_missing).length
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
            <SectionHeader testId={`costpos-group-time-${departmentId}`} first
              title={t('costpos.grp.ourTime')} kinds={[['time', ownLines.length + standingRows]]}
              subtotal={<>{formatHours(internalHours)} · {money(internalMoney, cur0)}</>} />
            {effortFieldsFor(departmentName).map(({ kind, labelKey, rowKey, descKey }, i) => {
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
            <CostingEffortStanding changeId={changeId} departmentId={departmentId}
              position={costingEffort} editable={editable} index={EFFORT_FIELDS.length + 1}
              pm={departmentName === 'Project Manager'} />
            {ownLines.map(rowOf)}
          </tbody>
          <tbody data-testid={`costpos-list-${departmentId}`}>
            {toolChanges.length > 0 && (
              <SectionHeader testId={`costpos-group-tool-${departmentId}`}
                title={t('costpos.grp.toolChange')}
                kinds={[['internal', internalChanges.length], ['external', externalChanges.length]]}
                subtotal={toolChanges.length > 1 ? rangeText(toolChanges) : undefined} />
            )}
            {toolChanges.map(rowOf)}
            {spareLines.length > 0 && (
              <SectionHeader testId={`costpos-group-spare-${departmentId}`}
                title={t('costpos.grp.spareParts')} kinds={[['spare', spareLines.length]]}
                subtotal={spareLines.length > 1 ? rangeText(spareLines) : undefined} />
            )}
            {spareLines.map(rowOf)}
            {toolChanges.length === 0 && spareLines.length === 0 && (
              <tr>
                <td />
                <td colSpan={6} className={`${cellCls} text-xs text-slate-500`}
                  data-testid={`costpos-empty-${departmentId}`}>
                  {t('costpos.noExternal')}
                </td>
              </tr>
            )}
          </tbody>
          {isToolEngineer && (
            <tbody data-testid={`costpos-other-${departmentId}`}>
              <SectionHeader testId={`costpos-group-other-${departmentId}`}
                title={t('costpos.grp.other')} kinds={[]} />
              <PartWeightRow key={`weight-${partWeightG ?? 'new'}`}
                changeId={changeId} departmentId={departmentId}
                weightG={partWeightG} editable={editable} index={n + 1}
                onSaved={weightSaved} />
            </tbody>
          )}
          <tfoot>
            {editable && (adding ? (
              <>
                <AddLine changeId={changeId} departmentId={departmentId} categories={categories}
                  ctx={ctx} onAdded={invalidate} v2={v2} onCancel={() => setAdding(false)}
                  onCategoriesChanged={() => qc.invalidateQueries({ queryKey: ['costing-tags', departmentId] })} />
              </>
            ) : (
              <tr>
                <td />
                <td colSpan={6} className={`${cellCls} pt-5 pb-3`}>
                  <button type="button" className={btnSm.secondary} data-testid={`costpos-add-open-${departmentId}`}
                    onClick={() => setAdding(true)}>{t('costpos.addCostLine')}</button>
                </td>
              </tr>
            ))}
            {/* Christoph 2026-11-08: the total lists every block line by line,
                in the sections' order and colours, then the grand total */}
            <tr className="border-t-2 border-slate-500">
              <td />
              <td colSpan={4} className={`${cellCls} pt-3 pb-4`} data-testid={`costpos-total-${departmentId}`}>
                <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-400">{t('costpos.total')}</p>
                <div className="grid grid-cols-[minmax(0,1fr)_auto] gap-x-8 gap-y-0.5 text-sm tabular-nums">
                  <TotalGroup group="time" title={t('costpos.grp.ourTime')}
                    sum={`${formatHours(internalHours)} · ${money(internalMoney, cur0)}`}
                    testId={`costpos-total-internal-${departmentId}`}
                    label={`${t('costpos.totInternal')} (${formatHours(internalHours)})`} />
                  {internalLines.filter((p) => (p.hours ?? 0) > 0 || (p.line_value ?? 0) > 0).map((p) => (
                    <TotalLine key={p.id}
                      label={`${titledName(p, p.label.replace(/ \(h\)$/, ''), categories)}: ${p.hours != null ? formatHours(p.hours) : ''}${p.rate != null ? ` × ${money(p.rate, p.rate_currency ?? cur0)}/h` : ''}`}
                      amount={p.line_value != null ? money(p.line_value, p.rate_currency ?? cur0) : t('costpos.noRate')} />
                  ))}
                  {([['internal', internalChanges], ['external', externalChanges], ['spare', spareLines]] as [LineGroup, CostPosition[]][])
                    .filter(([, lines]) => lines.length > 0).map(([g, lines]) => (
                      <TotalBlock key={g} group={g} lines={lines} currency={cur0} rangeText={rangeText(lines)} categories={categories} />
                    ))}
                  <span className="col-span-2 mt-2 border-t border-slate-600" />
                  <span className="text-slate-300">{t('costpos.totSpent')}</span>
                  <span className="text-right text-slate-300" data-testid={`costpos-total-spent-${departmentId}`}>
                    {formatHours(spentHours)}</span>
                  <span className="font-semibold text-slate-100">{t('costpos.totInternal')}</span>
                  <span className="text-right font-semibold text-slate-100">{formatHours(internalHours)} · {money(internalMoney, cur0)}</span>
                  <span className="font-semibold text-slate-100">{t('costpos.totExternal')}</span>
                  <span className="text-right font-semibold text-slate-100" data-testid={`costpos-total-external-${departmentId}`}>
                    {/* from–to over the quotes, always */}
                    {extHigh === 0 ? '-' : extLow === extHigh ? money(extLow, cur0)
                      : `${money(extLow, cur0)} – ${money(extHigh, cur0)}`}
                    {extHigh > 0 && extComplete && extFav > 0 && extLow !== extHigh && (
                      <span className="block text-xs font-normal text-slate-300">{t('costpos.favShort')}: {money(extFav, cur0)}</span>
                    )}
                  </span>
                  {(lead.days > 0 || lead.excluded.length > 0) && (
                    <>
                      <span className="text-slate-300">{t('costpos.leadLongest')}</span>
                      <span className="text-right text-slate-200" data-testid={`costpos-total-lead-${departmentId}`}>
                        {leadSummaryText(lead)}</span>
                    </>
                  )}
                  {totals.length > 1 && totals.map(([cur, v]) => (
                    <span key={cur || '-'} className="col-span-2 text-right text-xs text-slate-300">{money(v, cur)}</span>
                  ))}
                  {unpriced > 0 && (
                    <span data-testid={`costpos-unpriced-${departmentId}`}
                      className="col-span-2 text-right text-xs text-amber-300" title={t('costpos.noRateHint')}>
                      {t('costpos.unpricedInTotal').replace('{n}', String(unpriced))}
                    </span>
                  )}
                </div>
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
