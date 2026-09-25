import { describe, it, expect, vi, afterEach } from 'vitest'
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { useState } from 'react'
import Dialog from './Dialog'
import ConfirmDialog from './ConfirmDialog'
import ConfirmModal from './ConfirmModal'
import PlanConfirmDialog from '../changes/plan/ConfirmDialog'
import Button from './Button'
import EmptyState from './EmptyState'
import FieldGroup from './FieldGroup'

afterEach(cleanup)

function Harness({ onClose = () => {} }: { onClose?: () => void }) {
  const [open, setOpen] = useState(false)
  return (
    <>
      <button onClick={() => setOpen(true)}>Open it</button>
      <Dialog open={open} onClose={() => { onClose(); setOpen(false) }} title="Edit thing"
        description="Change the name." footer={<button>Save</button>}>
        <input aria-label="Name" />
      </Dialog>
    </>
  )
}

describe('Dialog', () => {
  it('renders nothing while closed', () => {
    render(<Dialog open={false} onClose={() => {}} title="Hidden" />)
    expect(screen.queryByRole('dialog')).toBeNull()
  })

  it('is named by its title and described by its description', () => {
    render(<Dialog open onClose={() => {}} title="Edit thing" description="Change the name." />)
    const d = screen.getByRole('dialog', { name: 'Edit thing' })
    expect(d.getAttribute('aria-modal')).toBe('true')
    expect(d.getAttribute('aria-describedby')).toBe(screen.getByText('Change the name.').id)
  })

  it('focuses the first field on open, closes on Escape and returns focus', () => {
    const onClose = vi.fn()
    render(<Harness onClose={onClose} />)
    const opener = screen.getByText('Open it')
    opener.focus()
    fireEvent.click(opener)
    expect(document.activeElement).toBe(screen.getByLabelText('Name'))
    fireEvent.keyDown(screen.getByRole('dialog'), { key: 'Escape' })
    expect(onClose).toHaveBeenCalledTimes(1)
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(document.activeElement).toBe(opener)
  })

  it('keeps Tab inside the dialog', () => {
    render(<Harness />)
    fireEvent.click(screen.getByText('Open it'))
    const save = screen.getByText('Save')
    save.focus()
    fireEvent.keyDown(save, { key: 'Tab' })
    expect(document.activeElement).toBe(screen.getByLabelText('Close'))
    fireEvent.keyDown(document.activeElement!, { key: 'Tab', shiftKey: true })
    expect(document.activeElement).toBe(save)
  })

  it('ignores Escape, backdrop and the close button while busy', () => {
    const onClose = vi.fn()
    render(<Dialog open busy onClose={onClose} title="Saving" />)
    const d = screen.getByRole('dialog')
    fireEvent.keyDown(d, { key: 'Escape' })
    fireEvent.mouseDown(d)
    fireEvent.click(screen.getByLabelText('Close'))
    expect(onClose).not.toHaveBeenCalled()
  })

  it('closes on a backdrop click unless turned off', () => {
    const onClose = vi.fn()
    const { rerender } = render(<Dialog open onClose={onClose} title="T"><p>inside</p></Dialog>)
    fireEvent.mouseDown(screen.getByText('inside'))
    expect(onClose).not.toHaveBeenCalled()
    fireEvent.mouseDown(screen.getByRole('dialog'))
    expect(onClose).toHaveBeenCalledTimes(1)
    rerender(<Dialog open onClose={onClose} title="T" closeOnBackdrop={false}><p>inside</p></Dialog>)
    fireEvent.mouseDown(screen.getByRole('dialog'))
    expect(onClose).toHaveBeenCalledTimes(1)
  })
})

