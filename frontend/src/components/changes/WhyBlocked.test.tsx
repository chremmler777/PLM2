import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest'
import { render, screen, fireEvent, cleanup, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import CockpitSummary from './CockpitSummary'
import OverrideDialog, { AbsorbDialog } from './OverrideDialog'
import TransitionDeviationsPanel from './TransitionDeviationsPanel'
import type { ChangeDetail } from '../../types/change'
import { changesApi } from '../../api/changes'
import { deciderGroup } from '../../lib/overrideRules'

vi.mock('../../api/changes', () => ({
  changesApi: {
    proposeDeviation: vi.fn().mockResolvedValue({ id: 9, status: 'pending' }),
    absorb: vi.fn().mockResolvedValue({ id: 10, status: 'pending' }),
    decideDeviation: vi.fn(),
    getRouting: vi.fn(),
  },
}))

const change = (over: Partial<ChangeDetail> = {}): ChangeDetail => ({
  id: 7, change_number: 'CR-2026-0007', project_id: 1, title: 'Housing fix',
  change_type: 'tooling', priority: 'medium', status: 'costing', customer_relevant: true,
  raised_by: 1, customer_response: 'pending', lead_id: 5, lead_name: 'Eva Eng',
  created_at: '2026-07-01T00:00:00', updated_at: '2026-07-01T00:00:00',
  impacted_items: [], assessments: [], attachments: [], ...over,
} as ChangeDetail)

const wrap = (ui: React.ReactElement) => (
  <QueryClientProvider client={new QueryClient()}>{ui}</QueryClientProvider>
)

describe('Why blocked (spec §0)', () => {
  beforeEach(() => { vi.clearAllMocks() })
  afterEach(cleanup)

  const costing = change({ next_step: { to: 'quoting', items: [
    { key: 'costing_input', kind: 'soft', n: 1, rule: 'costing_not_finalized',
      who: 'Process Engineer (Nathan, due Thu 22 Oct)' },
  ] } })

  it('names the owner and offers one Override bound to the rule', () => {
    const onOverride = vi.fn()
    render(wrap(<CockpitSummary change={costing} gates={[]} pendingDeviations={0}
      onAdvance={() => {}} advancing={false} onOverride={onOverride} />))
    const row = screen.getByTestId('why-costing_input')
    expect(row.textContent).toContain('Process Engineer (Nathan, due Thu 22 Oct)')
    fireEvent.click(screen.getByTestId('why-override-costing_not_finalized'))
    expect(onOverride).toHaveBeenCalledWith('quoting', 'costing_not_finalized')
  })

  it('release sign-offs on an older offer: the row signs again, only the viewer\'s side', () => {
    const onSign = vi.fn()
    const rel = change({ status: 'in_validation', next_step: { to: 'released', items: [
      { key: 'release_signoffs', kind: 'hard', exits: ['sign'], sides: ['pm', 'quality'],
        detail: 'v3', who: 'Project Management and Quality' },
    ] } })
    render(wrap(<CockpitSummary change={rel} gates={[]} pendingDeviations={0}
      onAdvance={() => {}} advancing={false} onSign={onSign} maySign={(s) => s === 'quality'} />))
    expect(screen.queryByTestId('why-sign-pm')).toBeNull()
    const btn = screen.getByTestId('why-sign-quality')
    expect(btn.textContent).toBe('Sign as Quality for v3')
    fireEvent.click(btn)
    expect(onSign).toHaveBeenCalledWith('quality')
  })

  it('no offer sent: the sign button names no empty version', () => {
    const rel = change({ status: 'in_validation', next_step: { to: 'released', items: [
      { key: 'release_signoffs', kind: 'hard', exits: ['sign'], sides: ['pm'],
        who: 'Project Management' },
    ] } })
    render(wrap(<CockpitSummary change={rel} gates={[]} pendingDeviations={0}
      onAdvance={() => {}} advancing={false} onSign={vi.fn()} maySign={() => true} />))
    expect(screen.getByTestId('why-sign-pm').textContent).toBe('Sign as PM')
  })

  it('a hard row says "No override" in words; a pending routing change is decided, not overridden', () => {
    const c = change({ status: 'in_assessment', next_step: { to: 'costing', items: [
      { key: 'routing_deviation', kind: 'soft', rule: 'routing_deviation_pending', who: 'Project Management' },
      { key: 'impacted_items', kind: 'hard', who: 'Eva Eng' },
    ] } })
    render(wrap(<CockpitSummary change={c} gates={[]} pendingDeviations={0}
      onAdvance={() => {}} advancing={false} onOverride={vi.fn()} />))
    expect(screen.queryByTestId('why-override-routing_deviation_pending')).toBeNull()
    expect(screen.getByTestId('why-impacted_items').textContent).toContain('No override.')
  })

  it('offers one Override per rule, not one per row', () => {
    const capture = change({ status: 'captured', next_step: { to: 'scoping', items: [
      { key: 'description', kind: 'soft', rule: 'capture_incomplete' },
      { key: 'attachment', kind: 'soft', rule: 'capture_incomplete' },
    ] } })
    render(wrap(<CockpitSummary change={capture} gates={[]} pendingDeviations={0}
      onAdvance={() => {}} advancing={false} onOverride={vi.fn()} />))
    expect(screen.getAllByTestId('why-override-capture_incomplete')).toHaveLength(1)
    expect(screen.getByTestId('why-attachment').querySelector('button')).not.toBeNull()
  })

  it('hides Override from a viewer who may not take the step', () => {
    render(wrap(<CockpitSummary change={costing} gates={[]} pendingDeviations={0}
      onAdvance={() => {}} advancing={false} onOverride={vi.fn()} may={() => false} />))
    expect(screen.queryByTestId('why-override-costing_not_finalized')).toBeNull()
  })

  it('shows an asked override instead of a second button', () => {
    const asked = change({ next_step: { to: 'quoting', items: [
      { key: 'costing_input', kind: 'soft', n: 1, rule: 'costing_not_finalized',
        override: { id: 4, status: 'pending' } },
    ] } })
    render(wrap(<CockpitSummary change={asked} gates={[]} pendingDeviations={0}
      onAdvance={() => {}} advancing={false} onOverride={vi.fn()} />))
    expect(screen.queryByTestId('why-override-costing_not_finalized')).toBeNull()
    expect(screen.getByTestId('why-override-state-costing_not_finalized').textContent)
      .toContain('Override #4 asked')
  })

  it('a hard rule has no Override and names its only way out', () => {
    const failed = change({ status: 'in_validation', next_step: { to: 'released', items: [
      { key: 'validation_failed', kind: 'hard', n: 1, exits: ['concession'], who: 'Tool Engineer: Part weight validated' },
    ] } })
    render(wrap(<CockpitSummary change={failed} gates={[]} pendingDeviations={0}
      onAdvance={() => {}} advancing={false} onOverride={vi.fn()} />))
    const row = screen.getByTestId('why-validation_failed')
    expect(row.textContent).toContain('No override.')
    expect(row.textContent).toContain('a concession (Quality)')
    expect(row.querySelector('button')).toBeNull()
  })

  it('an open price offers Absorb only to who may ask it', () => {
    const open = change({ status: 'released', next_step: { to: 'closed', items: [
      { key: 'price_open', kind: 'hard', exits: ['customer_accepts', 'absorb'] },
    ] } })
    const onAbsorb = vi.fn()
    const { unmount } = render(wrap(<CockpitSummary change={open} gates={[]} pendingDeviations={0}
      onAdvance={() => {}} advancing={false} onAbsorb={onAbsorb} canAbsorb={false} />))
    expect(screen.queryByTestId('why-absorb')).toBeNull()
    unmount()
    render(wrap(<CockpitSummary change={open} gates={[]} pendingDeviations={0}
      onAdvance={() => {}} advancing={false} onAbsorb={onAbsorb} canAbsorb />))
    fireEvent.click(screen.getByTestId('why-absorb'))
    expect(onAbsorb).toHaveBeenCalled()
  })
})

describe('OverrideDialog', () => {
  beforeEach(() => { vi.clearAllMocks() })
  afterEach(cleanup)

  it('needs a reason pick and a note, says whose OK, binds the rule', async () => {
    render(wrap(<OverrideDialog changeId={7} to="released" rule="lessons_missing"
      customerRelevant leadName="Eva Eng" onClose={() => {}} />))
    expect(screen.getByTestId('override-needs').textContent).toContain('a Quality member')
    const submit = screen.getByTestId('override-submit') as HTMLButtonElement
    fireEvent.change(screen.getByTestId('override-note'), { target: { value: 'lessons on Friday' } })
    expect(submit.disabled).toBe(true)
    fireEvent.click(screen.getByTestId('override-reason-in_parallel'))
    expect(submit.disabled).toBe(false)
    fireEvent.click(submit)
    await waitFor(() => expect(changesApi.proposeDeviation).toHaveBeenCalledWith(7, {
      to_status: 'released', reason: 'lessons on Friday', reason_code: 'in_parallel',
      guard_key: 'lessons_missing',
    }))
  })

  it('names the lead for the run team', () => {
    render(wrap(<OverrideDialog changeId={7} to="quoting" rule="costing_not_finalized"
      customerRelevant leadName="Eva Eng" onClose={() => {}} />))
    expect(screen.getByTestId('override-needs').textContent)
      .toContain('Eva Eng (lead), a Project Management member or an admin')
  })

  it('Absorb asks PM or Management (internal: the approver)', async () => {
    render(wrap(<AbsorbDialog changeId={7} customerRelevant onClose={() => {}} />))
    expect(screen.getByTestId('absorb-needs').textContent).toContain('Project Management or Management')
    fireEvent.click(screen.getByTestId('absorb-reason-small_amount'))
    fireEvent.change(screen.getByTestId('absorb-note'), { target: { value: 'EUR 300 over' } })
    expect((screen.getByTestId('absorb-submit') as HTMLButtonElement).disabled).toBe(true)
    fireEvent.change(screen.getByTestId('absorb-note'), { target: { value: 'EUR 300 over, no supplement' } })
    fireEvent.click(screen.getByTestId('absorb-submit'))
    await waitFor(() => expect(changesApi.absorb).toHaveBeenCalledWith(7, {
      reason_code: 'small_amount', note: 'EUR 300 over, no supplement' }))
    cleanup()
    render(wrap(<AbsorbDialog changeId={7} customerRelevant={false} onClose={() => {}} />))
    expect(screen.getByTestId('absorb-needs').textContent).toContain('internal approver')
  })

  it('mirrors the backend decider groups', () => {
    expect(deciderGroup('timing_not_validated', 'in_implementation')).toBe('quality')
    expect(deciderGroup('validation_open', 'released')).toBe('quality')
    expect(deciderGroup('price_open', 'closed', true)).toBe('pm_mgmt')
    expect(deciderGroup('price_open', 'closed', false)).toBe('approver')
    expect(deciderGroup('costing_not_finalized', 'quoting')).toBe('run')
  })
})

describe('TransitionDeviationsPanel', () => {
  afterEach(cleanup)

  it('shows the rule an override waives and whose OK it waits for', () => {
    render(wrap(<TransitionDeviationsPanel changeId={7} decidableIds={[]} deviations={[{
      id: 3, to_status: 'quoting', reason: 'customer wants it Monday', status: 'pending',
      proposed_by: 5, proposed_at: '2026-10-14T00:00:00', guard_key: 'costing_not_finalized',
      reason_code: 'customer_date', deciders: { group: 'run', lead_name: 'Eva Eng' },
    }]} />))
    expect(screen.getByTestId('deviation-rule-3').textContent)
      .toBe('Waives: Costing not finalized · Customer date / urgent')
    expect(screen.getByTestId('deviation-waiting-3').textContent)
      .toContain('Waiting for the OK of Eva Eng (lead)')
  })
})
