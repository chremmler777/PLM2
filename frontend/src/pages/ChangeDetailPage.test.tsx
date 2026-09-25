import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, cleanup, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import ChangeDetailPage from './ChangeDetailPage'
import { changesApi } from '../api/changes'
import { planApi } from '../api/changePlan'
import { useDepartments } from '../hooks/queries/useWorkflows'
import type { ChangeDetail } from '../types/change'
import { t } from '../i18n/cmLabels'
import { ACTS_AS_KEY } from '../lib/actsAs'

// ChangeDetailPage fetches via changesApi (get/getImplementation/getGates/listDeviations),
// plantsApi.list, and useDepartments (workflowApi.getDepartments). Heavy tab-content
// components are mocked out — this test only exercises tab selection, which is
// URL-driven via useSearchParams.
const { change } = vi.hoisted(() => ({
  change: {
    id: 1,
    change_number: 'GB-CM-0001',
    project_id: 1,
    title: 'Test change',
    description: null,
    reason: null,
    change_type: 'physical_part',
    priority: 'medium',
    status: 'in_assessment' as ChangeDetail['status'],
    lead_id: null as number | null,
    lead_name: null,
    raised_by: 1,
    customer_response: 'pending',
    customer_relevant: undefined as boolean | undefined,
    pm_signed_by: null as number | null,
    quality_signed_by: null as number | null,
    estimated_cost: null,
    quoted_price: null as number | null,
    created_at: '2026-07-01T00:00:00',
    updated_at: '2026-07-01T00:00:00',
    required_by_date: null,
    required_by_reason: null,
    deadline_state: null,
    impact_confirmed_at: null as string | null,
    blocked_department_ids: [] as number[],
    project_number: '1864' as string | null,
    project_name: 'VW426 Atlas' as string | null,
    quoted_at: null,
    quoted_on_time: null as boolean | null,
    active_deadline: null as 'quote' | 'release' | null,
    release_due_date: null,
    release_due_reason: null,
    impacted_items: [],
    assessments: [] as ChangeDetail['assessments'],
    attachments: [],
  } satisfies ChangeDetail,
}))

/** A tab the phase has not reached: focusable, but aria-disabled. */
const locked = (el: HTMLElement) => el.getAttribute('aria-disabled') === 'true'
/** Why a tab is locked: its accessible description (the tooltip shown on hover and focus). */
const why = (el: HTMLElement) => document.getElementById(el.getAttribute('aria-describedby') ?? '')?.textContent ?? null

vi.mock('../api/changes', () => ({
  changesApi: {
    get: vi.fn().mockResolvedValue(change),
    getImplementation: vi.fn().mockResolvedValue({ ready_to_go: false }),
    getGates: vi.fn().mockResolvedValue([]),
    listDeviations: vi.fn().mockResolvedValue([]),
    myActions: vi.fn().mockResolvedValue({ actions: [], memberships: [] }),
    stageState: vi.fn().mockRejectedValue(new Error('404')),
    uploadAttachment: vi.fn(),
    signOff: vi.fn().mockResolvedValue({}),
    update: vi.fn().mockResolvedValue({}),
    customerResponse: vi.fn().mockResolvedValue({}),
    listConcerns: vi.fn().mockResolvedValue([]),
    approveInternalCosts: vi.fn().mockResolvedValue({}),
    transition: vi.fn().mockResolvedValue({}),
    changelog: vi.fn().mockResolvedValue([]),
    proposeDeviation: vi.fn().mockResolvedValue({ id: 9 }),
    decideDeviation: vi.fn().mockResolvedValue({}),
    getSummation: vi.fn().mockRejectedValue(new Error('not in this test')),
  },
}))
const releaseMock = vi.hoisted(() => ({ blockers: [] as string[] }))
vi.mock('../api/changeRelease', () => ({
  changeReleaseApi: { get: vi.fn(async () => ({ blockers: releaseMock.blockers, checks: [], lessons: [] })) },
}))
vi.mock('../components/changes/PnlCard', () => ({
  default: ({ canSeeCosts }: { canSeeCosts?: boolean }) =>
    <div>{canSeeCosts === false ? 'mock-pnl-department-only' : 'mock-pnl-card'}</div>,
}))
vi.mock('../api/changePlan', () => ({
  planApi: {
    feedback: vi.fn().mockResolvedValue({ revision: 1, required: [], all_confirmed: true, validated_at: null, validated_by_name: null }),
    get: vi.fn().mockResolvedValue({ tasks: [] }),
    deviations: vi.fn().mockResolvedValue([]),
  },
}))
const { issuesList } = vi.hoisted(() => ({ issuesList: vi.fn() }))
vi.mock('../api/validationIssues', () => ({
  validationIssuesKey: (id: number) => ['change', id, 'validation-issues'],
  validationIssuesApi: { list: (...a: unknown[]) => issuesList(...a) },
}))
vi.mock('../components/changes/validation/IssuesPanel', () => ({
  default: (p: { title?: string; focusIssueId?: number | null; changeStatus: string }) => (
    <div data-testid="mock-issues-panel">{`${p.title} status=${p.changeStatus} focus=${p.focusIssueId}`}</div>
  ),
}))
vi.mock('../api/plants', () => ({
  plantsApi: { list: vi.fn().mockResolvedValue([]) },
}))
vi.mock('../api/client', () => ({
  default: { get: vi.fn().mockResolvedValue({ data: [] }) },
}))
vi.mock('../hooks/queries/useWorkflows', () => ({
  useDepartments: vi.fn(() => ({ data: [] })),
}))
const authState = vi.hoisted(() => ({
  current: { isAdmin: false, role: 'engineer', userId: null as number | null },
}))
vi.mock('../contexts/AuthContext', () => ({
  useAuth: () => authState.current,
}))

vi.mock('../components/changes/AssessmentBuckets', () => ({ default: () => <div>mock-assessment-buckets</div> }))
vi.mock('../components/changes/D1MasterPanel', () => ({ default: () => <div>mock-d1-panel</div> }))
vi.mock('../components/changes/SummationView', () => ({ default: () => <div>mock-summation</div> }))
vi.mock('../components/changes/CostLineGrid', () => ({ default: () => <div>mock-cost-line-grid</div> }))
vi.mock('../components/changes/DeviationBanner', () => ({ default: () => <div>mock-deviation-banner</div> }))
vi.mock('../components/changes/ReasonDialog', () => ({
  default: (p: { open?: boolean; title?: string; warning?: string }) => (
    <div>mock-reason-dialog{p.open ? <p data-testid={`reason-open-${p.title}`}>{p.warning}</p> : null}</div>),
}))
vi.mock('../components/changes/ImpactTree', () => ({ default: () => <div>mock-impact-tree</div> }))
vi.mock('../components/changes/ImplementationPanel', () => ({ default: () => <div>mock-implementation-panel</div> }))
vi.mock('../components/changes/LifecycleStepper', () => ({ default: () => <div>mock-lifecycle-stepper</div> }))
// F10/finding 6: `needs` is a plain function prop — CockpitSummary itself is
// mocked out (its own tests cover rendering), so it's exercised here by
// probing it for the keys these tests care about.
const NEEDS_PROBE_KEYS = ['signoff', 'internal-approval', 'validate-timing', 'to:quoting'] as const
vi.mock('../components/changes/CockpitSummary', () => ({
  gateStateText: (d?: string | null) => (d === 'no' ? 'answered No' : d === 'na' ? 'not answered Yes (it is n/a)' : 'not decided yet'),
  default: ({ waits = [], needs, warns, onAdvance, onDecideDeviation, deviationTargets, onAskDeviation }: {
    waits?: { key: string; text: string }[]
    needs?: (step: string) => string | null
    warns?: (step: string) => string | null
    onAdvance?: (to: string) => void
    onDecideDeviation?: (id?: number) => void
    deviationTargets?: { approved: string[]; pending: string[] }
    onAskDeviation?: (to: string, gateKey: string) => void
  }) => (
    <div>mock-cockpit-summary
      <p data-testid="mock-deviation-targets">{JSON.stringify(deviationTargets ?? null)}</p>
      <button type="button" onClick={() => onAskDeviation?.('in_implementation', 'release')}>mock-ask-deviation</button>
      {waits.map((w) => <p key={w.key} data-testid={`wait-${w.key}`}>{w.text}</p>)}
      {needs && NEEDS_PROBE_KEYS.map((k) => (
        <p key={k} data-testid={`needs-${k}`}>{needs(k) ?? 'allowed'}</p>
      ))}
      {warns && <p data-testid="warns-to:quoting">{warns('to:quoting') ?? 'no warning'}</p>}
      {/* Drives the confirm dialogs the same way the real advance buttons would. */}
      <button type="button" onClick={() => onAdvance?.('in_validation')}>mock-advance-in_validation</button>
      <button type="button" onClick={() => onAdvance?.('scoping')}>mock-advance-scoping</button>
      <button type="button" onClick={() => onAdvance?.('quoting')}>mock-advance-quoting</button>
      <button type="button" onClick={() => onAdvance?.('approved')}>mock-advance-approved</button>
      <button type="button" onClick={() => onDecideDeviation?.(5)}>mock-decide-deviation</button>
    </div>
  ),
}))
vi.mock('../components/changes/DeadlineChip', () => ({ DeadlineChip: () => <div>mock-deadline-chip</div> }))
vi.mock('../components/changes/AuditTimeline', () => ({ default: () => <div>mock-audit-timeline</div> }))
vi.mock('../components/changes/offer/OfferTab', () => ({
  default: (p: { canWrite: boolean; canSeePrices: boolean; canSignPm: boolean; canSignQuality: boolean }) => (
    <div data-testid="mock-offer-tab">{`write=${p.canWrite} prices=${p.canSeePrices} pm=${p.canSignPm} quality=${p.canSignQuality}`}</div>
  ),
}))
vi.mock('../components/changes/timing/TimingTab', () => ({
  default: (p: { canEditPlan: boolean; canPublish: boolean; canSetBankBuild?: boolean; canDecideDeviation?: boolean; isAdmin?: boolean; issues?: React.ReactNode }) => (
    <div data-testid="mock-timing-tab">
      {p.issues}
      <span data-testid="timing-rights">edit={String(p.canEditPlan)} publish={String(p.canPublish)}</span>
      <span data-testid="timing-rights-2">bank={String(p.canSetBankBuild)} decide={String(p.canDecideDeviation)} admin={String(p.isAdmin)}</span>
    </div>
  ),
}))
vi.mock('../components/changes/release/ReleaseTab', () => ({
  default: (p: { canManage: boolean; onAdvance?: (to: string) => void; focusIssueId?: number | null }) => (
    <div>
      <div data-testid="mock-release-tab">manage={String(p.canManage)}</div>
      <div data-testid="mock-release-focus">focus={String(p.focusIssueId)}</div>
      <button type="button" onClick={() => p.onAdvance?.('closed')}>mock-close</button>
      <button type="button" onClick={() => p.onAdvance?.('released')}>mock-release</button>
    </div>
  ),
}))

