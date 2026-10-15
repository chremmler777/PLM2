import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, fireEvent, cleanup, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import RouteDialog from './RouteDialog'
import type { Intake } from '../../api/intakes'

const changes = vi.hoisted(() => ({ list: vi.fn(), get: vi.fn() }))
vi.mock('../../api/changes', () => ({ changesApi: changes }))

const intake = (over: Partial<Intake> = {}): Intake => ({
  id: 7, part_id: 3, part_number: '886.197', part_name: 'Cover', customer_part_number: null,
  project_id: 1, project_name: 'P', revision_id: 40, revision_name: 'D', customer_index: 'D',
  revision_status: 'in_review', active_revision_name: 'C', file_count: 1, source: 'package',
  source_label: 'Customer package', batch_id: null, received_at: '2026-10-15', received_by_name: 'Eva',
  status: 'pending', waiting: true, revision_phase: 'official', part_phase: 'series',
  suggested_route: 'attach_ecr', phase_route: 'full_ecr', route: null, route_label: null, reason: null,
  decided_by_name: null, decided_at: null, change_id: null, change_number: null, change_title: null,
  change_status: null, change_origin: null, activated_at: null, escalated_at: null, superseded_by_id: null,
  created_at: '2026-10-15T10:00:00', needs_triage: true, can_decide: true, scoping_v2: true,
  live_change: { id: 5, change_number: 'CR-5', title: 'Live', status: 'in_assessment', lead_name: 'Holmes',
    customer_relevant: true, attachable: true },
  ...over,
})

function show(i: Intake, onSubmit = vi.fn()) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(<QueryClientProvider client={qc}>
    <RouteDialog intake={i} onClose={() => {}} onSubmit={onSubmit} />
  </QueryClientProvider>)
  return onSubmit
}
const submit = () => screen.getByTestId('route-submit') as HTMLButtonElement

describe('RouteDialog (§1 intake)', () => {
  afterEach(() => { cleanup(); vi.clearAllMocks() })

  it('names the live change, preselects attach to it and asks what changed', async () => {
    changes.list.mockResolvedValue([{ id: 5, change_number: 'CR-5', title: 'Live', status: 'in_assessment',
      customer_relevant: true, origin: 'customer' }])
    const onSubmit = show(intake())
    expect(screen.getByTestId('live-change').textContent).toContain('CR-5 (')
    expect(screen.getByTestId('live-change').textContent).toContain('lead Holmes')
    await waitFor(() => expect((screen.getByTestId('attach-change') as HTMLSelectElement).value).toBe('5'))
    // nothing picked: blocked until what changed is answered with a reference
    expect(submit().disabled).toBe(true)
    fireEvent.click(screen.getByTestId('area-geometry'))
    fireEvent.change(screen.getByTestId('what-ref'), { target: { value: 'ok' } })
    expect(submit().disabled).toBe(true)
    fireEvent.change(screen.getByTestId('what-ref'), { target: { value: 'Compare CR-118' } })
    expect(submit().disabled).toBe(false)
    fireEvent.click(submit())
    expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({
      route: 'attach_ecr', change_id: 5, what_changed: ['geometry'], what_changed_ref: 'Compare CR-118' }))
  })

  it('full ECR beside a live change needs the reason pick', () => {
    changes.list.mockResolvedValue([])
    const onSubmit = show(intake())
    fireEvent.click(screen.getByTestId('route-full_ecr').querySelector('input')!)
    fireEvent.click(screen.getByTestId('area-none'))
    fireEvent.change(screen.getByTestId('no-change-reason'), { target: { value: 'Title block only' } })
    expect(submit().disabled).toBe(true)
    fireEvent.change(screen.getByTestId('live-reason'), { target: { value: 'separate_topic' } })
    expect(submit().disabled).toBe(false)
    fireEvent.click(submit())
    expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({
      route: 'full_ecr', live_change_reason: 'separate_topic', what_changed: ['none'],
      no_change_reason: 'Title block only' }))
  })

  it('attaching to an internal change asks whether it is customer-driven', async () => {
    changes.list.mockResolvedValue([{ id: 5, change_number: 'CR-5', title: 'Live', status: 'scoping',
      customer_relevant: false, origin: 'internal' }])
    const onSubmit = show(intake({ live_change: { id: 5, change_number: 'CR-5', title: 'Live',
      status: 'scoping', lead_name: null, customer_relevant: false, attachable: true } }))
    fireEvent.click(screen.getByTestId('area-material'))
    fireEvent.change(screen.getByTestId('what-ref'), { target: { value: 'Drawing D zone B2' } })
    await screen.findByTestId('customer-driven')
    expect(submit().disabled).toBe(true)
    fireEvent.click(screen.getByTestId('customer-driven-yes'))
    expect(submit().disabled).toBe(false)
    fireEvent.click(submit())
    expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({ customer_driven: true }))
  })

  it('switch off: no what-changed step', () => {
    changes.list.mockResolvedValue([])
    show(intake({ scoping_v2: false, live_change: null, suggested_route: 'engineering_review' }))
    expect(screen.queryByTestId('what-changed')).toBeNull()
    expect(submit().disabled).toBe(false)
  })
})
