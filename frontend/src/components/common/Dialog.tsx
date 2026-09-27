/**
 * Dialog: the one modal in the app, on the native <dialog> element.
 *
 * - `showModal()` puts it in the top layer and makes the page behind inert.
 * - Escape (and a click on the backdrop, unless turned off) asks to close
 *   through `onClose`; the parent owns `open`.
 * - Tab and Shift+Tab stay inside the dialog.
 * - Focus goes to `initialFocus`, else the first `[data-autofocus]` element,
 *   else the first focusable one; on close it returns to what had it before.
 *   (React's `autoFocus` sets no attribute and fires before the dialog is
 *   shown, so it does not count here.)
 * - `busy` blocks Escape and backdrop close while a request is in flight.
 *   If the browser closes the dialog anyway (a close watcher skipping the
 *   cancel event, `form method="dialog"`), it is reopened while busy and
 *   reported through `onClose` otherwise. When busy disables the focused
 *   control, focus moves to the panel so it never leaves the dialog.
 *
 * Renders nothing while closed, so state inside resets on every open.
 */
import {
  useEffect, useId, useLayoutEffect, useRef,
  type KeyboardEvent as ReactKeyboardEvent, type MouseEvent as ReactMouseEvent,
  type ReactNode, type RefObject,
} from 'react'
import { X } from 'lucide-react'
import { btnIcon } from './buttonStyles'

export type DialogSize = 'sm' | 'md' | 'lg' | 'xl'

export interface DialogProps {
  open: boolean
  /** Called for Escape, backdrop click and the close button. The parent sets `open` to false. */
  onClose: () => void
  /** Visible heading; also the dialog's accessible name. */
  title: ReactNode
  /** One or two lines under the title; becomes the accessible description. */
  description?: ReactNode
  children?: ReactNode
  /** Action row, right-aligned (primary action last). */
  footer?: ReactNode
  size?: DialogSize
  /** Element to focus on open. */
  initialFocus?: RefObject<HTMLElement>
  /** While true, Escape, backdrop and the close button do nothing. */
  busy?: boolean
  /** Close on a click outside the panel. Default true; turn off for forms with typed input. */
  closeOnBackdrop?: boolean
  /** Show the X button in the header. Default true. */
  showClose?: boolean
  /** `alertdialog` for confirmations that interrupt. */
  role?: 'dialog' | 'alertdialog'
  className?: string
  'data-testid'?: string
}

const WIDTH: Record<DialogSize, string> = {
  sm: 'max-w-sm',
  md: 'max-w-md',
  lg: 'max-w-2xl',
  xl: 'max-w-4xl',
}

const FOCUSABLE =
  'a[href], area[href], button:not([disabled]), input:not([disabled]):not([type="hidden"]), ' +
  'select:not([disabled]), textarea:not([disabled]), iframe, summary, [contenteditable="true"], ' +
  '[tabindex]:not([tabindex="-1"])'

function focusables(root: HTMLElement): HTMLElement[] {
  return Array.from(root.querySelectorAll<HTMLElement>(FOCUSABLE)).filter(
    (el) => !el.hasAttribute('inert') && el.getAttribute('aria-hidden') !== 'true',
  )
}

export default function Dialog(props: DialogProps) {
  if (!props.open) return null
  return <OpenDialog {...props} />
}

export { Dialog }

