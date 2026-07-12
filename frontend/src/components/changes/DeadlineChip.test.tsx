import { describe, it, expect, afterEach } from 'vitest'
import { render, screen, cleanup } from '@testing-library/react'
import { DeadlineChip } from './DeadlineChip'

describe('DeadlineChip', () => {
  afterEach(cleanup)

  it('renders nothing without a date', () => {
    const { container } = render(<DeadlineChip date={null} state={null} />)
    expect(container.firstChild).toBeNull()
  })
  it('shows days left and at-risk styling', () => {
    const inTen = new Date(Date.now() + 10 * 864e5).toISOString()
    render(<DeadlineChip date={inTen} state="at_risk" />)
    expect(screen.getByText(/10\s?d/i)).toBeTruthy()
    expect(screen.getByTestId('deadline-chip').className).toContain('amber')
  })
  it('shows overdue in red', () => {
    const past = new Date(Date.now() - 3 * 864e5).toISOString()
    render(<DeadlineChip date={past} state="overdue" />)
    expect(screen.getByTestId('deadline-chip').className).toContain('red')
  })
  it('does not show a same-day end-of-day deadline as overdue-negative', () => {
    const today = new Date()
    const iso = `${today.toISOString().slice(0, 10)}T23:59:59Z`
    render(<DeadlineChip date={iso} state="on_track" />)
    const chip = screen.getByTestId('deadline-chip')
    expect(chip.textContent).not.toMatch(/over/)
  })
})
