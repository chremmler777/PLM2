import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, fireEvent, cleanup } from '@testing-library/react'
import ReasonDialog from './ReasonDialog'

describe('ReasonDialog', () => {
  afterEach(cleanup)

  it('will not submit an empty or whitespace-only memo', () => {
    const onSubmit = vi.fn()
    render(<ReasonDialog open title="Reject change" label="Why?"
      onSubmit={onSubmit} onClose={() => {}} />)
    const submit = screen.getByRole('button', { name: /Submit/ }) as HTMLButtonElement
    expect(submit.disabled).toBe(true)
    // Spaces are not a reason.
    fireEvent.change(screen.getByRole('textbox'), { target: { value: '   ' } })
    expect(submit.disabled).toBe(true)
    fireEvent.change(screen.getByRole('textbox'), { target: { value: '  because  ' } })
    expect(submit.disabled).toBe(false)
    fireEvent.click(submit)
    // Trimmed — the audit trail should not carry the user's stray spaces.
    expect(onSubmit).toHaveBeenCalledWith('because')
  })

  it('shows the consequence before the memo box when one is given', () => {
    render(<ReasonDialog open title="Reject change" label="Why?"
      warning="Rejecting stops this change here." danger
      onSubmit={() => {}} onClose={() => {}} />)
    const alert = screen.getByRole('alert')
    expect(alert.textContent).toContain('Rejecting stops this change here.')
    // The warning precedes the input, so it is read before it is dismissed.
    const textbox = screen.getByRole('textbox')
    expect(alert.compareDocumentPosition(textbox) & Node.DOCUMENT_POSITION_FOLLOWING)
      .toBeTruthy()
  })

  it('carries no warning region when none is given', () => {
    render(<ReasonDialog open title="Cancel change" label="Why?"
      onSubmit={() => {}} onClose={() => {}} />)
    expect(screen.queryByRole('alert')).toBeNull()
  })

  it('clears the memo between openings so a reason is never reused', () => {
    const { rerender } = render(<ReasonDialog open title="T" label="Why?"
      onSubmit={() => {}} onClose={() => {}} />)
    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'first reason' } })
    rerender(<ReasonDialog open={false} title="T" label="Why?"
      onSubmit={() => {}} onClose={() => {}} />)
    rerender(<ReasonDialog open title="T" label="Why?"
      onSubmit={() => {}} onClose={() => {}} />)
    expect((screen.getByRole('textbox') as HTMLTextAreaElement).value).toBe('')
  })
})