function wrap(initialPath: string) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[initialPath]}>
        <Routes>
          <Route path="/changes/:id" element={<ChangeDetailPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>
  )
}

describe('ChangeDetailPage URL-driven tabs', () => {
  afterEach(() => {
    cleanup()
    authState.current = { isAdmin: false, role: 'engineer', userId: null }
  })

  it('renders with the D1 tab active when ?tab=d1 for an admin', async () => {
    authState.current = { isAdmin: true, role: 'admin', userId: 99 }
    wrap('/changes/1?tab=d1')
    const d1Button = await screen.findByRole('tab', { name: 'D1' })
    expect(d1Button.getAttribute('aria-selected')).toBe('true')
    expect(screen.getByText('mock-d1-panel')).toBeDefined()
  })

  it('falls back to the phase tab when ?tab is invalid', async () => {
    wrap('/changes/1?tab=bogus')
    // in_assessment works on the Assessments tab.
    const phaseButton = await screen.findByRole('tab', { name: /Assessments/ })
    expect(phaseButton.getAttribute('aria-selected')).toBe('true')
    expect(screen.queryByText('mock-d1-panel')).toBeNull()
  })

  it('F8: opens on the tab of the current phase without ?tab, and Overview stays reachable', async () => {
    wrap('/changes/1')
    const phaseButton = await screen.findByRole('tab', { name: /Assessments/ })
    expect(phaseButton.getAttribute('aria-selected')).toBe('true')
    fireEvent.click(screen.getByRole('tab', { name: 'Overview' }))
    await waitFor(() => expect(screen.getByRole('tab', { name: 'Overview' }).getAttribute('aria-selected')).toBe('true'))
  })
})

describe('ChangeDetailPage governance tab gating', () => {
  afterEach(() => {
    cleanup()
    authState.current = { isAdmin: false, role: 'engineer', userId: null }
    change.lead_id = null
    vi.mocked(useDepartments).mockReturnValue({ data: [] } as unknown as ReturnType<typeof useDepartments>)
    vi.mocked(changesApi.myActions).mockResolvedValue({ actions: [], memberships: [] })
  })

  it('hides D1/Audit buttons and the Governance group for a non-lead, non-admin viewer', async () => {
    wrap('/changes/1')
    await screen.findByRole('tab', { name: 'Overview' })
    expect(screen.queryByRole('tab', { name: 'D1' })).toBeNull()
    expect(screen.queryByRole('tab', { name: 'Audit' })).toBeNull()
    expect(screen.queryByText('Governance')).toBeNull()
  })

  it('shows the Governance group with D1 and Audit for an admin', async () => {
    authState.current = { isAdmin: true, role: 'admin', userId: 99 }
    wrap('/changes/1')
    await screen.findByRole('tab', { name: 'Overview' })
    expect(screen.getByText('Governance')).toBeDefined()
    expect(screen.getByRole('tab', { name: 'D1' })).toBeDefined()
    expect(screen.getByRole('tab', { name: 'Audit' })).toBeDefined()
  })

  it('falls back to overview content for an unauthorized ?tab=audit deep link', async () => {
    wrap('/changes/1?tab=audit')
    const overviewButton = await screen.findByRole('tab', { name: 'Overview' })
    expect(overviewButton.getAttribute('aria-selected')).toBe('true')
    expect(screen.queryByText('mock-audit-timeline')).toBeNull()
    expect(screen.queryByRole('tab', { name: 'Audit' })).toBeNull()
  })

  it('shows the Governance group with D1 and Audit for the change lead', async () => {
    change.lead_id = 42
    authState.current = { isAdmin: false, role: 'engineer', userId: 42 }
    wrap('/changes/1')
    await screen.findByRole('tab', { name: 'Overview' })
    expect(screen.getByText('Governance')).toBeDefined()
    expect(screen.getByRole('tab', { name: 'D1' })).toBeDefined()
    expect(screen.getByRole('tab', { name: 'Audit' })).toBeDefined()
  })

  it('shows the Governance group with D1 and Audit for a Quality department member', async () => {
    vi.mocked(useDepartments).mockReturnValue({
      data: [{ id: 7, name: 'Quality', flow_type: 'action', is_active: true, sort_order: 1 }],
    } as unknown as ReturnType<typeof useDepartments>)
    vi.mocked(changesApi.myActions).mockResolvedValue({ actions: [], memberships: [7] })
    authState.current = { isAdmin: false, role: 'engineer', userId: 5 }
    wrap('/changes/1')
    await screen.findByRole('tab', { name: 'Overview' })
    expect(screen.getByText('Governance')).toBeDefined()
    expect(screen.getByRole('tab', { name: 'D1' })).toBeDefined()
    expect(screen.getByRole('tab', { name: 'Audit' })).toBeDefined()
  })
})

describe('ChangeDetailPage offer tab rights', () => {
  afterEach(() => {
    cleanup()
    authState.current = { isAdmin: false, role: 'engineer', userId: null }
    change.status = 'in_assessment'
    change.customer_relevant = undefined
    change.lead_id = null
    vi.mocked(useDepartments).mockReturnValue({ data: [] } as unknown as ReturnType<typeof useDepartments>)
    vi.mocked(changesApi.myActions).mockResolvedValue({ actions: [], memberships: [] })
  })

  it('gives Sales write and price access, no sign-off', async () => {
    vi.mocked(useDepartments).mockReturnValue({
      data: [{ id: 3, name: 'Sales', flow_type: 'action', is_active: true, sort_order: 1 }],
    } as unknown as ReturnType<typeof useDepartments>)
    vi.mocked(changesApi.myActions).mockResolvedValue({ actions: [], memberships: [3] })
    authState.current = { isAdmin: false, role: 'engineer', userId: 5 }
    change.status = 'quoted'
    change.customer_relevant = true
    wrap('/changes/1?tab=offer')
    await waitFor(() => expect(screen.getByTestId('mock-offer-tab').textContent)
      .toContain('write=true prices=true pm=false quality=false'))
  })

  it('gives PM read-only prices and the PM sign-off', async () => {
    vi.mocked(useDepartments).mockReturnValue({
      data: [{ id: 9, name: 'Project Manager', flow_type: 'action', is_active: true, sort_order: 1 }],
    } as unknown as ReturnType<typeof useDepartments>)
    vi.mocked(changesApi.myActions).mockResolvedValue({ actions: [], memberships: [9] })
    authState.current = { isAdmin: false, role: 'engineer', userId: 5 }
    change.status = 'quoted'
    change.customer_relevant = true
    wrap('/changes/1?tab=offer')
    await waitFor(() => expect(screen.getByTestId('mock-offer-tab').textContent)
      .toContain('write=false prices=true pm=true quality=false'))
  })

  it('gives a Quality member no prices but the Quality sign-off', async () => {
    vi.mocked(useDepartments).mockReturnValue({
      data: [{ id: 7, name: 'Quality', flow_type: 'action', is_active: true, sort_order: 1 }],
    } as unknown as ReturnType<typeof useDepartments>)
    vi.mocked(changesApi.myActions).mockResolvedValue({ actions: [], memberships: [7] })
    authState.current = { isAdmin: false, role: 'engineer', userId: 5 }
    change.status = 'quoted'
    change.customer_relevant = true
    wrap('/changes/1?tab=offer')
    await waitFor(() => expect(screen.getByTestId('mock-offer-tab').textContent)
      .toContain('write=false prices=false pm=false quality=true'))
  })

  it('labels the tab Approval for an internal change', async () => {
    change.status = 'costing'
    change.customer_relevant = false
    wrap('/changes/1')
    expect(await screen.findByRole('tab', { name: /Approval/ })).toBeDefined()
    expect(screen.queryByRole('tab', { name: /^Offer$/ })).toBeNull()
  })
})

