import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, cleanup } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import ChangeDetailPage from './ChangeDetailPage'
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
    status: 'in_assessment',
    lead_id: null,
    lead_name: null,
    raised_by: 1,
    customer_response: 'pending',
    pm_signed_by: null,
    quality_signed_by: null,
    estimated_cost: null,
    quoted_price: null,
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
    uploadAttachment: vi.fn(),
  },
}))
vi.mock('../api/plants', () => ({
  plantsApi: { list: vi.fn().mockResolvedValue([]) },
}))
vi.mock('../hooks/queries/useWorkflows', () => ({
  useDepartments: () => ({ data: [] }),
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
  afterEach(cleanup)

  it('renders with the D1 tab active when ?tab=d1', async () => {
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
