/**
 * The single entry point to starting a change. Every surface that offers it goes
 * through here, so the permission rule is stated once: unauthorized callers see
 * the button greyed with the reason rather than a 403 after filling the form.
 */
import { useCanStartChange } from '../../hooks/queries/useCanStartChange'
import { t } from '../../i18n/cmLabels'
import { btnPrimary } from '../common/buttonStyles'

export default function StartChangeButton({ onClick, label, className }: {
  onClick: () => void
  label: string
  className?: string
}) {
  const allowed = useCanStartChange()
  return (
    <button
      type="button"
      data-testid="start-change"
      disabled={!allowed}
      title={allowed ? undefined : t('start.salesOnly')}
      onClick={() => { if (allowed) onClick() }}
      className={`${className ?? btnPrimary} disabled:opacity-50 disabled:cursor-not-allowed`}
    >
      {label}
    </button>
  )
}
