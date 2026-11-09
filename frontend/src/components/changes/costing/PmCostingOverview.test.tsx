import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, cleanup, fireEvent, waitFor, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import PmCostingOverview, { externalOf, lineRange } from './PmCostingOverview'
import { changesApi } from '../../../api/changes'
import type { CostPosition } from '../../../types/change'

vi.mock('../../../api/changeOffer', () => ({
  changeOfferApi: { list: vi.fn().mockResolvedValue([{ id: 3, version: 2, status: 'sent', sent_at: '2026-11-09T08:00:00', sent_by_name: 'Karl Limburg' }]) },
}))
vi.mock('../../../api/changes', () => ({
  changesApi: {
    listCostPositions: vi.fn(),
    finalizeCheck: vi.fn(),
  },
}))

const pos = (over: Partial<CostPosition>): CostPosition => ({
  id: 1, department_id: 2, label: 'Line', kind: 'external', offers: [], ...over,
} as CostPosition)

const offer = (over: Record<string, unknown>) => ({
  id: 1, vendor_name: 'FZ', cost: 100, total_cost: 100, favorite: false, is_partial: false, ...over,
})

// Tool Engineer (2): our time + an external line with two quotes + a spare part
const POSITIONS: CostPosition[] = [
  pos({ id: 10, kind: 'internal_effort', label: 'Design', hours: 8, rate: 50, line_value: 400 }),
  pos({ id: 11, label: 'Insert', pricing: 'quote', effective_cost: 1200, favorite_offer_id: 21,
    effective_lead_time_calendar_days: 42,
    offers: [offer({ id: 21, vendor_name: 'FZ', cost: 1000, shipping_cost: 200, total_cost: 1200, favorite: true }),
      offer({ id: 22, vendor_name: 'Hi-Tech', cost: 1500, total_cost: 1500 })] as never }),
  pos({ id: 12, label: 'Spare part: Ejector pin', notes: 'spare part', pricing: 'quote',
    quantity: 10, quantity_unit: 'pcs', effective_cost: 1050, favorite_offer_id: 31,
    offers: [offer({ id: 31, vendor_name: 'Meusburger', cost: 100, shipping_cost: 50, total_cost: 1050, favorite: true })] as never }),
  // Development (3): one line without a price
  pos({ id: 13, department_id: 3, label: 'Gauge', pricing: 'estimate', effective_cost: null }),
]

const change = (over: Record<string, unknown> = {}) => ({
  id: 7, status: 'costing',
  assessments: [
    { id: 1, department_id: 2, owner_name: 'Dale', due_date: '2026-11-01', overdue: true },
    { id: 2, department_id: 3, owner_name: null, responsible_name: 'Cory', due_date: '2026-11-20', overdue: false },
    { id: 3, department_id: 4, owner_name: 'Russ', due_date: null, overdue: false },
  ],
  costing_owed_department_ids: [2, 3, 4],
  costing_finalized_department_ids: [4],
  costing_finalized_info: { 4: { at: '2026-11-07T10:00:00', by: 5, by_name: 'Russ Miller' } },
  open_supplier_waits: [{ id: 9, department_id: 3, vendor_name: 'FZ', position_id: 13, expected_by: '2026-11-05',
    overdue: true, is_open: true, phase: 'costing', chip: '' }],
  ...over,
}) as never

const summation = {
  currency: 'USD', by_plant: [],
  by_department: [
    { department_id: 2, one_time_internal: 400, one_time_external: 2250, lifecycle_internal: 0, lifecycle_external: 0 },
    { department_id: 3, one_time_internal: 0, one_time_external: 0, lifecycle_internal: 0, lifecycle_external: 0 },
    { department_id: 4, one_time_internal: 300, one_time_external: 0, lifecycle_internal: 0, lifecycle_external: 0 },
  ],
  positions_by_department: [{ department_id: 2, hours: 8, machine_hours: 0 }],
  lead_time_by_department: [{ department_id: 2, lead_time_days: 42 }, { department_id: 4, lead_time_days: 10 }],
  max_lead_time_days: 42,
  totals: { one_time_internal: 700, one_time_external: 2250, lifecycle_internal: 0, lifecycle_external: 0, grand_total: 2950 },
} as never

const NAMES: Record<number, string> = { 2: 'Tool Engineer', 3: 'Development', 4: 'Toolshop' }

function show(props: Record<string, unknown> = {}) {
  vi.mocked(changesApi.listCostPositions).mockResolvedValue(POSITIONS)
  vi.mocked(changesApi.finalizeCheck).mockImplementation(async (_c, d) => d === 2
    ? { reasons: ['Insert: FZ transport missing'], position_ids: [11],
      items: [{ tag: 'transport_missing', text: 'Insert: FZ transport missing (0 allowed)' },
        { tag: 'received', text: 'Insert – FZ: quote received', info: true }] }
    : { reasons: [], position_ids: [], items: [{ tag: 'waiting', text: 'FZ (Gauge): quote expected 11/05/2026' }] })
  const onJump = vi.fn()
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <PmCostingOverview change={change()} departmentIds={[2, 3, 4]} deptName={(id) => NAMES[id]}
        summation={summation} isPm onJump={onJump} {...props} />
    </QueryClientProvider>)
  return { onJump }
}

