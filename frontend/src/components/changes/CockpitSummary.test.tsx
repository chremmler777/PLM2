import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, fireEvent, cleanup } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import CockpitSummary from './CockpitSummary'
import type { ChangeDetail } from '../../types/change'
import { t } from '../../i18n/cmLabels'

const change = (over: Partial<ChangeDetail> = {}): ChangeDetail => ({
  id: 7, change_number: 'CR-2026-0007', project_id: 1, title: 'Housing fix',
  change_type: 'tooling', priority: 'medium', status: 'quoted',
  raised_by: 1, customer_response: 'pending', lead_id: 5, lead_name: 'Eva Eng',
  created_at: '2026-07-01T00:00:00', updated_at: '2026-07-01T00:00:00',
  impacted_items: [], assessments: [], attachments: [], ...over,
} as ChangeDetail)

const wrap = (ui: React.ReactElement) => (
  <QueryClientProvider client={new QueryClient()}>{ui}</QueryClientProvider>
)

describe('CockpitSummary', () => {
  afterEach(cleanup)

  it('shows lead, blockers, and one primary next action', () => {
    const onAdvance = vi.fn()
    render(wrap(<CockpitSummary
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
      onAdvance={onAdvance} advancing={false} />))
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
    render(wrap(<CockpitSummary change={change({ status: 'captured' })}
      gates={[]} pendingDeviations={0} onAdvance={() => {}} advancing={false} />))
    expect(screen.getByText(/Nothing blocking/)).toBeDefined()
  })

  it('marks a gate amber only when it guards a currently-available transition', () => {
    // status 'scoping' -> next is 'in_assessment'. feasibility guards
    // in_assessment, so a not-yes feasibility gate IS a real blocker. budget and
    // release guard later transitions, so they render muted, not amber.
    render(wrap(<CockpitSummary change={change({ status: 'scoping', assessments: [] })}
      gates={[
        { gate_key: 'feasibility', decision: 'na' },
        { gate_key: 'budget', decision: 'na' },
        { gate_key: 'release', decision: 'na' },
      ]}
      pendingDeviations={0} onAdvance={() => {}} advancing={false} />))
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
    render(wrap(<CockpitSummary change={change({ status: 'captured', assessments: [] })}
      gates={[
        { gate_key: 'feasibility', decision: 'na' },
        { gate_key: 'budget', decision: 'na' },
      ]}
      pendingDeviations={0} onAdvance={() => {}} advancing={false}
      onResolveGate={onResolveGate} />))
    fireEvent.click(screen.getByRole('button', { name: /Feasibility/ }))
    expect(onResolveGate).toHaveBeenCalledWith('feasibility')
    fireEvent.click(screen.getByRole('button', { name: /Budget/ }))
    expect(onResolveGate).toHaveBeenCalledWith('budget')
  })

  it('does not render gate rows as jump buttons when the viewer cannot see governance tabs', () => {
    const onResolveGate = vi.fn()
    render(wrap(<CockpitSummary change={change({ status: 'captured', assessments: [] })}
      gates={[
        { gate_key: 'feasibility', decision: 'na' },
        { gate_key: 'budget', decision: 'na' },
      ]}
      pendingDeviations={0} onAdvance={() => {}} advancing={false}
      onResolveGate={onResolveGate} canSeeGovernance={false} />))
    expect(screen.queryByRole('button', { name: /Feasibility/ })).toBeNull()
    expect(screen.getByText(/Feasibility/)).toBeDefined()
  })

  it('keeps the green nothing-blocking state while still listing later gates as muted', () => {
    render(wrap(<CockpitSummary change={change({ status: 'quoted', assessments: [] })}
      gates={[{ gate_key: 'budget', decision: 'na' }]}
      pendingDeviations={0} onAdvance={() => {}} advancing={false} />))
    expect(screen.getByText(/Nothing blocking/)).toBeDefined()
    const budgetRow = screen.getByText(/Budget/).closest('li')
    expect(budgetRow?.textContent).not.toContain('⚠')
    expect(budgetRow?.className).toContain('text-slate-400')
  })

  it('shows an impact-confirmation blocker row when approved and unconfirmed, and jumps via onShowImpact', () => {
    const onShowImpact = vi.fn()
    render(wrap(<CockpitSummary change={change({
      status: 'approved', assessments: [], impact_confirmed_at: null,
      impacted_items: [{ id: 1, part_id: 9 }] as ChangeDetail['impacted_items'],
    })}
      gates={[]} pendingDeviations={0} onAdvance={() => {}} advancing={false}
      onShowImpact={onShowImpact} />))
    expect(screen.queryByText(/Nothing blocking/)).toBeNull()
    const row = screen.getByRole('button', { name: /Impact confirmation pending/ })
    fireEvent.click(row)
    expect(onShowImpact).toHaveBeenCalled()
  })

  it('does not show the impact-confirmation blocker once confirmed', () => {
    render(wrap(<CockpitSummary change={change({
      status: 'approved', assessments: [],
      impact_confirmed_at: '2026-07-01T00:00:00', impact_confirmed_by: 9,
    })}
      gates={[]} pendingDeviations={0} onAdvance={() => {}} advancing={false} />))
    expect(screen.queryByText(/Impact confirmation pending/)).toBeNull()
    expect(screen.getByText(/Nothing blocking/)).toBeDefined()
  })

  it('renders a "Your actions" panel with a button per action and fires onAction with its target_tab', () => {
    const onAction = vi.fn()
    render(wrap(<CockpitSummary change={change()}
      gates={[]} pendingDeviations={0} onAdvance={() => {}} advancing={false}
      actions={[
        { kind: 'assessment', label: 'Submit assessment for R&D', target_tab: 'assessments', assessment_id: 1 },
        { kind: 'deviation_decision', label: 'Decide deviation #12', target_tab: 'overview', deviation_id: 12 },
      ]}
      onAction={onAction} />))
    expect(screen.getByText(/Your actions/)).toBeDefined()
    fireEvent.click(screen.getByRole('button', { name: 'Submit assessment for R&D' }))
    expect(onAction).toHaveBeenCalledWith('assessments')
    fireEvent.click(screen.getByRole('button', { name: 'Decide deviation #12' }))
    expect(onAction).toHaveBeenCalledWith('overview')
  })

  it('flags an unlocked impacted set as a blocker during scoping', () => {
    render(wrap(<CockpitSummary
      change={change({
        status: 'scoping',
        impact_confirmed_at: null,
        impacted_items: [{ id: 1, part_id: 9 }] as ChangeDetail['impacted_items'],
      })}
      gates={[]} pendingDeviations={0}
      onAdvance={vi.fn()} advancing={false} />))
    expect(screen.getByText(/impact/i)).toBeDefined()
    expect(screen.queryByText(/nothing/i)).toBeNull()
  })

  it('does not flag impact lock during scoping when no impacted items exist', () => {
    render(wrap(<CockpitSummary
      change={change({ status: 'scoping', impact_confirmed_at: null, impacted_items: [] })}
      gates={[]} pendingDeviations={0}
      onAdvance={vi.fn()} advancing={false} />))
    expect(screen.queryByText(/nothing/i)).not.toBeNull()
  })

  it('hides the "Your actions" panel entirely when there are no actions', () => {
    render(wrap(<CockpitSummary change={change()}
      gates={[]} pendingDeviations={0} onAdvance={() => {}} advancing={false}
      actions={[]} />))
    expect(screen.queryByText(/Your actions/)).toBeNull()
  })
})