describe('ChangeDetailPage tab model (costing to close)', () => {
  afterEach(() => {
    cleanup()
    authState.current = { isAdmin: false, role: 'engineer', userId: null }
    change.status = 'in_assessment'
    change.customer_relevant = undefined
    vi.mocked(useDepartments).mockReturnValue({ data: [] } as unknown as ReturnType<typeof useDepartments>)
    vi.mocked(changesApi.myActions).mockResolvedValue({ actions: [], memberships: [] })
  })

  const btn = (name: RegExp) => ({ disabled: locked(screen.getByRole('tab', { name })) })

  it('unlocks costing and offer at costing, timing at approved, release at in_validation', async () => {
    change.customer_relevant = true
    change.status = 'costing' as ChangeDetail['status']
    wrap('/changes/1')
    await screen.findByRole('tab', { name: /Costing/ })
    expect(btn(/Costing/).disabled).toBe(false)
    expect(btn(/Offer/).disabled).toBe(false)
    expect(btn(/Timing/).disabled).toBe(true)
    expect(btn(/Release/).disabled).toBe(true)
    cleanup()
    change.status = 'approved' as ChangeDetail['status']
    wrap('/changes/1')
    await screen.findByRole('tab', { name: /Timing/ })
    expect(btn(/Timing/).disabled).toBe(false)
    expect(btn(/Release/).disabled).toBe(true)
    cleanup()
    change.status = 'in_validation' as ChangeDetail['status']
    wrap('/changes/1')
    await screen.findByRole('tab', { name: /Release/ })
    expect(btn(/Release/).disabled).toBe(false)
  })

  it.each([
    ['costing', /Costing/],
    ['quoting', /Offer/],
    ['quoted', /Offer/],
    ['approved', /Timing/],
    ['in_implementation', /Timing/],
    ['in_validation', /Release/],
    ['released', /Release/],
  ])('marks the active phase tab at %s', async (status, name) => {
    change.customer_relevant = true
    change.status = status as ChangeDetail['status']
    wrap('/changes/1')
    const tab = await screen.findByRole('tab', { name })
    // The state is part of the tab's name ("Timing, Current phase"), not a label on a dot.
    expect(tab.textContent).toContain(t('tab.activePhase'))
  })

  it.each([
    ['commercial', 'costing', /Costing/],
    ['commercial', 'quoted', /Offer/],
    ['implementation', 'in_implementation', /Timing/],
    ['implementation', 'approved', /Timing/],
    ['implementation', 'in_validation', /Release/],
  ])('resolves the old ?tab=%s at %s', async (alias, status, name) => {
    change.customer_relevant = true
    change.status = status as ChangeDetail['status']
    wrap(`/changes/1?tab=${alias}`)
    const tab = await screen.findByRole('tab', { name })
    expect(tab.getAttribute('aria-selected')).toBe('true')
  })

  it('renders the timing tab with plan and publish rights for Scheduling', async () => {
    vi.mocked(useDepartments).mockReturnValue({
      data: [{ id: 11, name: 'Scheduling', flow_type: 'action', is_active: true, sort_order: 1 }],
    } as unknown as ReturnType<typeof useDepartments>)
    vi.mocked(changesApi.myActions).mockResolvedValue({ actions: [], memberships: [11] })
    authState.current = { isAdmin: false, role: 'engineer', userId: 5 }
    change.status = 'approved' as ChangeDetail['status']
    wrap('/changes/1?tab=timing')
    await waitFor(() => expect(screen.getByTestId('timing-rights').textContent)
      .toBe('edit=true publish=false'))
    // Scheduling sets the bank-build mode but does not lock/escalate deviations.
    expect(screen.getByTestId('timing-rights-2').textContent).toBe('bank=true decide=false admin=false')
  })

  it('gives Sales deviation decisions but not the bank-build mode', async () => {
    vi.mocked(useDepartments).mockReturnValue({
      data: [{ id: 12, name: 'Sales', flow_type: 'action', is_active: true, sort_order: 1 }],
    } as unknown as ReturnType<typeof useDepartments>)
    vi.mocked(changesApi.myActions).mockResolvedValue({ actions: [], memberships: [12] })
    authState.current = { isAdmin: false, role: 'engineer', userId: 5 }
    change.status = 'approved' as ChangeDetail['status']
    wrap('/changes/1?tab=timing')
    await waitFor(() => expect(screen.getByTestId('timing-rights').textContent)
      .toBe('edit=true publish=true'))
    expect(screen.getByTestId('timing-rights-2').textContent).toBe('bank=false decide=true admin=false')
  })

  it('gives PM both the bank-build mode and deviation decisions; admin answers for any team', async () => {
    vi.mocked(useDepartments).mockReturnValue({
      data: [{ id: 9, name: 'Project Manager', flow_type: 'action', is_active: true, sort_order: 1 }],
    } as unknown as ReturnType<typeof useDepartments>)
    vi.mocked(changesApi.myActions).mockResolvedValue({ actions: [], memberships: [9] })
    authState.current = { isAdmin: false, role: 'engineer', userId: 5 }
    change.status = 'approved' as ChangeDetail['status']
    wrap('/changes/1?tab=timing')
    await waitFor(() => expect(screen.getByTestId('timing-rights-2').textContent)
      .toBe('bank=true decide=true admin=false'))
    cleanup()
    vi.mocked(changesApi.myActions).mockResolvedValue({ actions: [], memberships: [] })
    authState.current = { isAdmin: true, role: 'admin', userId: 1 }
    wrap('/changes/1?tab=timing')
    await waitFor(() => expect(screen.getByTestId('timing-rights-2').textContent)
      .toBe('bank=true decide=true admin=true'))
  })

  it('treats an admin acting as a department as that department, not as admin', async () => {
    sessionStorage.setItem(ACTS_AS_KEY, '44')
    try {
      vi.mocked(useDepartments).mockReturnValue({
        data: [{ id: 44, name: 'Tool Engineer', flow_type: 'action', is_active: true, sort_order: 1 }],
      } as unknown as ReturnType<typeof useDepartments>)
      vi.mocked(changesApi.myActions).mockResolvedValue({ actions: [], memberships: [44] })
      authState.current = { isAdmin: true, role: 'admin', userId: 1 }
      change.status = 'approved' as ChangeDetail['status']
      wrap('/changes/1?tab=timing')
      await waitFor(() => expect(screen.getByTestId('timing-rights').textContent)
        .toBe('edit=false publish=false'))
      expect(screen.getByTestId('timing-rights-2').textContent).toBe('bank=false decide=false admin=false')
      cleanup()
      change.status = 'in_validation' as ChangeDetail['status']
      wrap('/changes/1?tab=release')
      await waitFor(() => expect(screen.getByTestId('mock-release-tab').textContent).toBe('manage=false'))
      cleanup()
      change.status = 'quoted' as ChangeDetail['status']
      change.customer_relevant = true
      wrap('/changes/1?tab=offer')
      await waitFor(() => expect(screen.getByTestId('mock-offer-tab').textContent)
        .toContain('write=false prices=false pm=false quality=false'))
    } finally {
      sessionStorage.removeItem(ACTS_AS_KEY)
    }
  })

  it('marks the Approval tab active for an internal change at costing', async () => {
    change.customer_relevant = false
    change.status = 'costing' as ChangeDetail['status']
    wrap('/changes/1')
    const approval = await screen.findByRole('tab', { name: /Approval/ })
    expect(approval.textContent).toContain(t('tab.activePhase'))
    change.customer_relevant = true
  })

  it('F15: one page width for every tab', async () => {
    change.customer_relevant = true
    change.status = 'quoted' as ChangeDetail['status']
    const { container } = wrap('/changes/1?tab=offer')
    await screen.findByTestId('mock-offer-tab')
    expect((container.firstChild as HTMLElement).className).toContain('max-w-[1400px]')
    cleanup()
    const r = wrap('/changes/1?tab=overview')
    await screen.findByRole('tab', { name: /Overview/ })
    expect((r.container.firstChild as HTMLElement).className).toContain('max-w-[1400px]')
  })

  it('gives PM the release management rights', async () => {
    vi.mocked(useDepartments).mockReturnValue({
      data: [{ id: 9, name: 'Project Manager', flow_type: 'action', is_active: true, sort_order: 1 }],
    } as unknown as ReturnType<typeof useDepartments>)
    vi.mocked(changesApi.myActions).mockResolvedValue({ actions: [], memberships: [9] })
    authState.current = { isAdmin: false, role: 'engineer', userId: 5 }
    change.status = 'in_validation' as ChangeDetail['status']
    wrap('/changes/1?tab=release')
    await waitFor(() => expect(screen.getByTestId('mock-release-tab').textContent).toBe('manage=true'))
  })
})

describe('ChangeDetailPage rejection', () => {
  afterEach(() => {
    cleanup()
    authState.current = { isAdmin: false, role: 'engineer', userId: null }
    vi.mocked(changesApi.get).mockResolvedValue(change)
  })

  it('states that the flow is stopped, why, and offers the way back', async () => {
    vi.mocked(changesApi.get).mockResolvedValue({
      ...change,
      status: 'rejected' as ChangeDetail['status'],
      rejection_reason: 'Customer withdrew the request',
    })
    authState.current = { isAdmin: true, role: 'admin', userId: 99 }
    wrap('/changes/1')
    expect(await screen.findByRole('alert')).toBeDefined()
    expect(screen.getByText(/the flow is stopped/i)).toBeDefined()
    expect(screen.getByText('Customer withdrew the request')).toBeDefined()
    expect(screen.getByRole('button', { name: /Reopen/ })).toBeDefined()
    authState.current = { isAdmin: false, role: 'engineer', userId: null }
  })

  it('offers Reopen only to the lead, PM or admin (spec §16 P1 4)', async () => {
    vi.mocked(changesApi.get).mockResolvedValue({
      ...change, status: 'rejected' as ChangeDetail['status'],
    })
    wrap('/changes/1')
    expect(await screen.findByText(/the flow is stopped/i)).toBeDefined()
    expect(screen.queryByRole('button', { name: /Reopen/ })).toBeNull()
  })

  it('shows no rejection banner or Reopen button on a live change', async () => {
    wrap('/changes/1?tab=overview')
    await screen.findByText('mock-lifecycle-stepper')
    expect(screen.queryByText(/the flow is stopped/i)).toBeNull()
    expect(screen.queryByRole('button', { name: /Reopen/ })).toBeNull()
  })
})

