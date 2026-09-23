import { describe, it, expect, afterEach, vi } from 'vitest'
import { windowOwnerId } from './windowOwner'

describe('windowOwnerId', () => {
  afterEach(() => { sessionStorage.clear(); vi.restoreAllMocks() })

  it('creates an id once and keeps it in sessionStorage for this tab', () => {
    sessionStorage.clear()
    const first = windowOwnerId()
    expect(first).toMatch(/^[a-z0-9-]{8,}$/)
    expect(sessionStorage.getItem('plm2.project.windowOwner')).toBe(first)
    expect(windowOwnerId()).toBe(first)
  })

  it('uses an id already stored for this tab', () => {
    sessionStorage.setItem('plm2.project.windowOwner', 'owner-x')
    expect(windowOwnerId()).toBe('owner-x')
  })

  it('stays stable within the page when storage throws', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw new Error('denied') })
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('denied') })
    const first = windowOwnerId()
    expect(first).toBeTruthy()
    expect(windowOwnerId()).toBe(first)
  })
})
