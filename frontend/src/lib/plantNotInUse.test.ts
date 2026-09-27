import { describe, it, expect } from 'vitest'
import { MEXICO_NOT_IN_USE_TEXT, plantNotInUse, plantsNotInUse } from './plantNotInUse'

describe('plantNotInUse (Mexico is not in use yet)', () => {
  it('knows Silao by its code, its location or its MXN local currency', () => {
    expect(plantNotInUse({ code: 'SIL' })?.label).toBe('Mexico (Silao)')
    expect(plantNotInUse({ code: 'sil' })?.label).toBe('Mexico (Silao)')
    expect(plantNotInUse({ location: 'MX' })?.label).toBe('Mexico (Silao)')
    expect(plantNotInUse({ local_currency: 'MXN' })?.label).toBe('Mexico (Silao)')
  })

  it('leaves the US plant and empty keys alone', () => {
    expect(plantNotInUse({ code: 'USA', location: 'US', local_currency: null })).toBeNull()
    expect(plantNotInUse({})).toBeNull()
    expect(plantNotInUse(null)).toBeNull()
  })

  it('lists each entry once however many plants match', () => {
    expect(plantsNotInUse([{ code: 'SIL' }, { local_currency: 'MXN' }, { code: 'USA' }])).toHaveLength(1)
    expect(plantsNotInUse([{ code: 'USA' }])).toHaveLength(0)
  })

  it('says it plainly, without dashes', () => {
    expect(MEXICO_NOT_IN_USE_TEXT).toBe('Mexico (Silao) is not in use yet. PLM runs for the US plant only for now; '
      + 'access for Mexico will be role based later.')
    expect(MEXICO_NOT_IN_USE_TEXT).not.toMatch(/[\u2013\u2014]/)
  })
})