describe('ChangeDetailPage capture phase', () => {
  afterEach(() => {
    cleanup()
    authState.current = { isAdmin: false, role: 'engineer', userId: null }
    change.status = 'in_assessment'
    change.description = null
    vi.mocked(changesApi.update).mockClear()
  })

  it('saves an edited description with a PATCH', async () => {
    authState.current = { isAdmin: true, role: 'admin', userId: 99 }
    change.status = 'captured' as ChangeDetail['status']
    wrap('/changes/1')
    fireEvent.change(await screen.findByTestId('description-input'),
      { target: { value: 'Clip rattles at 40 km/h' } })
    fireEvent.click(screen.getByTestId('description-save'))
    await waitFor(() => expect(changesApi.update).toHaveBeenCalledWith(
      1, { description: 'Clip rattles at 40 km/h' }))
  })

  it('locks the later-phase tabs while the change is captured', async () => {
    change.status = 'captured' as ChangeDetail['status']
    wrap('/changes/1')
    const scoping = await screen.findByRole('tab', { name: /Scoping/ })
    expect(locked(scoping)).toBe(true)
    // Scoping gets the handoff note; the other locked tabs the generic one.
    expect(why(scoping)).toBe(t('tab.scopingHandoff'))
    const impacted = screen.getByRole('tab', { name: /Impacted/ })
    expect(locked(impacted)).toBe(true)
    expect(why(impacted)).toBe(t('tab.lockedUntilScoping'))
    expect(locked(screen.getByRole('tab', { name: /Overview/ }))).toBe(false)
  })

  it('sends a deep link into a locked tab back to overview', async () => {
    change.status = 'captured' as ChangeDetail['status']
    wrap('/changes/1?tab=scoping')
    const overview = await screen.findByRole('tab', { name: /Overview/ })
    expect(overview.getAttribute('aria-selected')).toBe('true')
    // Overview content, not the scoping panel.
    expect(screen.getByText(/Reason:/)).toBeDefined()
  })

  it('unlocks scoping and impacted at scoping, but not the later phases', async () => {
    change.status = 'scoping' as ChangeDetail['status']
    wrap('/changes/1')
    const scoping = await screen.findByRole('tab', { name: /Scoping/ })
    expect(locked(scoping)).toBe(false)
    expect(locked(screen.getByRole('tab', { name: /Impacted/ }))).toBe(false)
    const costing = screen.getByRole('tab', { name: /Costing/ })
    expect(locked(costing)).toBe(true)
    expect(why(costing)).toBe(t('tab.lockedUntilPhase'))
    expect(locked(screen.getByRole('tab', { name: /Timing/ }))).toBe(true)
    expect(locked(screen.getByRole('tab', { name: /Assessments/ }))).toBe(true)
  })

  it('unlocks the costing tab once the change reaches costing', async () => {
    change.status = 'costing' as ChangeDetail['status']
    wrap('/changes/1')
    const costing = await screen.findByRole('tab', { name: /Costing/ })
    expect(locked(costing)).toBe(false)
    expect(locked(screen.getByRole('tab', { name: /Assessments/ }))).toBe(false)
    // Timing is still a phase away.
    expect(locked(screen.getByRole('tab', { name: /Timing/ }))).toBe(true)
  })

  it('a change rejected at scoping opens on Scoping and keeps the later stages locked', async () => {
    Object.assign(change, { status: 'rejected', stopped_at: 'scoping' })
    try {
      wrap('/changes/1')
      const scoping = await screen.findByRole('tab', { name: /Scoping/ })
      expect(scoping.getAttribute('aria-selected')).toBe('true')
      expect(locked(screen.getByRole('tab', { name: /Costing/ }))).toBe(true)
      const release = screen.getByRole('tab', { name: /Release/ })
      expect(locked(release)).toBe(true)
      // The reason is reachable by keyboard: the tab's description, shown on focus.
      expect(screen.getByTestId('tab-why-release').textContent).toBe(t('tab.lockedStopped'))
      expect(release.getAttribute('aria-describedby')).toBe(screen.getByTestId('tab-why-release').id)
      // No tab is the current phase of a stopped change.
      expect(screen.queryByText(new RegExp(t('tab.activePhase')))).toBeNull()
    } finally {
      Object.assign(change, { stopped_at: undefined })
    }
  })

  it('a change cancelled at costing opens on Overview; costing stays open, release locked', async () => {
    Object.assign(change, { status: 'cancelled', stopped_at: 'costing' })
    try {
      wrap('/changes/1')
      const overview = await screen.findByRole('tab', { name: 'Overview' })
      expect(overview.getAttribute('aria-selected')).toBe('true')
      expect(locked(screen.getByRole('tab', { name: /Costing/ }))).toBe(false)
      expect(locked(screen.getByRole('tab', { name: /Release/ }))).toBe(true)
    } finally {
      Object.assign(change, { stopped_at: undefined })
    }
  })

  it('withholds nothing from an off-path change', async () => {
    change.status = 'rejected' as ChangeDetail['status']
    wrap('/changes/1')
    const costing = await screen.findByRole('tab', { name: /Costing/ })
    expect(locked(costing)).toBe(false)
  })
})

describe('ChangeDetailPage costing tab', () => {
  afterEach(() => {
    cleanup()
    authState.current = { isAdmin: false, role: 'engineer', userId: null }
    change.status = 'in_assessment'
    change.customer_relevant = undefined
  })

  it('states the stage and no longer carries the timeline placeholder', async () => {
    authState.current = { isAdmin: true, role: 'admin', userId: 99 }
    change.status = 'costing' as ChangeDetail['status']
    change.customer_relevant = true
    wrap('/changes/1?tab=costing')
    expect((await screen.findByTestId('costing-stage')).textContent).toContain(t('costing.stageBody'))
    expect(screen.queryByTestId('quote-timeline-placeholder')).toBeNull()
  })

  it('offers PM, Sales, the lead and admin the reopen of costing while quoting, with a reason', async () => {
    authState.current = { isAdmin: true, role: 'admin', userId: 99 }
    change.status = 'quoting' as ChangeDetail['status']
    change.customer_relevant = true
    wrap('/changes/1?tab=costing')
    expect((await screen.findByTestId('costing-closed')).textContent).toContain(t('costing.closedHint'))
    // The reason dialog is mocked here; the button opening it is the contract.
    expect(screen.getByTestId('costing-reopen').textContent).toBe(t('costing.reopen'))
  })

  it('tells a bystander costing is closed without offering the reopen', async () => {
    authState.current = { isAdmin: false, role: 'engineer', userId: 5 }
    change.status = 'quoting' as ChangeDetail['status']
    wrap('/changes/1?tab=costing')
    await screen.findByTestId('costing-closed')
    expect(screen.queryByTestId('costing-reopen')).toBeNull()
  })

  it('mounts the full P&L card (which reads /summation) only for the cost roles; others get their department part', async () => {
    change.status = 'costing' as ChangeDetail['status']
    authState.current = { isAdmin: false, role: 'engineer', userId: 5 }
    wrap('/changes/1?tab=costing')
    await screen.findByTestId('costing-stage')
    expect(screen.queryByText('mock-pnl-card')).toBeNull()
    expect(screen.getByText('mock-pnl-department-only')).toBeDefined()
    cleanup()
    authState.current = { isAdmin: true, role: 'admin', userId: 99 }
    wrap('/changes/1?tab=costing')
    expect(await screen.findByText('mock-pnl-card')).toBeDefined()
  })

  it('opens the offer tab at quote creation', async () => {
    change.status = 'quoting' as ChangeDetail['status']
    change.customer_relevant = true
    wrap('/changes/1?tab=commercial')
    const offer = await screen.findByRole('tab', { name: /Offer/ })
    expect(locked(offer)).toBe(false)
    expect(offer.getAttribute('aria-selected')).toBe('true')
  })
})

describe('ChangeDetailPage description authz', () => {
  afterEach(() => {
    cleanup()
    authState.current = { isAdmin: false, role: 'engineer', userId: null }
    change.status = 'in_assessment'
    change.lead_id = null
    vi.mocked(useDepartments).mockReturnValue({ data: [] } as unknown as ReturnType<typeof useDepartments>)
    vi.mocked(changesApi.myActions).mockResolvedValue({ actions: [], memberships: [] })
  })

  it('lets a Sales department member edit the description at capture', async () => {
    vi.mocked(useDepartments).mockReturnValue({
      data: [{ id: 3, name: 'Sales', flow_type: 'action', is_active: true, sort_order: 1 }],
    } as unknown as ReturnType<typeof useDepartments>)
    vi.mocked(changesApi.myActions).mockResolvedValue({ actions: [], memberships: [3] })
    authState.current = { isAdmin: false, role: 'engineer', userId: 5 }
    change.status = 'captured' as ChangeDetail['status']
    wrap('/changes/1')
    expect(await screen.findByTestId('description-input')).toBeDefined()
  })

  it('freezes the description at kickoff — read-only from scoping on', async () => {
    vi.mocked(useDepartments).mockReturnValue({
      data: [{ id: 3, name: 'Sales', flow_type: 'action', is_active: true, sort_order: 1 }],
    } as unknown as ReturnType<typeof useDepartments>)
    vi.mocked(changesApi.myActions).mockResolvedValue({ actions: [], memberships: [3] })
    authState.current = { isAdmin: true, role: 'admin', userId: 99 }
    change.status = 'scoping' as ChangeDetail['status']
    wrap('/changes/1')
    await screen.findByRole('tab', { name: /Overview/ })
    expect(screen.queryByTestId('description-input')).toBeNull()
  })

  it('shows the description read-only to an unrelated viewer', async () => {
    authState.current = { isAdmin: false, role: 'engineer', userId: 5 }
    change.status = 'captured' as ChangeDetail['status']
    wrap('/changes/1')
    await screen.findByRole('tab', { name: /Overview/ })
    expect(screen.queryByTestId('description-input')).toBeNull()
  })
})

