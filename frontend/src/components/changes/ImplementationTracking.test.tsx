import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, cleanup, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import ImplementationTracking, { vendorLeadTimeLine } from './ImplementationTracking'
import { changesApi } from '../../api/changes'
import { t } from '../../i18n/cmLabels'

vi.mock('../../api/changes', () => ({
  changesApi: {
    implementationState: vi.fn(),
    listImplBookings: vi.fn(),
    listImplReports: vi.fn(),
    listImplEscalations: vi.fn(),
    listCostPositions: vi.fn(),
    addImplBooking: vi.fn(),
    deleteImplBooking: vi.fn(),
    addImplReport: vi.fn(),
    addImplEscalation: vi.fn(),
    resolveImplEscalation: vi.fn(),
  },
}))
vi.mock('sonner', () => ({ toast: { error: vi.fn(), success: vi.fn() } }))
vi.mock('../../contexts/AuthContext', () => ({ useAuth: () => ({ userId: 5, isAdmin: false }) }))

const departments = [{ id: 2, name: 'Development' }, { id: 4, name: 'Tool Engineer' }]

const stateRow = (over: Record<string, unknown> = {}) => ({
  department_id: 2, booked_hours: 0, last_report_at: null,
  at_risk_open: false, owes_report: false, ...over,
})

const render_ = (props: Record<string, unknown> = {}) => render(
  <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <ImplementationTracking changeId={7} status="in_implementation"
      departments={departments} myDepartmentIds={[2]}
      canSeeAll={false} canEscalate={false} {...props} />
  </QueryClientProvider>)

const setData = (over: {
  state?: unknown[]; bookings?: unknown[]; reports?: unknown[]
  escalations?: unknown[]; positions?: unknown[]
} = {}) => {
  vi.mocked(changesApi.implementationState).mockResolvedValue((over.state ?? []) as never)
  vi.mocked(changesApi.listImplBookings).mockResolvedValue((over.bookings ?? []) as never)
  vi.mocked(changesApi.listImplReports).mockResolvedValue((over.reports ?? []) as never)
  vi.mocked(changesApi.listImplEscalations).mockResolvedValue((over.escalations ?? []) as never)
  vi.mocked(changesApi.listCostPositions).mockResolvedValue((over.positions ?? []) as never)
}

describe('vendorLeadTimeLine', () => {
  it('reads the favourite offer of every quoted external position', () => {
    const line = vendorLeadTimeLine([
      {
        id: 1, department_id: 4, label: 'Equipment change', kind: 'external',
        pricing: 'quote',
        offers: [
          { id: 1, vendor_name: 'VendorB', cost: 900, lead_time_days: 60 },
          { id: 2, vendor_name: 'VendorA', cost: 800, lead_time_days: 30,
            lead_time_unit: 'business_days', favorite: true },
        ],
      },
      // No favourite yet, and an internal position — neither has a lead time
      // anybody could act on.
      { id: 2, department_id: 4, label: 'Trials', kind: 'external', pricing: 'quote',
        offers: [{ id: 3, vendor_name: 'VendorC', cost: 100, lead_time_days: 5 }] },
      { id: 3, department_id: 2, label: 'Drawings', kind: 'internal_effort', offers: [] },
    ] as never)
    expect(line).toBe(
      `${t('impl2.vendorLeadTimes')}: Equipment change — 30 business days (VendorA)`)
  })

  it('says nothing when no vendor has been picked', () => {
    expect(vendorLeadTimeLine([])).toBeNull()
  })
})

describe('ImplementationTracking scoping', () => {
  beforeEach(() => { vi.clearAllMocks() })
  afterEach(cleanup)

  it('gives an ordinary member their own block and counts the rest in a line', async () => {
    setData({ state: [stateRow({ department_id: 2 }), stateRow({ department_id: 4 })] })
    render_()
    expect(await screen.findByTestId('impl-block-2')).toBeTruthy()
    expect(screen.queryByTestId('impl-block-4')).toBeNull()
    expect(screen.getByTestId('impl-tracking-others').textContent).toContain('1')
  })

  it('shows every block to PM, Sales, the lead and admins', async () => {
    setData({ state: [stateRow({ department_id: 2 }), stateRow({ department_id: 4 })] })
    render_({ canSeeAll: true })
    expect(await screen.findByTestId('impl-block-2')).toBeTruthy()
    expect(screen.getByTestId('impl-block-4')).toBeTruthy()
    expect(screen.queryByTestId('impl-tracking-others')).toBeNull()
  })

  it('shows another department read-only — no booking or report controls', async () => {
    setData({ state: [stateRow({ department_id: 4 })] })
    render_({ canSeeAll: true })
    expect(await screen.findByTestId('impl-block-4')).toBeTruthy()
    expect(screen.queryByTestId('impl-booking-add-4')).toBeNull()
    expect(screen.queryByTestId('impl-report-add-4')).toBeNull()
  })

  it('closes the writes once the change has left implementation', async () => {
    setData({ state: [stateRow()] })
    render_({ status: 'in_validation' })
    expect(await screen.findByTestId('impl-tracking-readonly')).toBeTruthy()
    expect(screen.queryByTestId('impl-booking-add-2')).toBeNull()
    expect(screen.queryByTestId('impl-report-add-2')).toBeNull()
  })
})

