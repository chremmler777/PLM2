import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, cleanup, fireEvent } from '@testing-library/react'
import { useState } from 'react'
import { NumField } from './ui'
import { parseNum } from './offerFormat'
import { NUMBER_INPUT_HINT, NUMBER_INPUT_INVALID } from '../../../lib/format'

afterEach(cleanup)

function Harness({ initial, spy }: { initial: number | null; spy?: (v: number | null) => void }) {
  const [v, setV] = useState<number | null>(initial)
  return <NumField value={v} ariaLabel="Amount" testId="amt" onChange={(n) => { setV(n); spy?.(n) }} />
}

describe('NumField', () => {
  it('selects the whole value on focus, so typing replaces it', () => {
    render(<Harness initial={13200} />)
    const input = screen.getByTestId('amt') as HTMLInputElement
    expect(input.value).toBe('13,200')
    input.focus()
    fireEvent.focus(input)
    expect(input.value).toBe('13200')
    expect(input.selectionStart).toBe(0)
    expect(input.selectionEnd).toBe(input.value.length)
  })

  it('reports the typed number and never appends to the old one', () => {
    const spy = vi.fn()
    render(<Harness initial={13200} spy={spy} />)
    const input = screen.getByTestId('amt') as HTMLInputElement
    input.focus()
    fireEvent.focus(input)
    fireEvent.change(input, { target: { value: '500' } })
    expect(spy).toHaveBeenLastCalledWith(500)
    fireEvent.blur(input)
    expect(input.value).toBe('500')
  })

  it('shows the parsed value while the typed text reads differently', () => {
    render(<Harness initial={null} />)
    const input = screen.getByTestId('amt') as HTMLInputElement
    input.focus()
    fireEvent.focus(input)
    fireEvent.change(input, { target: { value: '1.5' } })
    // "1.5" is already how 1.5 reads: nothing to preview.
    expect(screen.queryByTestId('amt-preview')).toBeNull()
    // "." is the decimal point: "1.2345" is 1.2345 and reads the same.
    fireEvent.change(input, { target: { value: '1.2345' } })
    expect(screen.queryByTestId('amt-preview')).toBeNull()
    expect(input.getAttribute('aria-invalid')).toBeNull()
    // "1.234" looks like German thousands: refused as ambiguous, not guessed.
    fireEvent.change(input, { target: { value: '1.234' } })
    expect(input.getAttribute('aria-invalid')).toBe('true')
    expect(screen.getByTestId('amt-hint').textContent).toBe(NUMBER_INPUT_HINT)
    // A comma that is not a thousands group is refused, not read as a decimal.
    fireEvent.change(input, { target: { value: '1,5' } })
    expect(input.getAttribute('aria-invalid')).toBe('true')
    expect(screen.queryByTestId('amt-preview')).toBeNull()
    expect(screen.getByTestId('amt-hint').textContent).toBe(NUMBER_INPUT_HINT)
    expect(input.getAttribute('title')).toBe(NUMBER_INPUT_HINT)
    // "12,500" is a thousands group: taken, no hint.
    fireEvent.change(input, { target: { value: '12,500' } })
    expect(screen.queryByTestId('amt-hint')).toBeNull()
    expect(input.getAttribute('aria-invalid')).toBeNull()
    fireEvent.change(input, { target: { value: '12500' } })
    expect(screen.getByTestId('amt-preview').textContent).toBe('= 12,500')
    fireEvent.blur(input)
    expect(screen.queryByTestId('amt-preview')).toBeNull()
  })

  it('flags text that is not a number and reports nothing for it', () => {
    const spy = vi.fn()
    render(<Harness initial={4} spy={spy} />)
    const input = screen.getByTestId('amt') as HTMLInputElement
    fireEvent.focus(input)
    fireEvent.change(input, { target: { value: '1.23.4' } })
    expect(input.getAttribute('aria-invalid')).toBe('true')
    expect(spy).not.toHaveBeenCalled()
    expect(screen.queryByTestId('amt-preview')).toBeNull()
    expect(screen.getByTestId('amt-hint').textContent).toBe(NUMBER_INPUT_INVALID)
    expect(input.getAttribute('title')).toContain('Not a number')
    fireEvent.blur(input)
    expect(spy).not.toHaveBeenCalled()
    expect(input.value).toBe('4')
    expect(screen.getByTestId('amt-dropped').textContent).toBe(`"1.23.4" not saved. ${NUMBER_INPUT_INVALID}`)
  })

  // Each cleanly read keystroke is reported ("0" on the way to "0,5"), so
  // leaving with refused text must put the number from before focus back.
  it.each([
    [['0', '0,', '0,5'], 0],
    [['1', '1,', '1,2', '1,23', '1,234', '1,2345'], 1234],
  ])('restores the value from before focus after refused text %j', (keys, intermediate) => {
    const spy = vi.fn()
    render(<Harness initial={7.25} spy={spy} />)
    const input = screen.getByTestId('amt') as HTMLInputElement
    input.focus()
    fireEvent.focus(input)
    for (const k of keys) fireEvent.change(input, { target: { value: k } })
    expect(spy).toHaveBeenCalledWith(intermediate)
    expect(screen.getByTestId('amt-hint').textContent).toBe(NUMBER_INPUT_HINT)
    fireEvent.blur(input)
    expect(spy).toHaveBeenLastCalledWith(7.25)
    expect(input.value).toBe('7.25')
    expect(input.getAttribute('aria-invalid')).toBe('true')
    const msg = screen.getByTestId('amt-dropped')
    expect(msg.textContent).toBe(`"${keys[keys.length - 1]}" not saved. ${NUMBER_INPUT_HINT}`)
    expect(msg.getAttribute('role')).toBe('alert')
    // The next focus starts clean from the restored value.
    fireEvent.focus(input)
    expect(screen.queryByTestId('amt-dropped')).toBeNull()
    expect(input.value).toBe('7.25')
  })

  it('restores the value even when the parent has not applied the keystroke yet', () => {
    const spy = vi.fn()
    render(<NumField value={3} ariaLabel="Amount" testId="amt" onChange={spy} />)
    const input = screen.getByTestId('amt') as HTMLInputElement
    fireEvent.focus(input)
    fireEvent.change(input, { target: { value: '0' } })
    fireEvent.change(input, { target: { value: '0,5' } })
    fireEvent.blur(input)
    expect(spy.mock.calls).toEqual([[0], [3]])
  })

  it('reads en-US at rest', () => {
    render(<Harness initial={1234567.891} />)
    expect((screen.getByTestId('amt') as HTMLInputElement).value).toBe('1,234,567.891')
  })

  // The rest text is never parsed, and the edit text always parses back to
  // the same number.
  it.each([13200, 4.2, 1.234, -1.234, 12.5, 1234.5, 0.5, 1234567.891, 999.999, 0, 1e-7, 1e21])(
    'keeps %s through an unedited focus and blur', (v) => {
      const spy = vi.fn()
      render(<Harness initial={v} spy={spy} />)
      const input = screen.getByTestId('amt') as HTMLInputElement
      const rest = input.value
      input.focus()
      fireEvent.focus(input)
      expect(parseNum(input.value)).toBe(v)
      expect(input.getAttribute('aria-invalid')).toBeNull()
      fireEvent.blur(input)
      expect(spy).not.toHaveBeenCalled()
      expect(input.value).toBe(rest)
      expect(input.getAttribute('aria-invalid')).toBeNull()
      expect(screen.queryByTestId('amt-dropped')).toBeNull()
    })

  it('edits 1.234 as "1.2340", which never reads as German thousands', () => {
    render(<Harness initial={1.234} />)
    const input = screen.getByTestId('amt') as HTMLInputElement
    fireEvent.focus(input)
    expect(input.value).toBe('1.2340')
  })
})
