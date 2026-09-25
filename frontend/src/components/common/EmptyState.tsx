/**
 * EmptyState: what a big empty region says. A short title ("No impacted
 * items yet"), an optional one-line hint that says how it fills, and an
 * optional action. Use it for panels and tables, not for a single empty cell
 * (that stays "-").
 */
import type { ReactNode } from 'react'

export interface EmptyStateProps {
  title: string
  hint?: ReactNode
  /** A <Button> or link that fills the region. */
  action?: ReactNode
  /** A lucide icon element; decorative. */
  icon?: ReactNode
  /** `sm` for cards and table bodies, `md` (default) for tab-sized regions. */
  size?: 'sm' | 'md'
  /** Dashed outline around the region. Default true; off inside an already-bordered card. */
  bordered?: boolean
  className?: string
  'data-testid'?: string
}

export default function EmptyState({
  title, hint, action, icon, size = 'md', bordered = true, className = '', 'data-testid': testId,
}: EmptyStateProps) {
  const pad = size === 'sm' ? 'px-4 py-5' : 'px-6 py-10'
  return (
    <div data-testid={testId}
      className={`flex flex-col items-center justify-center text-center ${pad} ${
        bordered ? 'rounded-xl border border-dashed border-slate-700' : ''} ${className}`}>
      {icon && (
        <span aria-hidden="true" className={`${size === 'sm' ? 'mb-2' : 'mb-3'} text-slate-500`}>{icon}</span>
      )}
      <p className={`font-medium text-slate-300 ${size === 'sm' ? 'text-sm' : 'text-base'}`}>{title}</p>
      {hint && <p className="mt-1 max-w-prose text-sm text-slate-400">{hint}</p>}
      {action && <div className={size === 'sm' ? 'mt-3' : 'mt-4'}>{action}</div>}
    </div>
  )
}

export { EmptyState }
