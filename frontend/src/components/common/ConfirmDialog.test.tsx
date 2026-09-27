import { describe, it, expect, vi, afterEach } from 'vitest'
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import ConfirmDialog from './ConfirmDialog'

afterEach(cleanup)

function deferred() {
  let resolve!: () => void
  let reject!: (e: unknown) => void
  const promise = new Promise<void>((res, rej) => { resolve = res; reject = rej })
  return { promise, resolve, reject }
}

describe('ConfirmDialog while running', () => {
  it('keeps focus on the confirm button and ignores repeat clicks', async () => {
    const d = deferred()
    const onConfirm = vi.fn(() => d.promise)
    render(<ConfirmDialog open title="Approve?" onConfirm={onConfirm} onClose={() => {}} />)
    const ok = screen.getByTestId('confirm-ok') as HTMLButtonElement
    ok.focus()
    await act(async () => { fireEvent.click(ok) })
    expect(ok.disabled).toBe(false)
    expect(ok.getAttribute('aria-disabled')).toBe('true')
    expect(document.activeElement).toBe(ok)
    await act(async () => { fireEvent.click(ok) })
    expect(onConfirm).toHaveBeenCalledTimes(1)
    await act(async () => { d.resolve() })
  })

  it('does not close twice when closed from outside before the confirm resolves', async () => {
    const d = deferred()
    const onClose = vi.fn()
    const { rerender } = render(<ConfirmDialog open title="Approve?" onConfirm={() => d.promise} onClose={onClose} />)
    await act(async () => { fireEvent.click(screen.getByTestId('confirm-ok')) })
    rerender(<ConfirmDialog open={false} title="Approve?" onConfirm={() => d.promise} onClose={onClose} />)
    await act(async () => { d.resolve() })
    expect(onClose).not.toHaveBeenCalled()
  })

  it('drops a failure from an earlier open instead of showing it on the next one', async () => {
    const d = deferred()
    const props = { title: 'Send?', onConfirm: () => d.promise, onClose: () => {} }
    const { rerender } = render(<ConfirmDialog open {...props} />)
    await act(async () => { fireEvent.click(screen.getByTestId('confirm-ok')) })
    rerender(<ConfirmDialog open={false} {...props} />)
    rerender(<ConfirmDialog open {...props} />)
    await act(async () => { d.reject({ response: { data: { detail: 'Locked' } } }) })
    expect(screen.queryByRole('alert')).toBeNull()
    expect(screen.getByTestId('confirm-ok').getAttribute('aria-busy')).toBeNull()
  })
})
