import { describe, it, expect } from 'vitest'
import { projectLabel } from './project'

describe('projectLabel', () => {
  it('puts the number first', () => {
    expect(projectLabel('1864', 'VW426 Atlas')).toBe('1864 · VW426 Atlas')
  })

  it('copes with either half missing', () => {
    expect(projectLabel('1864', null)).toBe('1864')
    expect(projectLabel(null, 'VW426 Atlas')).toBe('VW426 Atlas')
    expect(projectLabel(null, null)).toBeNull()
  })
})