afterEach(() => { cleanup(); vi.clearAllMocks() })

describe('lineRange / externalOf (backend line totals, summed only)', () => {
  it('a quoted line runs from the cheapest to the dearest quote, partials on top', () => {
    expect(lineRange(POSITIONS[1])).toEqual({ low: 1200, high: 1500 })
    const withPart = pos({ pricing: 'quote', offers: [offer({ id: 1, total_cost: 50, is_partial: true }),
      offer({ id: 2, total_cost: 100 }), offer({ id: 3, total_cost: 300 })] as never })
    expect(lineRange(withPart)).toEqual({ low: 150, high: 350 })
  })
  it('counts the favourites and the lines still without a price', () => {
    expect(externalOf(POSITIONS.filter((p) => p.department_id === 2)))
      .toEqual({ low: 2250, high: 2550, fav: 2250, open: 0, lines: 2 })
    expect(externalOf([POSITIONS[3]]).open).toBe(1)
  })
})

describe('PmCostingOverview', () => {
  it('one row per department: status, who, due (overdue red), internal, external, lead', async () => {
    show()
    const row = await screen.findByTestId('pm-row-2')
    expect(within(row).getByText('Dale')).toBeTruthy()
    expect(screen.getByTestId('pm-due-2').textContent).toMatch(/overdue since/)
    expect(screen.getByTestId('pm-due-2').className).toMatch(/red/)
    expect(screen.getByTestId('pm-internal-2').textContent).toMatch(/400\.00 USD/)
    expect(screen.getByTestId('pm-internal-2').textContent).toMatch(/8 h/)
    await waitFor(() => expect(screen.getByTestId('pm-ext-range-2').textContent).toBe('2,250.00 USD – 2,550.00 USD'))
    expect(screen.getByTestId('pm-ext-fav-2').textContent).toMatch(/2,250\.00 USD/)
    expect(screen.getByTestId('pm-lead-2').textContent).toMatch(/42/)
    expect(within(screen.getByTestId('pm-row-3')).getByText('Cory')).toBeTruthy()
  })

  it('filled but not finalized is red; finalized is green with who and when', async () => {
    show()
    await waitFor(() => expect(screen.getByTestId('pm-status-2').textContent)
      .toBe('Not finalized'))
    expect(screen.getByTestId('pm-row-2').textContent).toMatch(/department not confirmed done/)
    expect(screen.getByTestId('pm-status-2').className).toMatch(/red/)
    expect(screen.getByTestId('pm-status-4').textContent).toBe('Finalized')
    expect(screen.getByTestId('pm-status-4').className).toMatch(/emerald/)
    expect(screen.getByTestId('pm-finalized-by-4').textContent).toBe('by Russ Miller, 7 Nov 2026')
    // a finalized department's check is not asked for
    await waitFor(() => expect(changesApi.finalizeCheck).toHaveBeenCalledTimes(2))
  })

  it('lists the open points from finalize-check and the supplier waits (overdue red)', async () => {
    show()
    const open2 = screen.getByTestId('pm-open-2')
    await waitFor(() => expect(open2.textContent).toMatch(/FZ transport missing/))
    expect(open2.textContent).not.toMatch(/quote received/)
    const w = screen.getByTestId('pm-wait-9')
    expect(w.textContent).toMatch(/Waiting on FZ \(Gauge\): overdue/)
    expect(w.className).toMatch(/red/)
    // the check's own "waiting" item is not listed twice
    expect(screen.getByTestId('pm-open-3').textContent).not.toMatch(/quote expected/)
  })

  it('the cost blocks line by line, open for the PM: our time, external, spare (amount x price + transport)', async () => {
    show()
    const lines = await screen.findByTestId('pm-lines-2')
    await waitFor(() => expect(within(lines).getByTestId('pm-block-time')).toBeTruthy())
    expect(within(lines).getByTestId('pm-line-10').textContent).toMatch(/8 h × 50\.00 USD.*400\.00 USD/)
    expect(within(lines).getByTestId('pm-line-11').textContent).toMatch(/FZ \(favourite of 2\).*incl\. 200\.00 USD transport.*1,200\.00 USD/)
    const spare = within(lines).getByTestId('pm-line-12').textContent ?? ''
    expect(spare).toMatch(/^Ejector pin/)
    expect(spare).toMatch(/10 × 100\.00 USD\/pc \+ 50\.00 USD transport/)
    expect(spare).toMatch(/1,050\.00 USD/)
    // the order of the costing sections
    const blocks = within(lines).getAllByTestId(/^pm-block-/).map((b) => b.dataset.testid)
    expect(blocks).toEqual(['pm-block-time', 'pm-block-external', 'pm-block-spare'])
    fireEvent.click(screen.getByTestId('pm-row-toggle-2'))
    expect(screen.queryByTestId('pm-lines-2')).toBeNull()
  })

  it('folded for everyone but the PM', async () => {
    show({ isPm: false })
    await screen.findByTestId('pm-row-2')
    expect(screen.queryByTestId('pm-lines-2')).toBeNull()
  })

  it('the total row: internal sum, external range, longest lead time and whose', async () => {
    show()
    await waitFor(() => expect(screen.getByTestId('pm-total-ext-range').textContent).toBe('2,250.00 USD – 2,550.00 USD'))
    expect(screen.getByTestId('pm-total-internal').textContent).toMatch(/700\.00 USD/)
    expect(screen.getByTestId('pm-total-ext-fav').textContent).toMatch(/1 without a price/)
    expect(screen.getByTestId('pm-total-lead').textContent).toMatch(/42/)
    expect(screen.getByTestId('pm-total-row').textContent).toMatch(/longest: Tool Engineer/)
  })

  it('a department name jumps to its bucket', async () => {
    const { onJump } = show()
    fireEvent.click(await screen.findByTestId('pm-row-jump-3'))
    expect(onJump).toHaveBeenCalledWith(3)
  })
})

