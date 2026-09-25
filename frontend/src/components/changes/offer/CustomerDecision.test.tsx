import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest'
import { render, screen, cleanup, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { addDaysIso, todayIso } from '../../../lib/format'
import CustomerDecision from './CustomerDecision'
import InternalApproval from './InternalApproval'
import { changesApi } from '../../../api/changes'
import type { ChangeDetail } from '../../../types/change'
import type { OfferOut } from '../../../types/changeOffer'
import { t } from '../../../i18n/cmLabels'

vi.mock('../../../api/changes', () => ({
  changesApi: {
    customerResponse: vi.fn().mockResolvedValue({}),
    signOff: vi.fn().mockResolvedValue({}),
    approveInternalCosts: vi.fn().mockResolvedValue({}),
  },
}))
vi.mock('sonner', () => ({ toast: { error: vi.fn(), success: vi.fn() } }))

const change = (over: Partial<ChangeDetail> = {}): ChangeDetail => ({
  id: 7, change_number: 'CR-7', project_id: 1, title: 'x', change_type: 'tooling',
  priority: 'medium', status: 'quoted', raised_by: 1, customer_response: 'pending',
  customer_relevant: true, pm_signed_by: null, quality_signed_by: null,
  created_at: '2026-07-01T00:00:00', updated_at: '2026-07-01T00:00:00',
  impacted_items: [], assessments: [], attachments: [], ...over,
} as ChangeDetail)

const sent = (over: Partial<OfferOut> = {}) => ({
  id: 10, version: 1, status: 'sent', currency: 'EUR', data: {},
  totals: { base: 0, factors: [], risks_total: 0, scrap: 0, free: 0, total_one_time: 100 },
  created_at: '2026-08-01T00:00:00', valid_until: '2026-09-01', days_left: -23, expired: true, ...over,
}) as OfferOut

const wrap = (ui: React.ReactElement) => render(
  <QueryClientProvider client={new QueryClient()}>{ui}</QueryClientProvider>)

describe('CustomerDecision', () => {
  afterEach(cleanup)
  beforeEach(() => { vi.clearAllMocks() })

  it('requires a release date before recording customer acceptance', async () => {
    wrap(<CustomerDecision change={change()} canRespond canSignPm={false} canSignQuality={false} userId={5} />)
    fireEvent.click(screen.getByText('Customer accepted'))
    const confirm = screen.getByTestId('accept-confirm') as HTMLButtonElement
    expect(confirm.disabled).toBe(true)
    fireEvent.change(screen.getByTestId('accept-release-due'), { target: { value: '2026-11-30' } })
    fireEvent.click(confirm)
    await waitFor(() => expect(changesApi.customerResponse).toHaveBeenCalledWith(7, 'accepted',
      { release_due_date: '2026-11-30T23:59:59Z', release_due_reason: null }))
  })

  it('asks for an override reason when the latest sent offer has expired', async () => {
    wrap(<CustomerDecision change={change()} latestSent={sent()} canRespond
      canSignPm={false} canSignQuality={false} userId={5} />)
    fireEvent.click(screen.getByText('Customer accepted'))
    expect(screen.getByTestId('accept-expired').textContent).toContain('1 Sep 2026')
    fireEvent.change(screen.getByTestId('accept-release-due'), { target: { value: '2026-11-30' } })
    const confirm = screen.getByTestId('accept-confirm') as HTMLButtonElement
    expect(confirm.disabled).toBe(true)
    fireEvent.change(screen.getByTestId('accept-override'), { target: { value: 'Price confirmed by mail' } })
    fireEvent.click(confirm)
    await waitFor(() => expect(changesApi.customerResponse).toHaveBeenCalledWith(7, 'accepted',
      expect.objectContaining({ expired_override_reason: 'Price confirmed by mail' })))
  })

  it('asks for no override reason on a valid offer', () => {
    wrap(<CustomerDecision change={change()} latestSent={sent({ expired: false, days_left: 12, valid_until: addDaysIso(todayIso(), 12) })} canRespond
      canSignPm={false} canSignQuality={false} userId={5} />)
    fireEvent.click(screen.getByText('Customer accepted'))
    expect(screen.queryByTestId('accept-override')).toBeNull()
  })

  it('asks for confirmation before recording a decline (irreversible)', async () => {
    wrap(<CustomerDecision change={change()} canRespond canSignPm={false} canSignQuality={false} userId={5} />)
    fireEvent.click(screen.getByText('Customer declined'))
    expect(changesApi.customerResponse).not.toHaveBeenCalled()
    expect(screen.getByTestId('decline-confirm-box').textContent).toContain('cannot be undone')
    fireEvent.click(screen.getByTestId('decline-confirm'))
    await waitFor(() => expect(changesApi.customerResponse).toHaveBeenCalledWith(7, 'declined', undefined))
    expect(screen.queryByTestId('accept-release-due')).toBeNull()
  })

  it('cancelling the decline confirmation records nothing', () => {
    wrap(<CustomerDecision change={change()} canRespond canSignPm={false} canSignQuality={false} userId={5} />)
    fireEvent.click(screen.getByText('Customer declined'))
    fireEvent.click(screen.getByText('Cancel'))
    expect(screen.queryByTestId('decline-confirm-box')).toBeNull()
    expect(changesApi.customerResponse).not.toHaveBeenCalled()
  })

  it.each([
    ['pending', 'Waiting for the customer'],
    ['negotiating', 'In negotiation'],
    ['accepted', 'Accepted'],
    ['declined', 'Declined'],
  ] as const)('labels the customer response %s in words', (resp, label) => {
    wrap(<CustomerDecision change={change({ customer_response: resp })} canRespond={false}
      canSignPm={false} canSignQuality={false} userId={5} />)
    expect(screen.getByTestId('customer-response').textContent).toBe(label)
  })

  it('disables the Quality sign-off for the user who already PM-signed (4-eyes)', () => {
    wrap(<CustomerDecision change={change({ pm_signed_by: 42 })} canRespond
      canSignPm canSignQuality userId={42} />)
    expect((screen.getByRole('button', { name: /Quality sign-off/ }) as HTMLButtonElement).disabled).toBe(true)
    expect(screen.getByText('PM and Quality sign-off must be different users')).toBeDefined()
  })

  it('leaves both sign-offs enabled when nobody has signed', () => {
    wrap(<CustomerDecision change={change()} canRespond canSignPm canSignQuality userId={42} />)
    expect((screen.getByRole('button', { name: /PM sign-off/ }) as HTMLButtonElement).disabled).toBe(false)
    expect((screen.getByRole('button', { name: /Quality sign-off/ }) as HTMLButtonElement).disabled).toBe(false)
  })

  it('shows only the sign-offs the viewer holds and no response buttons without the right', () => {
    wrap(<CustomerDecision change={change()} canRespond={false} canSignPm={false} canSignQuality userId={5} />)
    expect(screen.getByRole('button', { name: /Quality sign-off/ })).toBeDefined()
    expect(screen.queryByRole('button', { name: /PM sign-off/ })).toBeNull()
    expect(screen.queryByText('Customer accepted')).toBeNull()
  })
})

describe('InternalApproval', () => {
  afterEach(cleanup)
  beforeEach(() => { vi.clearAllMocks() })

  it('requires a release date before internal cost approval', async () => {
    wrap(<InternalApproval change={change({ status: 'costing', customer_relevant: false })} canApprove />)
    fireEvent.click(screen.getByText(t('internal.approve')))
    const confirm = screen.getByTestId('internal-approve-confirm') as HTMLButtonElement
    expect(confirm.disabled).toBe(true)
    fireEvent.change(screen.getByTestId('internal-release-due'), { target: { value: '2026-12-15' } })
    fireEvent.click(confirm)
    await waitFor(() => expect(changesApi.approveInternalCosts).toHaveBeenCalledWith(7,
      { note: null, release_due_date: '2026-12-15T23:59:59Z', release_due_reason: null }))
  })

  it('names who may approve instead of the button for anybody else', () => {
    wrap(<InternalApproval change={change({ status: 'costing', customer_relevant: false })} canApprove={false} />)
    expect(screen.getByText(/Project Manager department member/)).toBeDefined()
    expect(screen.queryByText(t('internal.approve'))).toBeNull()
  })

  it('takes the customer answer only at quoted, and never again once accepted', () => {
    wrap(<CustomerDecision change={change({ status: 'quoting' })} canRespond
      canSignPm={false} canSignQuality={false} userId={5} />)
    expect(screen.queryByTestId('customer-accepted')).toBeNull()
    cleanup()
    wrap(<CustomerDecision change={change({ status: 'quoted', customer_response: 'accepted' })} canRespond
      canSignPm={false} canSignQuality={false} userId={5} />)
    expect(screen.queryByTestId('customer-accepted')).toBeNull()
    expect(screen.queryByTestId('customer-declined')).toBeNull()
  })

  it('labels the accept box Release deadline and Note (optional)', () => {
    wrap(<CustomerDecision change={change()} canRespond canSignPm={false} canSignQuality={false} userId={5} />)
    fireEvent.click(screen.getByText('Customer accepted'))
    expect(screen.getByText('Release deadline')).toBeDefined()
    expect(screen.getByText('Note (optional)')).toBeDefined()
  })
})
