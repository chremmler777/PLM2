/**
 * Christoph 2026-11-09: the time chart full screen, as a popup over the page
 * (Sales plans the offer timing here). Same planner, same data: what is moved
 * in the popup is moved on the page. Esc or Close returns.
 */
import { useEffect, useRef, useState, type ReactNode } from 'react'
import { useMiddlePan } from '../../../hooks/useMiddlePan'
import { createPortal } from 'react-dom'
import { Maximize2, X } from 'lucide-react'
import { btnSm } from '../../common/buttonStyles'

export default function PlanFullscreen({ title, children, testId = 'plan-fullscreen' }: {
  title: string
  /** The planner rendered inside the popup. */
  children: ReactNode
  testId?: string
}) {
  const [open, setOpen] = useState(false)
  const box = useRef<HTMLDivElement>(null)
  useMiddlePan(box)
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false) }
    window.addEventListener('keydown', onKey)
    const prev = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => { window.removeEventListener('keydown', onKey); document.body.style.overflow = prev }
  }, [open])
  return (
    <>
      <button type="button" className={`${btnSm.secondary} inline-flex items-center gap-1`}
        data-testid={`${testId}-open`} onClick={() => setOpen(true)}>
        <Maximize2 aria-hidden="true" size={13} /> Full screen
      </button>
      {open && createPortal(
        <div role="dialog" aria-modal="true" aria-label={title} data-testid={testId}
          className="fixed inset-0 z-50 flex flex-col bg-slate-950/95 p-4">
          <div className="mb-3 flex items-center justify-between">
            <h2 className="text-base font-semibold text-slate-100">{title}</h2>
            <button type="button" className={`${btnSm.secondary} inline-flex items-center gap-1`}
              data-testid={`${testId}-close`} onClick={() => setOpen(false)}>
              <X aria-hidden="true" size={14} /> Close
            </button>
          </div>
          <div ref={box} className="min-h-0 flex-1 overflow-auto rounded-lg border border-slate-700 bg-slate-900 p-2"
            title="Hold the middle mouse button and drag to move the chart">
            {children}
          </div>
        </div>,
        document.body)}
    </>
  )
}