describe('ChangeDetailPage impacted-tab attention dot', () => {
  afterEach(() => {
    cleanup()
    change.status = 'in_assessment'
    change.impact_confirmed_at = null
  })

  it('marks the impacted tab while scoping still owes an impact confirmation', async () => {
    change.status = 'scoping' as ChangeDetail['status']
    change.impact_confirmed_at = null
    wrap('/changes/1')
    const dot = await screen.findByTestId('tab-open-work')
    expect(dot.closest('button')?.textContent).toContain('Impacted')
  })

  it('drops the mark once the impact is confirmed', async () => {
    change.status = 'scoping' as ChangeDetail['status']
    change.impact_confirmed_at = '2026-07-05T10:00:00'
    wrap('/changes/1')
    await screen.findByRole('tab', { name: /Impacted/ })
    expect(screen.queryByTestId('tab-open-work')).toBeNull()
  })

  it('drops the mark once the phase moves on', async () => {
    change.status = 'in_assessment' as ChangeDetail['status']
    change.impact_confirmed_at = null
    wrap('/changes/1')
    await screen.findByRole('tab', { name: /Impacted/ })
    expect(screen.queryByTestId('tab-open-work')).toBeNull()
  })
})

describe('ChangeDetailPage project in the header', () => {
  afterEach(() => {
    cleanup()
    change.project_number = '1864'
    change.project_name = 'VW426 Atlas'
  })

  it('names the project under the change, number first, linking to it', async () => {
    wrap('/changes/1?tab=overview')
    const link = await screen.findByTestId('change-project')
    expect(link.textContent).toBe('1864 · VW426 Atlas')
    expect(link.getAttribute('href')).toBe('/projects/1')
  })

  it('says nothing when the change carries no project', async () => {
    change.project_number = null
    change.project_name = null
    wrap('/changes/1')
    await screen.findByRole('tab', { name: /Overview/ })
    expect(screen.queryByTestId('change-project')).toBeNull()
  })
})

describe('ChangeDetailPage wait banner', () => {
  afterEach(() => {
    cleanup()
    change.status = 'in_assessment'
    change.customer_relevant = undefined
    change.blocked_department_ids = []
    vi.mocked(changesApi.listConcerns).mockResolvedValue([])
    vi.mocked(useDepartments).mockReturnValue({ data: [] } as unknown as ReturnType<typeof useDepartments>)
  })

  const concern = (over: Record<string, unknown> = {}) => ({
    id: 1, change_id: 1, kind: 'needs_info', note: 'What is the target price?',
    raised_by: 9, raised_at: '2026-08-01T09:00:00', is_open: true,
    department_id: null, answer_note: null, ...over,
  })

  it('names the teams the timing waits on at approved', async () => {
    const { planApi } = await import('../api/changePlan')
    vi.mocked(planApi.feedback).mockResolvedValueOnce({
      revision: 1, all_confirmed: false, validated_at: null, validated_by_name: null,
      required: [
        { department_id: 4, department_name: 'Tool Engineer', verdict: null, note: null, by_name: null, at: null, stale: false },
        { department_id: 2, department_name: 'Development', verdict: 'confirmed', note: null, by_name: 'A', at: null, stale: false },
      ],
    })
    change.status = 'approved' as ChangeDetail['status']
    change.customer_relevant = true
    wrap('/changes/1')
    expect((await screen.findByTestId('wait-timing-confirm')).textContent)
      .toBe('Timing: waiting on team confirmation: Tool Engineer')
  })

  it('tells every viewer the change is waiting on Sales', async () => {
    change.status = 'scoping' as ChangeDetail['status']
    vi.mocked(changesApi.listConcerns).mockResolvedValue([concern()] as never)
    wrap('/changes/1')
    const line = await screen.findByTestId('wait-sales-info-1')
    expect(line.textContent).toContain('What is the target price?')
  })

  it('switches to awaiting review once the answer is in', async () => {
    change.status = 'scoping' as ChangeDetail['status']
    vi.mocked(changesApi.listConcerns).mockResolvedValue([
      concern({ answer_note: 'customer confirmed 12.50',
        answered_at: '2026-08-02T00:00:00' })] as never)
    wrap('/changes/1')
    expect(await screen.findByTestId('wait-review-1')).toBeTruthy()
  })

  it('names a held department during assessment', async () => {
    vi.mocked(useDepartments).mockReturnValue({
      data: [{ id: 4, name: 'Tool Engineer', flow_type: 'action', is_active: true, sort_order: 1 }],
    } as unknown as ReturnType<typeof useDepartments>)
    change.status = 'in_assessment' as ChangeDetail['status']
    change.blocked_department_ids = [4]
    wrap('/changes/1')
    const line = await screen.findByTestId('wait-blocked-departments')
    expect(line.textContent).toContain('Tool Engineer')
  })

  it('waits on the rejection letter after a rejection', async () => {
    change.status = 'rejected' as ChangeDetail['status']
    change.customer_relevant = true
    wrap('/changes/1')
    expect(await screen.findByTestId('wait-rejection-letter')).toBeTruthy()
  })

  it('states waits once, in the cockpit, with no separate banner', async () => {
    change.status = 'scoping' as ChangeDetail['status']
    vi.mocked(changesApi.listConcerns).mockResolvedValue([concern()] as never)
    wrap('/changes/1')
    expect(await screen.findAllByTestId('wait-sales-info-1')).toHaveLength(1)
    expect(screen.queryByTestId('wait-banner')).toBeNull()
  })
})

describe('ChangeDetailPage confirm and cancel (F4, F6)', () => {
  afterEach(() => { cleanup(); change.status = 'in_assessment' as ChangeDetail['status'] })

  it('asks before closing and only then moves the change', async () => {
    authState.current = { isAdmin: true, role: 'admin', userId: 99 }
    change.status = 'released' as ChangeDetail['status']
    wrap('/changes/1?tab=release')
    fireEvent.click(await screen.findByText('mock-close'))
    const dialog = await screen.findByTestId('confirm-closed')
    expect(dialog.textContent).toContain('Closing is final')
    expect(changesApi.transition).not.toHaveBeenCalled()
    fireEvent.click(screen.getByTestId('confirm-go'))
    await waitFor(() => expect(changesApi.transition).toHaveBeenCalledWith(1, 'closed', { to: 'closed' }))
  })

  it('takes a change back to scoping only with a reason, and sends it', async () => {
    authState.current = { isAdmin: true, role: 'admin', userId: 99 }
    change.status = 'in_assessment' as ChangeDetail['status']
    vi.mocked(changesApi.transition).mockClear()
    wrap('/changes/1')
    fireEvent.click(await screen.findByText('mock-advance-scoping'))
    const dialog = await screen.findByTestId('confirm-scoping')
    expect(dialog.getAttribute('aria-modal')).toBe('true')
    const go = screen.getByTestId('confirm-go') as HTMLButtonElement
    expect(go.disabled).toBe(true)
    fireEvent.change(screen.getByTestId('confirm-reason'), { target: { value: '  Scope needs the carrier too ' } })
    expect(go.disabled).toBe(false)
    fireEvent.click(go)
    await waitFor(() => expect(changesApi.transition).toHaveBeenCalledWith(
      1, 'scoping', { to: 'scoping', reason: 'Scope needs the carrier too' }))
    authState.current = { isAdmin: false, role: 'engineer', userId: null }
  })

  it('holds the mother-plant hand-over while anything is missing and takes the description inline', async () => {
    authState.current = { isAdmin: true, role: 'admin', userId: 99 }
    const c = change as unknown as Record<string, unknown>
    change.status = 'captured' as ChangeDetail['status']
    c.origin = 'mother_plant'
    try {
      wrap('/changes/1')
      fireEvent.click(await screen.findByText('mock-advance-scoping'))
      await screen.findByTestId('confirm-scoping')
      expect((screen.getByTestId('confirm-go') as HTMLButtonElement).disabled).toBe(true)
      expect(screen.getByTestId('confirm-open').textContent).toContain(t('kickoff.description'))
      expect(screen.getByTestId('kickoff-description')).toBeTruthy()
      expect(screen.getByTestId('kickoff-description').querySelector('[data-testid="description-input"]')).toBeTruthy()
    } finally {
      delete c.origin
      authState.current = { isAdmin: false, role: 'engineer', userId: null }
    }
  })

  it('offers no Cancel once the change is released or closed', async () => {
    authState.current = { isAdmin: true, role: 'admin', userId: 99 }
    change.status = 'released' as ChangeDetail['status']
    wrap('/changes/1')
    await screen.findByText('mock-cockpit-summary')
    expect(screen.queryByTestId('header-cancel')).toBeNull()
    cleanup()
    change.status = 'in_assessment' as ChangeDetail['status']
    wrap('/changes/1')
    // Rare and destructive: behind "More actions", not beside the title.
    const item = await screen.findByTestId('header-cancel')
    expect(item.getAttribute('role')).toBe('menuitem')
    expect(item.closest('details')?.querySelector('summary')?.getAttribute('aria-label')).toBe('More actions')
    authState.current = { isAdmin: false, role: 'engineer', userId: null }
  })

  it('hides Cancel from a viewer without the right, and follows stage-state (spec §16 P1 4)', async () => {
    wrap('/changes/1')
    await screen.findByText('mock-cockpit-summary')
    expect(screen.queryByTestId('header-cancel')).toBeNull()
    cleanup()
    vi.mocked(changesApi.stageState).mockResolvedValueOnce({ can_transition: { cancelled: true } } as never)
    wrap('/changes/1')
    expect(await screen.findByTestId('header-cancel')).toBeDefined()
  })

  it('states that canceling is final', async () => {
    authState.current = { isAdmin: true, role: 'admin', userId: 99 }
    wrap('/changes/1')
    fireEvent.click(await screen.findByTestId('header-cancel'))
    expect(screen.getByTestId('reason-open-Cancel change').textContent).toMatch(/^Canceling is final/)
    authState.current = { isAdmin: false, role: 'engineer', userId: null }
  })
})

