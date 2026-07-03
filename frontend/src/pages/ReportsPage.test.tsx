import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, cleanup } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import ReportsPage from './ReportsPage'

vi.mock('../api/reports', () => ({
  reportsApi: {
    pipeline: vi.fn().mockResolvedValue({
      funnel: [
        { status: 'captured', count: 0 },
        { status: 'in_assessment', count: 3 },
        { status: 'costing', count: 0 },
        { status: 'quoted', count: 0 },
        { status: 'approved', count: 0 },
        { status: 'in_implementation', count: 0 },
        { status: 'in_validation', count: 0 },
        { status: 'released', count: 1 },
        { status: 'closed', count: 0 },
        { status: 'on_hold', count: 0 },
        { status: 'rejected', count: 0 },
        { status: 'cancelled', count: 0 },
      ],
      throughput: [{ month: '2026-07', released: 1 }],
      avg_stage_days: [{ from_status: 'captured', to_status: 'in_assessment', avg_days: 2.5 }],
      on_time_rate: 0.8,
    }),
    workload: vi.fn().mockResolvedValue({
      departments: [{ department_id: 1, name: 'Engineering', open: 4, overdue: 1 }],
      owners: [{ owner_id: 1, owner_name: 'Alice', open: 2, overdue: 0 }],
      at_risk_changes: [
        { id: 42, change_number: 'GB-CM-0042', title: 'Risky change', required_by_date: '2026-07-10', state: 'at_risk' },
      ],
      escalation_count: 2,
    }),
    cost: vi.fn().mockResolvedValue({
      projects: [{ project_id: 1, name: 'Project X', budget: 10000, actual: 8000 }],
      plants: [{ plant_id: 1, name: 'Plant A', actual: 5000 }],
    }),
  },
}))

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <ReportsPage />
      </MemoryRouter>
    </QueryClientProvider>
  )
}

describe('ReportsPage', () => {
  afterEach(() => cleanup())

  it('renders a funnel row per non-zero status with count and a drill-through link', async () => {
    renderPage()
    const count = await screen.findByText('3')
    expect(count).toBeDefined()
    const link = screen.getByRole('link', { name: /in assessment/i }) as HTMLAnchorElement
    expect(link.getAttribute('href')).toBe('/changes?status=in_assessment')
  })

  it('renders workload department row with open/overdue counts', async () => {
    renderPage()
    const cell = await screen.findByText('Engineering')
    const row = cell.closest('tr') as HTMLElement
    expect(row).not.toBeNull()
    expect(row.textContent).toContain('4')
    expect(row.textContent).toContain('1')
  })

  it('renders cost project row with formatted actual', async () => {
    renderPage()
    expect(await screen.findByText('Project X')).toBeDefined()
    expect(screen.getByText(/8[.,]000/)).toBeDefined()
  })
})
