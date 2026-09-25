import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, cleanup, fireEvent } from '@testing-library/react'
import { useState } from 'react'
import { NumField } from './ui'
import { parseNum } from './offerFormat'

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
    fireEvent.change(input, { target: { value: '1,5' } })
    expect(screen.getByTestId('amt-preview').textContent).toBe('= 1.5')
    fireEvent.change(input, { target: { value: '1.5' } })
    // "1.5" is already how 1.5 reads: nothing to preview.
    expect(screen.queryByTestId('amt-preview')).toBeNull()
    // A dot group is thousands: the preview says so.
    fireEvent.change(input, { target: { value: '1.234' } })
    expect(screen.getByTestId('amt-preview').textContent).toBe('= 1,234')
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
  })

  it('reads en-US at rest', () => {
    render(<Harness initial={1234567.891} />)
    expect((screen.getByTestId('amt') as HTMLInputElement).value).toBe('1,234,567.891')
  })

  // parseNum reads "1,234" as 1.234 and "1.234" as 1234: the rest text is
  // never parsed, and the edit text always parses back to the same number.
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
