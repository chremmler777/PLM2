import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest'
import { render, screen, cleanup, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import OfferTab, { type OfferTabProps } from './OfferTab'
import { changeOfferApi } from '../../../api/changeOffer'
import type { ChangeDetail } from '../../../types/change'
import type { OfferOut } from '../../../types/changeOffer'

vi.mock('../../../api/changeOffer', () => ({
  changeOfferApi: {
    list: vi.fn(), create: vi.fn(), patch: vi.fn(), refresh: vi.fn(),
    send: vi.fn(), received: vi.fn(), pdf: vi.fn(),
  },
}))
vi.mock('../../../api/changePlan', () => ({
  planApi: { get: vi.fn().mockResolvedValue({ tasks: [{ id: 1 }], summary: { duration_days: 60 } }) },
}))
vi.mock('../../../api/changes', () => ({
  changesApi: {
    listNegotiations: vi.fn().mockResolvedValue([]), addNegotiation: vi.fn(), deleteNegotiation: vi.fn(),
    customerResponse: vi.fn(), signOff: vi.fn(),
  },
}))
vi.mock('../plan/GanttPlanner', () => ({ default: () => <div data-testid="mock-gantt" /> }))
vi.mock('sonner', () => ({ toast: { error: vi.fn(), success: vi.fn() } }))
vi.mock('../../../contexts/AuthContext', () => ({ useAuth: () => ({ userId: 5, username: 'sales' }) }))

const change = (over: Partial<ChangeDetail> = {}): ChangeDetail => ({
  id: 7, change_number: 'CR-7', project_id: 1, title: 'Housing fix', change_type: 'tooling',
  priority: 'medium', status: 'quoting', raised_by: 1, customer_response: 'pending',
  customer_relevant: true,
  created_at: '2026-07-01T00:00:00', updated_at: '2026-07-01T00:00:00',
  impacted_items: [], assessments: [], attachments: [], ...over,
} as ChangeDetail)

const offer = (over: Partial<OfferOut> = {}): OfferOut => ({
  id: 11, version: 1, status: 'draft', currency: 'EUR',
  data: {
    recipient: { company: 'VW' }, subject: 'Offer', cbd_mode: 'detailed',
    cost_lines: [{ key: 'dept-2', label: 'Development', department: 'Development', category: 'internal',
      amount: 1000, source_amount: 1000, include: true }],
    factors: [{ key: 'margin', label: 'Margin', type: 'pct', value: 10, sign: 1, enabled: false }],
    risks: [
      { concern_id: 31, label: 'Sink marks', severity: 3, department: 'Tool Engineer', show: true, type: 'pct', value: 0 },
      { concern_id: 32, label: 'Cycle time', severity: 2, department: 'ME', show: false, type: 'pct', value: 0 },
    ],
    changeover: { mode: 'running_change' },
    piece_price: { enabled: false, rows: [] },
    timing: { include: true, weeks_from_order: 9 },
    terms: { payment: '30 days net' },
  },
  totals: {
    base: 1000, factors: [{ key: 'overhead', label: 'Overhead', amount: 150 }], risks_total: 0, scrap: 0, free: 0,
    total_one_time: 12345.5, piece_price_delta: null, annual_effect: null,
    internal_cost: 1000, margin_abs: 11345.5, margin_pct: 91.9,
  },
  created_at: '2026-09-20T10:00:00', warnings: [], diff: null,
  ...over,
})

const props = (over: Partial<OfferTabProps> = {}): OfferTabProps => ({
  change: change(), canWrite: true, canSeePrices: true, canSignPm: false, canSignQuality: false,
  canApproveInternalCosts: false, userId: 5, ...over,
})

const renderTab = (p: OfferTabProps) => render(
  <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <OfferTab {...p} />
  </QueryClientProvider>)

describe('OfferTab', () => {
  afterEach(cleanup)
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('shows one primary action when no offer exists and creates it', async () => {
    vi.mocked(changeOfferApi.list).mockResolvedValue([])
    vi.mocked(changeOfferApi.create).mockResolvedValue(offer())
    renderTab(props())
    const start = await screen.findByTestId('offer-start')
    expect(screen.getByTestId('offer-empty').textContent).toContain('pre-fills')
    fireEvent.click(start)
    await waitFor(() => expect(changeOfferApi.create).toHaveBeenCalledWith(7))
  })

  it('does not offer the start to PM (read only)', async () => {
    vi.mocked(changeOfferApi.list).mockResolvedValue([])
    renderTab(props({ canWrite: false }))
    await screen.findByTestId('offer-empty')
    expect(screen.queryByTestId('offer-start')).toBeNull()
  })

  it('at costing shows only the timing section with a note, and loads no offers', async () => {
    renderTab(props({ change: change({ status: 'costing' }) }))
    expect(await screen.findByTestId('offer-waits-costing')).toBeDefined()
    expect(screen.getByTestId('mock-gantt')).toBeDefined()
    expect(screen.queryByTestId('offer-price')).toBeNull()
    expect(changeOfferApi.list).not.toHaveBeenCalled()
  })

  it('keeps prices away from viewers without cost rights', async () => {
    renderTab(props({ canWrite: false, canSeePrices: false }))
    expect(await screen.findByTestId('offer-no-access')).toBeDefined()
    expect(changeOfferApi.list).not.toHaveBeenCalled()
  })

  it('renders the server totals, not a local sum', async () => {
    vi.mocked(changeOfferApi.list).mockResolvedValue([offer()])
    renderTab(props())
    expect((await screen.findByTestId('offer-total')).textContent).toBe('12.345,50 EUR')
    expect(screen.getByTestId('sum-total').textContent).toBe('12.345,50 EUR')
    expect(screen.getByTestId('sum-factor-overhead').textContent).toBe('150,00 EUR')
    expect(screen.getByTestId('offer-status').textContent).toBe('Draft v1')
  })

  it('patches the risk list after the debounce and shows the server totals', async () => {
    vi.mocked(changeOfferApi.list).mockResolvedValue([offer()])
    const saved = offer({ totals: { ...offer().totals, total_one_time: 999 } })
    vi.mocked(changeOfferApi.patch).mockResolvedValue(saved)
    renderTab(props())
    fireEvent.click(await screen.findByTestId('risk-show-32'))
    await waitFor(() => expect(changeOfferApi.patch).toHaveBeenCalledTimes(1), { timeout: 2000 })
    const body = vi.mocked(changeOfferApi.patch).mock.calls[0][2]
    expect(body.data?.risks?.find((r) => r.concern_id === 32)?.show).toBe(true)
    await waitFor(() => expect(screen.getByTestId('sum-total').textContent).toBe('999,00 EUR'))
    expect(screen.getByTestId('offer-save-state').textContent).toContain('Saved')
  })

  it('warns when a severity-3 risk is kept out of the offer', async () => {
    const o = offer()
    o.data.risks![0].show = false
    vi.mocked(changeOfferApi.list).mockResolvedValue([o])
    renderTab(props())
    expect(await screen.findByTestId('risk-severe-hidden')).toBeDefined()
  })

  it('send dialog: v1 needs no note and states the validity date', async () => {
    vi.mocked(changeOfferApi.list).mockResolvedValue([offer()])
    vi.mocked(changeOfferApi.send).mockResolvedValue(offer({ status: 'sent' }))
    renderTab(props())
    fireEvent.click(await screen.findByTestId('offer-send'))
    fireEvent.change(screen.getByTestId('send-received'), { target: { value: '2026-09-24' } })
    expect(screen.getByTestId('send-valid-until').textContent)
      .toBe('The offer is valid 30 days from receipt, until 24.10.2026.')
    expect(screen.queryByTestId('send-note')).toBeNull()
    fireEvent.click(screen.getByTestId('send-confirm'))
    await waitFor(() => expect(changeOfferApi.send).toHaveBeenCalledWith(7, 11, { received_at: '2026-09-24' }))
  })

  it('send dialog: from v2 the change note is required and the diff shown', async () => {
    const v1 = offer({ id: 10, version: 1, status: 'sent', valid_until: '2026-10-20', days_left: 26 })
    const v2 = offer({ id: 12, version: 2, diff: [{ field: 'total_one_time', before: 1000, after: 900 }] })
    vi.mocked(changeOfferApi.list).mockResolvedValue([v2, v1])
    vi.mocked(changeOfferApi.send).mockResolvedValue({ ...v2, status: 'sent' })
    renderTab(props({ change: change({ status: 'quoted' }) }))
    fireEvent.click(await screen.findByTestId('offer-send'))
    expect(screen.getByTestId('send-diff').textContent).toContain('total_one_time')
    const confirm = screen.getByTestId('send-confirm') as HTMLButtonElement
    expect(confirm.disabled).toBe(true)
    fireEvent.change(screen.getByTestId('send-note'), { target: { value: 'Margin down' } })
    expect(confirm.disabled).toBe(false)
    fireEvent.click(confirm)
    await waitFor(() => expect(changeOfferApi.send).toHaveBeenCalledWith(7, 12,
      expect.objectContaining({ change_note: 'Margin down' })))
  })

  it('shows the validity chip of the sent version and offers a new version', async () => {
    const v1 = offer({ status: 'sent', valid_until: '2026-10-01', days_left: 7 })
    vi.mocked(changeOfferApi.list).mockResolvedValue([v1])
    vi.mocked(changeOfferApi.create).mockResolvedValue(offer({ id: 12, version: 2 }))
    renderTab(props({ change: change({ status: 'quoted' }) }))
    const chip = await screen.findByTestId('offer-valid-chip')
    expect(chip.textContent).toContain('01.10.2026')
    expect(chip.className).toContain('amber')
    fireEvent.click(screen.getByTestId('offer-new-version'))
    await waitFor(() => expect(changeOfferApi.create).toHaveBeenCalled())
    expect(screen.getByTestId('offer-negotiation')).toBeDefined()
  })

  it('the Approval variant keeps the internal approval control', async () => {
    renderTab(props({
      change: change({ status: 'costing', customer_relevant: false }), canApproveInternalCosts: true,
      costSummary: <div>mock-summation</div>,
    }))
    expect(await screen.findByText('Approve internal costs')).toBeDefined()
    expect(screen.getByText('mock-summation')).toBeDefined()
    expect(changeOfferApi.list).not.toHaveBeenCalled()
  })
})
