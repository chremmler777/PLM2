/**
 * Button class strings: the one source for button looks.
 *
 * Rules (UI polish plan, section 1):
 * - sky-700 is the only primary (white on sky-700 passes WCAG AA). One primary per view.
 * - emerald means "done", amber means "needs attention": neither is a button colour.
 * - red is only for destructive actions.
 *
 * Use the <Button> component where you can; use these strings for links
 * styled as buttons, or where a plain <button> is easier (tables, menus).
 */

export type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'danger'
export type ButtonSize = 'sm' | 'md'

/** Layout, focus ring, disabled and press feedback shared by every variant. */
export const btnBase =
  'inline-flex items-center justify-center gap-1.5 whitespace-nowrap rounded-lg font-medium ' +
  'transition-colors select-none ' +
  'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400 ' +
  'focus-visible:ring-offset-2 focus-visible:ring-offset-slate-900 ' +
  'disabled:cursor-not-allowed disabled:opacity-50 aria-disabled:cursor-not-allowed aria-disabled:opacity-50'

export const btnSizes: Record<ButtonSize, string> = {
  sm: 'h-7 px-2.5 text-xs',
  md: 'h-9 px-4 text-sm',
}

export const btnVariants: Record<ButtonVariant, string> = {
  primary: 'bg-sky-700 text-white font-semibold hover:bg-sky-600 disabled:hover:bg-sky-700',
  secondary:
    'border border-slate-600 bg-slate-800/40 text-slate-200 hover:border-slate-500 hover:bg-slate-700/60 ' +
    'disabled:hover:bg-slate-800/40',
  ghost: 'text-slate-300 hover:bg-slate-700/60 hover:text-slate-100 disabled:hover:bg-transparent',
  danger: 'bg-red-600 text-white font-semibold hover:bg-red-500 disabled:hover:bg-red-600',
}

/** Full class string for a variant and size, plus any extra classes. */
export function buttonClass(
  variant: ButtonVariant = 'secondary',
  size: ButtonSize = 'md',
  extra = '',
): string {
  return [btnBase, btnSizes[size], btnVariants[variant], extra].filter(Boolean).join(' ')
}

export const btnPrimary = buttonClass('primary')
export const btnSecondary = buttonClass('secondary')
export const btnGhost = buttonClass('ghost')
export const btnDanger = buttonClass('danger')

/** Small (h-7, text-xs) versions, for toolbars, table rows and cards: `btnSm.primary`. */
export const btnSm: Record<ButtonVariant, string> = {
  primary: buttonClass('primary', 'sm'),
  secondary: buttonClass('secondary', 'sm'),
  ghost: buttonClass('ghost', 'sm'),
  danger: buttonClass('danger', 'sm'),
}

/** Square icon-only button (give it an aria-label). */
export const btnIcon =
  'inline-flex h-8 w-8 items-center justify-center rounded-md text-slate-400 transition-colors ' +
  'hover:bg-slate-700/60 hover:text-slate-100 ' +
  'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400 ' +
  'disabled:cursor-not-allowed disabled:opacity-50'