describe('CockpitSummary scoping decisions belong to the meeting', () => {
  afterEach(cleanup)

  it('offers no advance buttons in scoping, only a pointer to the meeting', () => {
    const onAction = vi.fn()
    render(wrap(<CockpitSummary change={change({ status: 'scoping', assessments: [] })}
      gates={[]} pendingDeviations={0} onAdvance={() => {}} advancing={false}
      onAction={onAction} />))
    // Proceeding and rejecting are the meeting's call — no button bypasses it.
    expect(screen.queryByRole('button', { name: /In Assessment/ })).toBeNull()
    expect(screen.queryByRole('button', { name: /Rejected/ })).toBeNull()
    const pointer = screen.getByText(/Record the decision in the scoping meeting/)
    fireEvent.click(pointer)
    expect(onAction).toHaveBeenCalledWith('scoping')
  })

  it('still offers the ordinary advance button on statuses the meeting does not own', () => {
    render(wrap(<CockpitSummary change={change({ status: 'captured', assessments: [] })}
      gates={[]} pendingDeviations={0} onAdvance={() => {}} advancing={false} />))
    expect(screen.getByRole('button', { name: /Scoping/ })).toBeDefined()
    expect(screen.queryByText(/Record the decision in the scoping meeting/)).toBeNull()
  })
})

