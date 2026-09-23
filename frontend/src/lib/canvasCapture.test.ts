import { describe, it, expect } from 'vitest'
import { fitWithin } from './canvasCapture'

describe('fitWithin', () => {
  it('scales the long side down to the maximum and keeps the aspect', () => {
    expect(fitWithin(1200, 600, 400)).toEqual({ width: 400, height: 200 })
    expect(fitWithin(300, 900, 400)).toEqual({ width: 133, height: 400 })
  })
  it('never scales up', () => {
    expect(fitWithin(200, 100, 400)).toEqual({ width: 200, height: 100 })
  })
})
