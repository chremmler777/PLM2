import { describe, expect, it } from 'vitest'
import { absorbNoteProblem, saysWhat } from './overrideRules'

describe('Absorb note (A4-07, backend cm_rules.says_what)', () => {
  it('refuses 15 letters that name nothing', () => {
    expect(saysWhat('aaaaaaaaaaaaaaaaaaaaa')).toBe(false)
    expect(saysWhat('checked checked checked')).toBe(false)
    expect(absorbNoteProblem('goodwill', 'aaaaaaaaaaaaaaaaaaaaa')).not.toBeNull()
  })
  it('takes a sentence that names the amount or the part', () => {
    expect(saysWhat('Rework 300 EUR goodwill on program G45')).toBe(true)
    expect(absorbNoteProblem('goodwill', 'Small amount, goodwill on the program')).toBeNull()
  })
})
