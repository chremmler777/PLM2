/**
 * Column definitions for the four cost sheet tabs. One generic table renders
 * them; a column says what it holds and the cell knows how to show and edit it.
 */
import type { ReactNode } from 'react'
import { formatMoney } from '../../lib/format'
import type {
  CostSheetOverview, CostSheetRow, CostSheetSection, PositionRate, SamplingRate,
} from '../../types/costSheet'

export type ColumnKind =
  | 'money' | 'number' | 'text' | 'currency'
  | 'department' | 'department_optional' | 'plant' | 'machine_class'
  | 'sampling_mode' | 'overhead_kind' | 'computed'

export interface Column {
  key: string
  label: string
  kind: ColumnKind
  /** Placeholder / display text when the value is empty. */
  empty?: string
  numeric?: boolean
  title?: string
  width?: string
  /** Read-only derived value. */
  render?: (row: CostSheetRow, ctx: SheetContext) => ReactNode
  /** Hidden in the add-row line (derived columns). */
  derived?: boolean
  /** Disabled for this row (e.g. flat price on a components row). */
  inactive?: (row: CostSheetRow) => boolean
}

export interface SheetContext {
  departments: CostSheetOverview['departments']
  plants: CostSheetOverview['plants']
  machineClasses: CostSheetOverview['machine_classes']
  currencies: string[]
}

export const SECTION_LABELS: Record<CostSheetSection, string> = {
  rates: 'Positions',
  machines: 'Machines',
  sampling: 'Sampling',
  overheads: 'Overheads',
}

export const SECTION_EXPORT: Record<CostSheetSection, string> = {
  rates: 'Positions',
  machines: 'Machines',
  sampling: 'Sampling',
  overheads: 'Overheads',
}

export const SECTION_BLURB: Record<CostSheetSection, string> = {
  rates: 'Hourly rate per department, optionally per position and plant. The most specific row wins: department + position + plant, then department + position, then department + plant, then the department default.',
  machines: 'Hourly machine rate per machine class, or for one named press. A named press beats its class; a plant row beats the all-plants row.',
  sampling: 'Price of one sampling trial per machine class: a flat price, or setup and run hours on the machine plus labour hours plus handling.',
  overheads: 'Personnel overhead on top of the position rate. Most specific wins: department + plant, then department, then plant, then the whole organization.',
}

const MISSING_LABEL: Record<string, string> = {
  machine_rate: 'no machine rate',
  labour_rate: 'no labour rate',
  machine_rate_currency: 'machine rate in other currency',
  labour_rate_currency: 'labour rate in other currency',
}

function overheadLabel(kind: string, value: number, currency = 'EUR'): string {
  return kind === 'percent'
    ? `+${value.toLocaleString('de-DE', { maximumFractionDigits: 2 })} %`
    : `+${formatMoney(value, currency)}/h`
}

