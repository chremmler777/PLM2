/**
 * Final walk fixes (P2-2, P2-3, P2-4, P2-6, P2-7): the pieces that are not a
 * page of their own. The page-level flows live in ChangeDetailPage.test.tsx.
 */
import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { toast } from 'sonner'
import { changesApi } from '../../api/changes'
import { actualCostsApi } from '../../api/actualCosts'
import TransitionDeviationsPanel from './TransitionDeviationsPanel'
import ActualCostsPanel from './pnl/ActualCostsPanel'
import PnlCard from './PnlCard'
import CostingBuckets from './CostingBuckets'
import DiffPanel from '../costSheet/DiffPanel'
import RevisionWorkflowSection from '../workflows/RevisionWorkflowSection'
import OfferPriceSection from './offer/OfferPriceSection'
import OfferDocumentSection from './offer/OfferDocumentSection'
import { unpricedByDepartment, unpricedMessage } from '../../lib/unpriced'
import { revisionsInCheckOf, revisionsInCheckText } from '../../lib/waitStates'
import { t } from '../../i18n/cmLabels'
import type { ChangeDetail } from '../../types/change'
import type { OfferData, OfferOut } from '../../types/changeOffer'

vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))
vi.mock('../../api/changes', () => ({
  changesApi: {
    decideDeviation: vi.fn().mockResolvedValue({}),
    costingContext: vi.fn(),
    getSummation: vi.fn(),
  },
}))
vi.mock('../../api/actualCosts', () => ({
  actualCostsApi: { list: vi.fn(), add: vi.fn(), remove: vi.fn() },
}))
vi.mock('./pnl/OfferVsActualSection', () => ({ default: () => null }))
vi.mock('./CostingSheetBar', () => ({ default: () => null }))
vi.mock('./CostPositions', () => ({ default: () => null }))
vi.mock('./CostLineGrid', () => ({ default: () => null }))
const wf = vi.hoisted(() => ({
  complete: vi.fn(),
}))
vi.mock('../../hooks/queries/useWorkflows', () => ({
  useRevisionWorkflow: () => ({ data: { id: 4, status: 'active' }, isLoading: false }),
  useCompleteTask: () => ({ mutate: wf.complete, isPending: false }),
  useCancelWorkflow: () => ({ mutate: vi.fn(), isPending: false }),
}))
vi.mock('../workflows/WorkflowProgress', () => ({
  default: (p: { onCompleteTask: (id: number, d: string) => void }) => (
    <button type="button" onClick={() => p.onCompleteTask(3, 'approved')}>approve-task</button>
  ),
}))

const wrap = (ui: React.ReactElement) =>
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    {ui}
  </QueryClientProvider>)

afterEach(() => { cleanup(); vi.clearAllMocks() })

describe('TransitionDeviationsPanel (P2-3)', () => {
  const dev = { id: 5, to_status: 'released', reason: 'Covered by the new timing', status: 'pending' as const,
    proposed_by: 16, proposed_at: '2026-09-25T10:00:00' }

  it('lets the approver decide with a note', async () => {
    wrap(<TransitionDeviationsPanel changeId={21} deviations={[dev]} decidableIds={[5]} />)
    fireEvent.change(screen.getByLabelText('Note on deviation #5'), { target: { value: 'ok by PM' } })
    fireEvent.click(screen.getByTestId('deviation-reject-5'))
    await waitFor(() => expect(changesApi.decideDeviation)
      .toHaveBeenCalledWith(21, 5, { decision: 'rejected', note: 'ok by PM' }))
  })

  it('tells anyone else whose decision it is, with no buttons', () => {
    wrap(<TransitionDeviationsPanel changeId={21} deviations={[dev]} decidableIds={[]} />)
    expect(screen.getByTestId('deviation-waiting-5').textContent).toContain('Never the requester')
    expect(screen.queryByTestId('deviation-approve-5')).toBeNull()
  })

  it('shows nothing when no deviation is pending', () => {
    wrap(<TransitionDeviationsPanel changeId={21} deviations={[{ ...dev, status: 'consumed' }]} decidableIds={[]} />)
    expect(screen.queryByTestId('transition-deviations')).toBeNull()
  })
})

