import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import IntakePanel from './IntakePanel'
import type { Intake } from '../../api/intakes'

const api = vi.hoisted(() => ({ list: vi.fn(), decide: vi.fn(), my: vi.fn(), review: vi.fn(), answer: vi.fn(), escalate: vi.fn() }))
vi.mock('../../api/intakes', async (orig) => ({
  ...(await orig<typeof import('../../api/intakes')>()), intakesApi: api,
}))
const changes = vi.hoisted(() => ({ list: vi.fn() }))
vi.mock('../../api/changes', () => ({ changesApi: changes }))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

const intake = (over: Partial<Intake> = {}): Intake => ({
  id: 7, part_id: 3, part_number: '20-1994-001', part_name: 'Cover', customer_part_number: '3CR.807.425',
  project_id: 1, project_name: '1994 Brose', revision_id: 40, revision_name: 'E2', customer_index: 'B',
  revision_status: 'in_review', active_revision_name: 'E1', file_count: 1, source: 'package',
  source_label: 'Customer package', batch_id: 'b1', received_at: '2026-09-20', received_by_name: 'Eva',
  status: 'pending', waiting: true, revision_phase: 'review', part_phase: 'nominated',
  suggested_route: 'engineering_review', route: null, route_label: null, reason: null,
  decided_by_name: null, decided_at: null, change_id: null, change_number: null, change_title: null,
  change_status: null, change_origin: null, activated_at: null, escalated_at: null, superseded_by_id: null,
  created_at: '2026-09-20T10:00:00', needs_triage: true, can_decide: true, ...over,
})

function wrap() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}><MemoryRouter>
    <IntakePanel partId={3} />
  </MemoryRouter></QueryClientProvider>)
}

describe('IntakePanel', () => {
  beforeEach(() => { Object.values(api).forEach((f) => f.mockReset()); changes.list.mockReset() })
  afterEach(cleanup)

  it('shows the pending banner and lets Development decide with the suggested route', async () => {
    api.list.mockResolvedValue({ can_triage: true, intakes: [intake()] })
    api.decide.mockResolvedValue(intake({ status: 'decided', route: 'engineering_review', route_label: 'Engineering review', change_number: 'ECR-9' }))
    wrap()
    expect((await screen.findByTestId('intake-banner')).textContent).toBe('Index E2 (customer B) pending triage')
    expect(screen.getByTestId('intake-panel').textContent).toContain('Active until decided: E1')
    fireEvent.click(screen.getByTestId('triage-7'))
    const dialog = screen.getByTestId('route-dialog')
    // the suggested route is preselected and marked, no reason needed
    expect(screen.getByTestId('route-engineering_review').textContent).toContain('Suggested: Review data (E level) before series')
    expect((screen.getByTestId('route-submit') as HTMLButtonElement).disabled).toBe(false)
    expect(dialog.textContent).not.toContain('—')
    fireEvent.click(screen.getByTestId('route-submit'))
    await waitFor(() => expect(api.decide).toHaveBeenCalledWith(7, { route: 'engineering_review', reason: undefined, change_id: undefined }))
  })

  it('needs a reason for administrative and a change for attach', async () => {
    api.list.mockResolvedValue({ can_triage: true, intakes: [intake()] })
    changes.list.mockResolvedValue([
      { id: 5, change_number: 'ECR-5', title: 'Open one', status: 'scoping' },
      { id: 6, change_number: 'ECR-6', title: 'Too late', status: 'in_validation' },
    ])
    wrap()
    fireEvent.click(await screen.findByTestId('triage-7'))
    fireEvent.click(screen.getByTestId('route-administrative').querySelector('input')!)
    const submit = screen.getByTestId('route-submit') as HTMLButtonElement
    expect(submit.disabled).toBe(true)
    fireEvent.change(screen.getByTestId('route-reason'), { target: { value: 'title block only' } })
    expect(submit.disabled).toBe(false)
    expect(submit.textContent).toBe('Activate now')
    fireEvent.click(screen.getByTestId('route-attach_ecr').querySelector('input')!)
    expect(submit.disabled).toBe(true)
    const select = await screen.findByTestId('attach-change')
    await waitFor(() => expect(select.textContent).toContain('ECR-5'))
    expect(select.textContent).not.toContain('ECR-6')
    fireEvent.change(select, { target: { value: '5' } })
    fireEvent.click(submit)
    await waitFor(() => expect(api.decide).toHaveBeenCalledWith(7, { route: 'attach_ecr', reason: 'title block only', change_id: 5 }))
  })

  it('names the reason field and closes the triage on Escape', async () => {
    api.list.mockResolvedValue({ can_triage: true, intakes: [intake()] })
    wrap()
    fireEvent.click(await screen.findByTestId('triage-7'))
    expect(screen.getByLabelText(/^Reason/).tagName).toBe('TEXTAREA')
    fireEvent.keyDown(screen.getByTestId('route-dialog'), { key: 'Escape' })
    await waitFor(() => expect(screen.queryByTestId('route-dialog')).toBeNull())
    expect(api.decide).not.toHaveBeenCalled()
  })

  it('is read-only for others and says who decides', async () => {
    api.list.mockResolvedValue({ can_triage: false, intakes: [intake({ can_decide: false })] })
    wrap()
    expect((await screen.findByTestId('intake-readonly')).textContent).toContain('Development decides')
    expect(screen.queryByTestId('triage-7')).toBeNull()
  })

  it('shows a decided index waiting on its change', async () => {
    api.list.mockResolvedValue({ can_triage: true, intakes: [intake({
      status: 'decided', needs_triage: false, can_decide: false, route: 'full_ecr', route_label: 'Full ECR',
      change_id: 12, change_number: 'ECR-12', change_status: 'costing', decided_by_name: 'Dora', decided_at: '2026-09-21T08:00:00' })] })
    wrap()
    const row = await screen.findByTestId('intake-linked')
    expect(row.textContent).toContain('Index E2 is pending: Full ECR in ECR-12 (Costing)')
    expect(screen.queryByTestId('intake-banner')).toBeNull()
  })

  it('renders nothing without a pending index', async () => {
    api.list.mockResolvedValue({ can_triage: true, intakes: [] })
    const { container } = wrap()
    await waitFor(() => expect(api.list).toHaveBeenCalled())
    expect(container.querySelector('[data-testid="intake-panel"]')).toBeNull()
  })
})