export const COLUMNS: Record<CostSheetSection, Column[]> = {
  rates: [
    { key: 'department_id', label: 'Department', kind: 'department', width: 'min-w-[11rem]' },
    { key: 'position', label: 'Position', kind: 'text', empty: 'Default', width: 'min-w-[9rem]',
      title: 'Empty = the department default' },
    { key: 'plant_id', label: 'Plant', kind: 'plant', empty: 'All plants', width: 'min-w-[9rem]' },
    { key: 'hourly_rate', label: 'Rate / h', kind: 'money', numeric: true, width: 'w-32' },
    { key: 'effective_rate', label: 'Effective / h', kind: 'computed', numeric: true, derived: true, width: 'min-w-[8.5rem]',
      title: 'Rate plus the most specific personnel overhead at this row\'s plant',
      render: (row) => {
        const r = row as unknown as PositionRate
        return (
          <span className="inline-flex flex-col items-end leading-tight">
            <span className="whitespace-nowrap text-slate-100 tabular-nums">{formatMoney(r.effective_rate, r.currency)}</span>
            {r.overhead && (
              <span className={`whitespace-nowrap text-[11px] ${r.effective_rate === null ? 'text-amber-400' : 'text-slate-500'}`}
                    title={r.effective_rate === null ? 'The per-hour overhead is in another currency than this rate' : undefined}>
                {r.effective_rate === null
                  ? `overhead in ${r.overhead.currency}`
                  : overheadLabel(r.overhead.kind, r.overhead.value, r.overhead.currency ?? r.currency)}
              </span>
            )}
          </span>
        )
      } },
    { key: 'currency', label: 'Cur.', kind: 'currency', width: 'w-20 min-w-[4.75rem]' },
    { key: 'note', label: 'Note', kind: 'text', width: 'min-w-[10rem]' },
  ],
  machines: [
    { key: 'machine_class_id', label: 'Machine class', kind: 'machine_class', width: 'min-w-[9rem]' },
    { key: 'machine_ref', label: 'Machine', kind: 'text', empty: 'Class rate', width: 'min-w-[9rem]',
      title: 'Empty = the rate for the whole class; a name = one specific press' },
    { key: 'plant_id', label: 'Plant', kind: 'plant', empty: 'All plants', width: 'min-w-[9rem]' },
    { key: 'tonnage_min', label: 'From t', kind: 'number', numeric: true, width: 'w-20' },
    { key: 'tonnage_max', label: 'To t', kind: 'number', numeric: true, width: 'w-20' },
    { key: 'hourly_rate', label: 'Rate / h', kind: 'money', numeric: true, width: 'w-32' },
    { key: 'currency', label: 'Cur.', kind: 'currency', width: 'w-20 min-w-[4.75rem]' },
    { key: 'note', label: 'Note', kind: 'text', width: 'min-w-[10rem]' },
  ],
  // Compact: fits a 1500 px window next to the sidebar. The currency follows
  // the plant and is shown with the price instead of in its own column.
  sampling: [
    { key: 'machine_class_id', label: 'Class', kind: 'machine_class', width: 'min-w-[7rem]' },
    { key: 'plant_id', label: 'Plant', kind: 'plant', empty: 'All plants', width: 'min-w-[7.5rem]' },
    { key: 'mode', label: 'Pricing', kind: 'sampling_mode', width: 'min-w-[8rem]' },
    { key: 'flat_price', label: 'Flat', kind: 'money', numeric: true, width: 'min-w-[5.75rem]',
      inactive: (r) => r.mode !== 'flat' },
    { key: 'setup_hours', label: 'Setup h', kind: 'number', numeric: true, width: 'min-w-[4rem]',
      inactive: (r) => r.mode !== 'components' },
    { key: 'run_hours_default', label: 'Run h', kind: 'number', numeric: true, width: 'min-w-[4rem]',
      inactive: (r) => r.mode !== 'components' },
    { key: 'labour_hours', label: 'Lab. h', kind: 'number', numeric: true, width: 'min-w-[4rem]',
      title: 'Labour hours per trial', inactive: (r) => r.mode !== 'components' },
    { key: 'labour_department_id', label: 'Labour dept.', kind: 'department_optional', empty: '-',
      width: 'min-w-[8rem]', inactive: (r) => r.mode !== 'components' },
    { key: 'labour_position', label: 'Position', kind: 'text', empty: 'Default',
      width: 'min-w-[6rem]', title: 'Which position rate prices the labour hours',
      inactive: (r) => r.mode !== 'components' },
    { key: 'handling_cost', label: 'Handling', kind: 'money', numeric: true, width: 'min-w-[5.75rem]',
      inactive: (r) => r.mode !== 'components' },
    { key: 'computed_price', label: 'Per trial', kind: 'computed', numeric: true, derived: true, width: 'min-w-[7.5rem]',
      title: 'Flat price, or (setup + run h) x machine rate + labour h x effective labour rate + handling. Empty when a part is missing.',
      render: (row) => {
        const r = row as unknown as SamplingRate
        const missing = r.breakdown?.missing ?? []
        return (
          <span className="inline-flex flex-col items-end leading-tight">
            <span className="whitespace-nowrap text-slate-100 tabular-nums">
              {r.computed_price === null ? 'incomplete' : formatMoney(r.computed_price, r.currency)}
            </span>
            {missing.length > 0 && (
              <span className="whitespace-nowrap text-[11px] text-amber-400">
                {missing.map((m) => MISSING_LABEL[m] ?? m).join(', ')}
              </span>
            )}
          </span>
        )
      } },
    { key: 'note', label: 'Note', kind: 'text', width: 'min-w-[5rem]' },
  ],
  overheads: [
    { key: 'department_id', label: 'Department', kind: 'department_optional', empty: 'All departments',
      width: 'min-w-[11rem]' },
    { key: 'plant_id', label: 'Plant', kind: 'plant', empty: 'All plants', width: 'min-w-[9rem]' },
    { key: 'kind', label: 'Kind', kind: 'overhead_kind', width: 'w-32' },
    { key: 'value', label: 'Value', kind: 'number', numeric: true, width: 'w-28',
      title: 'Percent: 25 = +25 % (0 to 300). Per hour: added to the rate' },
    { key: 'currency', label: 'Cur.', kind: 'currency', width: 'w-20 min-w-[4.75rem]',
      title: 'Per hour only; must match the rates it is added to',
      inactive: (r) => r.kind !== 'per_hour' },
    { key: 'note', label: 'Note', kind: 'text', width: 'min-w-[12rem]' },
  ],
}

