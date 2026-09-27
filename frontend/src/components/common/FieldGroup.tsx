/**
 * FieldGroup: a labelled group of controls (<fieldset> + <legend>).
 *
 * Use it instead of wrapping a radio group or several inputs in <label>:
 * a <label> names only its first control, so a radiogroup inside one gets
 * a garbled name and the group itself none. The legend names the group.
 */
import { useId, type ReactNode } from 'react'

export interface FieldGroupProps {
  legend: ReactNode
  /** One line under the controls; tied to the group with aria-describedby. */
  hint?: ReactNode
  children: ReactNode
  /** Hide the legend visually but keep it for screen readers. */
  legendHidden?: boolean
  disabled?: boolean
  className?: string
  'data-testid'?: string
}

/** Same look as the small field labels in forms (offer/ui Field), at AA contrast. */
const fieldLabelCls = 'mb-1 block text-[11px] text-slate-400'

export default function FieldGroup({
  legend, hint, children, legendHidden = false, disabled, className = '', 'data-testid': testId,
}: FieldGroupProps) {
  const hintId = useId()
  return (
    <fieldset disabled={disabled} aria-describedby={hint ? hintId : undefined}
      data-testid={testId} className={`m-0 min-w-0 border-0 p-0 ${className}`}>
      <legend className={legendHidden ? 'sr-only' : `${fieldLabelCls} p-0`}>{legend}</legend>
      {children}
      {hint && <p id={hintId} className="mt-1 text-[11px] text-slate-400">{hint}</p>}
    </fieldset>
  )
}

export { FieldGroup }