describe('ImplementationTracking booked time', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(changesApi.addImplBooking).mockResolvedValue({} as never)
    vi.mocked(changesApi.deleteImplBooking).mockResolvedValue({} as never)
  })
  afterEach(cleanup)

  it('books hours with a note and keeps a zero out of the log', async () => {
    setData({ state: [stateRow({ booked_hours: 12.5 })] })
    render_()
    expect((await screen.findByTestId('impl-hours-2')).textContent)
      .toBe(t('impl2.bookedHours').replace('{n}', '12.5'))

    // Nothing to book is not a booking.
    expect((screen.getByTestId('impl-booking-add-2') as HTMLButtonElement).disabled).toBe(true)
    fireEvent.change(screen.getByTestId('impl-booking-hours-2'), { target: { value: '3.5' } })
    fireEvent.change(screen.getByTestId('impl-booking-note-2'),
      { target: { value: 'tool trial at Ostrava' } })
    fireEvent.click(screen.getByTestId('impl-booking-add-2'))
    await waitFor(() => expect(changesApi.addImplBooking).toHaveBeenCalledWith(7, {
      department_id: 2, hours: 3.5, note: 'tool trial at Ostrava',
    }))
  })

  it('lets a member drop their own entry and nobody else’s', async () => {
    setData({
      state: [stateRow({ booked_hours: 5 })],
      bookings: [
        { id: 11, department_id: 2, hours: 2, note: 'mine', created_by: 5 },
        { id: 12, department_id: 2, hours: 3, note: 'someone else', created_by: 9 },
      ],
    })
    render_()
    expect(await screen.findByTestId('impl-booking-delete-11')).toBeTruthy()
    expect(screen.queryByTestId('impl-booking-delete-12')).toBeNull()
    fireEvent.click(screen.getByTestId('impl-booking-delete-11'))
    await waitFor(() => expect(changesApi.deleteImplBooking).toHaveBeenCalledWith(7, 11))
  })
})

describe('ImplementationTracking progress reports', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(changesApi.addImplReport).mockResolvedValue({} as never)
  })
  afterEach(cleanup)

  it('paints the cadence chip amber the moment a report is owed', async () => {
    setData({ state: [stateRow({ owes_report: true })] })
    const { unmount } = render_()
    const due = await screen.findByTestId('impl-cadence-2')
    expect(due.textContent).toBe(t('impl2.reportDue'))
    expect(due.className).toContain('amber')
    unmount()
    cleanup()

    setData({ state: [stateRow({ owes_report: false, last_report_at: '2026-08-10T09:00:00' })] })
    render_()
    const ok = await screen.findByTestId('impl-cadence-2')
    expect(ok.textContent).toBe(t('impl2.reported'))
    expect(ok.className).toContain('emerald')
  })

  it('shows the history with its author, the red chip and the risk note', async () => {
    setData({
      state: [stateRow({ at_risk_open: true })],
      reports: [{
        id: 21, department_id: 2, note: 'tool back from rework', at_risk: true,
        risk_note: 'second trial slipped a week', created_by_name: 'dev.eva',
        created_at: '2026-08-10T09:00:00',
      }],
    })
    render_()
    const row = await screen.findByTestId('impl-report-21')
    expect(row.textContent).toContain('tool back from rework')
    expect(row.textContent).toContain('dev.eva')
    expect(screen.getByTestId('impl-report-risk-21').textContent).toBe(t('impl2.atRisk'))
    expect(screen.getByTestId('impl-report-risknote-21').textContent)
      .toBe('second trial slipped a week')
    expect(screen.getByTestId('impl-atrisk-2')).toBeTruthy()
  })

  it('reveals the risk-note field on the toggle and will not send it empty', async () => {
    setData({ state: [stateRow()] })
    render_()
    fireEvent.change(await screen.findByTestId('impl-report-note-2'),
      { target: { value: 'trial 2 running' } })
    // A plain report needs nothing else.
    expect((screen.getByTestId('impl-report-add-2') as HTMLButtonElement).disabled).toBe(false)
    expect(screen.queryByTestId('impl-report-risknote-input-2')).toBeNull()

    fireEvent.click(screen.getByTestId('impl-report-atrisk-2'))
    expect(screen.getByTestId('impl-report-risknote-input-2')).toBeTruthy()
    expect((screen.getByTestId('impl-report-add-2') as HTMLButtonElement).disabled).toBe(true)
    expect(screen.getByTestId('impl-report-riskrequired-2').textContent)
      .toBe(t('impl2.riskNoteRequired'))

    fireEvent.change(screen.getByTestId('impl-report-risknote-input-2'),
      { target: { value: 'vendor slipped two weeks' } })
    fireEvent.click(screen.getByTestId('impl-report-add-2'))
    await waitFor(() => expect(changesApi.addImplReport).toHaveBeenCalledWith(7, {
      department_id: 2, note: 'trial 2 running', at_risk: true,
      risk_note: 'vendor slipped two weeks',
    }))
  })
})