describe('PmCostingOverview — spare part time critical (Christoph 2026-11-09)', () => {
  // change 31: tool change favourite Hitech 15 d, spare part Hasco 30 d
  const lines = (tc: boolean | null): CostPosition[] => [
    pos({ id: 64, label: 'Toolchange', pricing: 'quote', effective_cost: 5000, favorite_offer_id: 17,
      effective_lead_time_calendar_days: 15,
      offers: [offer({ id: 17, vendor_name: 'Hitech', cost: 5000, total_cost: 5000, favorite: true,
        lead_time_days: 15 })] as never }),
    pos({ id: 66, label: 'Spare part: dsafsdfsdfs', notes: 'From the assessment: x', pricing: 'quote',
      quantity: 20, quantity_unit: 'pcs', effective_cost: 200, favorite_offer_id: 31, time_critical: tc,
      counts_for_lead_time: tc !== false, effective_lead_time_calendar_days: 30,
      offers: [offer({ id: 31, vendor_name: 'Hasco', cost: 10, total_cost: 200, favorite: true,
        lead_time_days: 30 })] as never }),
  ]
  const render31 = (tc: boolean | null, lead: number) => {
    vi.mocked(changesApi.listCostPositions).mockResolvedValue(lines(tc))
    vi.mocked(changesApi.finalizeCheck).mockResolvedValue({ reasons: [], position_ids: [], items: [] } as never)
    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <PmCostingOverview change={change({ costing_finalized_department_ids: [], open_supplier_waits: [] })}
          departmentIds={[2]} deptName={(id) => NAMES[id]} isPm onJump={vi.fn()}
          summation={{ ...(summation as object), lead_time_by_department: [{ department_id: 2, lead_time_days: lead }],
            max_lead_time_days: lead } as never} />
      </QueryClientProvider>)
  }

  it('time critical: the spare part leads with 30 d', async () => {
    render31(true, 30)
    expect((await screen.findByTestId('pm-lead-why-2')).textContent)
      .toBe('30 d (spare part dsafsdfsdfs, time critical)')
    expect(screen.getByTestId('pm-total-lead-why-2').textContent)
      .toBe('30 d (spare part dsafsdfsdfs, time critical)')
    expect(screen.queryByTestId('pm-line-excluded-66')).toBeNull()
  })

  it('not time critical: 15 d from the Hitech tool change, the spare part excluded', async () => {
    render31(false, 15)
    expect((await screen.findByTestId('pm-lead-why-2')).textContent)
      .toBe('15 d (Hitech, tool change) · spare part not time critical (30 d) excluded')
    expect(screen.getByTestId('pm-total-lead').textContent).toMatch(/15/)
    expect(screen.getByTestId('pm-line-excluded-66').textContent).toMatch(/not counted/)
  })
})

describe('Offer sent (Christoph 2026-11-09)', () => {
  it('PM reads who sent the offer and when, once it is out', async () => {
    show({ change: change({ status: 'quoted', customer_relevant: true }) })
    const stamp = await screen.findByTestId('pm-overview-offer-sent')
    expect(stamp.textContent).toContain('Offer v2 sent by Karl Limburg on')
  })
  it('says nothing while the change is still in costing', async () => {
    show()
    await screen.findByTestId('pm-costing-overview')
    expect(screen.queryByTestId('pm-overview-offer-sent')).toBeNull()
  })
})
