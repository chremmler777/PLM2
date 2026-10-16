import { describe, expect, it } from 'vitest'
import { refOk } from './evidence'

describe('refOk (cm_rules.reference_refusal)', () => {
  it('refuses empty words and one word without a number', () => {
    for (const v of ['', 'ok', 'n/a', 'approved', 'customer', 'ok ok', 'na na na', 'asdfg']) {
      expect(refOk(v)).toBe(false)
    }
  })
  it('accepts a number or a few words', () => {
    for (const v of ['MR-2231', 'mail 2026-10-12', 'drawing rev C', 'PPAP approved by customer']) {
      expect(refOk(v)).toBe(true)
    }
  })
})
