import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, cleanup, fireEvent } from '@testing-library/react'
import { useState } from 'react'
import StatusSlideOver, { type StatusSection } from './StatusSlideOver'

// A section that opens a dialog of its own, like the gate or change editors do.
vi.mock('../ProjectSepSection', () => ({
  default: () => (
    <div role="dialog" aria-label="Nested editor">
      <input aria-label="nested field" />
      <input aria-label="self-handled field" onKeyDown={(e) => { if (e.key === 'Escape') e.preventDefault() }} />
    </div>
  ),
}))
vi.mock('../ProjectChangesSection', () => ({ default: () => <div>changes-section</div> }))
vi.mock('../ProjectLessonsSection', () => ({ default: () => <div>lessons-section</div> }))

function Harness({ onClose }: { onClose(): void }) {
  const [section, setSection] = useState<StatusSection | null>(null)
  return (
    <>
      <button onClick={() => setSection('sep')}>chip-sep</button>
      <button onClick={() => setSection('changes')}>chip-changes</button>
      <StatusSlideOver section={section} projectId={2} onClose={() => { onClose(); setSection(null) }} />
    </>
  )
}

function openVia(label: string) {
  const chip = screen.getByText(label)
  chip.focus()
  fireEvent.click(chip)
  return chip
}

describe('StatusSlideOver', () => {
  afterEach(cleanup)

  it('closes on Escape pressed in the slide-over itself', () => {
    const onClose = vi.fn()
    render(<Harness onClose={onClose} />)
    openVia('chip-changes')
    fireEvent.keyDown(screen.getByLabelText('Close'), { key: 'Escape' })
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('leaves Escape to a nested dialog that has focus', () => {
    const onClose = vi.fn()
    render(<Harness onClose={onClose} />)
    openVia('chip-sep')
    const field = screen.getByLabelText('nested field')
    field.focus()
    fireEvent.keyDown(field, { key: 'Escape' })
    expect(onClose).not.toHaveBeenCalled()
    expect(screen.getByTestId('status-slideover')).toBeTruthy()
  })

  it('leaves Escape alone when something inside already handled it', () => {
    const onClose = vi.fn()
    render(<Harness onClose={onClose} />)
    openVia('chip-sep')
    screen.getByLabelText('Close').focus()
    fireEvent.keyDown(screen.getByLabelText('self-handled field'), { key: 'Escape' })
    expect(onClose).not.toHaveBeenCalled()
  })

  it('moves focus into the slide-over on open and back to the chip on close', () => {
    render(<Harness onClose={() => {}} />)
    const chip = openVia('chip-changes')
    expect(screen.getByRole('dialog', { name: 'Changes' }).contains(document.activeElement)).toBe(true)
    fireEvent.keyDown(document.activeElement!, { key: 'Escape' })
    expect(screen.queryByTestId('status-slideover')).toBeNull()
    expect(document.activeElement).toBe(chip)
  })

  it('returns focus to the chip after a click outside as well', () => {
    render(<Harness onClose={() => {}} />)
    const chip = openVia('chip-changes')
    expect(document.activeElement).not.toBe(chip)
    fireEvent.click(screen.getByTestId('slideover-backdrop'))
    expect(document.activeElement).toBe(chip)
  })
})
