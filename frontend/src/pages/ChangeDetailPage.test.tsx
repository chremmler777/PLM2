import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, cleanup } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import ChangeDetailPage from './ChangeDetailPage'
import { changesApi } from '../api/changes'
import { useDepartments } from '../hooks/queries/useWorkflows'
import type { ChangeDetail } from '../types/change'

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
    impacted_items: [],
    assessments: [],
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
  },
}))
vi.mock('../components/changes/PnlCard', () => ({ default: () => <div>mock-pnl-card</div> }))
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

vi.mock('../components/changes/AssessmentRouting', () => ({ default: () => <div>mock-assessment-routing</div> }))
vi.mock('../components/changes/D1MasterPanel', () => ({ default: () => <div>mock-d1-panel</div> }))
vi.mock('../components/changes/SummationView', () => ({ default: () => <div>mock-summation</div> }))
vi.mock('../components/changes/CostLineGrid', () => ({ default: () => <div>mock-cost-line-grid</div> }))
vi.mock('../components/changes/DeviationBanner', () => ({ default: () => <div>mock-deviation-banner</div> }))
vi.mock('../components/changes/ReasonDialog', () => ({ default: () => <div>mock-reason-dialog</div> }))
vi.mock('../components/changes/ImpactTree', () => ({ default: () => <div>mock-impact-tree</div> }))
vi.mock('../components/changes/ImplementationPanel', () => ({ default: () => <div>mock-implementation-panel</div> }))
vi.mock('../components/changes/LifecycleStepper', () => ({ default: () => <div>mock-lifecycle-stepper</div> }))
vi.mock('../components/changes/CockpitSummary', () => ({ default: () => <div>mock-cockpit-summary</div> }))
vi.mock('../components/changes/DeadlineChip', () => ({ DeadlineChip: () => <div>mock-deadline-chip</div> }))
vi.mock('../components/changes/AuditTimeline', () => ({ default: () => <div>mock-audit-timeline</div> }))

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

describe('ChangeDetailPage commercial tab sign-off (F8)', () => {
  afterEach(() => {
    cleanup()
    authState.current = { isAdmin: false, role: 'engineer', userId: null }
    change.status = 'in_assessment'
    change.customer_relevant = undefined
    change.pm_signed_by = null
    change.quality_signed_by = null
  })

  it('disables the Quality sign-off button and shows the 4-eyes hint when the same user already PM-signed', async () => {
    authState.current = { isAdmin: true, role: 'admin', userId: 42 }
    change.status = 'quoted'
    change.customer_relevant = true
    change.pm_signed_by = 42
    change.quality_signed_by = null
    wrap('/changes/1?tab=commercial')
    const qualityButton = await screen.findByRole('button', { name: /Quality sign-off/ })
    expect(qualityButton).toHaveProperty('disabled', true)
    expect(screen.getByText('PM and Quality sign-off must be different users')).toBeDefined()
  })

  it('leaves both sign-off buttons enabled when no one has signed yet', async () => {
    authState.current = { isAdmin: true, role: 'admin', userId: 42 }
    change.status = 'quoted'
    change.customer_relevant = true
    change.pm_signed_by = null
    change.quality_signed_by = null
    wrap('/changes/1?tab=commercial')
    const pmButton = await screen.findByRole('button', { name: /PM sign-off/ })
    const qualityButton = screen.getByRole('button', { name: /Quality sign-off/ })
    expect(pmButton).toHaveProperty('disabled', false)
    expect(qualityButton).toHaveProperty('disabled', false)
    expect(screen.queryByText('PM and Quality sign-off must be different users')).toBeNull()
  })

  it('hides both sign-off buttons for a non-member, non-admin, non-PM viewer', async () => {
    vi.mocked(useDepartments).mockReturnValue({ data: [] } as unknown as ReturnType<typeof useDepartments>)
    vi.mocked(changesApi.myActions).mockResolvedValue({ actions: [], memberships: [] })
    authState.current = { isAdmin: false, role: 'engineer', userId: 5 }
    change.status = 'quoted'
    change.customer_relevant = true
    wrap('/changes/1?tab=commercial')
    await screen.findByText(/Customer response/)
    expect(screen.queryByRole('button', { name: /PM sign-off/ })).toBeNull()
    expect(screen.queryByRole('button', { name: /Quality sign-off/ })).toBeNull()
  })

  it('shows only the Quality sign-off button for a Quality department member', async () => {
    vi.mocked(useDepartments).mockReturnValue({
      data: [{ id: 7, name: 'Quality', flow_type: 'action', is_active: true, sort_order: 1 }],
    } as unknown as ReturnType<typeof useDepartments>)
    vi.mocked(changesApi.myActions).mockResolvedValue({ actions: [], memberships: [7] })
    authState.current = { isAdmin: false, role: 'engineer', userId: 5 }
    change.status = 'quoted'
    change.customer_relevant = true
    wrap('/changes/1?tab=commercial')
    const qualityButton = await screen.findByRole('button', { name: /Quality sign-off/ })
    expect(qualityButton).toBeDefined()
    expect(screen.queryByRole('button', { name: /PM sign-off/ })).toBeNull()
  })
})

describe('ChangeDetailPage commercial tab quoted-price and internal-approval authz', () => {
  afterEach(() => {
    cleanup()
    authState.current = { isAdmin: false, role: 'engineer', userId: null }
    change.status = 'in_assessment'
    change.customer_relevant = undefined
    change.lead_id = null
    vi.mocked(useDepartments).mockReturnValue({ data: [] } as unknown as ReturnType<typeof useDepartments>)
    vi.mocked(changesApi.myActions).mockResolvedValue({ actions: [], memberships: [] })
  })

  it('hides the quoted-price edit control for a non-lead, non-Sales, non-admin viewer', async () => {
    authState.current = { isAdmin: false, role: 'engineer', userId: 5 }
    change.status = 'costing'
    change.customer_relevant = true
    change.quoted_price = 1000
    wrap('/changes/1?tab=commercial')
    await screen.findByText(/Quoted price/)
    expect(screen.queryByRole('spinbutton')).toBeNull()
  })

  it('shows the quoted-price edit control for the change lead', async () => {
    change.lead_id = 5
    authState.current = { isAdmin: false, role: 'engineer', userId: 5 }
    change.status = 'costing'
    change.customer_relevant = true
    change.quoted_price = 1000
    wrap('/changes/1?tab=commercial')
    await screen.findByText(/Quoted price/)
    expect(screen.queryByRole('spinbutton')).not.toBeNull()
  })

  it('hides the internal-approve button for a non-PM, non-admin viewer', async () => {
    authState.current = { isAdmin: false, role: 'engineer', userId: 5 }
    change.status = 'costing'
    change.customer_relevant = false
    wrap('/changes/1?tab=commercial')
    await screen.findByText(/Project Manager department member/)
    expect(screen.queryByText('Approve internal costs')).toBeNull()
  })

  it('shows the internal-approve button for a Project Manager department member', async () => {
    vi.mocked(useDepartments).mockReturnValue({
      data: [{ id: 9, name: 'Project Manager', flow_type: 'action', is_active: true, sort_order: 1 }],
    } as unknown as ReturnType<typeof useDepartments>)
    vi.mocked(changesApi.myActions).mockResolvedValue({ actions: [], memberships: [9] })
    authState.current = { isAdmin: false, role: 'engineer', userId: 5 }
    change.status = 'costing'
    change.customer_relevant = false
    wrap('/changes/1?tab=commercial')
    expect(await screen.findByText('Approve internal costs')).toBeDefined()
  })
})
