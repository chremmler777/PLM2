import { describe, it, expect } from 'vitest'
import { retryUnlessNotFound } from './useWorksheet'

describe('retryUnlessNotFound', () => {
  it('gives up at once on 404 and retries other errors twice', () => {
    expect(retryUnlessNotFound(0, { response: { status: 404 } })).toBe(false)
    expect(retryUnlessNotFound(0, { response: { status: 500 } })).toBe(true)
    expect(retryUnlessNotFound(1, new Error('network'))).toBe(true)
    expect(retryUnlessNotFound(2, { response: { status: 500 } })).toBe(false)
  })
})
