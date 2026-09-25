import { describe, it, expect, afterEach } from 'vitest'
import { render, screen, cleanup } from '@testing-library/react'
import { DeadlineChip, deadlineText } from './DeadlineChip'
import { addDaysIso, formatDate, todayIso } from '../../lib/format'

describe('DeadlineChip', () => {
  afterEach(cleanup)

  it('renders nothing without a date', () => {
    const { container } = render(<DeadlineChip date={null} state={null} />)
    expect(container.firstChild).toBeNull()
  })
  it('renders nothing for a garbage date', () => {
    const { container } = render(<DeadlineChip date="not-a-date" state={null} />)
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
  it('counts a plain date in calendar days and titles it d MMM yyyy', () => {
    const tomorrow = addDaysIso(todayIso(), 1)
    render(<DeadlineChip date={tomorrow} state="on_track" />)
    const chip = screen.getByTestId('deadline-chip')
    expect(chip.textContent).toBe('in 1 d')
    expect(chip.getAttribute('title')).toBe(formatDate(tomorrow))
  })
  it('reads as a sentence for a named deadline', () => {
    render(<DeadlineChip date={addDaysIso(todayIso(), 5)} state="on_track" kind="release" />)
    expect(screen.getByTestId('deadline-chip').textContent).toBe('Release in 5 d')
  })
  it('names an overdue release deadline', () => {
    render(<DeadlineChip date={addDaysIso(todayIso(), -2)} state="overdue" kind="release" />)
    expect(screen.getByTestId('deadline-chip').textContent).toBe('Release 2 d overdue')
  })
  it('uses the same short words in lists: today, in n d, n d overdue', () => {
    expect(deadlineText(0)).toBe('today')
    expect(deadlineText(5)).toBe('in 5 d')
    expect(deadlineText(-2)).toBe('2 d overdue')
  })
  it('shows a clock icon, not a glyph, on the short chip', () => {
    render(<DeadlineChip date={addDaysIso(todayIso(), 3)} state="on_track" />)
    const chip = screen.getByTestId('deadline-chip')
    expect(chip.querySelector('svg[aria-hidden="true"]')).not.toBeNull()
    expect(chip.textContent).toBe('in 3 d')
  })
})
