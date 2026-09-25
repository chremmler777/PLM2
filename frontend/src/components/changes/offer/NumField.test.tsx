import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, cleanup, fireEvent } from '@testing-library/react'
import { useState } from 'react'
import { NumField } from './ui'
import { parseNum } from './offerFormat'
import { NUMBER_INPUT_HINT } from '../../../lib/format'

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
    // "." is the decimal point: "1.234" is 1.234 and reads the same.
    fireEvent.change(input, { target: { value: '1.234' } })
    expect(screen.queryByTestId('amt-preview')).toBeNull()
    expect(input.getAttribute('aria-invalid')).toBeNull()
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
    expect(screen.queryByTestId('amt-hint')).toBeNull()
    expect(input.getAttribute('title')).toContain('Not a number')
  })

  it('reads en-US at rest', () => {
    render(<Harness initial={1234567.891} />)
    expect((screen.getByTestId('amt') as HTMLInputElement).value).toBe('1,234,567.891')
  })

  // The rest text is never parsed, and the edit text always parses back to
  // the same number.
  it.each([13200, 4.2, 1.234, -1.234, 1234.5, 0.5, 1234567.891, 999.999, 0])(
    'keeps %s through an unedited focus and blur', (v) => {
      const spy = vi.fn()
      render(<Harness initial={v} spy={spy} />)
      const input = screen.getByTestId('amt') as HTMLInputElement
      const rest = input.value
      input.focus()
      fireEvent.focus(input)
      expect(parseNum(input.value)).toBe(v)
      fireEvent.blur(input)
      expect(spy).not.toHaveBeenCalled()
      expect(input.value).toBe(rest)
    })
})
