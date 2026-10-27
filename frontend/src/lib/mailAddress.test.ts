import { describe, it, expect } from 'vitest'
import { mailAddress } from './mailAddress'

describe('mailAddress', () => {
  it('adds the company domain to a bare username', () => {
    expect(mailAddress('jubei.hughes')).toBe('jubei.hughes@us.ktx.group')
  })
  it('is idempotent and leaves full addresses alone', () => {
    expect(mailAddress('karl@ktx.test')).toBe('karl@ktx.test')
    expect(mailAddress(mailAddress('jubei.hughes'))).toBe('jubei.hughes@us.ktx.group')
  })
  it('has no address for empty input', () => {
    expect(mailAddress(null)).toBeNull()
    expect(mailAddress('  ')).toBeNull()
  })
})
