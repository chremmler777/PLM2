import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { readStored, readStoredNumber, writeStored } from './safeStorage'

describe('safeStorage', () => {
  beforeEach(() => localStorage.clear())
  afterEach(() => { vi.restoreAllMocks() })

  it('round-trips a value', () => {
    writeStored('k', 'v')
    expect(readStored('k')).toBe('v')
  })

  it('returns null and swallows the error when reading throws', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw new Error('denied') })
    expect(readStored('k')).toBeNull()
  })

  it('swallows the error when writing throws', () => {
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('quota') })
    expect(() => writeStored('k', 'v')).not.toThrow()
  })

  it('reads and writes sessionStorage when asked, leaving localStorage alone', () => {
    sessionStorage.clear()
    writeStored('s', 'tab', 'session')
    expect(sessionStorage.getItem('s')).toBe('tab')
    expect(localStorage.getItem('s')).toBeNull()
    expect(readStored('s', 'session')).toBe('tab')
    expect(readStored('s')).toBeNull()
    sessionStorage.clear()
  })

  it('reads numbers with a fallback for garbage and clamps the range', () => {
    expect(readStoredNumber('w', 420, 280, 1600)).toBe(420)
    localStorage.setItem('w', 'abc')
    expect(readStoredNumber('w', 420, 280, 1600)).toBe(420)
    localStorage.setItem('w', '99999')
    expect(readStoredNumber('w', 420, 280, 1600)).toBe(1600)
    localStorage.setItem('w', '-5')
    expect(readStoredNumber('w', 420, 280, 1600)).toBe(280)
    localStorage.setItem('w', '512.6')
    expect(readStoredNumber('w', 420, 280, 1600)).toBe(513)
  })
})