describe('ConfirmDialog', () => {
  it('is an alertdialog; a sync confirm runs and closes', () => {
    const onConfirm = vi.fn()
    const onClose = vi.fn()
    render(<ConfirmDialog open title="Delete line?" body="It cannot be undone." confirmLabel="Delete line"
      onConfirm={onConfirm} onClose={onClose} />)
    const d = screen.getByRole('alertdialog', { name: 'Delete line?' })
    expect(d.getAttribute('aria-describedby')).toBe(screen.getByText('It cannot be undone.').id)
    expect(document.activeElement).toBe(screen.getByTestId('confirm-ok'))
    fireEvent.click(screen.getByTestId('confirm-ok'))
    expect(onConfirm).toHaveBeenCalledTimes(1)
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('focuses Cancel first when danger', () => {
    render(<ConfirmDialog open danger title="Discard?" onConfirm={() => {}} onClose={() => {}} />)
    expect(document.activeElement).toBe(screen.getByText('Cancel'))
  })

  it('stays open and shows the backend reason when an async confirm fails', async () => {
    const onClose = vi.fn()
    const onConfirm = vi.fn().mockRejectedValue({ response: { data: { detail: 'Offer is locked' } } })
    render(<ConfirmDialog open title="Send offer?" confirmLabel="Send offer"
      onConfirm={onConfirm} onClose={onClose} errorFallback="Could not send the offer" />)
    await act(async () => { fireEvent.click(screen.getByTestId('confirm-ok')) })
    expect(screen.getByRole('alert').textContent).toContain('Offer is locked')
    expect(onClose).not.toHaveBeenCalled()
    expect(screen.getByRole('alertdialog')).toBeTruthy()
  })

  it('shows a spinner and blocks Cancel while the confirm runs, then closes', async () => {
    let resolve!: () => void
    const onClose = vi.fn()
    render(<ConfirmDialog open title="Approve?" onConfirm={() => new Promise<void>((r) => { resolve = r })}
      onClose={onClose} />)
    await act(async () => { fireEvent.click(screen.getByTestId('confirm-ok')) })
    expect(screen.getByTestId('confirm-ok').getAttribute('aria-busy')).toBe('true')
    expect((screen.getByText('Cancel') as HTMLButtonElement).disabled).toBe(true)
    await act(async () => { resolve() })
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('keeps the plan/ConfirmDialog import path working', () => {
    expect(PlanConfirmDialog).toBe(ConfirmDialog)
  })
})

describe('ConfirmModal (legacy props)', () => {
  it('maps the old props and leaves closing to the parent', () => {
    const onConfirm = vi.fn()
    const onCancel = vi.fn()
    render(<ConfirmModal isOpen title="Cancel Workflow" message="Stop all tasks?" confirmText="Cancel workflow"
      isDangerous onConfirm={onConfirm} onCancel={onCancel} />)
    fireEvent.click(screen.getByText('Cancel workflow'))
    expect(onConfirm).toHaveBeenCalledTimes(1)
    expect(onCancel).not.toHaveBeenCalled()
    fireEvent.click(screen.getByText('Cancel'))
    expect(onCancel).toHaveBeenCalledTimes(1)
  })

  it('disables both buttons while isLoading', () => {
    render(<ConfirmModal isOpen isLoading title="T" message="M" onConfirm={() => {}} onCancel={() => {}} />)
    expect((screen.getByText('Cancel') as HTMLButtonElement).disabled).toBe(true)
    expect((screen.getByTestId('confirm-ok') as HTMLButtonElement).disabled).toBe(true)
  })
})

describe('Button', () => {
  it('defaults to type=button and blocks clicks while loading', () => {
    const onClick = vi.fn()
    const { rerender } = render(<Button onClick={onClick}>Save</Button>)
    const b = screen.getByRole('button', { name: 'Save' })
    expect(b.getAttribute('type')).toBe('button')
    rerender(<Button onClick={onClick} loading>Save</Button>)
    fireEvent.click(b)
    expect(onClick).not.toHaveBeenCalled()
    expect(b.getAttribute('aria-busy')).toBe('true')
  })
})

describe('EmptyState and FieldGroup', () => {
  it('renders title, hint and action', () => {
    render(<EmptyState title="No impacted items yet" hint="Scope the change first." action={<button>Open scoping</button>} />)
    expect(screen.getByText('No impacted items yet')).toBeTruthy()
    expect(screen.getByText('Scope the change first.')).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Open scoping' })).toBeTruthy()
  })

  it('names the group by its legend', () => {
    render(<FieldGroup legend="Severity" hint="How bad is it?"><input type="radio" aria-label="Low" /></FieldGroup>)
    const g = screen.getByRole('group', { name: 'Severity' })
    expect(g.getAttribute('aria-describedby')).toBe(screen.getByText('How bad is it?').id)
  })
})
