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
              <span className="whitespace-nowrap text-[11px] text-slate-500">
                {overheadLabel(r.overhead.kind, r.overhead.value, r.currency)}
              </span>
            )}
          </span>
        )
      } },
    { key: 'currency', label: 'Cur.', kind: 'currency', width: 'w-20 min-w-[4.75rem]' },
    { key: 'note', label: 'Note', kind: 'text', width: 'min-w-[10rem]' },
  ],
  machines: [
    { key: 'machine_class', label: 'Machine class', kind: 'machine_class', width: 'min-w-[9rem]' },
    { key: 'machine_ref', label: 'Machine', kind: 'text', empty: 'Class rate', width: 'min-w-[9rem]',
      title: 'Empty = the rate for the whole class; a name = one specific press' },
    { key: 'plant_id', label: 'Plant', kind: 'plant', empty: 'All plants', width: 'min-w-[9rem]' },
    { key: 'tonnage_min', label: 'From t', kind: 'number', numeric: true, width: 'w-20' },
    { key: 'tonnage_max', label: 'To t', kind: 'number', numeric: true, width: 'w-20' },
    { key: 'hourly_rate', label: 'Rate / h', kind: 'money', numeric: true, width: 'w-32' },
    { key: 'currency', label: 'Cur.', kind: 'currency', width: 'w-20 min-w-[4.75rem]' },
    { key: 'note', label: 'Note', kind: 'text', width: 'min-w-[10rem]' },
  ],
  sampling: [
    { key: 'machine_class', label: 'Machine class', kind: 'machine_class', width: 'min-w-[9rem]' },
    { key: 'plant_id', label: 'Plant', kind: 'plant', empty: 'All plants', width: 'min-w-[8rem]' },
    { key: 'mode', label: 'Pricing', kind: 'sampling_mode', width: 'min-w-[9rem]' },
    { key: 'flat_price', label: 'Flat price', kind: 'money', numeric: true, width: 'min-w-[7rem]',
      inactive: (r) => r.mode !== 'flat' },
    { key: 'setup_hours', label: 'Setup h', kind: 'number', numeric: true, width: 'min-w-[5rem]',
      inactive: (r) => r.mode !== 'components' },
    { key: 'run_hours_default', label: 'Run h', kind: 'number', numeric: true, width: 'min-w-[5rem]',
      inactive: (r) => r.mode !== 'components' },
    { key: 'labour_hours', label: 'Labour h', kind: 'number', numeric: true, width: 'min-w-[5rem]',
      inactive: (r) => r.mode !== 'components' },
    { key: 'labour_department_id', label: 'Labour dept.', kind: 'department_optional', empty: '-',
      width: 'min-w-[9rem]', inactive: (r) => r.mode !== 'components' },
    { key: 'handling_cost', label: 'Handling', kind: 'money', numeric: true, width: 'min-w-[7rem]',
      inactive: (r) => r.mode !== 'components' },
    { key: 'computed_price', label: 'Per trial', kind: 'computed', numeric: true, derived: true, width: 'min-w-[8.5rem]',
      title: 'Flat price, or (setup + run h) x machine rate + labour h x effective labour rate + handling',
      render: (row) => {
        const r = row as unknown as SamplingRate
        const missing = r.breakdown?.missing ?? []
        return (
          <span className="inline-flex flex-col items-end leading-tight">
            <span className="whitespace-nowrap text-slate-100 tabular-nums">{formatMoney(r.computed_price, r.currency)}</span>
            {missing.length > 0 && (
              <span className="whitespace-nowrap text-[11px] text-amber-400">
                no {missing.map((m) => m.replace('_', ' ')).join(', ')}
              </span>
            )}
          </span>
        )
      } },
    { key: 'currency', label: 'Cur.', kind: 'currency', width: 'w-20 min-w-[4.75rem]' },
    { key: 'note', label: 'Note', kind: 'text', width: 'min-w-[8rem]' },
  ],
  overheads: [
    { key: 'department_id', label: 'Department', kind: 'department_optional', empty: 'All departments',
      width: 'min-w-[11rem]' },
    { key: 'plant_id', label: 'Plant', kind: 'plant', empty: 'All plants', width: 'min-w-[9rem]' },
    { key: 'kind', label: 'Kind', kind: 'overhead_kind', width: 'w-32' },
    { key: 'value', label: 'Value', kind: 'number', numeric: true, width: 'w-28',
      title: 'Percent: 25 = +25 %. Per hour: added to the rate' },
    { key: 'note', label: 'Note', kind: 'text', width: 'min-w-[12rem]' },
  ],
}

/** The row a fresh "add" line starts from. */
export function blankRow(section: CostSheetSection, ctx: SheetContext): CostSheetRow {
  const firstDept = ctx.departments.find((d) => d.is_active)?.id ?? null
  const firstClass = ctx.machineClasses[0]?.name ?? ''
  switch (section) {
    case 'rates':
      return { department_id: firstDept, position: null, plant_id: null, hourly_rate: null, currency: 'EUR' }
    case 'machines':
      return { machine_class: firstClass, plant_id: null, hourly_rate: null, currency: 'EUR' }
    case 'sampling':
      return { machine_class: firstClass, plant_id: null, mode: 'flat', flat_price: null, currency: 'EUR' }
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
  const cIdx = new Map(ctx.machineClasses.map((c, i) => [c.name.toLowerCase(), i]))
  const key = (r: CostSheetRow): (string | number)[] => [
    r.department_id == null ? -1 : (dIdx.get(r.department_id as number) ?? 999),
    r.machine_class == null ? -1 : (cIdx.get(String(r.machine_class).toLowerCase()) ?? 999),
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
