import { describe, it, expect } from 'vitest'
import { diffLabel, diffValue, parseNum } from './offerFormat'
import { formatDate, formatDateTime, formatMoney } from '../../../lib/format'

describe('parseNum (German input)', () => {
  it.each([
    ['1.234', 1234],
    ['12.345.678', 12345678],
    ['1.234,5', 1234.5],
    ['1,5', 1.5],
    ['1.5', 1.5],
    ['1.23', 1.23],
    ['-2.000', -2000],
    ['1 234,50', 1234.5],
    ['1,', 1],
    ['', null],
    ['abc', null],
    ['1.23.4', null],
    ['1.23,4', null],
    ['1,2,3', null],
    ['0.125', 0.125],
    ['-0.125', -0.125],
    ['0.500', 0.5],
    ['1.2345', 1.2345],
    ['1.234,56', 1234.56],
    ['0.125,5', null],
  ] as const)('%s -> %s', (input, out) => {
    expect(parseNum(input)).toBe(out)
  })
})

describe('offer diff wording', () => {
  it('names raw keys and formats values in their unit', () => {
    expect(diffLabel('total_one_time')).toBe('Total one-time')
    expect(diffLabel('Terms payment')).toBe('Payment terms')
    expect(diffLabel('Cost line Development')).toBe('Cost line Development')
    expect(diffValue('Total one-time', 12345.5, 'EUR')).toBe('12.345,50 EUR')
    expect(diffValue('Cost line Development', 900)).toBe('900,00 EUR')
    expect(diffValue('Changeover', 'customer_pays_scrap')).toBe('Customer pays scrap')
    expect(diffValue('Timing weeks from order', 9)).toBe('9 weeks')
    expect(diffValue('Terms payment', null)).toBe('-')
    expect(diffValue('x', { mode: 'running_change', qty: 3 })).not.toContain('{')
  })
})

describe('lib/format', () => {
  it('formats dates as dd.mm.yyyy and money with the currency code', () => {
    expect(formatDate('2026-10-05')).toBe('05.10.2026')
    expect(formatDate('2026-10-05T12:00:00')).toBe('05.10.2026')
    expect(formatDate(null)).toBe('-')
    // Naive backend datetimes are UTC; tests run in Europe/Berlin (CEST, +2).
    expect(formatDateTime('2026-10-05T08:07:00')).toBe('05.10.2026 10:07')
    expect(formatMoney(1234.5)).toBe('1.234,50 EUR')
    expect(formatMoney(10, 'USD')).toBe('10,00 USD')
    expect(formatMoney(undefined)).toBe('-')
  })
})
