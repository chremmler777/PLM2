/**
 * The cost sheet columns as sort/filter definitions for the shared
 * ColumnHeader: value columns filter by the text the cell shows (department
 * name, "All plants", "No rate"), number columns by a from/to range.
 */
import type { FilterColumnDef } from '../common/tableFilters'
import type { CostSheetRow } from '../../types/costSheet'
import { displayValue } from './SheetCell'
import type { Column, SheetContext } from './columns'

const num = (v: unknown): number | null =>
  typeof v === 'number' && Number.isFinite(v) ? v : null

export function filterColumns(cols: Column[], ctx: SheetContext): FilterColumnDef<CostSheetRow>[] {
  return cols.map((c) => {
    if (c.numeric) {
      return {
        key: c.key, label: c.label, kind: 'number' as const,
        value: (r: CostSheetRow) => num(r[c.key]),
      }
    }
    return {
      key: c.key, label: c.label, kind: 'values' as const,
      value: (r: CostSheetRow) => {
        const v = r[c.key]
        return v === null || v === undefined || v === '' ? null : displayValue(c, r, ctx)
      },
      display: (r: CostSheetRow) => {
        const v = r[c.key]
        // An empty optional field shows its placeholder word (All plants,
        // All departments); a plain empty note stays blank.
        if ((v === null || v === undefined || v === '') && !c.empty) return ''
        return displayValue(c, r, ctx)
      },
    }
  })
}