describe('ChangeDetailPage needs("signoff") gates only the missing side (finding 6)', () => {
  afterEach(() => {
    cleanup()
    change.status = 'in_assessment' as ChangeDetail['status']
    change.pm_signed_by = null
    change.quality_signed_by = null
    authState.current = { isAdmin: false, role: 'engineer', userId: null }
    vi.mocked(useDepartments).mockReturnValue({ data: [] } as unknown as ReturnType<typeof useDepartments>)
    vi.mocked(changesApi.myActions).mockResolvedValue({ actions: [], memberships: [] })
  })

  it('lets a PM member sign off when only their own side is still missing', async () => {
    change.status = 'quoted' as ChangeDetail['status']
    change.pm_signed_by = null
    change.quality_signed_by = 2 // Quality already signed
    authState.current = { isAdmin: false, role: 'engineer', userId: 7 }
    vi.mocked(useDepartments).mockReturnValue({
      data: [{ id: 5, name: 'Project Manager' }],
    } as never)
    vi.mocked(changesApi.myActions).mockResolvedValue({ actions: [], memberships: [5] } as never)
    wrap('/changes/1')
    expect((await screen.findByTestId('needs-signoff')).textContent).toBe('allowed')
  })

  it('still refuses when the viewer\'s own side is already signed and only the other side is open', async () => {
    change.status = 'quoted' as ChangeDetail['status']
    change.pm_signed_by = 7 // this PM member already signed
    change.quality_signed_by = null // Quality is the one still missing
    authState.current = { isAdmin: false, role: 'engineer', userId: 7 }
    vi.mocked(useDepartments).mockReturnValue({
      data: [{ id: 5, name: 'Project Manager' }],
    } as never)
    vi.mocked(changesApi.myActions).mockResolvedValue({ actions: [], memberships: [5] } as never)
    wrap('/changes/1')
    expect((await screen.findByTestId('needs-signoff')).textContent).toBe('Needs the Project Manager and Quality')
  })
})

describe('ChangeDetailPage validate-timing step follows the Timing tab', () => {
  afterEach(() => {
    cleanup()
    change.status = 'in_assessment' as ChangeDetail['status']
    authState.current = { isAdmin: false, role: 'engineer', userId: null }
    vi.mocked(planApi.feedback).mockResolvedValue({ revision: 1, required: [], all_confirmed: true, validated_at: null, validated_by_name: null } as never)
  })

  it('is held while a team has not confirmed, like the tab button', async () => {
    change.status = 'approved' as ChangeDetail['status']
    authState.current = { isAdmin: true, role: 'admin', userId: 99 }
    vi.mocked(planApi.feedback).mockResolvedValue({ revision: 1, all_confirmed: false, validated_at: null,
      validated_by_name: null, required: [
        { department_id: 4, department_name: 'APQP', verdict: null, stale: false },
        { department_id: 5, department_name: 'Tool Engineer', verdict: 'confirmed', stale: false },
      ] } as never)
    wrap('/changes/1')
    await waitFor(() => expect(screen.getByTestId('needs-validate-timing').textContent)
      .toBe('Waiting for APQP to confirm the timing'))
  })

  it('is offered once every team confirmed', async () => {
    change.status = 'approved' as ChangeDetail['status']
    authState.current = { isAdmin: true, role: 'admin', userId: 99 }
    wrap('/changes/1')
    await waitFor(() => expect(planApi.feedback).toHaveBeenCalled())
    expect((await screen.findByTestId('needs-validate-timing')).textContent).toBe('allowed')
  })
})

describe('ChangeDetailPage internal-approval step gating (finding 3)', () => {
  afterEach(() => {
    cleanup()
    change.status = 'in_assessment' as ChangeDetail['status']
    authState.current = { isAdmin: false, role: 'engineer', userId: null }
    vi.mocked(useDepartments).mockReturnValue({ data: [] } as unknown as ReturnType<typeof useDepartments>)
    vi.mocked(changesApi.myActions).mockResolvedValue({ actions: [], memberships: [] })
  })

  it('needs("internal-approval") is open for a PM member, refused for anyone else', async () => {
    change.status = 'costing' as ChangeDetail['status']
    authState.current = { isAdmin: false, role: 'engineer', userId: 7 }
    vi.mocked(useDepartments).mockReturnValue({
      data: [{ id: 5, name: 'Project Manager' }],
    } as never)
    vi.mocked(changesApi.myActions).mockResolvedValue({ actions: [], memberships: [] } as never)
    wrap('/changes/1')
    expect((await screen.findByTestId('needs-internal-approval')).textContent).toBe('Needs the Project Manager')
    cleanup()
    vi.mocked(changesApi.myActions).mockResolvedValue({ actions: [], memberships: [5] } as never)
    wrap('/changes/1')
    expect((await screen.findByTestId('needs-internal-approval')).textContent).toBe('allowed')
  })
})

describe('ChangeDetailPage end-implementation confirm loading (finding 8)', () => {
  afterEach(() => {
    cleanup()
    change.status = 'in_assessment' as ChangeDetail['status']
    vi.mocked(planApi.get).mockResolvedValue({ tasks: [] } as never)
  })

  it('shows "Checking" only while the detailed plan is actually loading, not forever once it errors', async () => {
    change.status = 'in_implementation' as ChangeDetail['status']
    let failWith!: (e: unknown) => void
    vi.mocked(planApi.get).mockImplementation(() => new Promise((_resolve, reject) => { failWith = reject }))
    wrap('/changes/1')
    fireEvent.click(await screen.findByText('mock-advance-in_validation'))
    const dialog = await screen.findByTestId('confirm-in_validation')
    expect(dialog.textContent).toContain('Checking what is still open')
    failWith(new Error('boom'))
    // Previously this used `!detailedPlan`, which stays true forever on an
    // error — the dialog would say "Checking" for good. isLoading clears once
    // the query settles, even into an error.
    await waitFor(() => expect(dialog.textContent).not.toContain('Checking what is still open'))
  })
})

describe('ChangeDetailPage Resume goes back to the status before the hold (finding 9)', () => {
  afterEach(() => {
    cleanup()
    change.status = 'in_assessment' as ChangeDetail['status']
    vi.mocked(changesApi.changelog).mockResolvedValue([])
  })

  it('reads the changelog for the status entry that led into on_hold and resumes to its old_value', async () => {
    change.status = 'on_hold' as ChangeDetail['status']
    // The API shape: ChangelogResponse decodes the stored JSON text, so a
    // status arrives as a plain value.
    vi.mocked(changesApi.changelog).mockResolvedValue([
      { id: 1, action: 'status_changed', action_description: 'captured -> scoping', performed_by: 1,
        performed_at: '2026-07-01T00:00:00', field_name: 'status', old_value: 'captured', new_value: 'scoping' },
      { id: 2, action: 'status_changed', action_description: 'costing -> on_hold', performed_by: 1,
        performed_at: '2026-08-01T00:00:00', field_name: 'status', old_value: 'costing', new_value: 'on_hold' },
    ] as never)
    wrap('/changes/1')
    await screen.findByRole('button', { name: 'Resume' })
    // Resume is clickable before the changelog resolves too — its target is
    // read fresh at click time, so wait for the query before clicking rather
    // than racing it.
    await waitFor(() => expect(changesApi.changelog).toHaveBeenCalledWith(1))
    await waitFor(() => {
      fireEvent.click(screen.getByRole('button', { name: 'Resume' }))
      expect(changesApi.transition).toHaveBeenCalledWith(1, 'costing', { to: 'costing' })
    })
  })

  it('reads JSON-encoded changelog values too (the stored column shape)', async () => {
    change.status = 'on_hold' as ChangeDetail['status']
    vi.mocked(changesApi.changelog).mockResolvedValue([
      { id: 2, action: 'status_changed', action_description: 'quoted -> on_hold', performed_by: 1,
        performed_at: '2026-08-01T00:00:00', field_name: 'status', old_value: '"quoted"', new_value: '"on_hold"' },
    ] as never)
    wrap('/changes/1')
    await screen.findByRole('button', { name: 'Resume' })
    await waitFor(() => expect(changesApi.changelog).toHaveBeenCalledWith(1))
    await waitFor(() => {
      fireEvent.click(screen.getByRole('button', { name: 'Resume' }))
      expect(changesApi.transition).toHaveBeenCalledWith(1, 'quoted', { to: 'quoted' })
    })
  })

  it('falls back to in_assessment when the changelog carries no on_hold entry', async () => {
    change.status = 'on_hold' as ChangeDetail['status']
    vi.mocked(changesApi.changelog).mockResolvedValue([] as never)
    wrap('/changes/1')
    fireEvent.click(await screen.findByRole('button', { name: 'Resume' }))
    await waitFor(() => expect(changesApi.transition).toHaveBeenCalledWith(1, 'in_assessment', { to: 'in_assessment' }))
  })
})

