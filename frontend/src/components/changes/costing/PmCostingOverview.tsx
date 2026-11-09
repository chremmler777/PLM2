/**
 * Christoph 2026-11-08: "make sure PM sees all the important stuff". The PM
 * owns the change, closes costing and hands the offer to Sales: one compact
 * table at the top of the costing tab, one row per department that owes
 * costing, so nobody has to open every department to know where it stands.
 *
 * Every figure is the backend's: internal money and lead times from the
 * summation, line totals (amount x price + transport once) from the costing
 * positions (effective_cost, offer total_cost), open points from the
 * department's finalize-check. Here they are only summed and laid side by side.
 *
 * Each department row opens to its cost blocks line by line, in the costing
 * sections' order and colours: our time, internal change, external change,
 * spare parts. Open for the PM by default.
 */
import { Fragment, useState } from 'react'
import { useQueries, useQuery } from '@tanstack/react-query'
import { ChevronDown, ChevronRight } from 'lucide-react'
import { changesApi } from '../../../api/changes'
import { formatDate, formatDays, formatMoney, formatNumber } from '../../../lib/format'
import {
  countsForLeadTime, excludedText, leadSummary, leadSummaryText, lineGroupOf, spareName, type LineGroup,
} from '../CostPositions'
import { noCostWords } from './NoCostAndWaits'
import type { ChangeDetail, CostPosition, CostingOffer, Summation, SupplierWait } from '../../../types/change'

type CheckItem = { tag: string; text: string; info?: boolean }

const GROUPS: { key: LineGroup; label: string; dot: string }[] = [
  { key: 'time', label: 'Our time', dot: 'bg-slate-400' },
  { key: 'internal', label: 'Internal change', dot: 'bg-teal-400' },
  { key: 'external', label: 'External change', dot: 'bg-sky-400' },
  { key: 'spare', label: 'Spare parts', dot: 'bg-violet-400' },
]

/** Plain words for the finalize-check tags, the PM's reading of them. */
const TAG_WORDS: Record<string, string> = {
  transport_missing: 'transport', favourite: 'favourite', quote_missing: 'quote',
  price_missing: 'price', basis_missing: 'basis', hours_missing: 'hours',
  amount_missing: 'amount', compare: 'compare', empty: 'nothing entered',
  book_hours: 'book hours', support_hours: 'support hours', other: 'open',
  time_critical_missing: 'time critical?',
}

const alternatives = (p: CostPosition) => (p.offers ?? []).filter((o) => !o.is_partial)
const parts = (p: CostPosition) => (p.offers ?? []).filter((o) => o.is_partial)
const offerTotal = (o: CostingOffer) => Number(o.total_cost ?? o.cost ?? 0)

/** Cheapest to dearest a line can come to (backend line totals); null = nothing priced. */
export function lineRange(p: CostPosition): { low: number; high: number } | null {
  if (p.kind === 'external' && p.pricing === 'quote' && (p.offers ?? []).length > 0) {
    const base = parts(p).reduce((s, o) => s + offerTotal(o), 0)
    const vals = alternatives(p).map(offerTotal)
    if (!vals.length) return { low: base, high: base }
    return { low: base + Math.min(...vals), high: base + Math.max(...vals) }
  }
  if (p.effective_cost == null) return null
  return { low: Number(p.effective_cost), high: Number(p.effective_cost) }
}

export interface DeptExternal { low: number; high: number; fav: number; open: number; lines: number }

/** From-to and the favourites' sum over a department's supplier lines. */
export function externalOf(lines: CostPosition[]): DeptExternal {
  const out: DeptExternal = { low: 0, high: 0, fav: 0, open: 0, lines: 0 }
  for (const p of lines) {
    if (p.kind !== 'external') continue
    out.lines += 1
    const r = lineRange(p)
    if (r) { out.low += r.low; out.high += r.high }
    if (p.effective_cost != null) out.fav += Number(p.effective_cost)
    else out.open += 1
  }
  return out
}

const money = (v: number, cur?: string) => (cur ? formatMoney(v, cur) : formatNumber(v, { min: 2, max: 2 }))
const rangeText = (low: number, high: number, cur?: string) =>
  Math.abs(high - low) < 0.005 ? money(low, cur) : `${money(low, cur)} – ${money(high, cur)}`

/** Christoph 2026-11-08: filled is not done; only Finalize says the
 *  department confirmed its costing, so a filled, unfinalized row is red. */
