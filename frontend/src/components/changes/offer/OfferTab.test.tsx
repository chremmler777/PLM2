import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest'
import { render, screen, cleanup, fireEvent, waitFor, within } from '@testing-library/react'
import { planApi } from '../../../api/changePlan'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { addDaysIso, formatDate, todayIso } from '../../../lib/format'
import OfferTab, { type OfferTabProps } from './OfferTab'
import { changeOfferApi } from '../../../api/changeOffer'
import type { ChangeDetail } from '../../../types/change'
import type { OfferOut } from '../../../types/changeOffer'

vi.mock('../../../api/changeOffer', () => ({
  changeOfferApi: {
    list: vi.fn(), create: vi.fn(), patch: vi.fn(), refresh: vi.fn(),
    send: vi.fn(), received: vi.fn(), pdf: vi.fn(), discard: vi.fn(),
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
    expect((await screen.findByTestId('offer-total')).textContent).toBe('12,345.50 EUR')
    expect(screen.getByTestId('sum-total').textContent).toBe('12,345.50 EUR')
    expect(screen.getByTestId('sum-factor-overhead').textContent).toBe('150.00 EUR')
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
    await waitFor(() => expect(screen.getByTestId('sum-total').textContent).toBe('999.00 EUR'))
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
    const day = addDaysIso(todayIso(), -1)
    fireEvent.change(await screen.findByLabelText('Received by the customer on'), { target: { value: day } })
    expect(screen.getByTestId('send-valid-until').textContent)
      .toBe(`The offer is valid 30 days from receipt, until ${formatDate(addDaysIso(day, 30))}.`)
    expect(screen.queryByTestId('send-note')).toBeNull()
    fireEvent.click(screen.getByTestId('send-confirm'))
    await waitFor(() => expect(changeOfferApi.send).toHaveBeenCalledWith(7, 11, { received_at: day }))
    expect(changeOfferApi.patch).not.toHaveBeenCalled()
  })

  it('send dialog: no receipt date in the future or older than 60 days; the customer note is saved first', async () => {
    vi.mocked(changeOfferApi.list).mockResolvedValue([offer()])
    vi.mocked(changeOfferApi.patch).mockImplementation(async (_c, _o, body) => offer({ data: { ...offer().data, ...body.data } }))
    vi.mocked(changeOfferApi.send).mockResolvedValue(offer({ status: 'sent' }))
    renderTab(props())
    fireEvent.click(await screen.findByTestId('offer-send'))
    const date = await screen.findByLabelText('Received by the customer on') as HTMLInputElement
    // Shown as "25 Sep 2026", never the browser's mm/dd.
    expect(date.value).toBe(formatDate(todayIso()))
    const confirm = screen.getByTestId('send-confirm') as HTMLButtonElement
    fireEvent.change(date, { target: { value: addDaysIso(todayIso(), 1) } })
    expect(confirm.disabled).toBe(true)
    expect(screen.getByTestId('send-received-invalid').textContent).toContain('future')
    fireEvent.change(date, { target: { value: addDaysIso(todayIso(), -61) } })
    expect(confirm.disabled).toBe(true)
    fireEvent.change(date, { target: { value: todayIso() } })
    fireEvent.change(screen.getByTestId('send-customer-note'), { target: { value: 'Bank build included' } })
    fireEvent.click(confirm)
    await waitFor(() => expect(changeOfferApi.send).toHaveBeenCalled())
    expect(changeOfferApi.patch).toHaveBeenCalledWith(7, 11, { data: { customer_note: 'Bank build included' } })
  })

  it('discards a draft after asking once', async () => {
    vi.mocked(changeOfferApi.list).mockResolvedValue([offer()])
    vi.mocked(changeOfferApi.discard).mockResolvedValue(undefined)
    renderTab(props())
    fireEvent.click(await screen.findByTestId('offer-discard'))
    expect(changeOfferApi.discard).not.toHaveBeenCalled()
    fireEvent.click(within(await screen.findByTestId('offer-discard-confirm')).getByTestId('confirm-ok'))
    await waitFor(() => expect(changeOfferApi.discard).toHaveBeenCalledWith(7, 11))
  })

  it('factor and risk surcharge "show on offer" toggles patch the draft', async () => {
    vi.mocked(changeOfferApi.list).mockResolvedValue([offer()])
    vi.mocked(changeOfferApi.patch).mockImplementation(async (_c, _o, body) => offer({ data: { ...offer().data, ...body.data } }))
    renderTab(props())
    const show = await screen.findByTestId('factor-show-margin')
    // Margin is hidden by default (spread over the cost lines).
    expect(show.getAttribute('aria-checked')).toBe('false')
    fireEvent.click(show)
    fireEvent.click(screen.getByTestId('risk-surcharge-show'))
    await waitFor(() => expect(changeOfferApi.patch).toHaveBeenCalled(), { timeout: 2000 })
    const body = vi.mocked(changeOfferApi.patch).mock.calls[0][2]
    expect(body.data?.factors?.[0].show).toBe(true)
    expect(body.data?.show_risk_surcharge).toBe(true)
  })

  it('send dialog: from v2 the change note is required and the diff shown', async () => {
    const v1 = offer({ id: 10, version: 1, status: 'sent', valid_until: '2026-10-20', days_left: 26 })
    const v2 = offer({ id: 12, version: 2, diff: [{ field: 'total_one_time', before: 1000, after: 900 }] })
    vi.mocked(changeOfferApi.list).mockResolvedValue([v2, v1])
    vi.mocked(changeOfferApi.send).mockResolvedValue({ ...v2, status: 'sent' })
    renderTab(props({ change: change({ status: 'quoted' }) }))
    fireEvent.click(await screen.findByTestId('offer-send'))
    const diff = (await screen.findByTestId('send-diff')).textContent ?? ''
    expect(diff).toContain('Total one-time')
    expect(diff).toContain('1,000.00 EUR')
    expect(diff).toContain('900.00 EUR')
    expect(diff).not.toContain('total_one_time')
    const confirm = screen.getByTestId('send-confirm') as HTMLButtonElement
    expect(confirm.disabled).toBe(true)
    fireEvent.change(screen.getByTestId('send-note'), { target: { value: 'Margin down' } })
    expect(confirm.disabled).toBe(false)
    fireEvent.click(confirm)
    await waitFor(() => expect(changeOfferApi.send).toHaveBeenCalledWith(7, 12,
      expect.objectContaining({ change_note: 'Margin down' })))
  })

  it('shows the validity chip of the sent version and offers a new version', async () => {
    const until = addDaysIso(todayIso(), 7)
    const v1 = offer({ status: 'sent', valid_until: until, days_left: 7 })
    vi.mocked(changeOfferApi.list).mockResolvedValue([v1])
    vi.mocked(changeOfferApi.create).mockResolvedValue(offer({ id: 12, version: 2 }))
    renderTab(props({ change: change({ status: 'quoted' }) }))
    const chip = await screen.findByTestId('offer-valid-chip')
    expect(chip.textContent).toContain(formatDate(until))
    expect(chip.textContent).toContain('7 d left')
    expect(chip.className).toContain('amber')
    fireEvent.click(screen.getByTestId('offer-new-version'))
    await waitFor(() => expect(changeOfferApi.create).toHaveBeenCalled())
    expect(screen.getByTestId('offer-negotiation')).toBeDefined()
  })

  it('shows Accepted, not a countdown, once the customer accepted', async () => {
    const v2 = offer({ status: 'accepted', valid_until: '2026-10-25', days_left: null })
    vi.mocked(changeOfferApi.list).mockResolvedValue([v2])
    renderTab(props({ change: change({ status: 'approved', customer_response: 'accepted' }) }))
    expect((await screen.findByTestId('offer-status')).textContent).toBe('Accepted v1')
    expect(screen.queryByTestId('offer-valid-chip')).toBeNull()
    expect(screen.getByTestId('offer-header').textContent).not.toContain('null')
  })

  it('serializes saves: an edit during a PATCH waits for it and goes out alone', async () => {
    vi.mocked(changeOfferApi.list).mockResolvedValue([offer()])
    let resolveFirst: (o: OfferOut) => void = () => {}
    vi.mocked(changeOfferApi.patch)
      .mockImplementationOnce(() => new Promise<OfferOut>((r) => { resolveFirst = r }))
      .mockImplementation(async (_c, _o, body) => offer({ data: { ...offer().data, ...body.data } }))
    renderTab(props())
    fireEvent.click(await screen.findByTestId('risk-show-32'))
    await waitFor(() => expect(changeOfferApi.patch).toHaveBeenCalledTimes(1), { timeout: 2000 })
    // Second edit while the first PATCH is still in flight.
    fireEvent.click(screen.getByTestId('risk-show-31'))
    await new Promise((r) => setTimeout(r, 700))
    expect(changeOfferApi.patch).toHaveBeenCalledTimes(1)
    resolveFirst(offer({ data: { ...offer().data } }))
    await waitFor(() => expect(changeOfferApi.patch).toHaveBeenCalledTimes(2), { timeout: 2000 })
    const second = vi.mocked(changeOfferApi.patch).mock.calls[1][2]
    const risks = second.data?.risks ?? []
    expect(risks.find((r) => r.concern_id === 31)?.show).toBe(false)
    expect(risks.find((r) => r.concern_id === 32)?.show).toBe(true)
    await waitFor(() => expect(screen.getByTestId('offer-save-state').textContent).toContain('Saved'))
  })

  it('Send waits for the save, dims the totals meanwhile and opens with the saved totals', async () => {
    vi.mocked(changeOfferApi.list).mockResolvedValue([offer()])
    let resolveSave: (o: OfferOut) => void = () => {}
    vi.mocked(changeOfferApi.patch).mockImplementation(() => new Promise<OfferOut>((r) => { resolveSave = r }))
    renderTab(props())
    fireEvent.click(await screen.findByTestId('risk-show-32'))
    const send = screen.getByTestId('offer-send') as HTMLButtonElement
    expect(send.disabled).toBe(true)
    expect(screen.getByTestId('offer-sum-figures').dataset.stale).toBe('true')
    expect(screen.getByTestId('offer-header-totals').dataset.stale).toBe('true')
    await waitFor(() => expect(changeOfferApi.patch).toHaveBeenCalledTimes(1), { timeout: 2000 })
    resolveSave(offer({ totals: { ...offer().totals, total_one_time: 777 } }))
    await waitFor(() => expect(send.disabled).toBe(false))
    expect(screen.getByTestId('offer-sum-figures').dataset.stale).toBeUndefined()
    fireEvent.click(send)
    const dialog = await screen.findByRole('dialog')
    expect(dialog.textContent).toContain('777.00 EUR')
  })

  it('does not open the send dialog when the save fails', async () => {
    vi.mocked(changeOfferApi.list).mockResolvedValue([offer()])
    vi.mocked(changeOfferApi.patch).mockRejectedValue(new Error('boom'))
    renderTab(props())
    fireEvent.click(await screen.findByTestId('risk-show-32'))
    await waitFor(() => expect(screen.getByTestId('offer-save-state').textContent).toContain('Not saved'),
      { timeout: 2000 })
    fireEvent.click(screen.getByTestId('offer-send'))
    await waitFor(() => expect(changeOfferApi.patch).toHaveBeenCalledTimes(2))
    expect(screen.queryByRole('dialog')).toBeNull()
  })

  it('refresh does not run when the save before it fails', async () => {
    vi.mocked(changeOfferApi.list).mockResolvedValue([offer()])
    vi.mocked(changeOfferApi.patch).mockRejectedValue(new Error('boom'))
    renderTab(props())
    fireEvent.click(await screen.findByTestId('risk-show-32'))
    await waitFor(() => expect(screen.getByTestId('offer-save-state').textContent).toContain('Not saved'),
      { timeout: 2000 })
    fireEvent.click(screen.getByTestId('offer-refresh'))
    await waitFor(() => expect(changeOfferApi.patch).toHaveBeenCalledTimes(2))
    await new Promise((r) => setTimeout(r, 50))
    expect(changeOfferApi.refresh).not.toHaveBeenCalled()
  })

  it('locks the draft inputs while a refresh is running', async () => {
    vi.mocked(changeOfferApi.list).mockResolvedValue([offer()])
    let resolveRefresh: (o: OfferOut) => void = () => {}
    vi.mocked(changeOfferApi.refresh).mockImplementation(() => new Promise<OfferOut>((r) => { resolveRefresh = r }))
    renderTab(props())
    fireEvent.click(await screen.findByTestId('offer-refresh'))
    const fs = screen.getByTestId('offer-edit-fieldset') as HTMLFieldSetElement
    await waitFor(() => expect(fs.disabled).toBe(true))
    expect(fs.contains(screen.getByTestId('risk-show-32'))).toBe(true)
    resolveRefresh(offer())
    await waitFor(() => expect(fs.disabled).toBe(false))
  })

  it('leaving the tab retries keys left over from a failed save', async () => {
    vi.mocked(changeOfferApi.list).mockResolvedValue([offer()])
    vi.mocked(changeOfferApi.patch).mockRejectedValueOnce(new Error('boom'))
      .mockImplementation(async () => offer())
    const { unmount } = renderTab(props())
    fireEvent.click(await screen.findByTestId('risk-show-32'))
    await waitFor(() => expect(screen.getByTestId('offer-save-state').textContent).toContain('Not saved'),
      { timeout: 2000 })
    unmount()
    await waitFor(() => expect(changeOfferApi.patch).toHaveBeenCalledTimes(2))
    expect(vi.mocked(changeOfferApi.patch).mock.calls[1][2].data?.risks).toBeDefined()
  })

  it('PM reads the negotiation but records no customer answer', async () => {
    const v1 = offer({ status: 'sent', valid_until: '2026-10-20', days_left: 26 })
    vi.mocked(changeOfferApi.list).mockResolvedValue([v1])
    renderTab(props({ change: change({ status: 'quoted' }), canWrite: false, canSignPm: true }))
    expect(await screen.findByTestId('customer-decision')).toBeDefined()
    expect(screen.queryByText('Customer accepted')).toBeNull()
    expect(screen.queryByText('Customer declined')).toBeNull()
    expect(screen.getByRole('button', { name: /PM sign-off/ })).toBeDefined()
  })

  it('Sales records the customer answer', async () => {
    const v1 = offer({ status: 'sent', valid_until: '2026-10-20', days_left: 26 })
    vi.mocked(changeOfferApi.list).mockResolvedValue([v1])
    renderTab(props({ change: change({ status: 'quoted' }) }))
    expect(await screen.findByText('Customer accepted')).toBeDefined()
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

  it('an accepted offer offers no new version and shows the quote timing read-only', async () => {
    const v1 = offer({ status: 'accepted', valid_until: '2026-10-25' })
    vi.mocked(changeOfferApi.list).mockResolvedValue([v1])
    // quoted with the acceptance recorded (the change moves on at approval)
    renderTab(props({ change: change({ status: 'quoted', customer_response: 'accepted', accepted_offer_id: 11 }) }))
    await screen.findByTestId('offer-status')
    expect(screen.queryByTestId('offer-new-version')).toBeNull()
    expect(screen.getByTestId('offer-timing-planner').dataset.readonly).toBe('true')
    expect(screen.getByTestId('offer-read-only').textContent).toContain('accepted')
  })

  it('never checks the timing step while its quote plan has errors, and names the count', async () => {
    vi.mocked(planApi.get).mockResolvedValue({
      tasks: [{ id: 1 }], summary: { duration_days: 60 },
      validation: { errors: [{ code: 'x', message: 'Loop' }], warnings: [] },
    } as never)
    vi.mocked(changeOfferApi.list).mockResolvedValue([offer()])
    renderTab(props())
    const badge = await screen.findByTestId('offer-timing-errors')
    expect(badge.textContent).toContain('1 error')
    expect(screen.getByTestId('nav-offer-timing').dataset.state).toBe('error')
    expect(screen.getByTestId('nav-offer-timing').textContent).toContain('1 error')
    expect(screen.getByTestId('offer-timing').textContent).toContain('Step 1, open')
    // ... and the send waits for it, saying why.
    expect((screen.getByTestId('offer-send') as HTMLButtonElement).disabled).toBe(true)
    expect(screen.getByTestId('offer-send-reasons').textContent).toContain('The quote plan has 1 error')
    vi.mocked(planApi.get).mockResolvedValue({ tasks: [{ id: 1 }], summary: { duration_days: 60 } } as never)
  })

  it('warns about an empty recipient company but still lets the offer go', async () => {
    const o = offer()
    o.data.recipient = { company: '' }
    vi.mocked(changeOfferApi.list).mockResolvedValue([o])
    renderTab(props())
    const send = await screen.findByTestId('offer-send') as HTMLButtonElement
    expect(send.disabled).toBe(false)
    expect(screen.queryByTestId('offer-send-reasons')).toBeNull()
    expect(screen.getByTestId('offer-send-warnings').textContent).toContain('recipient company is empty')
  })

  it('a draft left over after the customer accepted cannot be sent, but can be discarded', async () => {
    const v1 = offer({ id: 10, version: 1, status: 'accepted' })
    const v2 = offer({ id: 11, version: 2, status: 'draft' })
    vi.mocked(changeOfferApi.list).mockResolvedValue([v2, v1])
    vi.mocked(changeOfferApi.discard).mockResolvedValue(undefined)
    renderTab(props({ change: change({ status: 'approved', customer_response: 'accepted', accepted_offer_id: 10 }) }))
    const send = await screen.findByTestId('offer-send') as HTMLButtonElement
    expect(send.disabled).toBe(true)
    expect(screen.getByTestId('offer-send-reasons').textContent)
      .toContain('The customer accepted v1: the offer is closed')
    fireEvent.click(screen.getByTestId('offer-discard'))
    fireEvent.click(within(await screen.findByTestId('offer-discard-confirm')).getByTestId('confirm-ok'))
    await waitFor(() => expect(changeOfferApi.discard).toHaveBeenCalledWith(7, 11))
  })

  it('shows no result against internal cost before anything is costed', async () => {
    vi.mocked(changeOfferApi.list).mockResolvedValue([offer({
      totals: { ...offer().totals, internal_cost: 0, margin_abs: 12345.5, margin_pct: null },
    })])
    renderTab(props())
    const margin = await screen.findByTestId('offer-margin')
    expect(margin.textContent).toContain('No internal cost yet')
    expect(margin.textContent).not.toContain('EUR')
  })
  it('marks an idea milestone as an option, apart from the committed ones', async () => {
    const o = offer()
    o.data.timing = { include: true, weeks_from_order: 9, milestones: [
      { label: 'SOP', date: '2026-12-01' },
      { label: 'Extra trial', date: '2026-11-10', idea: true },
    ] }
    vi.mocked(changeOfferApi.list).mockResolvedValue([o])
    renderTab(props())
    const items = await screen.findAllByTestId('offer-timing-milestone')
    expect(items).toHaveLength(2)
    expect(items[0].dataset.idea).toBeUndefined()
    expect(items[0].textContent).not.toContain('Option')
    expect(items[1].dataset.idea).toBe('true')
    expect(items[1].textContent).toContain('Extra trial')
    expect(items[1].textContent).toContain('Option')
    expect(items[1].getAttribute('title')).toContain('does not count in the weeks from order')
  })

  it('shows override_split in the price section and jumps there from the header', async () => {
    const msg = "Machine time and sampling now have their own lines: the amount set by hand on 'Development' was reduced by them so they are not counted twice. Check it"
    vi.mocked(changeOfferApi.list).mockResolvedValue([offer({ warnings: [{ code: 'override_split', message: msg, task_id: null }] })])
    renderTab(props())
    const priceWarnings = await screen.findByTestId('offer-price-warnings')
    expect(priceWarnings.querySelector('[data-code="override_split"]')?.textContent).toBe(msg)
    const price = document.getElementById('offer-price')!
    const spy = vi.fn()
    price.scrollIntoView = spy
    fireEvent.click(within(screen.getByTestId('offer-warnings')).getByText(msg))
    expect(spy).toHaveBeenCalled()
  })
})
