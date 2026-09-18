import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, cleanup, fireEvent } from '@testing-library/react'
import RevisionTimeline from './RevisionTimeline'
import { groupByMajor, type Revision } from './revisionGrouping'

const rev = (over: Partial<Revision>): Revision => ({
  id: 1, revision_name: 'E1', phase: 'review', status: 'approved', source: 'customer',
  part_phase_at_receipt: 'rfq', created_at: '2026-09-01T00:00:00', ...over,
})

const set: Revision[] = [
  rev({ id: 1, revision_name: 'E1', part_phase_at_receipt: 'rfq', customer_index: 'A' }),
  rev({ id: 2, revision_name: 'E1.1', parent_revision_id: 1, source: 'internal', status: 'draft' }),
  rev({ id: 3, revision_name: 'E2', part_phase_at_receipt: 'nominated' }),
  rev({ id: 4, revision_name: '1', phase: 'official', part_phase_at_receipt: 'nominated', customer_index: 'B' }),
  rev({ id: 5, revision_name: '1.2', phase: 'official', parent_revision_id: 4, source: 'internal', status: 'draft' }),
  rev({ id: 6, revision_name: '1.1', phase: 'official', parent_revision_id: 4, source: 'internal', status: 'rejected' }),
]

describe('groupByMajor', () => {
  it('puts official first, newest first, minors ascending', () => {
    const g = groupByMajor(set)
    expect(g.map((x) => x.major.revision_name)).toEqual(['1', 'E2', 'E1'])
    expect(g[0].minors.map((m) => m.revision_name)).toEqual(['1.1', '1.2'])
  })
})

describe('RevisionTimeline', () => {
  afterEach(cleanup)
  const noop = { onNewProposal: vi.fn(), onPromote: vi.fn(), onReject: vi.fn(), onUnreject: vi.fn() }

  it('shows phase-at-receipt, customer index and official badge', () => {
    render(<RevisionTimeline revisions={set} activeRevisionId={4} {...noop} />)
    const one = screen.getByTestId('major-1')
    expect(one.textContent).toContain('official')
    expect(one.textContent).toContain('nominated')
    expect(one.textContent).toContain('1 · B')
    expect(one.textContent).toContain('active')
    expect(screen.getByTestId('major-E1').textContent).toContain('rfq')
  })

  it('offers promote only on draft minors and new-proposal on majors', () => {
    render(<RevisionTimeline revisions={set} {...noop} />)
    fireEvent.click(screen.getByTestId('promote-5'))
    expect(noop.onPromote).toHaveBeenCalledWith(expect.objectContaining({ id: 5 }))
    expect(screen.queryByTestId('promote-6')).toBeNull()
    fireEvent.click(screen.getByTestId('new-proposal-4'))
    expect(noop.onNewProposal).toHaveBeenCalledWith(4)
  })
})
