import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, cleanup, fireEvent } from '@testing-library/react'
import { useState } from 'react'
import { NumField } from './ui'

afterEach(cleanup)

function Harness({ initial, spy }: { initial: number | null; spy?: (v: number | null) => void }) {
  const [v, setV] = useState<number | null>(initial)
  return <NumField value={v} ariaLabel="Amount" testId="amt" onChange={(n) => { setV(n); spy?.(n) }} />
}

describe('NumField', () => {
  it('selects the whole value on focus, so typing replaces it', () => {
    render(<Harness initial={13200} />)
    const input = screen.getByTestId('amt') as HTMLInputElement
    expect(input.value).toBe('13.200')
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
    expect(screen.getByTestId('amt-preview').textContent).toBe('= 1,5')
    fireEvent.change(input, { target: { value: '1.234' } })
    // "1.234" is already how 1234 reads: nothing to preview.
    expect(screen.queryByTestId('amt-preview')).toBeNull()
    fireEvent.change(input, { target: { value: '12500' } })
    expect(screen.getByTestId('amt-preview').textContent).toBe('= 12.500')
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
})
