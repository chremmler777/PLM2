/**
 * What changed against the previous version, per tab: added, removed and
 * changed rows, with the old and new value side by side.
 */
import { formatMoney, formatPercent } from '../../lib/format'
import type { CostSheetDiff, CostSheetSection, DiffSection } from '../../types/costSheet'
import { SECTION_LABELS, deptName, plantName, type SheetContext } from './columns'

const FIELD_LABELS: Record<string, string> = {
  hourly_rate: 'Rate / h', currency: 'Currency', note: 'Note', tonnage_min: 'From t',
  tonnage_max: 'To t', mode: 'Pricing', flat_price: 'Flat price', setup_hours: 'Setup h',
  run_hours_default: 'Run h', labour_hours: 'Labour h', labour_department_id: 'Labour dept.',
  labour_position: 'Labour position', handling_cost: 'Handling', kind: 'Kind', value: 'Value',
}
const MONEY = new Set(['hourly_rate', 'flat_price', 'handling_cost'])

export function diffCount(d: CostSheetDiff | undefined): number | null {
  if (!d) return null
  return (['rates', 'machines', 'sampling', 'overheads'] as CostSheetSection[])
    .reduce((n, s) => n + d[s].added.length + d[s].removed.length + d[s].changed.length, 0)
}

function rowLabel(section: CostSheetSection, r: Record<string, unknown>, ctx: SheetContext): string {
  const plant = plantName(ctx, r.plant_id) || 'All plants'
  switch (section) {
    case 'rates':
      return `${deptName(ctx, r.department_id)} · ${(r.position as string) || 'Default'} · ${plant}`
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
  if (v === null || v === undefined || v === '') return '-'
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
      {diff.from_version !== null && (
        <div className="grid gap-4 md:grid-cols-2">
          {(['rates', 'machines', 'sampling', 'overheads'] as CostSheetSection[]).map((s) => (
            <Section key={s} section={s} data={diff[s]} ctx={ctx} />
          ))}
        </div>
      )}
    </div>
  )
}