describe('ChangeDetailPage validation issues after the loop back (review F1)', () => {
  const issue = (over: Record<string, unknown> = {}) => ({
    id: 21, change_id: 1, number: 1, title: 'Clip hole out of tolerance', status: 'fixing', severity: 2,
    category: 'dimensional', description: 'x', created_by: 5, created_at: '2026-09-24T08:00:00',
    actions: [], attachments: [], escalation_level: 1, escalations: [], ...over,
  })
  afterEach(() => {
    cleanup()
    change.status = 'in_assessment' as ChangeDetail['status']
    issuesList.mockReset()
    authState.current = { isAdmin: false, role: 'engineer', userId: null }
  })

  it('keeps the Release tab open in implementation once an issue exists, and shows the issues on Timing', async () => {
    change.status = 'in_implementation' as ChangeDetail['status']
    issuesList.mockResolvedValue([issue()])
    wrap('/changes/1?tab=timing&issue=21')
    const panel = await screen.findByTestId('mock-issues-panel')
    expect(panel.textContent).toBe('Validation issues / recovery status=in_implementation focus=21')
    await waitFor(() => expect(locked(screen.getByRole('tab', { name: /Release/ }))).toBe(false))
    fireEvent.click(screen.getByRole('tab', { name: /Release/ }))
    expect(await screen.findByTestId('mock-release-tab')).toBeDefined()
  })

  it('passes a deep-linked issue to the Release tab', async () => {
    change.status = 'in_validation' as ChangeDetail['status']
    issuesList.mockResolvedValue([issue({ status: 'open' })])
    wrap('/changes/1?tab=release&issue=21')
    expect((await screen.findByTestId('mock-release-focus')).textContent).toBe('focus=21')
  })

  it('without issues the Release tab stays locked in implementation and Timing has no issues section', async () => {
    change.status = 'in_implementation' as ChangeDetail['status']
    issuesList.mockResolvedValue([])
    wrap('/changes/1?tab=timing')
    await screen.findByTestId('mock-timing-tab')
    expect(screen.queryByTestId('mock-issues-panel')).toBeNull()
    expect(locked(screen.getByRole('tab', { name: /Release/ }))).toBe(true)
  })

  it('the end-implementation dialog names the issues still fixing', async () => {
    authState.current = { isAdmin: true, role: 'admin', userId: 99 }
    change.status = 'in_implementation' as ChangeDetail['status']
    issuesList.mockResolvedValue([issue()])
    vi.mocked(planApi.get).mockResolvedValue({ tasks: [] } as never)
    wrap('/changes/1?tab=timing')
    await screen.findByTestId('mock-issues-panel')
    fireEvent.click(screen.getByRole('button', { name: 'mock-advance-in_validation' }))
    expect((await screen.findByTestId('confirm-info')).textContent).toContain('Still fixing: VI-1 Clip hole out of tolerance')
  })
})

describe('ChangeDetailPage deviations and truthful dialogs (final walk P2-3, P2-4, P2-6)', () => {
  afterEach(() => {
    cleanup()
    change.status = 'in_assessment' as ChangeDetail['status']
    releaseMock.blockers = []
    vi.mocked(changesApi.listDeviations).mockResolvedValue([])
    vi.mocked(changesApi.myActions).mockResolvedValue({ actions: [], memberships: [] } as never)
    vi.mocked(changesApi.getImplementation).mockResolvedValue({ ready_to_go: false } as never)
    vi.mocked(changesApi.getSummation).mockRejectedValue(new Error('not in this test'))
    authState.current = { isAdmin: false, role: 'engineer', userId: null }
  })

  it('release with open guards asks for a deviation with the reason instead of a bare refusal', async () => {
    authState.current = { isAdmin: true, role: 'admin', userId: 99 }
    change.status = 'in_validation' as ChangeDetail['status']
    releaseMock.blockers = ['Not ready to go: 4 impacted revisions have not completed their check workflow']
    vi.mocked(changesApi.transition).mockClear()
    wrap('/changes/1?tab=release')
    fireEvent.click(await screen.findByText('mock-release'))
    const dialog = await screen.findByTestId('confirm-released')
    await waitFor(() => expect(dialog.textContent).toContain('Release with a deviation'))
    expect(dialog.textContent).toContain('4 impacted revisions')
    const go = screen.getByTestId('confirm-go') as HTMLButtonElement
    expect(go.textContent).toBe('Ask for a deviation')
    expect(go.disabled).toBe(true)
    fireEvent.change(screen.getByTestId('confirm-reason'), { target: { value: 'ECN runs in the DMS track' } })
    fireEvent.click(go)
    await waitFor(() => expect(changesApi.proposeDeviation).toHaveBeenCalledWith(
      1, { to_status: 'released', reason: 'ECN runs in the DMS track' }))
    expect(changesApi.transition).not.toHaveBeenCalled()
  })

  it('a pending release deviation holds the dialog and says whose decision it waits on', async () => {
    authState.current = { isAdmin: true, role: 'admin', userId: 99 }
    change.status = 'in_validation' as ChangeDetail['status']
    releaseMock.blockers = ['6 plan deviations still open']
    vi.mocked(changesApi.listDeviations).mockResolvedValue([
      { id: 7, to_status: 'released', reason: 'x', status: 'pending', proposed_by: 16, proposed_at: '2026-09-25T10:00:00' },
    ] as never)
    wrap('/changes/1?tab=release')
    fireEvent.click(await screen.findByText('mock-release'))
    expect((await screen.findByTestId('confirm-hold')).textContent).toContain('Deviation #7')
    expect((screen.getByTestId('confirm-go') as HTMLButtonElement).disabled).toBe(true)
  })

  it('an approved release deviation lets the release go ahead as a transition', async () => {
    authState.current = { isAdmin: true, role: 'admin', userId: 99 }
    change.status = 'in_validation' as ChangeDetail['status']
    releaseMock.blockers = ['6 plan deviations still open']
    vi.mocked(changesApi.listDeviations).mockResolvedValue([
      { id: 7, to_status: 'released', reason: 'x', status: 'approved', proposed_by: 16, proposed_at: '2026-09-25T10:00:00' },
    ] as never)
    vi.mocked(changesApi.transition).mockClear()
    wrap('/changes/1?tab=release')
    fireEvent.click(await screen.findByText('mock-release'))
    expect((await screen.findByTestId('confirm-info')).textContent).toContain('Deviation #7 is approved')
    fireEvent.click(screen.getByTestId('confirm-go'))
    await waitFor(() => expect(changesApi.transition).toHaveBeenCalledWith(1, 'released', { to: 'released' }))
  })

  it('"Decide deviation #n" opens the decision panel on Overview, where the approver decides', async () => {
    authState.current = { isAdmin: true, role: 'admin', userId: 99 }
    change.status = 'in_validation' as ChangeDetail['status']
    vi.mocked(changesApi.listDeviations).mockResolvedValue([
      { id: 5, to_status: 'released', reason: 'Covered by the customer timing', status: 'pending', proposed_by: 16, proposed_at: '2026-09-25T10:00:00' },
    ] as never)
    vi.mocked(changesApi.myActions).mockResolvedValue({
      actions: [{ kind: 'deviation_decision', label: 'Decide deviation #5', target_tab: 'overview', deviation_id: 5 }],
      memberships: [],
    } as never)
    wrap('/changes/1?tab=release')
    fireEvent.click(await screen.findByText('mock-decide-deviation'))
    expect((await screen.findByTestId('deviation-5')).textContent).toContain('Covered by the customer timing')
    fireEvent.click(await screen.findByTestId('deviation-approve-5'))
    await waitFor(() => expect(changesApi.decideDeviation).toHaveBeenCalledWith(1, 5, { decision: 'approved' }))
  })

  it('close costing names hours without a cost sheet rate instead of "every department entered"', async () => {
    authState.current = { isAdmin: true, role: 'admin', userId: 99 }
    change.status = 'costing' as ChangeDetail['status']
    change.customer_relevant = true
    vi.mocked(changesApi.getSummation).mockResolvedValue({ unpriced_lines: [
      { position_id: 54, department_id: 6, label: 'Internal effort', kind: 'internal_effort', quantity: 3, unit: 'h', message: 'No rate' },
      { position_id: 55, department_id: 6, label: 'Support', kind: 'support_effort', quantity: 10, unit: 'h', message: 'No rate' },
    ] } as never)
    wrap('/changes/1?tab=overview')
    fireEvent.click(await screen.findByText('mock-advance-quoting'))
    const open = await screen.findByTestId('confirm-open')
    expect(open.textContent).toContain('No cost sheet rate for #6: 13 h unpriced')
    expect(screen.queryByTestId('confirm-clear')).toBeNull()
  })

  it('the cockpit knows which steps a deviation covers, and asking one opens the deviation banner (review M1)', async () => {
    change.status = 'approved' as ChangeDetail['status']
    vi.mocked(changesApi.listDeviations).mockResolvedValue([
      { id: 8, to_status: 'in_implementation', reason: 'x', status: 'approved', proposed_by: 16, proposed_at: '2026-09-25T10:00:00' },
      { id: 9, to_status: 'released', reason: 'y', status: 'pending', proposed_by: 16, proposed_at: '2026-09-25T10:00:00' },
    ] as never)
    wrap('/changes/1?tab=overview')
    await waitFor(() => expect(screen.getByTestId('mock-deviation-targets').textContent)
      .toBe(JSON.stringify({ approved: ['in_implementation'], pending: ['released'] })))
    expect(screen.queryByText('mock-deviation-banner')).toBeNull()
    fireEvent.click(screen.getByText('mock-ask-deviation'))
    expect(await screen.findByText('mock-deviation-banner')).toBeDefined()
  })

  it('names the revisions still in their check workflow while implementing', async () => {
    change.status = 'in_implementation' as ChangeDetail['status']
    vi.mocked(changesApi.getImplementation).mockResolvedValue({ ready_to_go: false, items: [
      { item_id: 1, revision_id: 3, instance_id: 4, instance_status: 'active', ready: false, waiting_on: ['Development'] },
      { item_id: 2, revision_id: 5, instance_id: 6, instance_status: 'completed', ready: true },
    ] } as never)
    wrap('/changes/1?tab=timing')
    expect((await screen.findByTestId('wait-revisions-in-check')).textContent)
      .toBe('1 impacted revision has not completed its check workflow; needs Development')
  })
})

