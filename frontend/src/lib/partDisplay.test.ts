import { describe, it, expect } from 'vitest'
import { comparePartNumbers, stripProjectCode } from './partDisplay'

describe('comparePartNumbers', () => {
  it('orders by the numeric suffix, so -10 comes after -9', () => {
    const nums = ['1994-10', '1994-1', '1994-2', '1994-9', '1994-100']
    expect([...nums].sort(comparePartNumbers)).toEqual(['1994-1', '1994-2', '1994-9', '1994-10', '1994-100'])
  })
  it('keeps a tool before its articles and falls back to text order', () => {
    expect(['20-3450', '3451', '10-3450', '3450'].sort(comparePartNumbers)).toEqual(['3450', '10-3450', '20-3450', '3451'])
    expect(comparePartNumbers('3450', '10-3450')).toBeLessThan(0)
    expect(comparePartNumbers('A', 'B')).toBeLessThan(0)
  })
})

describe('stripProjectCode', () => {
  it('drops a leading project code from the name, whatever the separator', () => {
    expect(stripProjectCode('1994 TOOL Handle', '1994')).toBe('TOOL Handle')
    expect(stripProjectCode('1994 - TOOL Handle', '1994')).toBe('TOOL Handle')
    expect(stripProjectCode('1994-TOOL Handle', '1994')).toBe('TOOL Handle')
  })
  it('leaves other names alone', () => {
    expect(stripProjectCode('19940 Cover', '1994')).toBe('19940 Cover')
    expect(stripProjectCode('Cover 1994', '1994')).toBe('Cover 1994')
    expect(stripProjectCode('1994', '1994')).toBe('1994')
    expect(stripProjectCode('TOOL Handle', undefined)).toBe('TOOL Handle')
  })
})
