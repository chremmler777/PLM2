import { describe, it, expect } from 'vitest'
import { shownLetter, shownLetters } from './constants'

describe('shownLetter (audit P3-11: R / I only in the change flow)', () => {
  it('reads A as R and S, C, I as I', () => {
    expect(['R', 'A', 'S', 'C', 'I'].map(shownLetter)).toEqual(['R', 'R', 'I', 'I', 'I'])
  })
  it('folds letters to one chip each, R first', () => {
    expect(shownLetters(['C', 'R'])).toEqual(['R', 'I'])
    expect(shownLetters(['R', 'A'])).toEqual(['R'])
    expect(shownLetters([])).toEqual([])
  })
})
