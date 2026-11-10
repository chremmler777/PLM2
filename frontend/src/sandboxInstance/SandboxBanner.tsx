/**
 * PLM2 sandbox instance (Christoph 2026-11-10, backend app/sandbox.py): a
 * second PLM2 under /plm2-sandbox/ where Project Management and Sales try the
 * change Offer and Timing pages on their OWN copy of the data and tell us what
 * to change. Built only with VITE_SANDBOX=1; the live app never renders it.
 *
 * Shows: an orange frame around the window (never mistaken for live PLM2), a
 * bar with Feedback and "Reset my copy", the landing redirect from "/", and a
 * full-screen notice for people who are not let in.
 */
import { useEffect, useRef, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import client from '../api/client'

export const IS_SANDBOX_INSTANCE = import.meta.env.VITE_SANDBOX === '1'

type Info = { username: string; landing: string }

const btn =
  'rounded px-3 py-1 text-xs font-semibold transition-colors disabled:opacity-50'

export default function SandboxBanner() {
  const [info, setInfo] = useState<Info | null>(null)
  const [denied, setDenied] = useState<string | null>(null)
  const [open, setOpen] = useState(false)
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  const [note, setNote] = useState<string | null>(null)
  const location = useLocation()
  const navigate = useNavigate()

  useEffect(() => {
    client.get('/v1/sandbox/info')
      .then((r) => setInfo(r.data))
      .catch((e) => {
        const d = e?.response?.data
        if (e?.response?.status === 403) setDenied(d?.detail ?? 'No access to the sandbox')
      })
  }, [])

  // First load only: the bare sandbox address opens on the landing change
  // ("/" itself redirects to /dashboard before the info arrives).
  const landed = useRef(false)
  useEffect(() => {
    if (!info || landed.current) return
    landed.current = true
    if (location.pathname === '/' || location.pathname === '/dashboard') {
      navigate(info.landing, { replace: true })
    }
  }, [info, location.pathname, navigate])

  const tab = new URLSearchParams(location.search).get('tab')

  const send = async () => {
    if (!text.trim()) return
    setBusy(true)
    try {
      await client.post('/v1/sandbox/feedback', {
        text, page: location.pathname + location.search, tab,
      })
      setText('')
      setOpen(false)
      setNote('Thanks, your feedback is saved.')
      setTimeout(() => setNote(null), 4000)
    } catch {
      setNote('Feedback could not be saved, please try again.')
    } finally {
      setBusy(false)
    }
  }

  const reset = async () => {
    if (!window.confirm('Reset your sandbox copy? Everything you changed here goes back to the start. Your feedback stays.')) return
    setBusy(true)
    try {
      await client.post('/v1/sandbox/reset')
      window.location.assign(import.meta.env.BASE_URL.replace(/\/$/, '') + (info?.landing ?? '/'))
    } catch {
      setNote('Reset failed, please try again.')
      setBusy(false)
    }
  }

  if (denied) {
    return (
      <div className="fixed inset-0 z-[9999] flex items-center justify-center bg-gray-950 p-6 text-center">
        <div className="max-w-md space-y-3">
          <div className="text-lg font-semibold text-orange-400">PLM2 sandbox</div>
          <p className="text-sm text-gray-300">{denied}.</p>
          <a className="text-sm text-blue-400 underline" href="/plm2/">Go to PLM2</a>
        </div>
      </div>
    )
  }

  return (
    <>
      <div aria-hidden className="pointer-events-none fixed inset-0 z-[9998] border-4 border-orange-500" />
      <div
        role="region"
        aria-label="Sandbox"
        className="fixed bottom-3 left-1/2 z-[9999] flex -translate-x-1/2 items-center gap-3 rounded-lg bg-orange-500 px-4 py-2 text-sm text-black shadow-lg"
      >
        <span className="font-bold">SANDBOX</span>
        <span className="hidden sm:inline">Your own copy. Nothing here is real, no mails go out.</span>
        <button className={`${btn} bg-black text-white hover:bg-gray-800`} disabled={busy}
          onClick={() => setOpen(true)}>Feedback</button>
        <button className={`${btn} border border-black hover:opacity-80`} disabled={busy}
          style={{ background: '#fff7ed', color: '#000' }}
          onClick={reset}>Reset my copy</button>
      </div>
      {note && (
        <div className="fixed bottom-16 left-1/2 z-[9999] -translate-x-1/2 rounded bg-gray-900 px-3 py-2 text-sm text-white shadow">{note}</div>
      )}
      {open && (
        <div className="fixed inset-0 z-[10000] flex items-center justify-center bg-black/60 p-4"
          onClick={() => setOpen(false)}>
          <div role="dialog" aria-label="Sandbox feedback" className="w-full max-w-lg space-y-3 rounded-lg bg-gray-900 p-4 text-gray-100 shadow-xl"
            onClick={(e) => e.stopPropagation()}>
            <div className="font-semibold">What should change on this page?</div>
            <div className="text-xs text-gray-400">
              Page: {location.pathname}{tab ? ` (tab ${tab})` : ''}. Usability, what you need to see,
              what is confusing or missing. One point per note is easiest for us.
            </div>
            <textarea autoFocus aria-label="Your feedback" value={text} onChange={(e) => setText(e.target.value)} rows={6}
              maxLength={5000}
              className="w-full rounded border border-gray-700 bg-gray-950 p-2 text-sm text-gray-100 focus:border-orange-500 focus:outline-none" />
            <div className="flex justify-end gap-2">
              <button className={`${btn} bg-gray-700 text-white hover:bg-gray-600`} onClick={() => setOpen(false)}>Cancel</button>
              <button className={`${btn} bg-orange-500 text-black hover:bg-orange-400`} disabled={busy || !text.trim()}
                onClick={send}>Send feedback</button>
            </div>
          </div>
        </div>
      )}
    </>
  )
}
