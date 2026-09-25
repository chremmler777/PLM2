import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { formatDateInput, parseDateInput } from './dateText'
import DateInput from './DateInput'

describe('date text (G19: no locale mm/dd)', () => {
  it('formats ISO as dd.mm.yyyy', () => {
    expect(formatDateInput('2026-10-05')).toBe('05.10.2026')
    expect(formatDateInput('')).toBe('')
    expect(formatDateInput('nonsense')).toBe('')
  })
  it('parses dd.mm.yyyy, dd.mm.yy, d.m.yyyy and ISO; rejects the rest', () => {
    expect(parseDateInput('05.10.2026')).toBe('2026-10-05')
    expect(parseDateInput('5.10.26')).toBe('2026-10-05')
    expect(parseDateInput('2026-10-05')).toBe('2026-10-05')
    expect(parseDateInput('31.02.2026')).toBeNull()
    expect(parseDateInput('10/05')).toBeNull()
    expect(parseDateInput('')).toBeNull()
  })
})

describe('DateInput', () => {
  afterEach(cleanup)
  it('commits a typed date on blur and reverts nonsense', () => {
    const onChange = vi.fn()
    render(<DateInput aria-label="Start" value="2026-10-05" onChange={onChange} />)
    const input = screen.getByLabelText('Start') as HTMLInputElement
    expect(input.value).toBe('05.10.2026')
    fireEvent.change(input, { target: { value: '07.10.2026' } })
    fireEvent.blur(input)
    expect(onChange).toHaveBeenCalledWith('2026-10-07')
    fireEvent.change(input, { target: { value: 'soon' } })
    fireEvent.blur(input)
    expect(input.value).toBe('05.10.2026')
  })
  it('picks a day from the calendar popover and respects max', () => {
    const onChange = vi.fn()
    render(<DateInput aria-label="Actual" value="2026-10-05" max="2026-10-10" onChange={onChange} />)
    fireEvent.click(screen.getByLabelText('Open calendar'))
    expect(screen.getByTestId('date-popover')).toBeTruthy()
    expect((screen.getByLabelText('20.10.2026') as HTMLButtonElement).disabled).toBe(true)
    fireEvent.click(screen.getByLabelText('08.10.2026'))
    expect(onChange).toHaveBeenCalledWith('2026-10-08')
  })
})
