import { describe, it, expect, afterEach } from 'vitest'
import { render, screen, cleanup } from '@testing-library/react'
import RevisionLabel from './RevisionLabel'

describe('RevisionLabel', () => {
  afterEach(cleanup)

  it('prints our E level bold and the customer index in normal weight', () => {
    render(<RevisionLabel name="E1" index="001" testId="r" />)
    const label = screen.getByTestId('r')
    expect(label.textContent).toBe('E1 · 001')
    expect(screen.getByText('E1').className).toContain('font-bold')
    expect(screen.getByText(/001/).className).toContain('font-normal')
  })

  it('prints the E level alone without an index, and nothing without a name', () => {
    render(<RevisionLabel name="E2" index="  " testId="a" />)
    expect(screen.getByTestId('a').textContent).toBe('E2')
    cleanup()
    const { container } = render(<RevisionLabel name={null} index="B" />)
    expect(container.textContent).toBe('')
  })
})
