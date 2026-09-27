/**
 * "2 filters active · 12 of 40 rows · Clear filters": the one line that says a
 * table is narrowed, and undoes it. Renders nothing while no filter is set.
 */
import { X } from 'lucide-react'
import { btnSm } from './buttonStyles'

export interface TableFilterBarProps {
  /** Active column filters (activeFilterCount). */
  count: number
  onClear: () => void
  /** Rows shown after filtering. */
  shown?: number
  /** Rows before filtering. */
  total?: number
  className?: string
}

export default function TableFilterBar({ count, onClear, shown, total, className = '' }: TableFilterBarProps) {
  if (count <= 0) return null
  return (
    <div data-testid="table-filter-bar"
      className={`flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-slate-400 ${className}`}>
      <span role="status" aria-live="polite">
        <span className="font-medium text-sky-300">{count} {count === 1 ? 'filter' : 'filters'} active</span>
        {shown !== undefined && total !== undefined && (
          <span className="tabular-nums"> · {shown} of {total} {total === 1 ? 'row' : 'rows'}</span>
        )}
      </span>
      <button type="button" onClick={onClear} className={btnSm.ghost}>
        <X aria-hidden="true" size={12} />
        Clear filters
      </button>
    </div>
  )
}
