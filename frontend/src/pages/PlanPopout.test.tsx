import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, cleanup, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import PlanPopout from './PlanPopout'

const mocks = vi.hoisted(() => ({
  change: vi.fn(), plan: vi.fn(), feedback: vi.fn(),
  planner: vi.fn((p: Record<string, unknown>) => p),
}))
vi.mock('../api/changes', () => ({ changesApi: { get: mocks.change } }))
vi.mock('../api/changePlan', () => ({ planApi: { get: mocks.plan, feedback: mocks.feedback } }))
vi.mock('../components/changes/plan/GanttPlanner', () => ({
  default: (p: Record<string, unknown>) => {
    mocks.planner(p)
    return <div data-testid="planner">{`${p.changeId} ${p.plan} ${p.mode} ${String(p.inWindow)} ${String(p.changeNumber)}`}</div>
  },
}))

function mount(path: string) {
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter initialEntries={[path]}>
        <Routes><Route path="/changes/:changeId/plan/:plan" element={<PlanPopout />} /></Routes>
      </MemoryRouter>
    </QueryClientProvider>)
}

describe('PlanPopout', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mocks.change.mockResolvedValue({ id: 6, change_number: 'CR-2026-0006', title: 'Rib change', status: 'in_implementation' })
    mocks.plan.mockResolvedValue({ baseline_set: false })
    mocks.feedback.mockResolvedValue({ validated_at: null })
  })
  afterEach(cleanup)

  it('renders only the quote plan planner, full page, in window mode, with the title', async () => {
    mount('/changes/6/plan/quote')
    await waitFor(() => expect(screen.getByTestId('plan-popout-header').textContent).toContain('CR-2026-0006'))
    expect(screen.getByTestId('plan-popout-header').textContent).toContain('Quote plan')
    expect(screen.getByTestId('planner').textContent).toBe('6 quote plan true CR-2026-0006')
    expect(document.title).toBe('CR-2026-0006 - Quote plan')
    expect(mocks.plan).not.toHaveBeenCalled()
  })

  it('tracks the detailed plan once the change is in implementation', async () => {
    mount('/changes/6/plan/detailed')
    await waitFor(() => expect(screen.getByTestId('planner').textContent).toBe('6 detailed track true CR-2026-0006'))
    expect(mocks.planner).toHaveBeenLastCalledWith(expect.objectContaining({ status: 'in_implementation', hideSeed: true }))
  })

  it('refuses an unknown plan', () => {
    mount('/changes/6/plan/other')
    expect(screen.getByTestId('plan-popout-invalid')).toBeTruthy()
    expect(screen.queryByTestId('planner')).toBeNull()
  })
})
