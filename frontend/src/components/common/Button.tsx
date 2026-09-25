import { forwardRef, type ButtonHTMLAttributes, type ReactNode } from 'react'
import { LoaderCircle } from 'lucide-react'
import { buttonClass, type ButtonSize, type ButtonVariant } from './buttonStyles'

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant
  size?: ButtonSize
  /** Shows a spinner in place of the icon and blocks clicks; the label stays so the width does not jump. */
  loading?: boolean
  /** Leading icon (a lucide icon element). Hidden from screen readers. */
  icon?: ReactNode
}

/**
 * The app button. Defaults to `type="button"` and the secondary look;
 * `variant="primary"` for the one main action of a view, `"danger"` only
 * for destructive ones.
 */
const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = 'secondary', size = 'md', loading = false, icon, className = '', disabled, type = 'button', children, ...rest },
  ref,
) {
  const iconSize = size === 'sm' ? 14 : 16
  return (
    <button
      ref={ref}
      type={type}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      className={buttonClass(variant, size, className)}
      {...rest}
    >
      {loading ? (
        <LoaderCircle aria-hidden="true" size={iconSize} className="shrink-0 motion-safe:animate-spin" />
      ) : icon ? (
        <span aria-hidden="true" className="inline-flex shrink-0">{icon}</span>
      ) : null}
      {children}
    </button>
  )
})

export default Button
export { Button }
