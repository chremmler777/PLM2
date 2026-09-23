import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { renderHook } from '@testing-library/react'
import { FakeBroadcastChannel } from '../testing/fakeBroadcastChannel'
import { selectionChannelName, selectionChannelSupported, useSelectionChannel, type SelectionMessage } from './useSelectionChannel'

function peer(name = 'plm2-project-2') {
  const got: unknown[] = []
  const channel = new FakeBroadcastChannel(name)
  channel.onmessage = (e) => { got.push(e.data) }
  return { channel, got }
}

describe('useSelectionChannel', () => {
  beforeEach(() => {
    FakeBroadcastChannel.reset()
    vi.stubGlobal('BroadcastChannel', FakeBroadcastChannel)
  })
  afterEach(() => { vi.unstubAllGlobals() })

  it('names the channel after the project', () => {
    expect(selectionChannelName(2)).toBe('plm2-project-2')
  })

  it('delivers messages of its own project only', () => {
    const got: SelectionMessage[] = []
    renderHook(() => useSelectionChannel(2, (m) => { got.push(m) }))
    peer('plm2-project-2').channel.postMessage({ type: 'hello' })
    peer('plm2-project-3').channel.postMessage({ type: 'bye' })
    expect(got).toEqual([{ type: 'hello' }])
  })

  it('posts to the other windows of the project', () => {
    const p = peer()
    const { result } = renderHook(() => useSelectionChannel(2, () => {}))
    result.current({ type: 'select', partId: 5, revisionId: 9 })
    expect(p.got).toEqual([{ type: 'select', partId: 5, revisionId: 9 }])
  })

  it('always calls the latest handler', () => {
    const first = vi.fn()
    const second = vi.fn()
    const { rerender } = renderHook(({ h }) => useSelectionChannel(2, h), { initialProps: { h: first } })
    rerender({ h: second })
    peer().channel.postMessage({ type: 'ping' })
    expect(first).not.toHaveBeenCalled()
    expect(second).toHaveBeenCalledWith({ type: 'ping' })
  })

  it('says goodbye on pagehide and on unmount', () => {
    const p = peer()
    const { unmount } = renderHook(() => useSelectionChannel(2, () => {}, { type: 'bye' }))
    window.dispatchEvent(new Event('pagehide'))
    unmount()
    expect(p.got).toEqual([{ type: 'bye' }, { type: 'bye' }])
  })

  it('is a harmless no-op without BroadcastChannel', () => {
    vi.stubGlobal('BroadcastChannel', undefined)
    expect(selectionChannelSupported()).toBe(false)
    const { result } = renderHook(() => useSelectionChannel(2, () => {}))
    expect(() => result.current({ type: 'ping' })).not.toThrow()
  })
})
