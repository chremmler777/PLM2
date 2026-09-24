import { describe, it, expect, vi, afterEach } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import {
  clampZoom, COMPACT_BELOW, fitZoom, isCompact, stepZoom, useDfmZoom, ZOOM_KEY, ZOOM_MAX, ZOOM_MIN,
} from './dfmZoom'

describe('dfm zoom helpers', () => {
  it('clamps to 50..150 and steps by 10', () => {
    expect(ZOOM_MIN).toBe(50)
    expect(ZOOM_MAX).toBe(150)
    expect(clampZoom(20)).toBe(50)
    expect(clampZoom(400)).toBe(150)
    expect(stepZoom(100, 1)).toBe(110)
    expect(stepZoom(100, -1)).toBe(90)
    expect(stepZoom(150, 1)).toBe(150)
    expect(stepZoom(50, -1)).toBe(50)
    // an odd fit value snaps onto the step grid
    expect(stepZoom(87, 1)).toBe(90)
    expect(stepZoom(87, -1)).toBe(80)
  })

  it('fits the canvas to the container width', () => {
    expect(fitZoom(1000, 1000)).toBe(100)
    expect(fitZoom(836, 1000)).toBe(83)
    expect(fitZoom(0, 1000)).toBe(50)
    expect(fitZoom(4000, 1000)).toBe(150)
  })

  it('switches to compact cards below 75%', () => {
    expect(COMPACT_BELOW).toBe(75)
    expect(isCompact(70)).toBe(true)
    expect(isCompact(75)).toBe(false)
    expect(isCompact(100)).toBe(false)
  })
})

describe('useDfmZoom', () => {
  afterEach(() => { localStorage.clear(); vi.restoreAllMocks() })

  it('starts at 100%, remembers the zoom and reads it back', () => {
    const { result } = renderHook(() => useDfmZoom())
    expect(result.current.zoom).toBe(100)
    act(() => result.current.zoomBy(-1))
    act(() => result.current.zoomBy(-1))
    expect(result.current.zoom).toBe(80)
    expect(localStorage.getItem(ZOOM_KEY)).toBe('80')
    const again = renderHook(() => useDfmZoom())
    expect(again.result.current.zoom).toBe(80)
    act(() => again.result.current.setZoom(999))
    expect(again.result.current.zoom).toBe(150)
  })

  it('keeps working when storage throws', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw new Error('blocked') })
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('blocked') })
    const { result } = renderHook(() => useDfmZoom())
    expect(result.current.zoom).toBe(100)
    act(() => result.current.zoomBy(1))
    expect(result.current.zoom).toBe(110)
  })
})