function OpenDialog({
  onClose, title, description, children, footer, size = 'md', initialFocus, busy = false,
  closeOnBackdrop = true, showClose = true, role = 'dialog', className = '', 'data-testid': testId,
}: DialogProps) {
  const ref = useRef<HTMLDialogElement>(null)
  const panelRef = useRef<HTMLDivElement>(null)
  // False once our own cleanup closes the element, so that close is not reported.
  const alive = useRef(true)
  const titleId = useId()
  const descId = useId()
  // Latest values for the native listeners without re-running the open effect.
  const latest = useRef({ onClose, busy })
  latest.current = { onClose, busy }

  useLayoutEffect(() => {
    const el = ref.current
    if (!el) return
    const previous = document.activeElement instanceof HTMLElement ? document.activeElement : null
    if (typeof el.showModal === 'function') {
      if (!el.open) el.showModal()
    } else {
      // jsdom and very old browsers: no top layer, but keep the semantics.
      el.setAttribute('open', '')
    }
    const alreadyInside = document.activeElement instanceof HTMLElement && el.contains(document.activeElement)
      && !document.activeElement.hasAttribute('data-dialog-close')
    const target = alreadyInside ? null :
      initialFocus?.current ??
      el.querySelector<HTMLElement>('[data-autofocus]') ??
      focusables(el).find((f) => !f.hasAttribute('data-dialog-close')) ??
      null
    target?.focus()
    alive.current = true
    return () => {
      alive.current = false
      if (typeof el.close === 'function' && el.open) el.close()
      if (previous && previous.isConnected) previous.focus({ preventScroll: true })
    }
    // Only on open/close; focus targets are read once.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // The browser's own cancel (Escape, Android back, close watchers).
  useEffect(() => {
    const el = ref.current
    if (!el) return
    const onCancel = (e: Event) => {
      e.preventDefault()
      if (!latest.current.busy) latest.current.onClose()
    }
    // The element closed without going through us. Reopen it while busy,
    // otherwise tell the parent so `open` matches what is on screen.
    const onNativeClose = () => {
      // `open` again: a close we queued ourselves (StrictMode re-run) that is stale now.
      if (!alive.current || !el.isConnected || el.open) return
      if (latest.current.busy) {
        if (!el.open && typeof el.showModal === 'function') el.showModal()
        return
      }
      latest.current.onClose()
    }
    el.addEventListener('cancel', onCancel)
    el.addEventListener('close', onNativeClose)
    return () => {
      el.removeEventListener('cancel', onCancel)
      el.removeEventListener('close', onNativeClose)
    }
  }, [])

  // Busy can disable the control that had focus, which drops focus to <body>
  // (or leaves it on a dead button). Park it on the panel instead.
  useEffect(() => {
    const el = ref.current
    if (!busy || !el) return
    const active = document.activeElement
    const lost = !(active instanceof HTMLElement) || !el.contains(active)
      || (active as HTMLButtonElement).disabled === true
    if (lost) panelRef.current?.focus({ preventScroll: true })
  }, [busy])

  const requestClose = () => { if (!busy) onClose() }

  const onKeyDown = (e: ReactKeyboardEvent<HTMLDialogElement>) => {
    if (e.key === 'Escape') {
      // Handled here so it also works where <dialog> has no cancel event,
      // and so an Escape inside a nested widget does not close two layers.
      e.preventDefault()
      e.stopPropagation()
      requestClose()
      return
    }
    if (e.key !== 'Tab' || !ref.current) return
    const list = focusables(ref.current)
    if (list.length === 0) { e.preventDefault(); return }
    const first = list[0]
    const last = list[list.length - 1]
    const active = document.activeElement
    const atStart = active === first || active === panelRef.current
    if (e.shiftKey && (atStart || !ref.current.contains(active))) {
      e.preventDefault(); last.focus()
    } else if (!e.shiftKey && (active === last || !ref.current.contains(active))) {
      e.preventDefault(); first.focus()
    }
  }

  // The dialog box is exactly the panel, so a click whose target is the
  // <dialog> itself landed on the ::backdrop.
  const onMouseDown = (e: ReactMouseEvent<HTMLDialogElement>) => {
    if (closeOnBackdrop && e.target === e.currentTarget) requestClose()
  }

  return (
    <dialog
      ref={ref}
      role={role === 'alertdialog' ? 'alertdialog' : undefined}
      aria-modal="true"
      aria-labelledby={titleId}
      aria-describedby={description ? descId : undefined}
      aria-busy={busy || undefined}
      data-testid={testId}
      onKeyDown={onKeyDown}
      onMouseDown={onMouseDown}
      className={`m-auto w-[calc(100vw-2rem)] ${WIDTH[size]} max-h-[calc(100dvh-2rem)] overflow-visible border-0 bg-transparent p-0 text-left text-sm font-normal normal-case tracking-normal whitespace-normal break-words text-slate-100 backdrop:bg-slate-950/70 open:flex motion-safe:animate-dialog-in ${className}`}
    >
      <div ref={panelRef} tabIndex={-1} className="flex max-h-[calc(100dvh-2rem)] w-full flex-col rounded-xl border border-slate-700 bg-slate-800 shadow-lift outline-none">
        <header className="flex items-start gap-3 px-5 pb-2 pt-4">
          <div className="min-w-0 flex-1">
            <h2 id={titleId} className="text-base font-semibold leading-snug text-slate-100">{title}</h2>
            {description && (
              <p id={descId} className="mt-1 text-sm leading-relaxed text-slate-400">{description}</p>
            )}
          </div>
          {showClose && (
            <button type="button" data-dialog-close aria-label="Close" onClick={requestClose}
              disabled={busy} className={`-mr-2 -mt-1 ${btnIcon}`}>
              <X aria-hidden="true" size={16} />
            </button>
          )}
        </header>
        {children != null && (
          <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-5 py-2 text-sm text-slate-300">
            {children}
          </div>
        )}
        {footer && (
          <footer className="flex flex-wrap items-center justify-end gap-2 px-5 pb-4 pt-3">
            {footer}
          </footer>
        )}
      </div>
    </dialog>
  )
}
