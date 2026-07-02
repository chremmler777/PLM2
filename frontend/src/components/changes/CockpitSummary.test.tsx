import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, fireEvent, cleanup } from '@testing-library/react'
import CockpitSummary from './CockpitSummary'
import type { ChangeDetail } from '../../types/change'

const change = (over: Partial<ChangeDetail> = {}): ChangeDetail => ({
  id: 7, change_number: 'CR-2026-0007', project_id: 1, title: 'Housing fix',
  change_type: 'tooling', priority: 'medium', status: 'quoted',
  raised_by: 1, customer_response: 'pending', lead_id: 5, lead_name: 'Eva Eng',
  created_at: '2026-07-01T00:00:00', updated_at: '2026-07-01T00:00:00',
  impacted_items: [], assessments: [], attachments: [], ...over,
} as ChangeDetail)

describe('CockpitSummary', () => {
  afterEach(cleanup)

  it('shows lead, blockers, and one primary next action', () => {
    const onAdvance = vi.fn()
    render(<CockpitSummary
      change={change({ assessments: [
        { id: 1, department_id: 2, verdict: 'pending', stage_order: 1,
          rasic_letter: 'R', status: 'active', owner_id: null, owner_name: null,
          accepted_at: null, due_date: '2026-06-01T00:00:00', overdue: true },
      ] as ChangeDetail['assessments'] })}
      gates={[
        { gate_key: 'feasibility', decision: 'yes' },
        { gate_key: 'budget', decision: 'na' },
      ]}
      pendingDeviations={1}
      onAdvance={onAdvance} advancing={false} />)
    expect(screen.getByText('Eva Eng')).toBeDefined()
    expect(screen.getByText(/Budget/)).toBeDefined()          // open gate named
    expect(screen.getByText(/Pending deviations/)).toBeDefined()
    expect(screen.getByText(/Overdue assessments/)).toBeDefined()
    const primary = screen.getByRole('button', { name: /Approved/ })
    expect(primary.className).toContain('bg-sky-600')
    fireEvent.click(primary)
    expect(onAdvance).toHaveBeenCalledWith('approved')
  })

  it('shows nothing-blocking empty state', () => {
    render(<CockpitSummary change={change({ status: 'captured' })}
      gates={[]} pendingDeviations={0} onAdvance={() => {}} advancing={false} />)
    expect(screen.getByText(/Nothing blocking/)).toBeDefined()
  })
})
