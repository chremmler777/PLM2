/**
 * "Open change" from a plan pop-out: the window that opened the pop-out
 * shows the change (its Timing tab) through its own router, without a
 * reload. The pop-out posts a message to its opener; a planner mounted in
 * the opener answers, navigates and acknowledges. Without an answer (the
 * opener shows another page, or no planner) the pop-out falls back to
 * loading the change in the opener.
 */
import { useEffect } from 'react'
import { useNavigate } from 'react-router-dom'

const OPEN = 'plm2:open-change'
const ACK = 'plm2:open-change-ack'

interface OpenMsg { type: typeof OPEN; nonce: string; path: string }
interface AckMsg { type: typeof ACK; nonce: string }

/** Router path of a change's Timing tab (inside the app's basename). */
export const changeTimingPath = (changeId: number) => `/changes/${changeId}?tab=timing`

/** Full URL of that path under the app's base, for plain links and reloads. */
export const changeTimingHref = (changeId: number) =>
  `${import.meta.env.BASE_URL ?? '/'}${changeTimingPath(changeId).slice(1)}`.replace(/\/{2,}/g, '/')

/** Several planners in one window hear the same message: one navigation. */
const handled = new Set<string>()

/** Mounted in the main window (by the planner): answers a pop-out's "Open change". */
export function OpenChangeBridge() {
  const navigate = useNavigate()
  useEffect(() => {
    const onMessage = (e: MessageEvent) => {
      if (e.origin !== window.location.origin) return
      const m = e.data as Partial<OpenMsg> | null
      if (!m || m.type !== OPEN || typeof m.nonce !== 'string' || typeof m.path !== 'string') return
      if (!m.path.startsWith('/changes/')) return
      const src = e.source as Window | null
      if (!handled.has(m.nonce)) {
        handled.add(m.nonce)
        navigate(m.path)
        try { window.focus() } catch { /* focus is the browser's call */ }
      }
      try { src?.postMessage({ type: ACK, nonce: m.nonce } satisfies AckMsg, window.location.origin) } catch { /* pop-out closed */ }
    }
    window.addEventListener('message', onMessage)
    return () => window.removeEventListener('message', onMessage)
  }, [navigate])
  return null
}

/**
 * Asks the opener to show the change. True when the click is handled here
 * (the caller then prevents the link's default); false when there is no
 * usable opener and the plain link should open.
 */
export function openChangeInOpener(changeId: number, waitMs = 400): boolean {
  const opener = window.opener as Window | null
  if (!opener || opener.closed) return false
  const nonce = `${Date.now()}-${Math.random().toString(36).slice(2)}`
  try { opener.focus() } catch { /* focus is the browser's call */ }
  let answered = false
  const onAck = (e: MessageEvent) => {
    const m = e.data as Partial<AckMsg> | null
    if (e.origin === window.location.origin && m?.type === ACK && m.nonce === nonce) answered = true
  }
  window.addEventListener('message', onAck)
  try {
    opener.postMessage({ type: OPEN, nonce, path: changeTimingPath(changeId) } satisfies OpenMsg, window.location.origin)
  } catch { /* fall through to the reload below */ }
  window.setTimeout(() => {
    window.removeEventListener('message', onAck)
    if (answered) return
    try {
      if (!opener.closed) opener.location.href = changeTimingHref(changeId)
    } catch { /* another origin: nothing more to do from here */ }
  }, waitMs)
  return true
}
