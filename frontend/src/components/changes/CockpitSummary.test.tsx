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
      // status 'quoted' -> next is 'approved'/'rejected'. Neither gate below
      // guards that transition (feasibility guards in_assessment, budget guards
      // costing, release guards in_implementation), so none should be amber.
      gates={[
        { gate_key: 'feasibility', decision: 'yes' },
        { gate_key: 'budget', decision: 'na' },
        { gate_key: 'release', decision: 'na' },
      ]}
      pendingDeviations={1}
      onAdvance={onAdvance} advancing={false} />)
    expect(screen.getByText('Eva Eng')).toBeDefined()
    const budgetRow = screen.getByText(/Budget/).closest('li')
    expect(budgetRow?.textContent).not.toContain('⚠')
    expect(budgetRow?.className).toContain('text-slate-400')
    const releaseRow = screen.getByText(/Release/).closest('li')
    expect(releaseRow?.textContent).not.toContain('⚠')
    expect(releaseRow?.className).toContain('text-slate-400')
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

  it('marks a gate amber only when it guards a currently-available transition', () => {
    // status 'captured' -> next is 'in_assessment'. feasibility guards
    // in_assessment, so a not-yes feasibility gate IS a real blocker. budget and
    // release guard later transitions, so they render muted, not amber.
    render(<CockpitSummary change={change({ status: 'captured', assessments: [] })}
      gates={[
        { gate_key: 'feasibility', decision: 'na' },
        { gate_key: 'budget', decision: 'na' },
        { gate_key: 'release', decision: 'na' },
      ]}
      pendingDeviations={0} onAdvance={() => {}} advancing={false} />)
    expect(screen.queryByText(/Nothing blocking/)).toBeNull()
    const feasibilityRow = screen.getByText(/Feasibility/).closest('li')
    expect(feasibilityRow?.textContent).toContain('⚠')
    expect(feasibilityRow?.className).toContain('text-amber-300')
    const budgetRow = screen.getByText(/Budget/).closest('li')
    expect(budgetRow?.textContent).not.toContain('⚠')
    expect(budgetRow?.className).toContain('text-slate-400')
    const releaseRow = screen.getByText(/Release/).closest('li')
    expect(releaseRow?.textContent).not.toContain('⚠')
    expect(releaseRow?.className).toContain('text-slate-400')
  })

  it('gate rows act in place: clicking one calls onResolveGate with its key', () => {
    const onResolveGate = vi.fn()
    render(<CockpitSummary change={change({ status: 'captured', assessments: [] })}
      gates={[
        { gate_key: 'feasibility', decision: 'na' },
        { gate_key: 'budget', decision: 'na' },
      ]}
      pendingDeviations={0} onAdvance={() => {}} advancing={false}
      onResolveGate={onResolveGate} />)
    fireEvent.click(screen.getByRole('button', { name: /Feasibility/ }))
    expect(onResolveGate).toHaveBeenCalledWith('feasibility')
    fireEvent.click(screen.getByRole('button', { name: /Budget/ }))
    expect(onResolveGate).toHaveBeenCalledWith('budget')
  })

  it('keeps the green nothing-blocking state while still listing later gates as muted', () => {
    render(<CockpitSummary change={change({ status: 'quoted', assessments: [] })}
      gates={[{ gate_key: 'budget', decision: 'na' }]}
      pendingDeviations={0} onAdvance={() => {}} advancing={false} />)
    expect(screen.getByText(/Nothing blocking/)).toBeDefined()
    const budgetRow = screen.getByText(/Budget/).closest('li')
    expect(budgetRow?.textContent).not.toContain('⚠')
    expect(budgetRow?.className).toContain('text-slate-400')
  })

  it('shows an impact-confirmation blocker row when approved and unconfirmed, and jumps via onShowImpact', () => {
    const onShowImpact = vi.fn()
    render(<CockpitSummary change={change({ status: 'approved', assessments: [], impact_confirmed_at: null })}
      gates={[]} pendingDeviations={0} onAdvance={() => {}} advancing={false}
      onShowImpact={onShowImpact} />)
    expect(screen.queryByText(/Nothing blocking/)).toBeNull()
    const row = screen.getByRole('button', { name: /Impact confirmation pending/ })
    fireEvent.click(row)
    expect(onShowImpact).toHaveBeenCalled()
  })

  it('does not show the impact-confirmation blocker once confirmed', () => {
    render(<CockpitSummary change={change({
      status: 'approved', assessments: [],
      impact_confirmed_at: '2026-07-01T00:00:00', impact_confirmed_by: 9,
    })}
      gates={[]} pendingDeviations={0} onAdvance={() => {}} advancing={false} />)
    expect(screen.queryByText(/Impact confirmation pending/)).toBeNull()
    expect(screen.getByText(/Nothing blocking/)).toBeDefined()
  })
})