describe('Actual costs in the change currency (P2-2)', () => {
  const list = (over: Record<string, unknown> = {}) => ({
    items: [{ id: 3, change_id: 21, department_id: null, department_name: null, category: 'external',
      vendor_name: 'Werkzeugbau Meyer GmbH', amount: 8750, cost_date: '2026-09-25', note: null,
      attachment_id: null, created_by: 16, created_by_name: 'cody', created_at: '2026-09-25', can_delete: false }],
    total: 8750, can_write: true, writable_department_ids: null, cost_role: true, ...over,
  })

  it('states the form and the list in the costing currency, not EUR', async () => {
    vi.mocked(actualCostsApi.list).mockResolvedValue(list() as never)
    vi.mocked(changesApi.costingContext).mockResolvedValue({ currency: 'USD' } as never)
    wrap(<ActualCostsPanel changeId={21} />)
    await waitFor(() => expect(screen.getByTestId('actual-cost-total').textContent).toContain('USD'))
    expect(screen.getByTestId('actual-cost-3').textContent).toContain('8.750,00 USD')
    fireEvent.click(screen.getByTestId('actual-cost-open'))
    expect(screen.getByTestId('actual-cost-form').textContent).toContain('Amount (USD)')
    expect(screen.getByTestId('actual-cost-form').textContent).not.toContain('EUR')
  })

  it('never adds two currencies: a line in its own currency gets its own total', async () => {
    vi.mocked(actualCostsApi.list).mockResolvedValue(list({
      currency: 'USD',
      items: [...list().items, { ...list().items[0], id: 4, amount: 100, currency: 'EUR' }],
    }) as never)
    vi.mocked(changesApi.costingContext).mockRejectedValue(new Error('403'))
    wrap(<ActualCostsPanel changeId={21} />)
    await waitFor(() => expect(screen.getByTestId('actual-cost-total').textContent)
      .toBe('8.750,00 USD · 100,00 EUR'))
  })
})

describe('Cost sheet diff currency (P2-2)', () => {
  const ctx = {
    departments: [{ id: 27, name: 'Tool Engineer', is_active: true }],
    plants: [{ id: 2, name: 'USA Toccoa', code: 'US', is_active: true, currency: 'USD', currency_confirmed: false }],
    machineClasses: [], currencies: ['EUR', 'USD'],
  } as never
  const empty = { added: [], removed: [], changed: [] }

  it('shows a changed rate in the row\'s currency (plant USD), not EUR', () => {
    render(<DiffPanel ctx={ctx} diff={{
      from_version: 3, from_version_id: 8, to_version: 4, to_version_id: 9,
      rates: { added: [], removed: [], changed: [{ department_id: 27, position: 'Toolmaker', plant_id: 2,
        changes: { hourly_rate: { old: 19.5, new: 21 } }, pct: 7.7 }] },
      machines: empty, sampling: empty, overheads: empty,
    }} />)
    expect(screen.getByText('19,50 USD')).toBeDefined()
    expect(screen.getByText('21,00 USD')).toBeDefined()
    expect(screen.queryByText(/EUR/)).toBeNull()
  })

  it('a row that names its currency (or changes it) wins over the plant', () => {
    render(<DiffPanel ctx={ctx} diff={{
      from_version: 3, from_version_id: 8, to_version: 4, to_version_id: 9,
      rates: { added: [{ department_id: 27, position: null, plant_id: 2, hourly_rate: 30, currency: 'MXN' }],
        removed: [], changed: [{ department_id: 27, position: null, plant_id: 2,
          changes: { hourly_rate: { old: 10, new: 20 }, currency: { old: 'EUR', new: 'USD' } } }] },
      machines: empty, sampling: empty, overheads: empty,
    }} />)
    expect(screen.getByText('10,00 EUR')).toBeDefined()
    expect(screen.getByText('20,00 USD')).toBeDefined()
    expect(screen.getByText('30,00 MXN')).toBeDefined()
  })
})

describe('Unpriced hours said per department (P2-6)', () => {
  const lines = [
    { position_id: 54, department_id: 6, label: 'Internal', kind: 'internal_effort', quantity: 3, unit: 'h', message: 'x' },
    { position_id: 55, department_id: 6, label: 'Support', kind: 'support_effort', quantity: 10, unit: 'h', message: 'x' },
    { position_id: 60, department_id: 27, label: 'Trials', kind: 'sampling', quantity: 2, unit: 'trial', message: 'x' },
  ]
  const name = (id: number) => (id === 6 ? 'Project Manager' : 'Tool Engineer')

  it('groups the lines and never invents a rate', () => {
    expect(unpricedByDepartment(lines, name).map((u) => u.message)).toEqual([
      'No cost sheet rate for Project Manager: 13 h unpriced',
      'No cost sheet rate for Tool Engineer: 2 trials unpriced',
    ])
    expect(unpricedMessage('Project Manager', 8, 0, true)).toBe('No cost sheet rate for Project Manager: 8 h booked, unpriced')
  })

  it('the P&L card on the costing tab names them with the hours, once per department', async () => {
    vi.mocked(changesApi.getSummation).mockResolvedValue({
      currency: 'USD', totals: { one_time_internal: 0, one_time_external: 0, lifecycle_internal: 0,
        lifecycle_external: 0, grand_total: 0 },
      unpriced_lines: lines.slice(0, 2),
      warnings: [{ code: 'no_rate', message: '2 costing lines have no rate in the cost sheet' },
        { code: 'no_rate_department', message: 'No cost sheet rate for Project Manager: hours unpriced' }],
    } as never)
    wrap(<PnlCard change={{ id: 21, status: 'costing', customer_relevant: true, quoted_price: null } as ChangeDetail}
      departments={[{ id: 6, name: 'Project Manager' }]} />)
    await waitFor(() => expect(screen.getAllByTestId('pnl-unpriced')).toHaveLength(1))
    const text = screen.getByTestId('pnl-costing-warnings').textContent ?? ''
    expect(text).toContain('No cost sheet rate for Project Manager: 13 h unpriced')
    expect(text).not.toContain('Project Manager: hours unpriced')
    expect(text).toContain('2 costing lines have no rate')
  })

  it('a costing bucket with hours but no rate reads "No rate", not "Empty"', async () => {
    vi.mocked(changesApi.getSummation).mockResolvedValue({
      by_department: [{ department_id: 6, one_time_internal: 0, one_time_external: 0,
        lifecycle_internal: 0, lifecycle_external: 0 }],
      unpriced_lines: lines.slice(0, 2),
    } as never)
    wrap(<CostingBuckets canSeeAll editable={false} myDepartmentIds={[]} plants={[]}
      departments={[{ id: 6, name: 'Project Manager' }]}
      change={{ id: 21, status: 'costing', assessments: [{ id: 1, department_id: 6, stage_order: 1 }] } as never} />)
    await waitFor(() => expect(screen.getByTestId('costing-state-6').textContent).toBe(t('costing.noRate')))
  })
})

