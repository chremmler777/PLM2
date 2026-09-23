import { describe, it, expect } from 'vitest'
import { comparePartNumbers, labelledNumbers, shortName, stripProjectCode } from './partDisplay'

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

describe('shortName', () => {
  it('drops the customer number and the project code the row already shows', () => {
    expect(shortName('206.882.251 Handle LH', '1994', '206.882.251')).toBe('Handle LH')
    expect(shortName('1994 206.882.251 Cover', '1994', '206.882.251')).toBe('Cover')
    expect(shortName('Handle 206.882.251 LH', '1994', '206.882.251')).toBe('Handle LH')
    expect(shortName('1994 TOOL Handle', '1994', null)).toBe('TOOL Handle')
  })
  it('keeps the full name when stripping would leave nothing', () => {
    expect(shortName('206.882.251', '1994', '206.882.251')).toBe('206.882.251')
  })
  it('does not cut a number that only shares a prefix', () => {
    expect(shortName('206.882.2519 Special', null, '206.882.251')).toBe('206.882.2519 Special')
  })
})

describe('labelledNumbers', () => {
  it('lists KTX, Tier 1 and OEM in that order and leaves missing ones out', () => {
    expect(labelledNumbers({ part_number: '20-1994-005-0', tier1_part_number: 'S00H54-110', customer_part_number: '206.887.233' })
      .map((n) => `${n.label} ${n.value}`)).toEqual(['KTX 20-1994-005-0', 'Tier 1 S00H54-110', 'OEM 206.887.233'])
    expect(labelledNumbers({ part_number: '199401', tier1_part_number: null }).map((n) => n.key)).toEqual(['ktx'])
  })
})
