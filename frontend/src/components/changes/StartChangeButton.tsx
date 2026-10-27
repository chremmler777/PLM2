/**
 * The single entry point to starting a change. Every surface that offers it goes
 * through here, so the permission rule is stated once: unauthorized callers see
 * the button greyed with the reason written under it (F19: a tooltip alone was
 * missed) rather than a 403 after filling the form.
 */
import { useCanStartChange } from '../../hooks/queries/useCanStartChange'
import { useIsReadOnlyViewer } from '../../hooks/queries/useEffectiveRole'
import { t } from '../../i18n/cmLabels'
import { btnPrimary } from '../common/buttonStyles'

export default function StartChangeButton({ onClick, label, className, block }: {
  onClick: () => void
  label: string
  className?: string
  /** In a menu: the button and its reason fill the row (left aligned). */
  block?: boolean
}) {
  const allowed = useCanStartChange()
  const viewer = useIsReadOnlyViewer()
  // A read-only user (no department) is told how to get one; everybody else
  // who may not start reads who does.
  const reason = viewer ? t('start.viewerOnly') : t('start.salesOnly')
  const button = (
    <button
      type="button"
      data-testid="start-change"
      disabled={!allowed}
      title={allowed ? undefined : reason}
      aria-describedby={allowed ? undefined : 'start-change-reason'}
      onClick={() => { if (allowed) onClick() }}
      className={`${className ?? btnPrimary} disabled:opacity-50 disabled:cursor-not-allowed`}
    >
      {label}
    </button>
  )
  // One tree whether allowed or not, so the button never remounts when the
  // permission answer arrives.
  return (
    <span className={block ? 'flex flex-col' : 'inline-flex flex-col items-end'}>
      {button}
      {!allowed && <span id="start-change-reason" data-testid="start-change-reason"
        className={`mt-1 max-w-xs text-xs text-slate-400 ${block ? 'px-2 text-left' : 'text-right'}`}>
        {reason}
      </span>}
    </span>
  )
}
