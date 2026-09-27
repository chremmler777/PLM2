import { describe, it, expect } from 'vitest'
import { diffLabel, diffValue, parseNum } from './offerFormat'
import {
  formatDate, formatDateTime, formatMoney, parseNumberInput, readNumberInput,
} from '../../../lib/format'

describe('parseNum (en-US input: dot decimals, comma thousands groups only)', () => {
  it.each([
    ['1.234', null], // looks like German thousands: ambiguous, refused
    ['12,500', 12500],
    ['1,234,567.5', 1234567.5],
    ['1,234.50', 1234.5],
    ['12,345,678.9', 12345678.9],
    ['-2,000', -2000],
    ['1.5', 1.5],
    ['0.125', 0.125],
    ['-0.125', -0.125],
    ['1.2345', 1.2345],
    ['12500', 12500],
    ['1 234.50', 1234.5],
    ['.5', 0.5],
    ['', null],
    ['abc', null],
    ['1.23.4', null],
    ["1'234", null],
    // A comma that is not a 3-digit thousands group is refused, never a decimal.
    ['12,5', null],
    ['1,5', null],
    ['1,', null],
    ['1,2345', null],
    ['0,500', null],
    ['12,34.5', null],
    ['1,2,3', null],
    ['1.234,5', null],
    ['1,234,5', null],
  ] as const)('%s -> %s', (input, out) => {
    expect(parseNum(input)).toBe(out)
  })

  it('reports a stray comma as ambiguous, other junk as invalid', () => {
    expect(readNumberInput('12,5')).toEqual({ value: null, error: 'ambiguous' })
    expect(readNumberInput('1.234,5')).toEqual({ value: null, error: 'ambiguous' })
    expect(readNumberInput('1.23.4')).toEqual({ value: null, error: 'invalid' })
    expect(readNumberInput(' ')).toEqual({ value: null, error: null })
    expect(parseNum).toBe(parseNumberInput)
  })
})

describe('offer diff wording', () => {
  it('names raw keys and formats values in their unit', () => {
    expect(diffLabel('total_one_time')).toBe('Total one-time')
    expect(diffLabel('Terms payment')).toBe('Payment terms')
    expect(diffLabel('Cost line Development')).toBe('Cost line Development')
    expect(diffValue('Total one-time', 12345.5, 'EUR')).toBe('12,345.50 EUR')
    expect(diffValue('Cost line Development', 900)).toBe('900.00 EUR')
    expect(diffValue('Piece price delta', 0.4125, 'EUR')).toBe('+0.4125 EUR')
    expect(diffValue('Scrap quantity', 12000)).toBe('12,000 pcs')
    expect(diffValue('Changeover', 'customer_pays_scrap')).toBe('Customer pays scrap')
    expect(diffValue('Timing weeks from order', 9)).toBe('9 weeks')
    expect(diffValue('Terms payment', null)).toBe('-')
    expect(diffValue('x', { mode: 'running_change', qty: 3 })).not.toContain('{')
  })
})

describe('lib/format', () => {
  it('formats dates as d MMM yyyy and money with the currency code', () => {
    expect(formatDate('2026-10-05')).toBe('5 Oct 2026')
    expect(formatDate('2026-10-05T12:00:00')).toBe('5 Oct 2026')
    expect(formatDate(null)).toBe('-')
    // Naive backend datetimes are UTC; tests run in Europe/Berlin (CEST, +2).
    expect(formatDateTime('2026-10-05T08:07:00')).toBe('5 Oct 2026, 10:07')
    expect(formatMoney(1234.5)).toBe('1,234.50 EUR')
    expect(formatMoney(10, 'USD')).toBe('10.00 USD')
    expect(formatMoney(undefined)).toBe('-')
  })
})
