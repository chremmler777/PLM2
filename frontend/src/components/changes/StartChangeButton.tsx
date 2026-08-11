/**
 * The single entry point to starting a change. Every surface that offers it goes
 * through here, so the permission rule is stated once: unauthorised callers see
 * the button greyed with the reason rather than a 403 after filling the form.
 */
import { useCanStartChange } from '../../hooks/queries/useCanStartChange'
import { t } from '../../i18n/cmLabels'

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
      className={`${className ?? 'px-4 py-2 rounded-lg bg-blue-600 text-white text-sm font-medium hover:bg-blue-700'} disabled:opacity-50 disabled:cursor-not-allowed`}
    >
      {label}
    </button>
  )
}
