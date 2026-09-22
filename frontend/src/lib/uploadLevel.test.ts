import { describe, it, expect } from 'vitest'
import { detectedIndex, defaultLevel, inferFileType, nextMajorName, nextProposalName, type ParsedRow } from './uploadLevel'

const row = (o: Partial<ParsedRow>): ParsedRow => ({
  filename: 'f', customer_part_number: null, variant: null, kind: null, kind_label: null,
  model_type: null, customer_index: null, release: null, dated: null, ...o,
})

describe('detectedIndex', () => {
  it('returns the single index across files', () => {
    expect(detectedIndex([row({ customer_index: '003' }), row({ customer_index: '003' }), row({})]))
      .toEqual({ index: '003', mixed: false })
  })
  it('flags mixed indexes and returns none', () => {
    expect(detectedIndex([row({ customer_index: '003' }), row({ customer_index: '004' })]))
      .toEqual({ index: null, mixed: true })
  })
  it('handles nothing detected', () => {
    expect(detectedIndex([row({}), row({})]))
      .toEqual({ index: null, mixed: false })
  })
})

describe('defaultLevel', () => {
  it('attaches when nothing detected', () => expect(defaultLevel(null, '003')).toBe('attach'))
  it('attaches when detected equals current', () => expect(defaultLevel('003', '003')).toBe('attach'))
  it('offers a new major when detected differs', () => expect(defaultLevel('004', '003')).toBe('major'))
  it('offers a new major when current has no index but a file carries one', () => expect(defaultLevel('003', null)).toBe('major'))
})

describe('inferFileType', () => {
  it('maps extensions', () => {
    expect(inferFileType('a.CATPart')).toBe('cad')
    expect(inferFileType('a.stp')).toBe('cad')
    expect(inferFileType('a.pdf')).toBe('drawing')
    expect(inferFileType('a.dxf')).toBe('drawing')
    expect(inferFileType('a.png')).toBe('picture')
    expect(inferFileType('a.xlsx')).toBe('document')
  })
})

describe('next names', () => {
  it('next review and official majors', () => {
    expect(nextMajorName(['E1', 'E1.1', 'E2'], 'review')).toBe('E3')
    expect(nextMajorName(['E1', 'E2'], 'official')).toBe('1')
    expect(nextMajorName(['E1', '1', '1.1', '2'], 'official')).toBe('3')
    expect(nextMajorName([], 'review')).toBe('E1')
  })
  it('next proposal under a parent', () => {
    expect(nextProposalName(['E1', 'E1.1', 'E1.2'], 'E1')).toBe('E1.3')
    expect(nextProposalName(['E1'], 'E1')).toBe('E1.1')
    expect(nextProposalName(['1', '1.1'], '1')).toBe('1.2')
  })
})