describe('CockpitSummary phase-aware deadline widget', () => {
  afterEach(cleanup)

  it('shows the frozen quoted-late fact while waiting on the customer', () => {
    render(wrap(<CockpitSummary change={change({
      status: 'quoted', customer_relevant: true,
      required_by_date: '2026-06-01T23:59:59', quoted_at: '2026-06-10T00:00:00',
      quoted_on_time: false, active_deadline: null,
    })} gates={[]} pendingDeviations={0} onAdvance={() => {}} advancing={false} />))
    expect(screen.getByTestId('quoted-fact-chip')).toBeDefined()
    expect(screen.getByText(new RegExp(t('deadline.quotedLate')))).toBeDefined()
    expect(screen.queryByTestId('deadline-edit')).toBeNull()
  })

  it('shows the release deadline editor once active', () => {
    render(wrap(<CockpitSummary change={change({
      status: 'approved', customer_relevant: true, active_deadline: 'release',
      release_due_date: '2026-10-01T23:59:59', release_due_reason: null,
      deadline_state: 'on_track',
    })} gates={[]} pendingDeviations={0} onAdvance={() => {}} advancing={false} />))
    expect(screen.getByTestId('deadline-chip')).toBeDefined()
    expect(screen.getByTestId('deadline-edit')).toBeDefined()
  })

  it('hides the quote deadline editor for internal changes', () => {
    render(wrap(<CockpitSummary change={change({
      status: 'costing', customer_relevant: false, active_deadline: null,
      required_by_date: null,
    })} gates={[]} pendingDeviations={0} onAdvance={() => {}} advancing={false} />))
    expect(screen.queryByTestId('deadline-edit')).toBeNull()
  })
})

describe('CockpitSummary kickoff readiness at capture', () => {
  afterEach(cleanup)

  const captured = (over: Partial<ChangeDetail> = {}) => render(wrap(
    <CockpitSummary change={change({ status: 'captured', ...over })}
      gates={[]} pendingDeviations={0} onAdvance={() => {}} advancing={false} />))

  it('names every missing kickoff requirement for a customer change', () => {
    captured({ customer_relevant: true, description: null, attachments: [], required_by_date: null })
    const hint = screen.getByTestId('kickoff-hint')
    expect(hint.textContent).toContain(t('kickoff.description'))
    expect(hint.textContent).toContain(t('kickoff.attachment'))
    expect(hint.textContent).toContain(t('deadline.quote'))
  })

  it('drops the requirement it already has and never asks internal changes for a quote date', () => {
    captured({
      customer_relevant: false, description: 'Clip rattles', required_by_date: null,
      attachments: [] as ChangeDetail['attachments'],
    })
    const hint = screen.getByTestId('kickoff-hint')
    expect(hint.textContent).not.toContain(t('kickoff.description'))
    expect(hint.textContent).not.toContain(t('deadline.quote'))
    expect(hint.textContent).toContain(t('kickoff.attachment'))
  })

  it('reports readiness once description, attachment and date are there', () => {
    captured({
      customer_relevant: true, description: 'Clip rattles',
      required_by_date: '2026-09-01T23:59:59',
      attachments: [{ id: 1 }] as unknown as ChangeDetail['attachments'],
    })
    expect(screen.queryByTestId('kickoff-hint')).toBeNull()
    expect(screen.getByTestId('kickoff-ready')).toBeDefined()
  })

  it('says nothing about kickoff once the change has left capture', () => {
    render(wrap(<CockpitSummary change={change({ status: 'in_assessment', description: null })}
      gates={[]} pendingDeviations={0} onAdvance={() => {}} advancing={false} />))
    expect(screen.queryByTestId('kickoff-hint')).toBeNull()
    expect(screen.queryByTestId('kickoff-ready')).toBeNull()
  })

  it('tags capture with Sales, scoping with project management, and leaves later stages untagged', () => {
    captured()
    expect(screen.getByTestId('stage-responsible').textContent).toContain(t('role.sales'))
    cleanup()
    render(wrap(<CockpitSummary change={change({ status: 'scoping' })}
      gates={[]} pendingDeviations={0} onAdvance={() => {}} advancing={false} />))
    expect(screen.getByTestId('stage-responsible').textContent).toContain(t('role.pmShort'))
    cleanup()
    render(wrap(<CockpitSummary change={change({ status: 'in_assessment' })}
      gates={[]} pendingDeviations={0} onAdvance={() => {}} advancing={false} />))
    expect(screen.queryByTestId('stage-responsible')).toBeNull()
  })
})
