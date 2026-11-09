/**
 * Christoph 2026-11-09: hold the middle mouse button and drag to move a wide
 * chart (scrolls the element and any scrollable box inside it under the cursor).
 */
import { useEffect, type RefObject } from 'react'

const scrollableAt = (start: Element | null, root: HTMLElement): HTMLElement[] => {
  const out: HTMLElement[] = []
  for (let e = start as HTMLElement | null; e && root.contains(e); e = e.parentElement) {
    const s = getComputedStyle(e)
    if ((/(auto|scroll)/.test(s.overflowX) && e.scrollWidth > e.clientWidth)
      || (/(auto|scroll)/.test(s.overflowY) && e.scrollHeight > e.clientHeight)) out.push(e)
  }
  return out.length ? out : [root]
}

export function useMiddlePan(ref: RefObject<HTMLElement | null>) {
  useEffect(() => {
    const root = ref.current
    if (!root) return
    let boxes: HTMLElement[] = []
    let x = 0, y = 0
    const move = (e: MouseEvent) => {
      const dx = e.clientX - x, dy = e.clientY - y
      x = e.clientX; y = e.clientY
      // horizontal to the innermost box that scrolls sideways, vertical to the one that scrolls down
      const h = boxes.find((b) => b.scrollWidth > b.clientWidth)
      const v = boxes.find((b) => b.scrollHeight > b.clientHeight)
      if (h) h.scrollLeft -= dx
      if (v) v.scrollTop -= dy
      e.preventDefault()
    }
    const up = () => {
      root.style.cursor = ''
      window.removeEventListener('mousemove', move)
      window.removeEventListener('mouseup', up)
    }
    const down = (e: MouseEvent) => {
      if (e.button !== 1) return
      e.preventDefault()   // no autoscroll icon
      boxes = scrollableAt(e.target as Element, root)
      x = e.clientX; y = e.clientY
      root.style.cursor = 'grabbing'
      window.addEventListener('mousemove', move)
      window.addEventListener('mouseup', up)
    }
    root.addEventListener('mousedown', down)
    return () => { root.removeEventListener('mousedown', down); up() }
  }, [ref])
}
