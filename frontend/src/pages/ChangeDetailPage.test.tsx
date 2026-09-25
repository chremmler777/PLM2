import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, cleanup, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import ChangeDetailPage from './ChangeDetailPage'
import { changesApi } from '../api/changes'
import { useDepartments } from '../hooks/queries/useWorkflows'
import type { ChangeDetail } from '../types/change'
import { t } from '../i18n/cmLabels'

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

vi.mock('../api/changes', () => ({
  changesApi: {
    get: vi.fn().mockResolvedValue(change),
    getImplementation: vi.fn().mockResolvedValue({ ready_to_go: false }),
    getGates: vi.fn().mockResolvedValue([]),
    listDeviations: vi.fn().mockResolvedValue([]),
    myActions: vi.fn().mockResolvedValue({ actions: [], memberships: [] }),
    uploadAttachment: vi.fn(),
    signOff: vi.fn().mockResolvedValue({}),
    update: vi.fn().mockResolvedValue({}),
    customerResponse: vi.fn().mockResolvedValue({}),
    listConcerns: vi.fn().mockResolvedValue([]),
    approveInternalCosts: vi.fn().mockResolvedValue({}),
  },
}))
vi.mock('../components/changes/PnlCard', () => ({ default: () => <div>mock-pnl-card</div> }))
vi.mock('../api/changePlan', () => ({
  planApi: {
    feedback: vi.fn().mockResolvedValue({ revision: 1, required: [], all_confirmed: true, validated_at: null, validated_by_name: null }),
  },
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
vi.mock('../components/changes/ReasonDialog', () => ({ default: () => <div>mock-reason-dialog</div> }))
vi.mock('../components/changes/ImpactTree', () => ({ default: () => <div>mock-impact-tree</div> }))
vi.mock('../components/changes/ImplementationPanel', () => ({ default: () => <div>mock-implementation-panel</div> }))
vi.mock('../components/changes/LifecycleStepper', () => ({ default: () => <div>mock-lifecycle-stepper</div> }))
vi.mock('../components/changes/CockpitSummary', () => ({
  default: ({ waits = [] }: { waits?: { key: string; text: string }[] }) => (
    <div>mock-cockpit-summary
      {waits.map((w) => <p key={w.key} data-testid={`wait-${w.key}`}>{w.text}</p>)}
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
  default: (p: { canEditPlan: boolean; canPublish: boolean; canSetBankBuild?: boolean; canDecideDeviation?: boolean; isAdmin?: boolean }) => (
    <div data-testid="mock-timing-tab">
      <span data-testid="timing-rights">edit={String(p.canEditPlan)} publish={String(p.canPublish)}</span>
      <span data-testid="timing-rights-2">bank={String(p.canSetBankBuild)} decide={String(p.canDecideDeviation)} admin={String(p.isAdmin)}</span>
    </div>
  ),
}))
vi.mock('../components/changes/release/ReleaseTab', () => ({
  default: (p: { canManage: boolean }) => <div data-testid="mock-release-tab">manage={String(p.canManage)}</div>,
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
    const d1Button = await screen.findByRole('button', { name: 'D1' })
    expect(d1Button.className).toContain('border-b-2')
    expect(screen.getByText('mock-d1-panel')).toBeDefined()
  })

  it('falls back to overview when ?tab is invalid', async () => {
    wrap('/changes/1?tab=bogus')
    const overviewButton = await screen.findByRole('button', { name: 'Overview' })
    expect(overviewButton.className).toContain('border-b-2')
    expect(screen.queryByText('mock-d1-panel')).toBeNull()
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
    await screen.findByRole('button', { name: 'Overview' })
    expect(screen.queryByRole('button', { name: 'D1' })).toBeNull()
    expect(screen.queryByRole('button', { name: 'Audit' })).toBeNull()
    expect(screen.queryByText('Governance')).toBeNull()
  })

  it('shows the Governance group with D1 and Audit for an admin', async () => {
    authState.current = { isAdmin: true, role: 'admin', userId: 99 }
    wrap('/changes/1')
    await screen.findByRole('button', { name: 'Overview' })
    expect(screen.getByText('Governance')).toBeDefined()
    expect(screen.getByRole('button', { name: 'D1' })).toBeDefined()
    expect(screen.getByRole('button', { name: 'Audit' })).toBeDefined()
  })

  it('falls back to overview content for an unauthorized ?tab=audit deep link', async () => {
    wrap('/changes/1?tab=audit')
    const overviewButton = await screen.findByRole('button', { name: 'Overview' })
    expect(overviewButton.className).toContain('border-b-2')
    expect(screen.queryByText('mock-audit-timeline')).toBeNull()
    expect(screen.queryByRole('button', { name: 'Audit' })).toBeNull()
  })

  it('shows the Governance group with D1 and Audit for the change lead', async () => {
    change.lead_id = 42
    authState.current = { isAdmin: false, role: 'engineer', userId: 42 }
    wrap('/changes/1')
    await screen.findByRole('button', { name: 'Overview' })
    expect(screen.getByText('Governance')).toBeDefined()
    expect(screen.getByRole('button', { name: 'D1' })).toBeDefined()
    expect(screen.getByRole('button', { name: 'Audit' })).toBeDefined()
  })

  it('shows the Governance group with D1 and Audit for a Quality department member', async () => {
    vi.mocked(useDepartments).mockReturnValue({
      data: [{ id: 7, name: 'Quality', flow_type: 'action', is_active: true, sort_order: 1 }],
    } as unknown as ReturnType<typeof useDepartments>)
    vi.mocked(changesApi.myActions).mockResolvedValue({ actions: [], memberships: [7] })
    authState.current = { isAdmin: false, role: 'engineer', userId: 5 }
    wrap('/changes/1')
    await screen.findByRole('button', { name: 'Overview' })
    expect(screen.getByText('Governance')).toBeDefined()
    expect(screen.getByRole('button', { name: 'D1' })).toBeDefined()
    expect(screen.getByRole('button', { name: 'Audit' })).toBeDefined()
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
    expect(await screen.findByRole('button', { name: /Approval/ })).toBeDefined()
    expect(screen.queryByRole('button', { name: /^Offer$/ })).toBeNull()
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

  const btn = (name: RegExp) => screen.getByRole('button', { name }) as HTMLButtonElement

  it('unlocks costing and offer at costing, timing at approved, release at in_validation', async () => {
    change.customer_relevant = true
    change.status = 'costing' as ChangeDetail['status']
    wrap('/changes/1')
    await screen.findByRole('button', { name: /Costing/ })
    expect(btn(/Costing/).disabled).toBe(false)
    expect(btn(/Offer/).disabled).toBe(false)
    expect(btn(/Timing/).disabled).toBe(true)
    expect(btn(/Release/).disabled).toBe(true)
    cleanup()
    change.status = 'approved' as ChangeDetail['status']
    wrap('/changes/1')
    await screen.findByRole('button', { name: /Timing/ })
    expect(btn(/Timing/).disabled).toBe(false)
    expect(btn(/Release/).disabled).toBe(true)
    cleanup()
    change.status = 'in_validation' as ChangeDetail['status']
    wrap('/changes/1')
    await screen.findByRole('button', { name: /Release/ })
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
    const tab = await screen.findByRole('button', { name })
    expect(tab.querySelector('[aria-label="' + t('tab.activePhase') + '"]')).not.toBeNull()
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
    const tab = await screen.findByRole('button', { name })
    expect(tab.className).toContain('border-b-2')
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

  it('marks the Approval tab active for an internal change at costing', async () => {
    change.customer_relevant = false
    change.status = 'costing' as ChangeDetail['status']
    wrap('/changes/1')
    const approval = await screen.findByRole('button', { name: /Approval/ })
    expect(approval.querySelector('[aria-label="' + t('tab.activePhase') + '"]')).not.toBeNull()
    change.customer_relevant = true
  })

  it('widens the page for the offer, timing and release work', async () => {
    change.customer_relevant = true
    change.status = 'quoted' as ChangeDetail['status']
    const { container } = wrap('/changes/1?tab=offer')
    await screen.findByTestId('mock-offer-tab')
    expect((container.firstChild as HTMLElement).className).toContain('max-w-[1400px]')
    cleanup()
    const r = wrap('/changes/1')
    await screen.findByRole('button', { name: /Overview/ })
    expect((r.container.firstChild as HTMLElement).className).toContain('max-w-5xl')
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
    wrap('/changes/1')
    expect(await screen.findByRole('alert')).toBeDefined()
    expect(screen.getByText(/the flow is stopped/i)).toBeDefined()
    expect(screen.getByText('Customer withdrew the request')).toBeDefined()
    expect(screen.getByRole('button', { name: /Reopen/ })).toBeDefined()
  })

  it('shows no rejection banner or Reopen button on a live change', async () => {
    wrap('/changes/1')
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
    const scoping = await screen.findByRole('button', { name: /Scoping/ })
    expect((scoping as HTMLButtonElement).disabled).toBe(true)
    // Scoping gets the handoff note; the other locked tabs the generic one.
    expect(scoping.getAttribute('title')).toBe(t('tab.scopingHandoff'))
    const impacted = screen.getByRole('button', { name: /Impacted/ })
    expect((impacted as HTMLButtonElement).disabled).toBe(true)
    expect(impacted.getAttribute('title')).toBe(t('tab.lockedUntilScoping'))
    expect((screen.getByRole('button', { name: /Overview/ }) as HTMLButtonElement).disabled).toBe(false)
  })

  it('sends a deep link into a locked tab back to overview', async () => {
    change.status = 'captured' as ChangeDetail['status']
    wrap('/changes/1?tab=scoping')
    const overview = await screen.findByRole('button', { name: /Overview/ })
    expect(overview.className).toContain('border-b-2')
    // Overview content, not the scoping panel.
    expect(screen.getByText(/Reason:/)).toBeDefined()
  })

  it('unlocks scoping and impacted at scoping, but not the later phases', async () => {
    change.status = 'scoping' as ChangeDetail['status']
    wrap('/changes/1')
    const scoping = await screen.findByRole('button', { name: /Scoping/ })
    expect((scoping as HTMLButtonElement).disabled).toBe(false)
    expect((screen.getByRole('button', { name: /Impacted/ }) as HTMLButtonElement).disabled).toBe(false)
    const costing = screen.getByRole('button', { name: /Costing/ })
    expect((costing as HTMLButtonElement).disabled).toBe(true)
    expect(costing.getAttribute('title')).toBe(t('tab.lockedUntilPhase'))
    expect((screen.getByRole('button', { name: /Timing/ }) as HTMLButtonElement).disabled).toBe(true)
    expect((screen.getByRole('button', { name: /Assessments/ }) as HTMLButtonElement).disabled).toBe(true)
  })

  it('unlocks the costing tab once the change reaches costing', async () => {
    change.status = 'costing' as ChangeDetail['status']
    wrap('/changes/1')
    const costing = await screen.findByRole('button', { name: /Costing/ })
    expect((costing as HTMLButtonElement).disabled).toBe(false)
    expect((screen.getByRole('button', { name: /Assessments/ }) as HTMLButtonElement).disabled).toBe(false)
    // Timing is still a phase away.
    expect((screen.getByRole('button', { name: /Timing/ }) as HTMLButtonElement).disabled).toBe(true)
  })

  it('withholds nothing from an off-path change', async () => {
    change.status = 'rejected' as ChangeDetail['status']
    wrap('/changes/1')
    const costing = await screen.findByRole('button', { name: /Costing/ })
    expect((costing as HTMLButtonElement).disabled).toBe(false)
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

  it('opens the offer tab at quote creation', async () => {
    change.status = 'quoting' as ChangeDetail['status']
    change.customer_relevant = true
    wrap('/changes/1?tab=commercial')
    const offer = await screen.findByRole('button', { name: /Offer/ })
    expect((offer as HTMLButtonElement).disabled).toBe(false)
    expect(offer.className).toContain('border-b-2')
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
    await screen.findByRole('button', { name: /Overview/ })
    expect(screen.queryByTestId('description-input')).toBeNull()
  })

  it('shows the description read-only to an unrelated viewer', async () => {
    authState.current = { isAdmin: false, role: 'engineer', userId: 5 }
    change.status = 'captured' as ChangeDetail['status']
    wrap('/changes/1')
    await screen.findByRole('button', { name: /Overview/ })
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
    await screen.findByRole('button', { name: /Impacted/ })
    expect(screen.queryByTestId('tab-open-work')).toBeNull()
  })

  it('drops the mark once the phase moves on', async () => {
    change.status = 'in_assessment' as ChangeDetail['status']
    change.impact_confirmed_at = null
    wrap('/changes/1')
    await screen.findByRole('button', { name: /Impacted/ })
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
    wrap('/changes/1')
    const link = await screen.findByTestId('change-project')
    expect(link.textContent).toBe('1864 · VW426 Atlas')
    expect(link.getAttribute('href')).toBe('/projects/1')
  })

  it('says nothing when the change carries no project', async () => {
    change.project_number = null
    change.project_name = null
    wrap('/changes/1')
    await screen.findByRole('button', { name: /Overview/ })
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
