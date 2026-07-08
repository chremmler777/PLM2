import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, cleanup, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import PnlPage from './PnlPage'

const summaryFixture = {
  totals: { revenue: 100000, internal_cost: 20000, external_cost: 10000, total_cost: 30000, margin: 70000, margin_pct: 70 },
  pipeline: { revenue: 40000, internal_cost: 8000, external_cost: 2000, total_cost: 10000, margin: 30000, margin_pct: 75 },
  realized: { revenue: 60000, internal_cost: 12000, external_cost: 8000, total_cost: 20000, margin: 40000, margin_pct: 66.67 },
  by_project: [{ project_id: 1, name: 'Project X', revenue: 100000, total_cost: 30000, margin: 70000 }],
  by_branch: {
    customer: { revenue: 90000, internal_cost: 18000, external_cost: 9000, total_cost: 27000, margin: 63000, margin_pct: 70 },
    internal: { revenue: 10000, internal_cost: 2000, external_cost: 1000, total_cost: 3000, margin: 7000, margin_pct: 70 },
  },
  count: 2,
}

const rowsFixture = [
  {
    change_id: 1, change_number: 'GB-CM-0001', title: 'Positive margin change',
    project_id: 1, project_name: 'Project X', branch: 'customer', status: 'quoted',
    revenue: 50000, internal_cost: 8000, external_cost: 2000, total_cost: 10000,
    margin: 40000, margin_pct: 80, effort_hours: 12, pending_price: false, realized: false,
  },
  {
    change_id: 2, change_number: 'GB-CM-0002', title: 'Pending price change',
    project_id: 1, project_name: 'Project X', branch: 'customer', status: 'costing',
    revenue: null, internal_cost: 5000, external_cost: 1000, total_cost: 6000,
    margin: null, margin_pct: null, effort_hours: 4, pending_price: true, realized: false,
  },
]

const changesMock = vi.fn().mockResolvedValue({ rows: rowsFixture })
const summaryMock = vi.fn().mockResolvedValue(summaryFixture)

vi.mock('../api/pnl', () => ({
  pnlApi: {
    changes: (...args: unknown[]) => changesMock(...args),
    summary: (...args: unknown[]) => summaryMock(...args),
  },
}))

vi.mock('../api/client', () => ({
  default: {
    get: vi.fn((url: string) => {
      if (url === '/v1/plants') {
        return Promise.resolve({ data: [{ id: 9, name: 'Plant A', code: 'PA' }] })
      }
      return Promise.resolve({ data: [{ id: 1, name: 'Project X' }] })
    }),
  },
}))

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <PnlPage />
      </MemoryRouter>
    </QueryClientProvider>
  )
}

describe('PnlPage', () => {
  afterEach(() => cleanup())

  it('renders summary tiles from summary data', async () => {
    renderPage()
    expect(await screen.findByText(/100[.,]000/)).toBeDefined()
    expect(screen.getByText(/70[.,]000/)).toBeDefined()
    expect(screen.getByText('70.0%')).toBeDefined()
  })

  it('renders a row with an emerald margin badge for positive margin', async () => {
    renderPage()
    const link = await screen.findByRole('link', { name: 'GB-CM-0001' })
    expect(link.getAttribute('href')).toBe('/changes/1?tab=commercial')
    const row = link.closest('tr') as HTMLElement
    const badge = row.querySelector('.text-emerald-400, .bg-emerald-900, [class*="emerald"]')
    expect(badge).not.toBeNull()
  })

  it('shows a "price pending" chip and dash revenue for pending_price rows', async () => {
    renderPage()
    const link = await screen.findByRole('link', { name: 'GB-CM-0002' })
    const row = link.closest('tr') as HTMLElement
    expect(row.textContent).toMatch(/price pending/i)
    expect(row.textContent).toContain('—')
  })

  it('triggers a refetch with the branch param when the branch filter changes', async () => {
    renderPage()
    await screen.findByRole('link', { name: 'GB-CM-0001' })
    changesMock.mockClear()
    summaryMock.mockClear()

    fireEvent.click(screen.getByRole('button', { name: /internal/i }))

    await waitFor(() => {
      expect(changesMock).toHaveBeenCalledWith(expect.objectContaining({ branch: 'internal' }))
    })
  })

  it('triggers a refetch with the plant_id param when the plant filter changes', async () => {
    renderPage()
    await screen.findByRole('link', { name: 'GB-CM-0001' })
    changesMock.mockClear()
    summaryMock.mockClear()

    const select = await screen.findByLabelText(/plant/i)
    fireEvent.change(select, { target: { value: '9' } })

    await waitFor(() => {
      expect(changesMock).toHaveBeenCalledWith(expect.objectContaining({ plant_id: 9 }))
    })
  })

  it('triggers a refetch with date_from/date_to params when the date filters change', async () => {
    renderPage()
    await screen.findByRole('link', { name: 'GB-CM-0001' })
    changesMock.mockClear()
    summaryMock.mockClear()

    fireEvent.change(screen.getByLabelText(/from/i), { target: { value: '2026-01-01' } })
    await waitFor(() => {
      expect(changesMock).toHaveBeenCalledWith(expect.objectContaining({ date_from: '2026-01-01' }))
    })

    fireEvent.change(screen.getByLabelText(/to/i), { target: { value: '2026-01-31' } })
    await waitFor(() => {
      expect(changesMock).toHaveBeenCalledWith(
        expect.objectContaining({ date_from: '2026-01-01', date_to: '2026-01-31' })
      )
    })
  })
})
