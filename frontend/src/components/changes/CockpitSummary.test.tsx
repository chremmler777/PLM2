import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, fireEvent, cleanup, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import CockpitSummary, { nextStepFor, pluralizeLabel } from './CockpitSummary'
import type { ChangeDetail, MyAction } from '../../types/change'
import { t } from '../../i18n/cmLabels'
import { changesApi } from '../../api/changes'

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
      change={change({ customer_response: 'accepted', pm_signed_by: 1, quality_signed_by: 2, assessments: [
        { id: 1, department_id: 2, verdict: 'pending', stage_order: 1,
          rasic_letter: 'R', status: 'active', owner_id: null, owner_name: null,
          accepted_at: null, due_date: '2026-06-01T00:00:00', overdue: true },
      ] as ChangeDetail['assessments'] })}
      // status 'quoted', accepted and signed -> next is 'approved' -> next is 'approved'/'rejected'. Neither gate below
      // guards that transition (feasibility guards in_assessment, budget guards
      // costing, release guards in_implementation), so none should be amber.
      gates={[
        { gate_key: 'feasibility', decision: 'yes' },
        { gate_key: 'budget', decision: 'no' },
        { gate_key: 'release', decision: 'no' },
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
    expect(screen.getByTestId('blocked-pending-deviations')).toBeDefined()
    expect(screen.getByText(/Overdue assessments/)).toBeDefined()
    expect(screen.getByTestId('next-resolve-first').textContent).toBe('First: Pending deviations: 1')
    // One truth: with blockers listed, the move is not the primary. The
    // primary says how many and leads to the first; the move stays secondary.
    const resolve = screen.getByTestId('next-resolve-blockers')
    expect(resolve.textContent).toBe('Resolve 2 blockers first')
    expect(resolve.className).toContain('bg-sky-700')
    const move = screen.getByRole('button', { name: 'Record approval' })
    expect(move.className).not.toContain('bg-sky-700')
    expect(move.title).toContain('2 blockers open')
    fireEvent.click(move)
    expect(onAdvance).toHaveBeenCalledWith('approved')
  })

  it('without blockers the move is the one primary, named by its verb', () => {
    const onAdvance = vi.fn()
    render(wrap(<CockpitSummary
      change={change({ customer_response: 'accepted', pm_signed_by: 1, quality_signed_by: 2 })}
      gates={[]} pendingDeviations={0} onAdvance={onAdvance} advancing={false} />))
    expect(screen.queryByTestId('next-resolve-blockers')).toBeNull()
    const primary = screen.getByRole('button', { name: 'Record approval' })
    expect(primary.className).toContain('bg-sky-700')
    fireEvent.click(primary)
    expect(onAdvance).toHaveBeenCalledWith('approved')
  })

  it('"Resolve first" leads to the first blocker that has a place to go', () => {
    const onGo = vi.fn()
    render(wrap(<CockpitSummary change={change({ status: 'in_validation' })}
      gates={[]} pendingDeviations={0} onAdvance={() => {}} advancing={false} onGo={onGo}
      waits={[
        { key: 'info', text: 'FYI only', info: true },
        { key: 'checks', text: 'validation checks open (2 departments)', tab: 'release' },
        { key: 'lessons', text: 'Lessons learned step not done', tab: 'release' },
      ]} />))
    const resolve = screen.getByTestId('next-resolve-blockers')
    // Info lines are listed but hold nothing up.
    expect(resolve.textContent).toBe('Resolve 2 blockers first')
    expect(screen.getByTestId('next-resolve-first').textContent).toContain('validation checks open')
    fireEvent.click(resolve)
    expect(onGo).toHaveBeenCalledWith('release')
    expect(screen.getByTestId('next-to-released').textContent).toBe('Release change')
  })

  it('does not list an action that is the same job as the next step', () => {
    render(wrap(<CockpitSummary change={change({ status: 'quoting' })}
      gates={[]} pendingDeviations={0} onAdvance={() => {}} advancing={false}
      actions={[
        { kind: 'offer_build', label: 'Build and send the offer', target_tab: 'offer' },
        { kind: 'deviation_decision', label: 'Decide deviation #3', target_tab: 'overview', deviation_id: 3 },
      ] as MyAction[]} />))
    expect(screen.getAllByText('Build and send the offer')).toHaveLength(1)
    expect(screen.getByTestId('your-actions').textContent).toContain('Decide deviation #3')
  })

  it('lists stage-task actions by label, links their target_tab, and skips the step twins', () => {
    const onAction = vi.fn()
    render(wrap(<CockpitSummary change={change({ status: 'quoting' })}
      gates={[]} pendingDeviations={0} onAdvance={() => {}} advancing={false}
      onAction={onAction}
      actions={[
        // create_quote is the task list's name for the offer step: not twice.
        { kind: 'create_quote', label: 'Create the quote', target_tab: 'commercial' },
        { kind: 'costing_update', label: 'Costing update after scope change',
          target_tab: 'commercial', department_id: 4, hint: 'Scope changed' },
        { kind: 'bank_build', label: 'Decide the bank build', target_tab: 'implementation' },
        { kind: 'scoping_wrapup', label: 'Wrap up scoping', target_tab: 'scoping' },
      ] as MyAction[]} />))
    const box = screen.getByTestId('your-actions')
    expect(box.textContent).not.toContain('Create the quote')
    expect(screen.getAllByText('Build and send the offer')).toHaveLength(1)
    const costing = screen.getByTestId('action-costing_update')
    expect(costing.getAttribute('title')).toBe('Scope changed')
    fireEvent.click(costing)
    expect(onAction).toHaveBeenLastCalledWith('commercial')
    fireEvent.click(screen.getByTestId('action-bank_build'))
    expect(onAction).toHaveBeenLastCalledWith('implementation')
    fireEvent.click(screen.getByTestId('action-scoping_wrapup'))
    expect(onAction).toHaveBeenLastCalledWith('scoping')
  })

  it('does not list kickoff next to the hand-over-to-scoping button', () => {
    render(wrap(<CockpitSummary change={change({ status: 'captured' })}
      gates={[]} pendingDeviations={0} onAdvance={() => {}} advancing={false}
      actions={[
        { kind: 'kickoff', label: 'Hand over to scoping', target_tab: 'overview' },
        { kind: 'deviation_decision', label: 'Decide deviation #3', target_tab: 'overview', deviation_id: 3 },
      ] as MyAction[]} />))
    expect(screen.getByTestId('next-to-scoping')).toBeTruthy()
    expect(screen.getByTestId('your-actions').textContent).not.toContain('Hand over to scoping')
  })

  it('compact bar: the same next step and the blockers count, from one source', () => {
    const onShowOverview = vi.fn()
    render(wrap(<CockpitSummary variant="compact" change={change({ status: 'in_validation' })}
      gates={[]} pendingDeviations={0} onAdvance={() => {}} advancing={false}
      onShowOverview={onShowOverview}
      waits={[{ key: 'checks', text: 'validation checks open', tab: 'release' }]} />))
    expect(screen.getByTestId('cockpit-compact')).toBeDefined()
    expect(screen.getByTestId('compact-blockers').textContent).toBe('1 blocker')
    fireEvent.click(screen.getByTestId('compact-blockers'))
    expect(onShowOverview).toHaveBeenCalled()
    expect(screen.getByTestId('next-resolve-blockers').textContent).toBe('Resolve 1 blocker first')
    expect(screen.queryByText('Blocked by')).toBeNull()
  })

  it('compact bar without blockers shows the primary step itself', () => {
    render(wrap(<CockpitSummary variant="compact" change={change({ status: 'released' })}
      gates={[]} pendingDeviations={0} onAdvance={() => {}} advancing={false} />))
    expect(screen.getByTestId('next-to-closed').textContent).toBe('Close change')
    expect(screen.queryByTestId('compact-blockers')).toBeNull()
  })

  it('compact bar says why a held step is held, beside the button', () => {
    render(wrap(<CockpitSummary variant="compact" change={change({ status: 'released' })}
      gates={[]} pendingDeviations={0} onAdvance={() => {}} advancing={false}
      needs={(k) => (k === 'to:closed' ? 'Needs the Project Manager or the change lead' : null)} />))
    expect((screen.getByTestId('next-to-closed') as HTMLButtonElement).disabled).toBe(true)
    expect(screen.getByTestId('compact-held').textContent).toBe('Needs the Project Manager or the change lead')
  })

  it('a warning sits beside a live step and never disables it', () => {
    const onAdvance = vi.fn()
    const warns = (k: string) => (k === 'to:closed' ? 'Check that nothing was forgotten.' : null)
    render(wrap(<CockpitSummary change={change({ status: 'released' })}
      gates={[]} pendingDeviations={0} onAdvance={onAdvance} advancing={false} warns={warns} />))
    const go = screen.getByTestId('next-to-closed') as HTMLButtonElement
    expect(go.disabled).toBe(false)
    expect(screen.getByTestId('next-warn-closed').textContent).toBe('Check that nothing was forgotten.')
    expect(screen.queryByTestId('next-needs')).toBeNull()
    fireEvent.click(go)
    expect(onAdvance).toHaveBeenCalledWith('closed')
    cleanup()
    render(wrap(<CockpitSummary variant="compact" change={change({ status: 'released' })}
      gates={[]} pendingDeviations={0} onAdvance={() => {}} advancing={false} warns={warns} />))
    expect((screen.getByTestId('next-to-closed') as HTMLButtonElement).disabled).toBe(false)
    expect(screen.getByTestId('compact-warn').textContent).toBe('Check that nothing was forgotten.')
  })

  it('names an undecided gate "not decided yet", not "n/a"', () => {
    render(wrap(<CockpitSummary change={change({ status: 'scoping', assessments: [] })}
      gates={[{ gate_key: 'feasibility', decision: null as unknown as 'na' }]}
      pendingDeviations={0} onAdvance={() => {}} advancing={false} />))
    expect(screen.getByText(/Feasibility gate: not decided yet/)).toBeDefined()
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
        { gate_key: 'budget', decision: 'no' },
        { gate_key: 'release', decision: 'no' },
      ]}
      pendingDeviations={0} onAdvance={() => {}} advancing={false} />))
    expect(screen.queryByText(/Nothing blocking/)).toBeNull()
    // In words, no "NA" jargon.
    expect(screen.getByText(/Feasibility gate: not answered Yes \(it is n\/a\)/)).toBeDefined()
    expect(screen.queryByText(/\bNA\b/)).toBeNull()
    const feasibilityRow = screen.getByText(/Feasibility/).closest('li')
    expect(feasibilityRow?.getAttribute('data-blocking')).toBe('true')
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
        { gate_key: 'feasibility', decision: 'no' },
        { gate_key: 'budget', decision: 'no' },
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
        { gate_key: 'feasibility', decision: 'no' },
        { gate_key: 'budget', decision: 'no' },
      ]}
      pendingDeviations={0} onAdvance={() => {}} advancing={false}
      onResolveGate={onResolveGate} canSeeGovernance={false} />))
    expect(screen.queryByRole('button', { name: /Feasibility/ })).toBeNull()
    expect(screen.getByText(/Feasibility/)).toBeDefined()
  })

  it('hides a later gate nobody has set (no "Gate Release: NA" noise)', () => {
    render(wrap(<CockpitSummary change={change({ status: 'quoted', assessments: [] })}
      gates={[{ gate_key: 'release', decision: 'na' }]}
      pendingDeviations={0} onAdvance={() => {}} advancing={false} />))
    expect(screen.getByText(/Nothing blocking/)).toBeDefined()
    expect(screen.queryByText(/Release gate/)).toBeNull()
  })

  it('keeps the green nothing-blocking state while still listing later gates as muted', () => {
    render(wrap(<CockpitSummary change={change({ status: 'quoted', assessments: [] })}
      gates={[{ gate_key: 'budget', decision: 'no' }]}
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

  it('lists backup items apart, muted, with the main name, and still actionable (spec §18)', () => {
    const onAction = vi.fn()
    render(wrap(<CockpitSummary change={change()}
      gates={[]} pendingDeviations={0} onAdvance={() => {}} advancing={false}
      actions={[
        { kind: 'assessment', label: 'Submit assessment for R&D', target_tab: 'assessments', assessment_id: 1, role: 'main' },
        { kind: 'impact_confirm', label: 'Confirm impacted items', target_tab: 'impacted', role: 'backup', main_name: 'Cody Hrtyanski' },
      ]}
      onAction={onAction} />))
    const main = screen.getByTestId('your-actions')
    const backup = screen.getByTestId('backup-actions')
    expect(backup.textContent).toContain(t('actions.asBackup'))
    expect(backup.textContent).toContain('Cody Hrtyanski')
    expect(backup.textContent).toContain('Confirm impacted items')
    expect(main.textContent).toContain('Submit assessment for R&D')
    fireEvent.click(screen.getByRole('button', { name: /Confirm impacted items/ }))
    expect(onAction).toHaveBeenCalledWith('impacted')
  })

  it('shows only the "As backup" group when every item is backup', () => {
    render(wrap(<CockpitSummary change={change()}
      gates={[]} pendingDeviations={0} onAdvance={() => {}} advancing={false}
      actions={[{ kind: 'impact_confirm', label: 'Confirm impacted items', target_tab: 'impacted', role: 'backup', main_name: 'Cody' }]} />))
    expect(screen.queryByTestId('your-actions')).toBeNull()
    expect(screen.getByTestId('backup-actions')).toBeDefined()
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
    const pointer = screen.getByText(/Record the scoping meeting: proceed/)
    fireEvent.click(pointer)
    expect(onAction).toHaveBeenCalledWith('scoping')
  })

  it('points a viewer who cannot record the meeting at Scoping without telling them to record it', () => {
    render(wrap(<CockpitSummary change={change({ status: 'scoping', assessments: [] })}
      gates={[]} pendingDeviations={0} onAdvance={() => {}} advancing={false}
      canRecordMeeting={false} />))
    expect(screen.queryByText(/Record the scoping meeting/)).toBeNull()
    expect(screen.getByText(/The scoping meeting decides/)).toBeDefined()
  })

  it('offers Reject at capture to a viewer who may reject, and hides it otherwise', () => {
    render(wrap(<CockpitSummary change={change({ status: 'captured', assessments: [] })}
      gates={[]} pendingDeviations={0} onAdvance={() => {}} advancing={false}
      may={(to) => to === 'rejected' || to === 'scoping'} />))
    expect(screen.getByRole('button', { name: new RegExp(t('next.reject')) })).toBeDefined()
    cleanup()
    render(wrap(<CockpitSummary change={change({ status: 'captured', assessments: [] })}
      gates={[]} pendingDeviations={0} onAdvance={() => {}} advancing={false}
      may={(to) => to === 'scoping'} />))
    expect(screen.queryByRole('button', { name: new RegExp(t('next.reject')) })).toBeNull()
  })

  it('still offers the ordinary advance button on statuses the meeting does not own', () => {
    render(wrap(<CockpitSummary change={change({ status: 'captured', assessments: [] })}
      gates={[]} pendingDeviations={0} onAdvance={() => {}} advancing={false} />))
    expect(screen.getByRole('button', { name: 'Hand over to scoping' })).toBeDefined()
    expect(screen.queryByText(/Record the scoping meeting: proceed/)).toBeNull()
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

  it('tags every stage with its agreed owner — Sales, PM or Team', () => {
    captured()
    expect(screen.getByTestId('stage-responsible').textContent).toContain(t('role.sales'))
    cleanup()
    render(wrap(<CockpitSummary change={change({ status: 'scoping' })}
      gates={[]} pendingDeviations={0} onAdvance={() => {}} advancing={false} />))
    expect(screen.getByTestId('stage-responsible').textContent).toContain(t('role.pmShort'))
    cleanup()
    // Assessment and costing are the team's stages (agreed 2026-08-12).
    render(wrap(<CockpitSummary change={change({ status: 'in_assessment' })}
      gates={[]} pendingDeviations={0} onAdvance={() => {}} advancing={false} />))
    expect(screen.getByTestId('stage-responsible').textContent).toContain(t('role.team'))
  })
})

describe('CockpitSummary waits', () => {
  afterEach(cleanup)

  const waits = [
    { key: 'assessment-round', text: 'Assessment: waiting on Development, Tool Engineer (1/3)',
      tab: 'assessments' as const },
  ]

  it('lists what the change waits on under Blocked by, instead of nothing blocking', () => {
    const onGo = vi.fn()
    render(wrap(<CockpitSummary change={change({ status: 'in_assessment', assessments: [] })}
      gates={[]} pendingDeviations={0} onAdvance={() => {}} advancing={false}
      waits={waits} onGo={onGo} />))
    expect(screen.queryByText(/Nothing blocking/)).toBeNull()
    const row = screen.getByTestId('wait-assessment-round')
    expect(row.textContent).toContain('waiting on Development, Tool Engineer (1/3)')
    fireEvent.click(screen.getByRole('button', { name: /waiting on Development/ }))
    expect(onGo).toHaveBeenCalledWith('assessments')
  })

  it('names held departments through their wait line', () => {
    render(wrap(<CockpitSummary change={change({
      status: 'in_assessment', blocked_department_ids: [2, 4], assessments: [],
    })} gates={[]} pendingDeviations={0} onAdvance={() => {}} advancing={false}
      waits={[{ key: 'blocked-departments', text: 'Held by own concern: Tool Engineer',
        tab: 'assessments' }]} />))
    expect(screen.queryByText(/Nothing blocking/)).toBeNull()
    expect(screen.getByTestId('wait-blocked-departments').textContent).toContain('Tool Engineer')
  })

  it('says nothing is blocking when there are no waits', () => {
    render(wrap(<CockpitSummary change={change({
      status: 'in_assessment', blocked_department_ids: [], assessments: [],
    })} gates={[]} pendingDeviations={0} onAdvance={() => {}} advancing={false} waits={[]} />))
    expect(screen.getByText(/Nothing blocking/)).toBeDefined()
  })

  it('engineering review: lock the impact, then answer the review; never a raw advance', () => {
    const base = { customer_relevant: false, pm_signed_by: null, quality_signed_by: null, timing_validated_at: null,
      origin: 'engineering_review', status: 'scoping' }
    expect(nextStepFor({ ...base, impact_confirmed_at: null } as never))
      .toEqual([{ kind: 'go', key: 'lock-impact', label: 'Lock the impacted set (Development)', tab: 'impacted' }])
    expect(nextStepFor({ ...base, impact_confirmed_at: '2026-09-25T08:00:00' } as never))
      .toEqual([{ kind: 'go', key: 'review', label: 'Answer the review', tab: 'review' }])
    expect(nextStepFor({ ...base, status: 'closed' } as never)).toEqual([])
  })

  it('the review step waits once the viewer answered (P3 final walk)', () => {
    const base = { status: 'scoping', origin: 'engineering_review', customer_relevant: true,
      customer_response: null, pm_signed_by: null, quality_signed_by: null,
      timing_validated_at: null, internal_approved_at: null, impact_confirmed_at: '2026-09-25T08:00:00' }
    const mine = { answer: null, can_answer: true }
    const done = { answer: 'no_impact', can_answer: true }
    const other = { answer: null, can_answer: false }
    expect(nextStepFor(base as never, null, { open_count: 2, impact_count: 0, answers: [mine, other] }))
      .toEqual([{ kind: 'go', key: 'review', label: 'Answer the review', tab: 'review' }])
    expect(nextStepFor(base as never, null, { open_count: 1, impact_count: 0, answers: [done, other] }))
      .toEqual([{ kind: 'wait', key: 'review-answers', text: 'Waiting on 1 review answer' }])
    expect(nextStepFor(base as never, null, { open_count: 0, impact_count: 1, can_escalate: true, answers: [done] })[0])
      .toMatchObject({ kind: 'go', key: 'review-escalate' })
    expect(nextStepFor(base as never, null, { open_count: 0, impact_count: 1, can_escalate: false, answers: [done] })[0])
      .toMatchObject({ kind: 'wait', key: 'review-escalate' })
    expect(nextStepFor(base as never, null, { open_count: 0, impact_count: 0, answers: [done] })[0])
      .toMatchObject({ kind: 'wait', key: 'review-done' })
  })

  it('F3: a dedicated act drives quoting, quoted and approved; no raw transition buttons', () => {
    const base = { customer_relevant: true, pm_signed_by: null, quality_signed_by: null, timing_validated_at: null }
    expect(nextStepFor({ ...base, status: 'quoting', customer_response: 'pending' } as never))
      .toEqual([{ kind: 'go', key: 'offer', label: 'Build and send the offer', tab: 'offer' }])
    expect(nextStepFor({ ...base, status: 'quoted', customer_response: 'pending' } as never)[0])
      .toMatchObject({ kind: 'go', key: 'answer', tab: 'offer' })
    expect(nextStepFor({ ...base, status: 'quoted', customer_response: 'accepted' } as never)[0])
      .toMatchObject({ kind: 'go', key: 'signoff' })
    expect(nextStepFor({ ...base, status: 'approved', customer_response: 'accepted' } as never)[0])
      .toMatchObject({ kind: 'go', key: 'validate-timing', tab: 'timing' })
    expect(nextStepFor({ ...base, status: 'approved', customer_response: 'accepted',
      timing_validated_at: '2026-09-20' } as never)).toEqual([{ kind: 'advance', to: 'in_implementation' }])
    expect(nextStepFor({ ...base, status: 'in_validation', customer_response: 'accepted' } as never))
      .toEqual([{ kind: 'advance', to: 'released' }])
  })

  it('offers a quiet "Start implementation" alongside timing validation, for the deviation retry loop', () => {
    const base = { customer_relevant: true, pm_signed_by: 1, quality_signed_by: 2, timing_validated_at: null }
    expect(nextStepFor({ ...base, status: 'approved', customer_response: 'accepted' } as never)).toEqual([
      { kind: 'go', key: 'validate-timing', label: 'Validate the timing', tab: 'timing' },
      { kind: 'advance', to: 'in_implementation', label: t('cockpit.startImplementation'), hint: t('cockpit.startImplementationHint') },
    ])
  })

  it('renders "Start implementation" as a secondary, quiet button with its tooltip, and advances on click', () => {
    const onAdvance = vi.fn()
    render(wrap(<CockpitSummary change={change({
      status: 'approved', customer_response: 'accepted', pm_signed_by: 1, quality_signed_by: 2,
      timing_validated_at: null,
    })} gates={[]} pendingDeviations={0} onAdvance={onAdvance} advancing={false} />))
    const primary = screen.getByRole('button', { name: 'Validate the timing' })
    expect(primary.className).toContain('bg-sky-700')
    const secondary = screen.getByRole('button', { name: t('cockpit.startImplementation') })
    expect(secondary.className).not.toContain('bg-sky-700')
    expect((secondary as HTMLButtonElement).disabled).toBe(false)
    expect(secondary.title).toBe(t('cockpit.startImplementationHint'))
    fireEvent.click(secondary)
    expect(onAdvance).toHaveBeenCalledWith('in_implementation')
  })

  it('at costing, an internal change without internal_approved_at is sent to Approval instead of straight to Approved', () => {
    expect(nextStepFor({
      status: 'costing', customer_relevant: false, customer_response: 'pending',
      pm_signed_by: null, quality_signed_by: null, timing_validated_at: null, internal_approved_at: null,
    } as never)).toEqual([{ kind: 'go', key: 'internal-approval', label: t('internal.approve'), tab: 'offer' }])
    expect(nextStepFor({
      status: 'costing', customer_relevant: false, customer_response: 'pending',
      pm_signed_by: null, quality_signed_by: null, timing_validated_at: null, internal_approved_at: '2026-09-20',
    } as never)).toEqual([{ kind: 'advance', to: 'approved' }])
    // A customer-relevant change never sees the internal-approval step.
    expect(nextStepFor({
      status: 'costing', customer_relevant: true, customer_response: 'pending',
      pm_signed_by: null, quality_signed_by: null, timing_validated_at: null, internal_approved_at: null,
    } as never)).toEqual([{ kind: 'advance', to: 'quoting' }])
  })

  it('at costing, waits on cost input with no primary move to quote creation', () => {
    render(wrap(<CockpitSummary change={change({
      status: 'costing', customer_relevant: true, costing_pending_department_ids: [27, 28],
    })} gates={[]} pendingDeviations={0} onAdvance={vi.fn()} advancing={false} />))
    expect(screen.getByTestId('next-wait-costing-input').textContent)
      .toContain('Waiting on cost input from 2 departments')
    const quote = screen.getByTestId('next-to-quoting')
    expect(quote.className).not.toContain('bg-sky-700')
  })

  it('the Approve internal costs step is gated by needs("internal-approval") like any other', () => {
    render(wrap(<CockpitSummary change={change({
      status: 'costing', customer_relevant: false, internal_approved_at: null,
    })} gates={[]} pendingDeviations={0} onAdvance={vi.fn()} advancing={false}
      needs={(k) => (k === 'internal-approval' ? 'Needs the Project Manager' : null)} />))
    const btn = screen.getByRole('button', { name: t('internal.approve') }) as HTMLButtonElement
    expect(btn.disabled).toBe(true)
    expect(btn.title).toBe('Needs the Project Manager')
  })

  it('F3: at quoting the next step jumps to the offer tab, no Quoted/Approved/Rejected buttons', () => {
    const onGo = vi.fn()
    render(wrap(<CockpitSummary change={change({ status: 'quoting', customer_relevant: true })}
      gates={[]} pendingDeviations={0} onAdvance={vi.fn()} advancing={false} onGo={onGo} />))
    expect(screen.queryByRole('button', { name: /Quoted|Approved|Rejected/ })).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'Build and send the offer' }))
    expect(onGo).toHaveBeenCalledWith('offer')
  })

  it('F10: a step the viewer may not take is disabled and says who may', () => {
    const onAdvance = vi.fn()
    render(wrap(<CockpitSummary change={change({ status: 'released' })}
      gates={[]} pendingDeviations={0} onAdvance={onAdvance} advancing={false}
      needs={(k) => (k === 'to:closed' ? 'Needs the Project Manager or the change lead' : null)} />))
    const btn = screen.getByRole('button', { name: 'Close change' }) as HTMLButtonElement
    expect(btn.disabled).toBe(true)
    expect(btn.title).toBe('Needs the Project Manager or the change lead')
    expect(screen.getByTestId('next-needs').textContent).toContain('Needs the Project Manager')
  })

  it('pluralizes the backend action labels', () => {
    expect(pluralizeLabel('Decide 1 plan deviation(s): lock or escalate')).toBe('Decide 1 plan deviation: lock or escalate')
    expect(pluralizeLabel('Decide 3 plan deviation(s): lock or escalate')).toBe('Decide 3 plan deviations: lock or escalate')
  })
})

describe('CockpitSummary early stages (spec §16)', () => {
  afterEach(cleanup)
  const round = (over: Record<string, unknown> = {}) => ({
    first_stage: 1, total: 2, submitted: 1, all_submitted: false,
    waiting_on: [{ department_id: 4, department_name: 'Quality' }],
    not_feasible: [], declined_pending: [], verdicts: [], open_risks: [],
    routing_deviation_pending: false, can_close: false, ...over,
  })
  const inAssessment = change({ status: 'in_assessment' })

  it('has no primary while departments are still answering', () => {
    render(wrap(<CockpitSummary change={inAssessment} gates={[]} pendingDeviations={0}
      onAdvance={() => {}} advancing={false} assessment={round()} />))
    expect(screen.getByTestId('next-wait-waiting').textContent).toContain('Waiting on 1 department')
    expect(screen.queryByTestId('next-to-costing')).toBeNull()
    expect(screen.getByTestId('next-to-rejected').className).not.toContain('bg-sky-700')
  })

  it('offers "Close assessment" once every first-stage R/A answered', () => {
    const onAdvance = vi.fn()
    render(wrap(<CockpitSummary change={inAssessment} gates={[]} pendingDeviations={0}
      onAdvance={onAdvance} advancing={false}
      assessment={round({ waiting_on: [], all_submitted: true, submitted: 2 })} />))
    const go = screen.getByTestId('next-to-costing')
    expect(go.textContent).toBe('Close assessment')
    expect(go.className).toContain('bg-sky-700')
    fireEvent.click(go)
    expect(onAdvance).toHaveBeenCalledWith('costing')
  })

  it('offers reject, back to scoping and an override when a department is not feasible', () => {
    const onStepAction = vi.fn()
    render(wrap(<CockpitSummary change={inAssessment} gates={[]} pendingDeviations={0}
      onAdvance={() => {}} advancing={false} onStepAction={onStepAction}
      assessment={round({ waiting_on: [], all_submitted: true,
        not_feasible: [{ department_id: 27, department_name: 'Tool Engineer', has_change_ppt: true }] })} />))
    expect(screen.getByTestId('next-wait-not-feasible').textContent).toContain('Tool Engineer: not feasible')
    expect(screen.getByTestId('next-to-rejected').textContent).toBe('Reject change')
    // None of the three ways out is pre-chosen.
    expect(screen.getByTestId('next-to-rejected').className).not.toContain('bg-sky-700')
    expect(screen.getByTestId('next-to-scoping').textContent).toBe('Back to scoping')
    fireEvent.click(screen.getByTestId('next-override-costing'))
    expect(onStepAction).toHaveBeenCalledWith('override-costing')
    expect(screen.queryByTestId('next-to-costing')).toBeNull()
  })

  it('tells a department at not feasible that the lead or PM decides, with no ways out offered', () => {
    render(wrap(<CockpitSummary change={inAssessment} gates={[]} pendingDeviations={0}
      onAdvance={() => {}} advancing={false} may={() => false}
      assessment={round({ waiting_on: [], all_submitted: true,
        not_feasible: [{ department_id: 27, department_name: 'Tool Engineer', has_change_ppt: true }] })} />))
    expect(screen.getByTestId('next-wait-not-feasible').textContent)
      .toContain('Tool Engineer: not feasible. The change lead or Project Management decides how to go on.')
    expect(screen.queryByTestId('next-override-costing')).toBeNull()
    expect(screen.queryByTestId('next-to-rejected')).toBeNull()
    expect(screen.queryByTestId('next-to-scoping')).toBeNull()
  })

  it('hides steps the viewer may not take and says who may', () => {
    render(wrap(<CockpitSummary change={inAssessment} gates={[]} pendingDeviations={0}
      onAdvance={() => {}} advancing={false} may={() => false}
      assessment={round({ waiting_on: [], all_submitted: true })} />))
    expect(screen.queryByTestId('next-to-costing')).toBeNull()
    expect(screen.queryByTestId('next-to-rejected')).toBeNull()
    expect(screen.getByTestId('next-needs').textContent).toContain('change lead, Project Management or an admin')
  })

  it('makes "Send rejection letter" the step of a rejected customer change', () => {
    render(wrap(<CockpitSummary change={change({ status: 'rejected', customer_relevant: true })}
      gates={[]} pendingDeviations={0} onAdvance={() => {}} advancing={false} />))
    expect(screen.getByTestId('next-send-rejection').textContent).toBe('Send rejection letter')
  })

  it('shows no deadline on an ended change and labels the Status dates', () => {
    render(wrap(<CockpitSummary change={change({ status: 'cancelled', customer_relevant: true,
      required_by_date: '2026-10-01', deadline_state: 'on_track' })}
      gates={[]} pendingDeviations={0} onAdvance={() => {}} advancing={false} />))
    expect(screen.queryByTestId('deadline-chip')).toBeNull()
    expect(screen.getByTestId('status-dates').textContent).toBe('Created 1 Jul 2026 · last change 1 Jul 2026')
  })

  it('lists a missing lead among the kickoff needs', () => {
    render(wrap(<CockpitSummary change={change({ status: 'captured', lead_id: null, lead_name: null })}
      gates={[]} pendingDeviations={0} onAdvance={() => {}} advancing={false} />))
    expect(screen.getByTestId('kickoff-hint').textContent).toContain('No lead assigned')
  })
})

describe('CockpitSummary end states (spec §16 P1 7)', () => {
  afterEach(cleanup)
  it('names a rejected-then-closed change as such on the Status card', () => {
    render(wrap(<CockpitSummary change={change({ status: 'closed', rejected_at: '2026-09-20T00:00:00' })}
      gates={[]} pendingDeviations={0} onAdvance={() => {}} advancing={false} />))
    expect(screen.getByTestId('status-pill').textContent).toBe('Rejected, closed')
    expect(screen.getByText('Ended: no further step')).toBeDefined()
  })
})

describe('CockpitSummary gate holds the next step (final walk P2-5)', () => {
  afterEach(cleanup)

  it('disables the step a gate holds, with the reason and the way to D1', () => {
    const onResolveGate = vi.fn()
    const onAdvance = vi.fn()
    render(wrap(<CockpitSummary
      change={change({ status: 'approved', timing_validated_at: '2026-09-20T00:00:00', customer_relevant: true })}
      gates={[{ gate_key: 'release', decision: 'na' }]} pendingDeviations={0}
      onAdvance={onAdvance} advancing={false} onResolveGate={onResolveGate} />))
    const step = screen.getByTestId('next-to-in_implementation') as HTMLButtonElement
    expect(step.disabled).toBe(true)
    expect(step.title).toBe('Release gate not answered Yes (it is n/a): decide it on D1 first')
    fireEvent.click(step)
    expect(onAdvance).not.toHaveBeenCalled()
    fireEvent.click(screen.getByTestId('next-gate-release').querySelector('button')!)
    expect(onResolveGate).toHaveBeenCalledWith('release')
  })

  it('a decided gate leaves the step live', () => {
    render(wrap(<CockpitSummary
      change={change({ status: 'approved', timing_validated_at: '2026-09-20T00:00:00', customer_relevant: true })}
      gates={[{ gate_key: 'release', decision: 'yes' }]} pendingDeviations={0}
      onAdvance={() => {}} advancing={false} onResolveGate={() => {}} />))
    expect((screen.getByTestId('next-to-in_implementation') as HTMLButtonElement).disabled).toBe(false)
    expect(screen.queryByTestId('next-gate-release')).toBeNull()
  })

  it('without the governance tabs the reason names who decides, no dead-end jump', () => {
    render(wrap(<CockpitSummary
      change={change({ status: 'approved', timing_validated_at: '2026-09-20T00:00:00', customer_relevant: true })}
      gates={[{ gate_key: 'release', decision: 'no' }]} pendingDeviations={0}
      onAdvance={() => {}} advancing={false} onResolveGate={() => {}} canSeeGovernance={false} />))
    const line = screen.getByTestId('next-gate-release')
    expect(line.textContent).toContain('Release gate answered No: the change lead decides it on D1')
    expect(line.querySelector('button')).toBeNull()
  })
})

describe('CockpitSummary deviation decisions (final walk P2-3)', () => {
  afterEach(cleanup)

  it('"Decide deviation #n" opens the decision panel on that deviation', () => {
    const onDecideDeviation = vi.fn()
    const onAction = vi.fn()
    render(wrap(<CockpitSummary change={change()} gates={[]} pendingDeviations={1}
      onAdvance={() => {}} advancing={false} onAction={onAction} onDecideDeviation={onDecideDeviation}
      actions={[{ kind: 'deviation_decision', label: 'Decide deviation #12', target_tab: 'overview', deviation_id: 12 }]} />))
    fireEvent.click(screen.getByRole('button', { name: 'Decide deviation #12' }))
    expect(onDecideDeviation).toHaveBeenCalledWith(12)
    expect(onAction).not.toHaveBeenCalled()
    fireEvent.click(screen.getByTestId('blocked-pending-deviations').querySelector('button')!)
    expect(onDecideDeviation).toHaveBeenLastCalledWith()
  })
})

describe('CockpitSummary gate held step and deviations (review M1)', () => {
  afterEach(cleanup)
  const approved = () => change({ status: 'approved', timing_validated_at: '2026-09-20T00:00:00', customer_relevant: true })

  it('an approved deviation covering the step keeps it live (the gate is a soft guard)', () => {
    const onAdvance = vi.fn()
    render(wrap(<CockpitSummary change={approved()}
      gates={[{ gate_key: 'release', decision: 'no' }]} pendingDeviations={0}
      deviationTargets={{ approved: ['in_implementation'], pending: [] }}
      onAdvance={onAdvance} advancing={false} onResolveGate={() => {}} />))
    const step = screen.getByTestId('next-to-in_implementation') as HTMLButtonElement
    expect(step.disabled).toBe(false)
    fireEvent.click(step)
    expect(onAdvance).toHaveBeenCalledWith('in_implementation')
    expect(screen.getByTestId('next-gate-release').textContent).toContain('approved deviation')
    expect(screen.queryByTestId('next-ask-deviation-in_implementation')).toBeNull()
  })

  it('offers "Ask for a deviation" next to the D1 link on a gate held step', () => {
    const onAskDeviation = vi.fn()
    render(wrap(<CockpitSummary change={approved()}
      gates={[{ gate_key: 'release', decision: 'na' }]} pendingDeviations={0}
      deviationTargets={{ approved: [], pending: [] }} onAskDeviation={onAskDeviation}
      onAdvance={() => {}} advancing={false} onResolveGate={() => {}} />))
    expect((screen.getByTestId('next-to-in_implementation') as HTMLButtonElement).disabled).toBe(true)
    fireEvent.click(screen.getByTestId('next-ask-deviation-in_implementation'))
    expect(onAskDeviation).toHaveBeenCalledWith('in_implementation', 'release')
  })

  it('a pending deviation is named instead of a second ask', () => {
    render(wrap(<CockpitSummary change={approved()}
      gates={[{ gate_key: 'release', decision: 'na' }]} pendingDeviations={1}
      deviationTargets={{ approved: [], pending: ['in_implementation'] }} onAskDeviation={() => {}}
      onAdvance={() => {}} advancing={false} onResolveGate={() => {}} />))
    expect((screen.getByTestId('next-to-in_implementation') as HTMLButtonElement).disabled).toBe(true)
    expect(screen.queryByTestId('next-ask-deviation-in_implementation')).toBeNull()
    expect(screen.getByTestId('next-gate-release').textContent).toContain('waits for its decision')
  })
})

describe('CockpitSummary late assessment flag', () => {
  afterEach(() => { cleanup(); vi.restoreAllMocks() })

  const late: MyAction = {
    kind: 'late_assessment', label: 'Chase Purchasing: assessment owed on stage 1, added after the stage had passed',
    target_tab: 'assessments', assessment_id: 41, department_id: 9,
    department_name: 'Purchasing', stage_order: 1,
  }

  it('offers Take off routing beside Chase and files a remove deviation with the reason', async () => {
    const post = vi.spyOn(changesApi, 'postDeviation').mockResolvedValue({} as never)
    vi.spyOn(changesApi, 'getRouting').mockResolvedValue({
      change_id: 7, template_id: 1, template_version: 1, has_deviation: false,
      deviation_status: 'none', stages: [] })
    const onAction = vi.fn()
    render(wrap(<CockpitSummary change={change({ status: 'costing' })} gates={[]}
      pendingDeviations={0} onAdvance={vi.fn()} advancing={false}
      actions={[late]} onAction={onAction} />))
    fireEvent.click(screen.getByTestId('action-late_assessment'))
    expect(onAction).toHaveBeenCalledWith('assessments')
    fireEvent.click(screen.getByTestId('action-late-takeoff-41'))
    expect(screen.getByText('Take Purchasing off the routing')).toBeDefined()
    const submit = screen.getByTestId('take-off-routing-submit') as HTMLButtonElement
    expect(submit.disabled).toBe(true)                 // a reason is required
    fireEvent.change(screen.getByTestId('take-off-routing-reason'),
      { target: { value: 'not impacted after all' } })
    fireEvent.click(submit)
    await waitFor(() => expect(post).toHaveBeenCalledWith(7, {
      op: 'remove', department_id: 9, stage_order: 1, reason: 'not impacted after all',
    }))
  })

  it('shows the pending removal instead of a second Take off routing', async () => {
    vi.spyOn(changesApi, 'getRouting').mockResolvedValue({
      change_id: 7, template_id: 1, template_version: 1, has_deviation: true,
      deviation_status: 'pending_approval', stages: [{ stage_order: 1, departments: [
        { department_id: 9, rasic_letter: 'R', tier: 'blocking', status: 'active',
          verdict: 'pending', assessment_id: 41, pending_removal: true },
      ] }],
    })
    render(wrap(<CockpitSummary change={change({ status: 'costing' })} gates={[]}
      pendingDeviations={1} onAdvance={vi.fn()} advancing={false}
      actions={[late]} onAction={vi.fn()} />))
    expect((await screen.findByTestId('action-late-removal-41')).textContent)
      .toBe(t('routingDev.removalPending'))
    expect(screen.queryByTestId('action-late-takeoff-41')).toBeNull()
    expect(screen.getByTestId('action-late_assessment')).toBeDefined()   // Chase stays
  })

  it('offers no Take off routing on other actions', () => {
    render(wrap(<CockpitSummary change={change({ status: 'costing' })} gates={[]}
      pendingDeviations={0} onAdvance={vi.fn()} advancing={false}
      actions={[{ ...late, kind: 'assessment', label: 'Submit assessment for Purchasing' }]} />))
    expect(screen.queryByTestId('action-late-takeoff-41')).toBeNull()
  })
})
