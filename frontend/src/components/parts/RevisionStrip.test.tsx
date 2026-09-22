import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, cleanup, fireEvent } from '@testing-library/react'
import RevisionStrip from './RevisionStrip'

const revs = [
  { id: 1, revision_name: 'E1', customer_index: '003', status: 'approved', phase: 'review' as const, parent_revision_id: null },
  { id: 2, revision_name: 'E1.1', customer_index: null, status: 'draft', phase: 'review' as const, parent_revision_id: 1 },
  { id: 3, revision_name: 'E2', customer_index: '004', status: 'approved', phase: 'review' as const, parent_revision_id: null },
]

describe('RevisionStrip', () => {
  afterEach(cleanup)

  it('renders majors as tabs with minors nested and marks active and selected', () => {
    render(<RevisionStrip revisions={revs} selectedId={2} activeId={3} onSelect={() => {}} />)
    const e1 = screen.getByTestId('rev-tab-1')
    const e11 = screen.getByTestId('rev-tab-2')
    const e2 = screen.getByTestId('rev-tab-3')
    expect(e1.textContent).toContain('E1 · 003')
    expect(e11.textContent).toContain('E1.1')
    expect(e11.textContent).toContain('proposal')
    expect(e2.textContent).toContain('active')
    expect(e11.getAttribute('aria-selected')).toBe('true')
    expect(e1.getAttribute('aria-selected')).toBe('false')
    // minor sits inside its major's group
    expect(screen.getByTestId('rev-group-1').contains(e11)).toBe(true)
  })

  it('selects on click and offers a proposal on the selected major', () => {
    const onSelect = vi.fn(); const onNew = vi.fn()
    render(<RevisionStrip revisions={revs} selectedId={1} activeId={1} onSelect={onSelect} onNewProposal={onNew} />)
    fireEvent.click(screen.getByTestId('rev-tab-3'))
    expect(onSelect).toHaveBeenCalledWith(3)
    fireEvent.click(screen.getByText('+ Proposal'))
    expect(onNew).toHaveBeenCalledWith(1)
  })

  it('greys frozen and rejected revisions', () => {
    render(<RevisionStrip revisions={[{ ...revs[0], status: 'frozen' }, { ...revs[1], status: 'rejected' }]} selectedId={1} activeId={1} onSelect={() => {}} />)
    expect(screen.getByTestId('rev-tab-1').className).toContain('opacity-')
    expect(screen.getByTestId('rev-tab-2').className).toContain('line-through')
  })

  it('renders nothing for no revisions', () => {
    const { container } = render(<RevisionStrip revisions={[]} selectedId={null} activeId={null} onSelect={() => {}} />)
    expect(container.textContent).toContain('No revisions')
  })
})
