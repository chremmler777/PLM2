/**
 * ConfirmDialog: yes/no on top of <Dialog>.
 *
 * `onConfirm` may return a promise. While it runs the dialog stays open, the
 * confirm button shows a spinner and Escape is blocked; if it rejects, the
 * backend's reason is shown inside the dialog and it stays open so the user
 * can retry or cancel. When it resolves (or returns nothing) the dialog
 * closes through `onClose`, unless `closeOnConfirm` is false (the parent
 * then closes it, for example from a mutation's onSuccess).
 *
 * The confirm button stays focusable while running (aria-disabled, clicks
 * ignored) so focus never drops out of the dialog. A confirm that settles
 * after the dialog was closed from outside, or reopened, is ignored.
 */
import { useEffect, useRef, useState, type ReactNode } from 'react'
import { CircleAlert, LoaderCircle } from 'lucide-react'
import Dialog from './Dialog'
import Button from './Button'
import { apiErrorMessage } from '../../lib/apiError'

export interface ConfirmDialogProps {
  open: boolean
  title: string
  body?: ReactNode
  /** The verb for the step ("Discard draft", "Send offer"), never just "OK". */
  confirmLabel?: string
  cancelLabel?: string
  /** Red confirm button; Cancel gets the initial focus. */
  danger?: boolean
  /** External in-flight flag (for example a mutation's isPending). */
  pending?: boolean
  onConfirm: () => unknown | Promise<unknown>
  onClose: () => void
  /** Close after a successful confirm. Default true. */
  closeOnConfirm?: boolean
  /** Shown when the failure carries no backend reason. */
  errorFallback?: string
  'data-testid'?: string
}

export default function ConfirmDialog({
  open, title, body, confirmLabel = 'Confirm', cancelLabel = 'Cancel', danger = false, pending = false,
  onConfirm, onClose, closeOnConfirm = true, errorFallback = 'That did not work. Try again.',
  'data-testid': testId,
}: ConfirmDialogProps) {
  const [running, setRunning] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const cancelRef = useRef<HTMLButtonElement>(null)
  const okRef = useRef<HTMLButtonElement>(null)
  const busy = pending || running
  // Bumped on every open/close and every confirm; a result whose token is
  // stale belongs to an earlier open and is dropped.
  const runToken = useRef(0)
  const openRef = useRef(open)
  openRef.current = open
  // After a failure put focus on the safe choice (Cancel when danger).
  useEffect(() => { if (error) (danger ? cancelRef : okRef).current?.focus() }, [error, danger])
  // A dialog closed from outside starts clean next time.
  useEffect(() => {
    runToken.current += 1
    if (!open) { setError(null); setRunning(false) }
  }, [open])
  // A string body is the dialog's accessible description; other nodes go in the body.
  const textBody = typeof body === 'string' && body.trim() ? body : undefined
  const hasBody = !textBody && body != null && body !== ''

  const close = () => { setError(null); onClose() }

  const confirm = async () => {
    if (busy) return
    const token = ++runToken.current
    const current = () => token === runToken.current && openRef.current
    setError(null)
    let result: unknown
    try {
      result = onConfirm()
      if (result && typeof (result as Promise<unknown>).then === 'function') {
        setRunning(true)
        await result
      }
    } catch (e) {
      if (!current()) return
      setRunning(false)
      setError(apiErrorMessage(e, errorFallback))
      return
    }
    if (!current()) return
    setRunning(false)
    if (closeOnConfirm) close()
  }

  return (
    <Dialog open={open} onClose={close} title={title} description={textBody} size="sm" busy={busy}
      role="alertdialog" showClose={false} initialFocus={danger ? cancelRef : okRef}
      data-testid={testId}
      footer={(
        <>
          <Button ref={cancelRef} onClick={close} disabled={busy}>{cancelLabel}</Button>
          <Button ref={okRef} variant={danger ? 'danger' : 'primary'}
            icon={busy ? <LoaderCircle size={16} className="motion-safe:animate-spin" /> : undefined}
            aria-disabled={busy || undefined} aria-busy={busy || undefined}
            onClick={() => { void confirm() }} data-testid="confirm-ok">
            {confirmLabel}
          </Button>
        </>
      )}
    >
      {hasBody || error ? (
        <>
          {hasBody && body}
          {error && (
            <p role="alert" className={`${hasBody ? 'mt-3 ' : ''}flex items-start gap-2 rounded-lg border border-red-500/40 bg-red-500/10 px-3 py-2 text-sm text-red-200`}>
              <CircleAlert aria-hidden="true" size={16} className="mt-0.5 shrink-0 text-red-300" />
              <span>{error}</span>
            </p>
          )}
        </>
      ) : null}
    </Dialog>
  )
}

export { ConfirmDialog }
