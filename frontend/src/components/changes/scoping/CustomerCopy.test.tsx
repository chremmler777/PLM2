import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react'
import CustomerCopy from './CustomerCopy'

vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

describe('CustomerCopy', () => {
  afterEach(() => { cleanup(); vi.restoreAllMocks() })

  it('copies on plain http by select-and-copy (no clipboard API there)', async () => {
    const { toast } = await import('sonner')
    Object.defineProperty(window, 'isSecureContext', { value: false, configurable: true })
    const exec = vi.fn().mockReturnValue(true)
    ;(document as unknown as { execCommand: unknown }).execCommand = exec
    render(<CustomerCopy text="Hello" testId="cc" />)
    fireEvent.click(screen.getByTestId('cc-copy'))
    await waitFor(() => expect(exec).toHaveBeenCalledWith('copy'))
    expect(toast.success).toHaveBeenCalled()
    expect(screen.queryByTestId('cc-copy-box')).toBeNull()
  })

  it('the shown text has its own copy button', () => {
    render(<CustomerCopy text="Hello" testId="cc" />)
    fireEvent.click(screen.getByText('Show text'))
    expect(screen.getByTestId('cc-copy-box').textContent).toBe('Copy')
  })
})
