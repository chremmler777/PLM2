/**
 * What changed against the previous version, per tab: added, removed and
 * changed rows, with the old and new value side by side.
 */
import { useQuery } from '@tanstack/react-query'
import { costSheetMachinesApi } from '../../api/costSheetMachines'
import { formatMoney, formatPercent } from '../../lib/format'
import type { CostSheetDiff, CostSheetSection, DiffSection } from '../../types/costSheet'
import { SECTION_LABELS, deptName, plantName, type SheetContext } from './columns'

const FIELD_LABELS: Record<string, string> = {
  hourly_rate: 'Rate / h', currency: 'Currency', note: 'Note', tonnage_min: 'From t',
  tonnage_max: 'To t', mode: 'Pricing', flat_price: 'Flat price', setup_hours: 'Setup h',
  run_hours_default: 'Run h', labour_hours: 'Labour h', labour_department_id: 'Labour dept.',
  handling_cost: 'Handling', kind: 'Kind', value: 'Value',
  entered_rate: 'Typed local rate', entered_currency: 'Typed in',
}
const MONEY = new Set(['hourly_rate', 'flat_price', 'handling_cost'])

export function diffCount(d: CostSheetDiff | undefined): number | null {
  if (!d) return null
  return (['rates', 'machines', 'sampling', 'overheads'] as CostSheetSection[])
    .reduce((n, s) => n + d[s].added.length + d[s].removed.length + d[s].changed.length, 0)
    + (d.machine_items
      ? d.machine_items.added.length + d.machine_items.removed.length + d.machine_items.changed.length
      : 0)
    + (d.fx_rates?.length ?? 0)
}