type Status = 'not_started' | 'in_progress' | 'finalized' | 'no_cost'
const STATUS: Record<Status, { label: string; cls: string }> = {
  not_started: { label: 'Not started', cls: 'bg-slate-700 text-slate-300' },
  in_progress: { label: 'Not finalized', cls: 'bg-red-900/70 text-red-100' },
  finalized: { label: 'Finalized', cls: 'bg-emerald-900/70 text-emerald-200' },
  no_cost: { label: 'No cost', cls: 'bg-slate-700 text-slate-200' },
}

/** One costing line in the PM's words: what, how it is priced, what it comes to. */
function LineText({ p, cur }: { p: CostPosition; cur?: string }) {
  const group = lineGroupOf(p)
  if (group === 'time') {
    const qty = p.kind === 'sampling' ? (p.trials ?? 0) : (p.hours ?? 0)
    const unit = p.kind === 'sampling' ? 'trials' : 'h'
    return (
      <>
        <span className="text-slate-200">{p.label}</span>
        <span className="text-slate-400">
          {formatNumber(qty)} {unit}
          {p.rate != null ? ` × ${money(Number(p.rate), p.rate_currency ?? cur)}` : ''}
        </span>
        <span className="tabular-nums text-right">
          {p.rate_missing
            ? <span className="text-amber-300">no rate</span>
            : p.line_value != null ? money(Number(p.line_value), p.rate_currency ?? cur) : '-'}
        </span>
      </>
    )
  }
  const fav = (p.offers ?? []).find((o) => o.id === p.favorite_offer_id)
  const r = lineRange(p)
  const qty = p.quantity_unit === 'pcs' && (p.quantity ?? 0) > 0 ? Number(p.quantity) : null
  const ship = fav && !fav.shipping_included ? fav.shipping_cost : null
  let how: string
  if (p.pricing === 'quote') {
    const n = alternatives(p).length
    how = fav
      ? `${fav.vendor_name}${n > 1 ? ` (favourite of ${n})` : ''}`
      : n > 1 ? `${n} quotes, no favourite` : 'no quote yet'
  } else {
    how = `estimate${p.vendor_name ? `, ${p.vendor_name}` : ''}`
  }
  const unitPrice = fav ? Number(fav.cost) : p.est_cost != null ? Number(p.est_cost) : null
  if (group === 'spare' && qty != null && unitPrice != null) {
    how += ` · ${formatNumber(qty)} × ${money(unitPrice, cur)}/pc`
      + (ship != null ? ` + ${money(Number(ship), cur)} transport` : fav && fav.shipping_included ? ' (transport incl.)' : '')
  } else if (group === 'spare' && qty == null) {
    how += ' · amount missing'
  } else if (fav && ship != null && Number(ship) > 0) {
    how += ` · incl. ${money(Number(ship), cur)} transport`
  }
  return (
    <>
      <span className="text-slate-200">{group === 'spare' ? spareName(p.label) : p.label}</span>
      <span className="text-slate-400">{how}</span>
      <span className="tabular-nums text-right">
        {p.effective_cost != null
          ? money(Number(p.effective_cost), cur)
          : r ? <span className="text-amber-300">{rangeText(r.low, r.high, cur)}</span>
            : <span className="text-amber-300">no price</span>}
      </span>
    </>
  )
}

/** Under a department's lead time: what sets it ("30 d (spare part X, time
 *  critical)") when the lines explain the number, and any spare part left out. */
function LeadWhy({ lead, info, testId }: {
  lead: number | null; info: ReturnType<typeof leadSummary>; testId: string
}) {
  const text = lead != null && lead > 0 && info.days === lead ? leadSummaryText(info) : excludedText(info)
  if (!text) return null
  return <span className="block whitespace-normal text-[11px] text-slate-500" data-testid={testId}>{text}</span>
}

function Breakdown({ lines, cur }: { lines: CostPosition[]; cur?: string }) {
  if (!lines.length) return <p className="px-2 py-1 text-xs text-slate-500">No cost lines yet.</p>
  return (
    <div className="space-y-1.5 px-2 py-1.5">
      {GROUPS.map((g) => {
        const mine = lines.filter((p) => lineGroupOf(p) === g.key)
        if (!mine.length) return null
        return (
          <div key={g.key} data-testid={`pm-block-${g.key}`}>
            <p className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-slate-400">
              <span aria-hidden="true" className={`inline-block h-2 w-2 rounded-full ${g.dot}`} />{g.label}
            </p>
            <ul className="mt-0.5">
              {mine.map((p) => {
                const days = p.effective_lead_time_calendar_days ?? p.lead_time_days
                return (
                  <li key={p.id} data-testid={`pm-line-${p.id}`}
                    className="grid grid-cols-[minmax(10rem,16rem)_1fr_9rem_4rem] gap-3 border-t border-slate-800 py-0.5 pl-3.5 text-xs">
                    <LineText p={p} cur={cur} />
                    <span className="text-right tabular-nums text-slate-400">
                      {days ? formatDays(days) : ''}
                      {days && !countsForLeadTime(p) ? (
                        <span className="block text-[11px] text-slate-500" data-testid={`pm-line-excluded-${p.id}`}>
                          not time critical, not counted</span>
                      ) : null}
                    </span>
                  </li>
                )
              })}
            </ul>
          </div>
        )
      })}
    </div>
  )
}