describe('Revision check workflows (P2-4)', () => {
  it('the toast says why completing a task failed', () => {
    wf.complete.mockImplementation((_v: unknown, o: { onError: (e: unknown) => void }) =>
      o.onError({ response: { data: { detail: 'Only Development may complete this task' } } }))
    render(<RevisionWorkflowSection revisionId={3} />)
    fireEvent.click(screen.getByText('approve-task'))
    expect(toast.error).toHaveBeenCalledWith('Only Development may complete this task')
  })

  it('counts the revisions still in their check workflow and who they need', () => {
    const rc = revisionsInCheckOf([
      { revision_id: 1, instance_id: 2, instance_status: 'active', ready: false, waiting_on: ['Development'] },
      { revision_id: 3, instance_id: 4, instance_status: 'active', ready: false, waiting_on: ['Development', 'Quality'] },
      { revision_id: 5, instance_id: 6, instance_status: 'completed', ready: true },
      { revision_id: null, instance_id: null, instance_status: null, ready: false },
      { revision_id: 7, instance_id: 8, instance_status: 'canceled', ready: false },
    ])
    expect(rc).toEqual({ count: 2, needs: ['Development', 'Quality'] })
    expect(revisionsInCheckText(rc)).toBe('2 revisions still in their check workflow; needs Development, Quality')
    expect(revisionsInCheckText({ count: 1, needs: [] })).toBe('1 revision still in its check workflow')
  })
})

describe('Offer as the customer reads it (P2-7)', () => {
  const data: OfferData = {
    cost_lines: [
      { key: 'dept:27', label: 'Tool Engineer internal effort', department: 'Tool Engineer', category: 'internal',
        amount: 3622, include: true, customer_category: 'Engineering' },
      { key: 'pos:46', label: 'Rib insert', department: 'Tool Engineer', category: 'external',
        amount: 8750, include: true, customer_category: 'Tooling' },
      { key: 'pos:48', label: 'Sampling', department: 'Tool Engineer', category: 'internal',
        amount: 500, include: true, customer_category: 'Sampling and trials' },
    ],
  } as OfferData

  it('previews the customer category of every cost line', () => {
    render(<OfferPriceSection data={data} update={vi.fn()} editable={false} currency="USD" />)
    expect(screen.getByText('Customer reads')).toBeDefined()
    expect(screen.getByTestId('cost-line-customer-pos:46').textContent).toBe('Tooling')
    expect(screen.getByTestId('cost-line-customer-pos:48').textContent).toBe('Sampling and trials')
  })

  it('keeps the column away until the backend names the categories', () => {
    render(<OfferPriceSection data={{ cost_lines: data.cost_lines!.map((l) => ({ ...l, customer_category: null })) } as OfferData}
      update={vi.fn()} editable={false} currency="USD" />)
    expect(screen.queryByText('Customer reads')).toBeNull()
  })

  it('the PDF outline names the sender and the CBD by customer category', () => {
    const offer = { version: 1, currency: 'USD', totals: { total_one_time: 12872 }, warnings: [],
      issued_by: 'KTX Group US Corp.' } as unknown as OfferOut
    render(<OfferDocumentSection offer={offer} data={data} update={vi.fn()} editable={false}
      changeNumber="CR-2026-0021" onPreview={vi.fn()} />)
    const outline = screen.getByTestId('doc-outline').textContent ?? ''
    expect(outline).toContain('Issued by')
    expect(outline).toContain('KTX Group US Corp.')
    expect(outline).toContain('Engineering 3.622,00 USD; Tooling 8.750,00 USD; Sampling and trials 500,00 USD')
    expect(outline).not.toContain('Tool Engineer internal effort')
  })
})
