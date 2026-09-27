import { afterEach, describe, expect, it, vi } from 'vitest'
import { act, cleanup, render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { OpenChangeBridge, changeTimingHref, changeTimingPath, openChangeInOpener } from './openChange'

function Where() {
  const l = useLocation()
  return <p data-testid="where">{l.pathname + l.search}</p>
}

const post = (data: unknown, origin = window.location.origin) =>
  act(() => { window.dispatchEvent(new MessageEvent('message', { data, origin })) })

describe('Open change from a plan pop-out', () => {
  afterEach(() => { cleanup(); vi.useRealTimers(); vi.unstubAllGlobals() })

  it('the main window navigates through its router and answers', () => {
    render(<MemoryRouter initialEntries={['/changes/6?tab=overview']}>
      <OpenChangeBridge /><Routes><Route path="*" element={<Where />} /></Routes>
    </MemoryRouter>)
    const reply = vi.fn()
    act(() => {
      const e = new MessageEvent('message', { data: { type: 'plm2:open-change', nonce: 'n1', path: changeTimingPath(6) }, origin: window.location.origin })
      Object.defineProperty(e, 'source', { value: { postMessage: reply } })
      window.dispatchEvent(e)
    })
    expect(screen.getByTestId('where').textContent).toBe('/changes/6?tab=timing')
    expect(reply).toHaveBeenCalledWith({ type: 'plm2:open-change-ack', nonce: 'n1' }, window.location.origin)
    // Another origin or another message is ignored.
    post({ type: 'plm2:open-change', nonce: 'n2', path: '/changes/9?tab=timing' }, 'https://evil.example')
    post('changed')
    expect(screen.getByTestId('where').textContent).toBe('/changes/6?tab=timing')
  })

  it('the pop-out asks its opener and reloads it only when nobody answers', () => {
    vi.useFakeTimers()
    const opener = { closed: false, focus: vi.fn(), postMessage: vi.fn(), location: { href: 'x' } }
    vi.stubGlobal('opener', opener)
    expect(openChangeInOpener(6)).toBe(true)
    expect(opener.postMessage).toHaveBeenCalledWith(
      expect.objectContaining({ type: 'plm2:open-change', path: '/changes/6?tab=timing' }), window.location.origin)
    vi.advanceTimersByTime(500)
    expect(opener.location.href).toBe(changeTimingHref(6))

    // Answered: the opener is left to its router.
    opener.location.href = 'x'
    opener.postMessage.mockImplementation((m: { nonce: string }) => {
      window.dispatchEvent(new MessageEvent('message', { data: { type: 'plm2:open-change-ack', nonce: m.nonce }, origin: window.location.origin }))
    })
    expect(openChangeInOpener(6)).toBe(true)
    vi.advanceTimersByTime(500)
    expect(opener.location.href).toBe('x')
  })

  it('without an opener the plain link opens', () => {
    vi.stubGlobal('opener', null)
    expect(openChangeInOpener(6)).toBe(false)
  })
})
