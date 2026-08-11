/**
 * Every blocking wait on a change, stated in one place for everyone who opens
 * it. Not a notification and not role-gated: whoever looks should see what the
 * change is waiting on, even when it is not their turn to act.
 */
import { t } from '../../i18n/cmLabels'
import type { WaitState } from '../../lib/waitStates'

export default function WaitBanner({ waits, onGo }: {
  waits: WaitState[]
  onGo?: (tab: string) => void
}) {
  if (waits.length === 0) return null
  return (
    <div data-testid="wait-banner"
      className="rounded-lg border border-amber-700/60 bg-amber-950/30 px-3 py-2 space-y-1">
      {waits.map((w) => (
        <p key={w.key} data-testid={`wait-${w.key}`}
          className="flex items-baseline gap-2 text-xs text-amber-200">
          <span aria-hidden className="flex-shrink-0">⏳</span>
          <span className="min-w-0">{w.text}</span>
          {w.tab && onGo && (
            <button type="button"
              className="ml-auto flex-shrink-0 text-amber-300/80 hover:text-amber-100 underline decoration-dotted underline-offset-2"
              onClick={() => onGo(w.tab!)}>
              {t('scoping.showDetails')}
            </button>
          )}
        </p>
      ))}
    </div>
  )
}