/** The row a fresh "add" line starts from. */
export function blankRow(section: CostSheetSection, ctx: SheetContext): CostSheetRow {
  const firstDept = ctx.departments.find((d) => d.is_active)?.id ?? null
  const firstClass = ctx.machineClasses.find((c) => c.is_active)?.id ?? null
  switch (section) {
    case 'rates':
      return { department_id: firstDept, position: null, plant_id: null, hourly_rate: null }
    case 'machines':
      return { machine_class_id: firstClass, plant_id: null, hourly_rate: null }
    case 'sampling':
      return { machine_class_id: firstClass, plant_id: null, mode: 'flat', flat_price: null }
    case 'overheads':
      return { department_id: null, plant_id: null, kind: 'percent', value: null }
  }
}

export function deptName(ctx: SheetContext, id: unknown): string {
  if (id === null || id === undefined) return ''
  return ctx.departments.find((d) => d.id === id)?.name ?? `#${id}`
}

export function plantName(ctx: SheetContext, id: unknown): string {
  if (id === null || id === undefined) return ''
  return ctx.plants.find((p) => p.id === id)?.name ?? `#${id}`
}

/** Stable reading order for a tab: department (their sort order), then
 * position (default first), then plant (all plants first). */
export function sortRows(rows: CostSheetRow[], ctx: SheetContext): CostSheetRow[] {
  const dIdx = new Map(ctx.departments.map((d, i) => [d.id, i]))
  const cIdx = new Map(ctx.machineClasses.map((c, i) => [c.id, i]))
  const key = (r: CostSheetRow): (string | number)[] => [
    r.department_id == null ? -1 : (dIdx.get(r.department_id as number) ?? 999),
    r.machine_class_id == null ? -1 : (cIdx.get(r.machine_class_id as number) ?? 999),
    String(r.position ?? r.machine_ref ?? ''),
    r.plant_id == null ? '' : plantName(ctx, r.plant_id),
    r.id as number,
  ]
  return [...rows].sort((a, b) => {
    const ka = key(a), kb = key(b)
    for (let i = 0; i < ka.length; i++) {
      if (ka[i] < kb[i]) return -1
      if (ka[i] > kb[i]) return 1
    }
    return 0
  })
}