describe('ChangeDetailPage UI polish (WP3)', () => {
  afterEach(() => {
    cleanup()
    change.status = 'in_assessment' as ChangeDetail['status']
    authState.current = { isAdmin: false, role: 'engineer', userId: null }
    vi.mocked(changesApi.changelog).mockResolvedValue([])
  })

  it('keeps the full cockpit on Overview and a slim sticky bar on every other tab', async () => {
    wrap('/changes/1?tab=overview')
    await screen.findByText('mock-lifecycle-stepper')
    expect(screen.queryByTestId('change-bar')).toBeNull()
    cleanup()
    wrap('/changes/1?tab=assessments')
    const bar = await screen.findByTestId('change-bar')
    expect(bar.className).toContain('sticky')
    expect(bar.querySelector('h1')?.textContent).toContain(change.change_number)
    // The same cockpit (one source for the next step), in its compact form.
    expect(bar.textContent).toContain('mock-cockpit-summary')
    expect(screen.queryByText('mock-lifecycle-stepper')).toBeNull()
  })

  it('has a skip link to the tab content and a labelled tab panel', async () => {
    wrap('/changes/1?tab=overview')
    const skip = await screen.findByText('Skip to the tab content')
    expect(skip.getAttribute('href')).toBe('#change-main')
    const panel = screen.getByRole('tabpanel')
    expect(panel.getAttribute('aria-labelledby')).toBe(screen.getByRole('tab', { name: 'Overview' }).id)
  })

  it('moves between tabs with the arrow keys', async () => {
    wrap('/changes/1?tab=overview')
    const overview = await screen.findByRole('tab', { name: 'Overview' })
    overview.focus()
    fireEvent.keyDown(overview, { key: 'ArrowRight' })
    expect(document.activeElement).toBe(screen.getByRole('tab', { name: /Scoping/ }))
  })

  it('shows a closed change as a read-only record, without a duplicate status line', async () => {
    change.status = 'closed' as ChangeDetail['status']
    vi.mocked(changesApi.changelog).mockResolvedValue([
      { id: 1, action: 'status', action_description: '', performed_by: 1, performed_at: '2026-09-25T10:00:00',
        field_name: 'status', old_value: 'released', new_value: 'closed' },
    ] as never)
    wrap('/changes/1?tab=overview')
    const banner = await screen.findByTestId('closed-banner')
    await waitFor(() => expect(banner.textContent).toContain('Closed 25 Sep 2026'))
    expect(screen.queryByText('Status:')).toBeNull()
    expect(screen.queryByLabelText('Priority')).toBeNull()
  })

  it('asks once more before recording the approval, by the same verb as the button', async () => {
    change.status = 'quoted' as ChangeDetail['status']
    wrap('/changes/1?tab=overview')
    await screen.findByText('mock-cockpit-summary')
    fireEvent.click(screen.getByText('mock-advance-approved'))
    const dialog = await screen.findByTestId('confirm-approved')
    expect(dialog.textContent).toContain('Record approval')
    expect(screen.getByTestId('confirm-go').textContent).toBe('Record approval')
  })

  it('never holds "Close costing" on the costing total: a zero total is a warning beside the step and in the confirm', async () => {
    authState.current = { isAdmin: true, role: 'admin', userId: 99 }
    change.status = 'costing' as ChangeDetail['status']
    const zero = { one_time_internal: 0, one_time_external: 0, lifecycle_internal: 0, lifecycle_external: 0 }
    // A department that legitimately costs nothing booked a zero line: the
    // backend counts it as an answer, so the step must stay open.
    vi.mocked(changesApi.getSummation).mockResolvedValue({
      currency: 'USD', unpriced_lines: [],
      by_department: [{ department_id: change.assessments[0]?.department_id ?? 1, ...zero }],
      totals: { ...zero, grand_total: 0 }, effort_by_department: [],
    } as never)
    wrap('/changes/1?tab=overview')
    await waitFor(() => expect(screen.getByTestId('warns-to:quoting').textContent)
      .toBe('The total is 0.00 USD. Check that nothing was forgotten.'))
    expect(screen.getByTestId('needs-to:quoting').textContent).toBe('allowed')
    fireEvent.click(screen.getByText('mock-advance-quoting'))
    await screen.findByTestId('confirm-quoting')
    expect((await screen.findByTestId('confirm-warning')).textContent)
      .toBe('The total is 0.00 USD. Check that nothing was forgotten.')
    const go = screen.getByTestId('confirm-go') as HTMLButtonElement
    expect(go.disabled).toBe(false)
    fireEvent.click(go)
    await waitFor(() => expect(changesApi.transition).toHaveBeenCalledWith(1, 'quoting', { to: 'quoting' }))
    cleanup()
    vi.mocked(changesApi.getSummation).mockResolvedValue({
      currency: 'USD', unpriced_lines: [],
      by_department: [{ department_id: change.assessments[0]?.department_id ?? 1, ...zero, one_time_internal: 100 }],
      totals: { ...zero, grand_total: 100 }, effort_by_department: [],
    } as never)
    wrap('/changes/1?tab=overview')
    await waitFor(() => expect(screen.getByTestId('warns-to:quoting').textContent).toBe('no warning'))
    vi.mocked(changesApi.getSummation).mockRejectedValue(new Error('not in this test'))
  })

  it('resuming from hold into validation asks a plain resume, not "Finish implementation"', async () => {
    authState.current = { isAdmin: true, role: 'admin', userId: 99 }
    change.status = 'on_hold' as ChangeDetail['status']
    vi.mocked(changesApi.changelog).mockResolvedValue([
      { id: 1, action: 'status', action_description: '', performed_by: 1, performed_at: '2026-09-25T10:00:00',
        field_name: 'status', old_value: 'in_validation', new_value: 'on_hold' },
    ] as never)
    wrap('/changes/1?tab=overview')
    fireEvent.click(await screen.findByRole('button', { name: 'Resume' }))
    await screen.findByTestId('confirm-in_validation')
    expect(screen.getByRole('dialog', { name: 'Resume' })).toBeDefined()
    expect(screen.getByTestId('confirm-go').textContent).toBe('Resume')
    expect(screen.getByTestId('confirm-consequence').textContent).toContain('goes back to Validation')
  })

  it('selects Overview when ?tab names a tab that is not rendered (the review still loading)', async () => {
    wrap('/changes/1?tab=review')
    const overview = await screen.findByRole('tab', { name: 'Overview' })
    expect(screen.queryByRole('tab', { name: 'Review' })).toBeNull()
    expect(overview.getAttribute('aria-selected')).toBe('true')
    expect(overview.tabIndex).toBe(0)
    expect(screen.getByRole('tabpanel').getAttribute('aria-labelledby')).toBe(overview.id)
  })

  it('"More actions": arrow keys reach the items, Escape closes and returns focus', async () => {
    authState.current = { isAdmin: true, role: 'admin', userId: 99 }
    wrap('/changes/1?tab=overview')
    const cancel = await screen.findByTestId('header-cancel')
    const details = cancel.closest('details') as HTMLDetailsElement
    const summary = details.querySelector('summary') as HTMLElement
    summary.focus()
    fireEvent.keyDown(summary, { key: 'ArrowDown' })
    expect(details.open).toBe(true)
    expect(document.activeElement).toBe(cancel)
    fireEvent.keyDown(cancel, { key: 'Escape' })
    expect(details.open).toBe(false)
    expect(document.activeElement).toBe(summary)
  })

  it('titles the finish-implementation confirm with its verb', async () => {
    change.status = 'in_implementation' as ChangeDetail['status']
    wrap('/changes/1?tab=overview')
    fireEvent.click(await screen.findByText('mock-advance-in_validation'))
    await screen.findByTestId('confirm-in_validation')
    expect(screen.getByRole('dialog', { name: 'Finish implementation' })).toBeDefined()
    expect(screen.getByTestId('confirm-go').textContent).toBe('Finish implementation')
  })
})
