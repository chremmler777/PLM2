import { describe, it, expect, afterEach } from 'vitest'
import { render, screen, cleanup } from '@testing-library/react'
import RevisionBadge, { revisionLabel } from './RevisionBadge'

describe('revisionLabel', () => {
  it('joins name and index with a middle dot', () => {
    expect(revisionLabel('E2', 'B')).toBe('E2 · B')
    expect(revisionLabel('E2', null)).toBe('E2')
    expect(revisionLabel('E2', '  ')).toBe('E2')
    expect(revisionLabel(null, 'B')).toBe('')
  })
})

describe('RevisionBadge', () => {
  afterEach(cleanup)
  it('renders the label, colours by phase, and says no data when there is none', () => {
    render(<RevisionBadge name="1" index="C" phase="official" testId="b1" />)
    const b = screen.getByTestId('b1')
    expect(b.textContent).toBe('1 · C')
    expect(b.className).toContain('amber')
    cleanup()
    render(<RevisionBadge name={null} testId="b2" />)
    expect(screen.getByTestId('b2').textContent).toBe('no data')
  })
})
