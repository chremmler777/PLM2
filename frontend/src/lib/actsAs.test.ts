import { describe, it, expect, beforeEach } from 'vitest'
import { ACTS_AS_HEADER, getActsAsDepartmentId, setActsAsDepartmentId } from './actsAs'
import { attachActsAs } from '../api/client'

describe('acting-as header', () => {
  beforeEach(() => sessionStorage.clear())

  it('attaches the chosen department to every request', () => {
    setActsAsDepartmentId(4)
    expect(getActsAsDepartmentId()).toBe(4)
    const config = attachActsAs({
      headers: { 'Content-Type': 'application/json' } as Record<string, unknown>,
    })
    expect(config.headers[ACTS_AS_HEADER]).toBe('4')
    // The existing headers survive.
    expect(config.headers['Content-Type']).toBe('application/json')
  })

  it('sends nothing while the admin is themselves', () => {
    const config = attachActsAs({ headers: {} as Record<string, unknown> })
    expect(config.headers[ACTS_AS_HEADER]).toBeUndefined()
  })

  it('drops the header again once cleared', () => {
    setActsAsDepartmentId(4)
    setActsAsDepartmentId(null)
    expect(getActsAsDepartmentId()).toBeNull()
    expect(attachActsAs({ headers: {} as Record<string, unknown> }).headers[ACTS_AS_HEADER]).toBeUndefined()
  })

  it('ignores a junk stored value', () => {
    sessionStorage.setItem('plm2.actsAsDepartmentId', 'not-a-number')
    expect(getActsAsDepartmentId()).toBeNull()
  })
})
