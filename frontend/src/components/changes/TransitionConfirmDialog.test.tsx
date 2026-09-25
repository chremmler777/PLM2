import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, cleanup, fireEvent } from '@testing-library/react'
import TransitionConfirmDialog, { type TransitionConfirm } from './TransitionConfirmDialog'

afterEach(cleanup)

const base: TransitionConfirm = {
  to: 'scoping', title: 'Back to scoping', consequence: 'The change goes back.', open: [], confirmLabel: 'Back to scoping',
}

describe('TransitionConfirmDialog', () => {
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
