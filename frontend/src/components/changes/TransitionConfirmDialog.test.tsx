import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, cleanup, fireEvent } from '@testing-library/react'
import TransitionConfirmDialog, { type TransitionConfirm } from './TransitionConfirmDialog'

afterEach(cleanup)

const base: TransitionConfirm = {
  to: 'scoping', title: 'Back to scoping', consequence: 'The change goes back.', open: [], confirmLabel: 'Back to scoping',
}

describe('TransitionConfirmDialog', () => {
  // Christoph 2026-11-02: a hold takes a reason AND a review date
  const hold: TransitionConfirm = { ...base, to: 'on_hold', title: 'Put on hold', confirmLabel: 'Put on hold',
    reason: { label: 'Why?' },
    date: { label: 'Check again on', defaultValue: '2026-11-16', min: '2026-11-03', max: '2027-02-02' } }

  it('sends the prefilled review date with the reason', () => {
    const onConfirm = vi.fn()
    render(<TransitionConfirmDialog confirm={hold} onConfirm={onConfirm} onClose={() => {}} />)
    expect((screen.getByTestId('confirm-date') as HTMLInputElement).value).toBe('2026-11-16')
    fireEvent.change(screen.getByTestId('confirm-reason'), { target: { value: 'No PO yet' } })
    fireEvent.click(screen.getByTestId('confirm-go'))
    expect(onConfirm).toHaveBeenCalledWith('No PO yet', '2026-11-16')
  })

  it('holds the confirm while the review date is out of range', () => {
    const onConfirm = vi.fn()
    render(<TransitionConfirmDialog confirm={hold} onConfirm={onConfirm} onClose={() => {}} />)
    fireEvent.change(screen.getByTestId('confirm-reason'), { target: { value: 'No PO yet' } })
    fireEvent.change(screen.getByTestId('confirm-date'), { target: { value: '2027-06-01' } })
    expect((screen.getByTestId('confirm-go') as HTMLButtonElement).disabled).toBe(true)
    fireEvent.change(screen.getByTestId('confirm-date'), { target: { value: '' } })
    expect((screen.getByTestId('confirm-go') as HTMLButtonElement).disabled).toBe(true)
    cleanup()
    render(<TransitionConfirmDialog confirm={base} onConfirm={onConfirm} onClose={() => {}} />)
    expect(screen.queryByTestId('confirm-date')).toBeNull()
  })

  it('is a modal named by its title; Escape closes it', () => {
    const onClose = vi.fn()
    render(<TransitionConfirmDialog confirm={base} onConfirm={() => {}} onClose={onClose} />)
    const dialog = screen.getByRole('dialog', { name: 'Back to scoping' })
    expect(dialog.getAttribute('aria-modal')).toBe('true')
    fireEvent.keyDown(dialog, { key: 'Escape' })
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('keeps Tab inside the dialog', () => {
    render(<TransitionConfirmDialog confirm={base} onConfirm={() => {}} onClose={() => {}} />)
    const [notYet, go] = screen.getAllByRole('button')
    expect(document.activeElement).toBe(notYet)
    go.focus()
    fireEvent.keyDown(go, { key: 'Tab' })
    expect(document.activeElement).toBe(notYet)
    fireEvent.keyDown(notYet, { key: 'Tab', shiftKey: true })
    expect(document.activeElement).toBe(go)
  })

  it('shows a warning without holding the step', () => {
    const onConfirm = vi.fn()
    render(<TransitionConfirmDialog confirm={{ ...base, warning: 'The total is 0.00 EUR.', open: ['Dept: no rate'] }}
      onConfirm={onConfirm} onClose={() => {}} />)
    expect(screen.getByTestId('confirm-warning').textContent).toBe('The total is 0.00 EUR.')
    const go = screen.getByTestId('confirm-go') as HTMLButtonElement
    expect(go.disabled).toBe(false)
    fireEvent.click(go)
    expect(onConfirm).toHaveBeenCalledTimes(1)
  })

  it('hides the warning while still loading', () => {
    render(<TransitionConfirmDialog confirm={{ ...base, warning: 'The total is 0.00 EUR.', loading: true }}
      onConfirm={() => {}} onClose={() => {}} />)
    expect(screen.queryByTestId('confirm-warning')).toBeNull()
  })

  it('asks for a required reason, focused first, and hands it over trimmed', () => {
    const onConfirm = vi.fn()
    render(<TransitionConfirmDialog confirm={{ ...base, reason: { label: 'Why?' } }}
      onConfirm={onConfirm} onClose={() => {}} />)
    const reason = screen.getByLabelText('Why?')
    expect(document.activeElement).toBe(reason)
    const go = screen.getByTestId('confirm-go') as HTMLButtonElement
    expect(go.disabled).toBe(true)
    fireEvent.change(reason, { target: { value: '  scope grows ' } })
    fireEvent.click(go)
    expect(onConfirm).toHaveBeenCalledWith('scope grows')
  })

  it('holds the step while something is open when asked to', () => {
    const { rerender } = render(<TransitionConfirmDialog
      confirm={{ ...base, open: ['Description'], holdWhileOpen: true }} onConfirm={() => {}} onClose={() => {}} />)
    expect((screen.getByTestId('confirm-go') as HTMLButtonElement).disabled).toBe(true)
    rerender(<TransitionConfirmDialog confirm={{ ...base, open: [], holdWhileOpen: true }}
      onConfirm={() => {}} onClose={() => {}} />)
    expect((screen.getByTestId('confirm-go') as HTMLButtonElement).disabled).toBe(false)
  })
})
