/**
 * One department's workplace failing to render must not take the page with it:
 * the bucket shows what went wrong and a retry, every other bucket and the
 * cockpit keep working. (A checklist answer shape the form did not expect used
 * to black out the whole change.)
 */
import { Component, type ErrorInfo, type ReactNode } from 'react'
import { t } from '../../i18n/cmLabels'

interface Props {
  /** Names the bucket in the message and in the console. */
  name: string
  children: ReactNode
}

interface State { error: Error | null }

export default class BucketErrorBoundary extends Component<Props, State> {
  state: State = { error: null }

  static getDerivedStateFromError(error: Error): State {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error(`Assessment bucket "${this.props.name}" failed to render`, error, info.componentStack)
  }

  render() {
    if (!this.state.error) return this.props.children
    return (
      <div role="alert" data-testid="bucket-error"
        className="rounded-lg border border-red-800/60 bg-red-950/40 px-3 py-2 text-sm text-red-100">
        <p className="font-medium">{t('bucket.crashed').replace('{d}', this.props.name)}</p>
        <p className="mt-0.5 text-xs text-red-200/70">{t('bucket.crashedHint')}</p>
        <button type="button" data-testid="bucket-error-retry"
          onClick={() => this.setState({ error: null })}
          className="mt-2 rounded border border-red-700/70 px-2 py-0.5 text-xs text-red-100 hover:bg-red-900/50">
          {t('bucket.retry')}
        </button>
      </div>
    )
  }
}
