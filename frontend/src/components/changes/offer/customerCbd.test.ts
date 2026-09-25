import { describe, it, expect } from 'vitest'
import { customerCbd, r2, spreadCbd } from './customerCbd'
import type { OfferData } from '../../../types/changeOffer'

describe('customerCbd rounds like the PDF (Python round)', () => {
  it('rounds ties to even on the exact binary value', () => {
    expect(r2(0.125)).toBe(0.12)
    expect(r2(0.375)).toBe(0.38)
    expect(r2(1.125)).toBe(1.12)
    expect(r2(2.675)).toBe(2.67) // stored as 2.67499...
    expect(r2(1.005)).toBe(1) // stored as 1.00499...
    expect(r2(-0.125)).toBe(-0.12)
    expect(r2(12345.675)).toBe(12345.67) // stored as 12345.67499...
    expect(r2(3)).toBe(3)
    expect(r2(0.1 + 0.2)).toBe(0.3)
    // Past 2^53 cents: one decimal parse, as Python's round (values from CPython).
    expect(r2(1e14 + 0.03125)).toBe(100000000000000.03)
    expect(r2(-(1e14 + 0.03125))).toBe(-100000000000000.03)
    expect(r2(1e14 + 0.09375)).toBe(100000000000000.1)
    expect(r2(1e14 + 0.109375)).toBe(100000000000000.11)
    expect(r2(1e14 + 0.125)).toBe(100000000000000.12) // exact tie, to even
    expect(r2(1e14 + 0.375)).toBe(100000000000000.38) // exact tie, to even
  })

  it('spreads a hidden amount to the same cents as offer_pdf.spread_cbd', () => {
    // Python: [('A', 1.12), ('B', 1.13)]
    expect(spreadCbd([{ label: 'A', amount: 1 }, { label: 'B', amount: 1 }], 0.25))
      .toEqual([{ label: 'A', amount: 1.12 }, { label: 'B', amount: 1.13 }])
  })

  it('reads a null show or include as false, like Python .get(k, True) with None', () => {
    const data = {
      cost_lines: [
        { key: 'a', label: 'A', category: 'internal', amount: 100, include: true, customer_category: 'Engineering' },
        { key: 'b', label: 'B', category: 'internal', amount: 50, include: null as unknown as boolean, customer_category: 'Tooling' },
      ],
    } as OfferData
    const rows = customerCbd(data, {
      total_one_time: 110,
      factors: [{ key: 'margin', label: 'Margin', amount: 10, show: null as unknown as boolean }],
      risks_total: 0, scrap: 0,
    })
    // B is not included; the margin with show: null is hidden and folded in.
    expect(rows).toEqual([{ label: 'Engineering', amount: 110 }])
  })
})
