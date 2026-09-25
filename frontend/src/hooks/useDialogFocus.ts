import { useEffect, useRef, type RefObject } from 'react'

const FOCUSABLE = 'a[href], button:not([disabled]), textarea:not([disabled]), input:not([disabled]), '
  + 'select:not([disabled]), [tabindex]:not([tabindex="-1"])'

/**
 * A modal's keyboard contract: focus moves into the dialog when it opens
 * (the `[data-autofocus]` element, else the first focusable one), Tab and
 * Shift+Tab stay inside it, Escape calls `onClose`, and focus goes back to
 * where it was when the dialog closes.
 */
export function useDialogFocus(ref: RefObject<HTMLElement | null>, open: boolean, onClose: () => void) {
  // Callers pass inline arrows: keep the latest without re-running the effect
  // (a re-run would bounce focus out of the field being typed in).
  const closeRef = useRef(onClose)
  useEffect(() => { closeRef.current = onClose })
  useEffect(() => {
    if (!open) return
    const root = ref.current
    if (!root) return
    const before = document.activeElement as HTMLElement | null
    const items = () => Array.from(root.querySelectorAll<HTMLElement>(FOCUSABLE))
    if (!root.contains(document.activeElement)) {
      const first = root.querySelector<HTMLElement>('[data-autofocus]') ?? items()[0] ?? root
      first.focus()
    }
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') { e.stopPropagation(); closeRef.current(); return }
      if (e.key !== 'Tab') return
      const list = items()
      if (list.length === 0) { e.preventDefault(); return }
      const first = list[0]
      const last = list[list.length - 1]
      const at = document.activeElement
      // Focus in a popover the dialog owns (a portal, e.g. a calendar) moves
      // on its own terms.
      if (at && at !== document.body && !root.contains(at)) return
      if (e.shiftKey && (at === first || at === document.body)) { e.preventDefault(); last.focus() }
      else if (!e.shiftKey && (at === last || at === document.body)) { e.preventDefault(); first.focus() }
    }
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('keydown', onKey)
      if (before && document.contains(before)) before.focus()
    }
  }, [ref, open])
}