/** Own rates of MachineDB machines; names come from the synced machine list. */
function MachineItemsSection({ data }: { data: DiffSection }) {
  const q = useQuery({ queryKey: ['cost-sheet', 'machines', 'names'],
    queryFn: () => costSheetMachinesApi.list() })
  const names = new Map((q.data?.machines ?? []).map((m) => [m.id, m.internal_name]))
  // an unchanged typed currency is not in the diff: the plant's local one
  const locals = new Map((q.data?.machines ?? []).map((m) => [m.id, m.local_currency]))
  const name = (r: Record<string, unknown>) => names.get(r.machine_id as number) ?? `Machine ${r.machine_id}`
  const money = (v: unknown, cur: unknown) => formatMoney(v as number, (cur as string) || 'EUR')
  return (
    <div>
      <h4 className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-slate-400">Machine rates</h4>
      <ul className="space-y-1 text-sm">
        {data.changed.map((c, i) => {
          // each side in its own currency: a currency change reads 90.00 EUR -> 99.00 USD
          const ch = c.changes
          const side = (f: string, s: 'old' | 'new') => (ch[f] ? ch[f][s] : c[f])
          const oldCur = side('currency', 'old') ?? c.currency
          const newCur = side('currency', 'new') ?? c.currency
          const localMoved = ch.entered_rate || ch.entered_currency
          const localVal = (s: 'old' | 'new') => {
            const v = side('entered_rate', s)
            return v == null ? '-' : money(v, side('entered_currency', s) ?? locals.get(c.machine_id as number))
          }
          return (
            <li key={`c${i}`} className="flex flex-wrap items-baseline gap-x-3 gap-y-0.5 text-slate-200"
              data-testid={`diff-machine-item-${c.machine_id}`}>
              <span>{name(c)}</span>
              {ch.hourly_rate && (
                <span className="text-slate-400">
                  Rate / h: <span className="text-slate-500 line-through">{money(ch.hourly_rate.old, oldCur)}</span>
                  {' '}<span className="text-sky-300">{money(ch.hourly_rate.new, newCur)}</span>
                  {c.pct !== undefined && !ch.currency && (
                    <span className={`ml-1 text-xs ${c.pct >= 0 ? 'text-amber-300' : 'text-emerald-300'}`}>
                      {formatPercent(c.pct, 1, { sign: true })}
                    </span>
                  )}
                </span>
              )}
              {ch.currency && (
                <span className="text-slate-400">
                  Currency: <span className="text-slate-500 line-through">{(ch.currency.old as string) || '-'}</span>
                  {' '}<span className="text-sky-300">{(ch.currency.new as string) || '-'}</span>
                </span>
              )}
              {localMoved && (
                <span className="text-slate-400">
                  Typed local: <span className="text-slate-500 line-through">{localVal('old')}</span>
                  {' '}<span className="text-sky-300">{localVal('new')}</span>
                </span>
              )}
              {ch.note && (
                <span className="text-slate-400">
                  Note: <span className="text-slate-500 line-through">{(ch.note.old as string) || '-'}</span>
                  {' '}<span className="text-sky-300">{(ch.note.new as string) || '-'}</span>
                </span>
              )}
            </li>
          )
        })}
        {data.added.map((r, i) => (
          <li key={`a${i}`} className="text-slate-300">
            <span className="mr-2 rounded bg-emerald-500/15 px-1.5 text-[11px] font-medium text-emerald-300">new</span>
            {name(r)}<span className="ml-2 text-slate-400">{money(r.hourly_rate, r.currency)}</span>
          </li>
        ))}
        {data.removed.map((r, i) => (
          <li key={`r${i}`} className="text-slate-400">
            <span className="mr-2 rounded bg-red-500/15 px-1.5 text-[11px] font-medium text-red-300">removed</span>
            <span className="line-through">{name(r)}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}

function rowLabel(section: CostSheetSection, r: Record<string, unknown>, ctx: SheetContext): string {
  const plant = plantName(ctx, r.plant_id) || 'All plants'
  switch (section) {
    case 'rates':
      return `${deptName(ctx, r.department_id)} · ${plant}`
    case 'machines':
      return `${r.machine_class}${r.machine_ref ? ` · ${r.machine_ref}` : ''} · ${plant}`
    case 'sampling':
      return `${r.machine_class} · ${plant}`
    case 'overheads':
      return `${deptName(ctx, r.department_id) || 'All departments'} · ${plant}`
  }
}

/**
 * The row's own currency: the row says it, else a currency change on the row
 * (old or new side), else its plant's currency. Never a blanket EUR: a USA
 * Toccoa rate is in USD.
 */
function rowCurrency(r: Record<string, unknown>, ctx: SheetContext, side: 'old' | 'new' = 'new'): string {
  const change = (r.changes as Record<string, { old: unknown; new: unknown }> | undefined)?.currency
  if (change && typeof change[side] === 'string' && change[side]) return change[side] as string
  if (typeof r.currency === 'string' && r.currency) return r.currency
  const plant = ctx.plants.find((p) => p.id === r.plant_id)
  return plant?.currency || 'EUR'
}

function fmt(field: string, v: unknown, ctx: SheetContext, currency?: string): string {
  if (v === null || v === undefined || v === '') return field === 'hourly_rate' ? 'No rate' : '-'
  if (MONEY.has(field)) return formatMoney(v as number, currency)
  if (field === 'labour_department_id') return deptName(ctx, v)
  return String(v)
}

function addedValue(r: Record<string, unknown>, ctx: SheetContext): string {
  const cur = rowCurrency(r, ctx)
  if ('hourly_rate' in r) return fmt('hourly_rate', r.hourly_rate, ctx, cur)
  if (r.mode === 'flat') return fmt('flat_price', r.flat_price, ctx, cur)
  if (r.mode === 'components') return 'components'
  if (r.kind === 'percent') return `+${r.value} %`
  if (r.kind === 'per_hour') return `+${fmt('hourly_rate', r.value, ctx, cur)}/h`
  return ''
}

function Section({ section, data, ctx }: { section: CostSheetSection; data: DiffSection; ctx: SheetContext }) {
  const empty = !data.added.length && !data.removed.length && !data.changed.length
  return (
    <div>
      <h4 className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-slate-400">
        {SECTION_LABELS[section]}
      </h4>
      {empty ? <p className="text-sm text-slate-600">No changes.</p> : (
        <ul className="space-y-1 text-sm">
          {data.changed.map((c, i) => (
            <li key={`c${i}`} className="flex flex-wrap items-baseline gap-x-3 gap-y-0.5">
              <span className="text-slate-200">{rowLabel(section, c, ctx)}</span>
              {Object.entries(c.changes).map(([f, ch]) => (
                <span key={f} className="text-slate-400">
                  {FIELD_LABELS[f] ?? f}: <span className="text-slate-500 line-through">{fmt(f, ch.old, ctx, rowCurrency(c, ctx, 'old'))}</span>
                  {' '}<span className="text-sky-300">{fmt(f, ch.new, ctx, rowCurrency(c, ctx, 'new'))}</span>
                  {f === 'hourly_rate' && c.pct !== undefined && (
                    <span className={`ml-1 text-xs ${c.pct >= 0 ? 'text-amber-300' : 'text-emerald-300'}`}>
                      {formatPercent(c.pct, 1, { sign: true })}
                    </span>
                  )}
                </span>
              ))}
            </li>
          ))}
          {data.added.map((r, i) => (
            <li key={`a${i}`} className="text-slate-300">
              <span className="mr-2 rounded bg-emerald-500/15 px-1.5 text-[11px] font-medium text-emerald-300">new</span>
              {rowLabel(section, r, ctx)}
              <span className="ml-2 text-slate-400">{addedValue(r, ctx)}</span>
            </li>
          ))}
          {data.removed.map((r, i) => (
            <li key={`r${i}`} className="text-slate-400">
              <span className="mr-2 rounded bg-red-500/15 px-1.5 text-[11px] font-medium text-red-300">removed</span>
              <span className="line-through">{rowLabel(section, r, ctx)}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

export default function DiffPanel({ diff, ctx }: { diff: CostSheetDiff; ctx: SheetContext }) {
  return (
    <div className="rounded-lg border border-slate-700 bg-slate-800/60 p-4">
      <p className="mb-3 text-sm text-slate-400">
        {diff.from_version === null
          ? `Version ${diff.to_version} is the first one; nothing to compare with.`
          : `Version ${diff.to_version} compared with version ${diff.from_version}.`}
      </p>
      {diff.from_version !== null && (diff.fx_rates ?? []).length > 0 && (
        <ul data-testid="diff-fx" className="mb-3 space-y-1 text-sm">
          {(diff.fx_rates ?? []).map((f) => {
            const [base, quote] = f.pair.split('/')
            return (
              <li key={f.pair} className="text-slate-300">
                Exchange rate 1 {base} ={' '}
                <span className="text-slate-500 line-through">{f.old ?? 'not set'}</span>{' '}
                <span className="text-sky-300">{f.new ?? 'not set'}</span> {quote}
              </li>
            )
          })}
        </ul>
      )}
      {diff.from_version !== null && (
        <div className="grid gap-4 md:grid-cols-2">
          {(['rates', 'machines', 'sampling', 'overheads'] as CostSheetSection[]).map((s) => (
            <Section key={s} section={s} data={diff[s]} ctx={ctx} />
          ))}
          {diff.machine_items && (diff.machine_items.added.length + diff.machine_items.removed.length
            + diff.machine_items.changed.length > 0) && (
            <MachineItemsSection data={diff.machine_items} />
          )}
        </div>
      )}
    </div>
  )
}
