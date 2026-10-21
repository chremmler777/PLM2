import { describe, it, expect } from 'vitest'
import { contentBounds, squareCrop } from './canvasCapture'

function img(w: number, h: number, bg: number[], box?: [number, number, number, number]) {
  const d = new Uint8ClampedArray(w * h * 4)
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
    const inBox = box && x >= box[0] && x <= box[2] && y >= box[1] && y <= box[3]
    d.set(inBox ? [200, 100, 50, 255] : [...bg, 255], (y * w + x) * 4)
  }
  return d
}

describe('contentBounds', () => {
  it('finds the part against the background', () => {
    expect(contentBounds(img(100, 50, [15, 23, 42], [40, 10, 59, 29]), 100, 50))
      .toEqual({ x0: 40, y0: 10, x1: 59, y1: 29 })
  })
  it('ignores tiny anti-aliasing differences from the background', () => {
    const d = img(20, 20, [15, 23, 42])
    d.set([18, 25, 44, 255], (5 * 20 + 5) * 4)
    expect(contentBounds(d, 20, 20)).toBeNull()
  })
  it('returns null for an empty frame', () => {
    expect(contentBounds(img(10, 10, [249, 250, 251]), 10, 10)).toBeNull()
  })
})

describe('squareCrop', () => {
  it('centres a square around the part with a margin', () => {
    expect(squareCrop({ x0: 40, y0: 10, x1: 59, y1: 29 }, 0.1))
      .toEqual({ x: 38, y: 8, side: 24 })
  })
  it('uses the long side of a flat part', () => {
    expect(squareCrop({ x0: 10, y0: 45, x1: 89, y1: 54 }, 0))
      .toEqual({ x: 10, y: 10, side: 80 })
  })
})