export default function PmCostingOverview({
  change, departmentIds, deptName, summation, isPm, onJump,
}: {
  change: ChangeDetail
  /** The departments that owe costing, in the buckets' order. */
  departmentIds: number[]
  deptName: (id: number) => string
  summation: Summation | undefined
  /** PM (or admin): the cost blocks are open by default. */
  isPm: boolean
  onJump: (departmentId: number) => void
}) {
  const changeId = change.id
  const cur = summation?.currency
  const finalized = new Set(change.costing_finalized_department_ids ?? [])
  const [closed, setClosed] = useState<Set<number>>(() => new Set(isPm ? [] : departmentIds))
  const toggle = (id: number) => setClosed((s) => {
    const n = new Set(s)
    if (n.has(id)) n.delete(id); else n.add(id)
    return n
  })

  const { data: positions = [] } = useQuery<CostPosition[]>({
    queryKey: ['costing-positions', changeId],
    queryFn: () => changesApi.listCostPositions(changeId),
  })
  const checks = useQueries({
    queries: departmentIds.map((id) => ({
      queryKey: ['change', changeId, 'finalize-check', id],
      queryFn: () => changesApi.finalizeCheck(changeId, id),
      enabled: !finalized.has(id),
    })),
  })
  const waits: SupplierWait[] = (change.open_supplier_waits ?? []).filter((w) => w.is_open && w.phase !== 'implementation')
  const labelOf = (pid?: number | null) => positions.find((p) => p.id === pid)?.label

  const rows = departmentIds.map((id, i) => {
    const lines = positions.filter((p) => p.department_id === id)
    const dep = summation?.by_department.find((d) => d.department_id === id)
    const pos = summation?.positions_by_department?.find((d) => d.department_id === id)
    const internal = dep ? dep.one_time_internal + dep.lifecycle_internal : null
    const hours = (pos?.hours ?? 0) + (pos?.machine_hours ?? 0)
    const ext = externalOf(lines.filter((p) => !p.currency || !cur || p.currency === cur))
    const lead = summation?.lead_time_by_department?.find((d) => d.department_id === id)?.lead_time_days ?? null
    const noCost = change.costing_no_cost?.[String(id)]
    const status: Status = finalized.has(id) ? (noCost ? 'no_cost' : 'finalized')
      : lines.length > 0 || (internal ?? 0) !== 0 ? 'in_progress' : 'not_started'
    const a = change.assessments.find((x) => x.department_id === id)
    const items: CheckItem[] = finalized.has(id) ? [] : ((checks[i]?.data?.items as CheckItem[] | undefined) ?? [])
    // waits come from the change's own list (expected date, overdue); the
    // check's "waiting" item says the same, so it is left out here
    const blockers = items.filter((x) => !x.info && x.tag !== 'waiting')
    const deptWaits = waits.filter((w) => w.department_id === id)
    const fin = change.costing_finalized_info?.[String(id)]
    // Christoph 2026-11-09: who sets the department's lead time; a spare part
    // that is not time critical is left out (the summation applies the same rule)
    const leadInfo = leadSummary(lines)
    return { id, lines, internal, hours, ext, lead, leadInfo, noCost, status, a, blockers, deptWaits, fin }
  })

  const sumInternal = rows.reduce((s, r) => s + (r.internal ?? 0), 0)
  const sumHours = rows.reduce((s, r) => s + r.hours, 0)
  const sumLow = rows.reduce((s, r) => s + r.ext.low, 0)
  const sumHigh = rows.reduce((s, r) => s + r.ext.high, 0)
  const sumFav = rows.reduce((s, r) => s + r.ext.fav, 0)
  const sumOpen = rows.reduce((s, r) => s + r.ext.open, 0)
  const leadMax = summation?.max_lead_time_days ?? Math.max(0, ...rows.map((r) => r.lead ?? 0))
  const longest = rows.filter((r) => r.lead != null && r.lead === leadMax && leadMax > 0)
  const done = rows.filter((r) => r.status === 'finalized' || r.status === 'no_cost').length
  const openPoints = rows.reduce((s, r) => s + r.blockers.length + r.deptWaits.filter((w) => w.overdue).length, 0)

  const th = 'px-2 py-1.5 text-left text-[11px] font-normal uppercase tracking-wide text-slate-500'
  const td = 'px-2 py-1.5 align-top'
  const num = `${td} whitespace-nowrap text-right tabular-nums`
  return (
    <section data-testid="pm-costing-overview" aria-label="Costing overview"
      className="rounded-lg border border-slate-700 bg-slate-900/50">
      <header className="flex flex-wrap items-baseline gap-x-4 gap-y-1 px-3 py-2">
        <h3 className="text-sm font-semibold text-slate-100">Costing overview</h3>
        <span className="text-xs text-slate-400" data-testid="pm-overview-progress">
          {done} of {rows.length} finalized
          {openPoints > 0 && <> · <span className="text-amber-300">{openPoints} open point{openPoints === 1 ? '' : 's'}</span></>}
        </span>
      </header>
      <div className="overflow-x-auto border-t border-slate-700">
        <table className="w-full text-sm">
          <thead>
            <tr>
              <th className={th}>Department</th>
              <th className={th}>Status</th>
              <th className={th}>Who / due</th>
              <th className={`${th} text-right`}>Internal</th>
              <th className={`${th} text-right`}>External from – to</th>
              <th className={`${th} text-right`}>Favourites</th>
              <th className={`${th} text-right`}>Lead</th>
              <th className={th}>Open points</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => {
              const open = !closed.has(r.id)
              const who = r.a?.owner_name ?? r.a?.responsible_name ?? null
              const due = r.status === 'finalized' || r.status === 'no_cost' ? null : r.a?.due_date ?? null
              return (
                <Fragment key={r.id}>
                  <tr data-testid={`pm-row-${r.id}`} className="border-t border-slate-800">
                    <td className={td}>
                      <span className="flex items-center gap-1.5">
                        <button type="button" aria-expanded={open} data-testid={`pm-row-toggle-${r.id}`}
                          aria-label={`${open ? 'Hide' : 'Show'} the cost lines of ${deptName(r.id)}`}
                          onClick={() => toggle(r.id)} className="text-slate-500 hover:text-slate-300">
                          {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                        </button>
                        <button type="button" data-testid={`pm-row-jump-${r.id}`} onClick={() => onJump(r.id)}
                          className="whitespace-nowrap text-left font-medium text-slate-100 underline-offset-2 hover:underline">
                          {deptName(r.id)}
                        </button>
                      </span>
                    </td>
                    <td className={td}>
                      <span data-testid={`pm-status-${r.id}`}
                        className={`whitespace-nowrap rounded px-1.5 py-0 text-[11px] font-medium ${STATUS[r.status].cls}`}>
                        {STATUS[r.status].label}
                      </span>
                      {r.status === 'in_progress' && (
                        <span className="mt-0.5 block text-[11px] text-red-300">department not confirmed done</span>
                      )}
                      {r.status === 'no_cost' && (
                        <span className="ml-1 text-[11px] text-slate-400">{noCostWords(r.noCost)}</span>
                      )}
                      {(r.status === 'finalized' || r.status === 'no_cost') && (r.fin?.by_name || r.fin?.at) && (
                        <span className="mt-0.5 block text-[11px] text-emerald-300/90" data-testid={`pm-finalized-by-${r.id}`}>
                          {r.fin?.by_name ? `by ${r.fin.by_name}` : ''}{r.fin?.at ? `${r.fin?.by_name ? ', ' : ''}${formatDate(r.fin.at)}` : ''}
                        </span>
                      )}
                    </td>
                    <td className={`${td} text-xs`}>
                      <span className="block text-slate-300">{who ?? <span className="text-slate-500">nobody named</span>}</span>
                      {due && (
                        <span data-testid={`pm-due-${r.id}`}
                          className={`block ${r.a?.overdue ? 'font-medium text-red-300' : 'text-slate-500'}`}>
                          {r.a?.overdue ? 'overdue since ' : 'due '}{formatDate(due)}
                        </span>
                      )}
                    </td>
                    <td className={`${num}`} data-testid={`pm-internal-${r.id}`}>
                      <span className="block text-slate-200">{r.internal != null ? money(r.internal, cur) : '-'}</span>
                      {r.hours > 0 && <span className="block text-xs text-slate-500">{formatNumber(r.hours)} h</span>}
                    </td>
                    <td className={`${num} text-slate-300`} data-testid={`pm-ext-range-${r.id}`}>
                      {r.ext.lines === 0 ? <span className="text-slate-500">-</span> : rangeText(r.ext.low, r.ext.high, cur)}
                    </td>
                    <td className={`${num}`} data-testid={`pm-ext-fav-${r.id}`}>
                      {r.ext.lines === 0 ? <span className="text-slate-500">-</span> : (
                        <>
                          <span className="block text-slate-200">{money(r.ext.fav, cur)}</span>
                          {r.ext.open > 0 && (
                            <span className="block text-xs text-amber-300">{r.ext.open} line{r.ext.open === 1 ? '' : 's'} without a price</span>
                          )}
                        </>
                      )}
                    </td>
                    <td className={`${num} text-slate-300`} data-testid={`pm-lead-${r.id}`}>
                      {r.lead != null ? formatDays(r.lead) : '-'}
                      <LeadWhy lead={r.lead} info={r.leadInfo} testId={`pm-lead-why-${r.id}`} />
                    </td>
                    <td className={`${td} text-xs`} data-testid={`pm-open-${r.id}`}>
                      {r.blockers.length === 0 && r.deptWaits.length === 0
                        ? <span className="text-slate-500">{r.status === 'not_started' ? 'nothing entered yet'
                          : r.status === 'in_progress' ? 'nothing missing: ready to finalize' : 'none'}</span>
                        : (
                          <ul className="space-y-0.5">
                            {r.blockers.map((b, n) => (
                              <li key={`b${n}`} className="text-amber-200">
                                <span className="mr-1 text-[10px] font-semibold uppercase text-amber-400">{TAG_WORDS[b.tag] ?? b.tag.replace(/_/g, ' ')}</span>
                                {b.text}
                              </li>
                            ))}
                            {r.deptWaits.map((w) => (
                              <li key={`w${w.id}`} data-testid={`pm-wait-${w.id}`}
                                className={w.overdue ? 'text-red-300' : 'text-slate-300'}>
                                Waiting on {w.vendor_name}{labelOf(w.position_id) ? ` (${labelOf(w.position_id)})` : ''}:
                                {w.overdue ? ' overdue, was expected ' : ' expected '}{formatDate(w.expected_by)}
                              </li>
                            ))}
                          </ul>
                        )}
                    </td>
                  </tr>
                  {open && (
                    <tr data-testid={`pm-lines-${r.id}`}>
                      <td colSpan={8} className="bg-slate-950/30 px-2 pb-2">
                        <Breakdown lines={r.lines} cur={cur} />
                      </td>
                    </tr>
                  )}
                </Fragment>
              )
            })}
            <tr data-testid="pm-total-row" className="border-t border-slate-600 bg-slate-800/60 font-medium">
              <td className={`${td} text-slate-100`} colSpan={3}>Total ({rows.length} departments)</td>
              <td className={`${num} text-slate-100`} data-testid="pm-total-internal">
                <span className="block">{money(sumInternal, cur)}</span>
                {sumHours > 0 && <span className="block text-xs font-normal text-slate-400">{formatNumber(sumHours)} h</span>}
              </td>
              <td className={`${num} text-slate-100`} data-testid="pm-total-ext-range">
                {rangeText(sumLow, sumHigh, cur)}
              </td>
              <td className={`${num} text-slate-100`} data-testid="pm-total-ext-fav">
                <span className="block">{money(sumFav, cur)}</span>
                {sumOpen > 0 && <span className="block text-xs font-normal text-amber-300">{sumOpen} without a price</span>}
              </td>
              <td className={`${num} text-slate-100`} data-testid="pm-total-lead">
                {leadMax > 0 ? formatDays(leadMax) : '-'}
              </td>
              <td className={`${td} text-xs font-normal text-slate-400`}>
                {longest.length > 0 && <>longest: {longest.map((r) => deptName(r.id)).join(', ')}</>}
                {longest.filter((r) => r.leadInfo.days === leadMax).map((r) => (
                  <span key={r.id} className="block" data-testid={`pm-total-lead-why-${r.id}`}>
                    {leadSummaryText(r.leadInfo)}</span>
                ))}
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      {summation?.mixed_currency && (
        <p className="border-t border-slate-700 px-3 py-1.5 text-xs text-amber-300">
          Some amounts are in another currency and not in these totals (no conversion).
        </p>
      )}
    </section>
  )
}