describe('ImplementationTracking escalations', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(changesApi.addImplEscalation).mockResolvedValue({} as never)
    vi.mocked(changesApi.resolveImplEscalation).mockResolvedValue({} as never)
  })
  afterEach(cleanup)

  const atRisk = {
    state: [stateRow({ at_risk_open: true })],
    reports: [{ id: 21, department_id: 2, note: 'slipping', at_risk: true,
      risk_note: 'vendor late' }],
  }

  it('shows the escalation log to a plain member but gives them no controls', async () => {
    setData({
      ...atRisk,
      escalations: [{
        id: 31, direction: 'customer', note: 'told the customer about CW40',
        report_id: 21, resolved_at: null, created_by_name: 'sales.anna',
      }],
    })
    render_()
    const row = await screen.findByTestId('impl-escalation-2-31')
    expect(row.textContent).toContain('told the customer about CW40')
    expect(screen.getByTestId('impl-escalation-direction-31').textContent)
      .toBe(t('impl2.direction.customer'))
    expect(screen.getByTestId('impl-escalation-state-31').textContent)
      .toBe(t('impl2.escalationOpen'))
    expect(screen.queryByTestId('impl-escalation-open-2')).toBeNull()
    expect(screen.queryByTestId('impl-escalation-resolve-31')).toBeNull()
    // Somebody has taken it somewhere — no hint, and none for a plain member anyway.
    expect(screen.queryByTestId('impl-escalation-hint-2')).toBeNull()
  })

  it('nags Sales while a flagged risk has been taken nowhere', async () => {
    setData(atRisk)
    render_({ canEscalate: true, canSeeAll: true })
    expect((await screen.findByTestId('impl-escalation-hint-2')).textContent)
      .toBe(t('impl2.escalationHint'))
  })

  it('drops the nag once an escalation is open', async () => {
    setData({
      ...atRisk,
      escalations: [{ id: 31, direction: 'internal', note: 'raised in the daily',
        report_id: 21, resolved_at: null }],
    })
    render_({ canEscalate: true, canSeeAll: true })
    expect(await screen.findByTestId('impl-escalation-2-31')).toBeTruthy()
    expect(screen.queryByTestId('impl-escalation-hint-2')).toBeNull()
  })

  it('escalates against the flagged report, in the chosen direction', async () => {
    setData(atRisk)
    render_({ canEscalate: true })
    fireEvent.click(await screen.findByTestId('impl-escalation-open-2'))
    fireEvent.click(screen.getByTestId('impl-escalation-direction-internal-2'))
    fireEvent.change(screen.getByTestId('impl-escalation-note-2'),
      { target: { value: 'need a second tool slot' } })
    fireEvent.click(screen.getByTestId('impl-escalation-submit-2'))
    await waitFor(() => expect(changesApi.addImplEscalation).toHaveBeenCalledWith(7, {
      direction: 'internal', note: 'need a second tool slot', report_id: 21,
    }))
  })

  it('resolves an escalation only with a written note', async () => {
    setData({
      ...atRisk,
      escalations: [{ id: 31, direction: 'customer', note: 'CW40 slip', report_id: 21,
        resolved_at: null }],
    })
    render_({ canEscalate: true })
    fireEvent.click(await screen.findByTestId('impl-escalation-resolve-31'))
    expect((screen.getByTestId('impl-escalation-resolve-confirm-31') as HTMLButtonElement)
      .disabled).toBe(true)
    fireEvent.change(screen.getByTestId('impl-escalation-resolution-31'),
      { target: { value: 'customer accepted CW42' } })
    fireEvent.click(screen.getByTestId('impl-escalation-resolve-confirm-31'))
    await waitFor(() => expect(changesApi.resolveImplEscalation)
      .toHaveBeenCalledWith(7, 31, 'customer accepted CW42'))
  })

  it('shows a settled escalation as history, with no resolve control left', async () => {
    setData({
      ...atRisk,
      escalations: [{ id: 31, direction: 'customer', note: 'CW40 slip', report_id: 21,
        resolved_at: '2026-08-11T09:00:00', resolution_note: 'customer accepted CW42' }],
    })
    render_({ canEscalate: true })
    const row = await screen.findByTestId('impl-escalation-2-31')
    expect(row.textContent).toContain('customer accepted CW42')
    expect(screen.queryByTestId('impl-escalation-resolve-31')).toBeNull()
  })

  it('lists an escalation tied to no report once, outside the blocks', async () => {
    setData({
      state: [stateRow()],
      escalations: [{ id: 41, direction: 'internal', note: 'programme-level slip',
        report_id: null, resolved_at: null }],
    })
    render_({ canSeeAll: true })
    expect(await screen.findByTestId('impl-escalations-change')).toBeTruthy()
    expect(screen.getByTestId('impl-escalation-change-41')).toBeTruthy()
    expect(screen.queryByTestId('impl-escalation-2-41')).toBeNull()
  })
})
