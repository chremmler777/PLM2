import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest'
import { render, screen, cleanup, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { addDaysIso, todayIso } from '../../../lib/format'
import CustomerDecision, { addWorkingDaysIso } from './CustomerDecision'
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

  it('HARD #4/#9: a signature on an older offer can be given again for the latest one', async () => {
    const owed = change({ customer_response: 'accepted', pm_signed_by: 3, quality_signed_by: 4,
      next_step: { to: 'approved', items: [
        { key: 'pm_signoff', kind: 'hard', exits: ['sign'], sides: ['pm'], detail: 'v2' },
      ] } })
    wrap(<CustomerDecision change={owed} canRespond={false} canSignPm canSignQuality userId={5} />)
    const pm = screen.getByTestId('signoff-pm') as HTMLButtonElement
    expect(pm.disabled).toBe(false)
    expect(pm.textContent).toBe('PM: Sign again for v2')
    expect((screen.getByTestId('signoff-quality') as HTMLButtonElement).disabled).toBe(true)
    fireEvent.click(pm)
    await waitFor(() => expect(changesApi.signOff).toHaveBeenCalledWith(7, 'pm'))
  })

  it('requires a release date before recording customer acceptance (switch off)', async () => {
    wrap(<CustomerDecision change={change({ commercial_v2: false })} canRespond canSignPm={false} canSignQuality={false} userId={5} />)
    fireEvent.click(screen.getByText('Customer accepted'))
    const confirm = screen.getByTestId('accept-confirm') as HTMLButtonElement
    expect(confirm.disabled).toBe(true)
    fireEvent.change(screen.getByLabelText(t('customer.releaseDue')), { target: { value: '2026-11-30' } })
    fireEvent.click(confirm)
    await waitFor(() => expect(changesApi.customerResponse).toHaveBeenCalledWith(7, 'accepted',
      { release_due_date: '2026-11-30T23:59:59Z', release_due_reason: null }))
  })

  it('asks for an override reason when the latest sent offer has expired (switch off)', async () => {
    wrap(<CustomerDecision change={change({ commercial_v2: false })} latestSent={sent()} canRespond
      canSignPm={false} canSignQuality={false} userId={5} />)
    fireEvent.click(screen.getByText('Customer accepted'))
    expect(screen.getByTestId('accept-expired').textContent).toContain('1 Sep 2026')
    fireEvent.change(screen.getByLabelText(t('customer.releaseDue')), { target: { value: '2026-11-30' } })
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

  it('asks for confirmation before recording a decline (irreversible, switch off)', async () => {
    wrap(<CustomerDecision change={change({ commercial_v2: false })} canRespond canSignPm={false} canSignQuality={false} userId={5} />)
    fireEvent.click(screen.getByText('Customer declined'))
    expect(changesApi.customerResponse).not.toHaveBeenCalled()
    expect(screen.getByTestId('decline-confirm-box').textContent).toContain('cannot be undone')
    fireEvent.click(screen.getByTestId('decline-confirm'))
    await waitFor(() => expect(changesApi.customerResponse).toHaveBeenCalledWith(7, 'declined', undefined))
    expect(screen.queryByLabelText(t('customer.releaseDue'))).toBeNull()
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

describe('CustomerDecision §7 (COMMERCIAL_V2)', () => {
  afterEach(cleanup)
  beforeEach(() => { vi.clearAllMocks() })
  const mail = { id: 81, filename: 'PO 4500123456.msg', content_type: 'x', size_bytes: 1, phase: 'baseline',
    kind: 'customer_email', created_at: '2026-10-14T10:00:00' } as const
  const valid = () => sent({ expired: false, days_left: 12, valid_until: addDaysIso(todayIso(), 12),
    totals: { base: 0, factors: [], risks_total: 0, scrap: 0, free: 0, total_one_time: 4200 } as OfferOut['totals'],
    index_changes: [{ number: '886.197', offer: 'C', now: 'D' }] })

  it('accept needs evidence, the PO match and the confirmed total; nothing preselected', async () => {
    wrap(<CustomerDecision change={change({ release_due_date: '2026-12-18T00:00:00', attachments: [mail] })}
      latestSent={valid()} canRespond canSignPm={false} canSignQuality={false} userId={5} />)
    fireEvent.click(screen.getByText('Customer accepted'))
    const confirm = screen.getByTestId('accept-confirm') as HTMLButtonElement
    expect((screen.getByTestId('po-match-yes') as HTMLInputElement).checked).toBe(false)
    expect((screen.getByTestId('po-match-no') as HTMLInputElement).checked).toBe(false)
    expect(screen.getByTestId('accept-index-warning').textContent).toContain('886.197 C → D')
    // NEGATIVE: no evidence yet
    expect(confirm.disabled).toBe(true)
    fireEvent.change(screen.getByTestId('answer-ref'), { target: { value: 'ok' } })
    fireEvent.click(screen.getByTestId('po-match-yes'))
    fireEvent.click(screen.getByTestId('accept-total'))
    expect(confirm.disabled).toBe(true)      // 'ok' is no evidence
    fireEvent.change(screen.getByTestId('answer-mail'), { target: { value: '81' } })
    // NEGATIVE: a "no" needs what differs
    fireEvent.click(screen.getByTestId('po-match-no'))
    expect(confirm.disabled).toBe(true)
    fireEvent.change(screen.getByTestId('answer-differs'), { target: { value: '886.198 added on the PO' } })
    expect(confirm.disabled).toBe(false)
    expect(screen.getByTestId('accept-box').textContent).toContain('This mail says yes to v1 at')
    fireEvent.click(confirm)
    await waitFor(() => expect(changesApi.customerResponse).toHaveBeenCalledWith(7, 'accepted', expect.objectContaining({
      attachment_id: 81, po_match: 'no', confirm_total: true, differs: '886.198 added on the PO' })))
  })

  it('still talking records the next contact, +5 working days by default', async () => {
    wrap(<CustomerDecision change={change()} latestSent={valid()} canRespond canSignPm={false} canSignQuality={false} userId={5} />)
    fireEvent.click(screen.getByTestId('customer-talking'))
    fireEvent.click(screen.getByTestId('talk-confirm'))
    await waitFor(() => expect(changesApi.customerResponse).toHaveBeenCalledWith(7, 'negotiating',
      { next_contact: addWorkingDaysIso(todayIso(), 5) }))
  })

  it('decline needs the customer reference and says the change is rejected', async () => {
    wrap(<CustomerDecision change={change()} latestSent={valid()} canRespond canSignPm={false} canSignQuality={false} userId={5} />)
    fireEvent.click(screen.getByText('Customer declined'))
    expect(screen.getByTestId('decline-confirm-box').textContent).toContain('rejection letter')
    const confirm = screen.getByTestId('decline-confirm') as HTMLButtonElement
    expect(confirm.disabled).toBe(true)      // NEGATIVE: no reference
    fireEvent.change(screen.getByTestId('answer-ref'), { target: { value: 'Mail 14 Oct, too expensive' } })
    fireEvent.click(confirm)
    await waitFor(() => expect(changesApi.customerResponse).toHaveBeenCalledWith(7, 'declined',
      { ref: 'Mail 14 Oct, too expensive' }))
  })

  it('every viewer reads who signed, when and on which version', () => {
    wrap(<CustomerDecision change={change({ pm_signed_by: 3, pm_signed_by_name: 'Pat PM', pm_signed_at: '2026-10-14T09:00:00',
      pm_signed_offer_id: 10 })} latestSent={valid()} canRespond={false} canSignPm={false} canSignQuality={false} userId={5} />)
    expect(screen.getByTestId('signers').textContent).toBe('PM: Pat PM, 14 Oct 2026, v1 · Quality: pending')
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
    fireEvent.change(screen.getByLabelText(t('customer.releaseDue')), { target: { value: '2026-12-15' } })
    fireEvent.click(confirm)
    await waitFor(() => expect(changesApi.approveInternalCosts).toHaveBeenCalledWith(7,
      { note: null, release_due_date: '2026-12-15T23:59:59Z', release_due_reason: null }))
  })

  it('names who may approve instead of the button for anybody else', () => {
    wrap(<InternalApproval change={change({ status: 'costing', customer_relevant: false })} canApprove={false} />)
    expect(screen.getByTestId('internal-approvers').textContent)
      .toBe('Internal costs are approved by a Project Management member or an admin (never the raiser)')
    cleanup()
    // HARD #8: the backend names the approvers (never the raiser)
    wrap(<InternalApproval change={change({ status: 'costing', customer_relevant: false })} canApprove={false}
      approvers="Christoph Demmler" />)
    expect(screen.getByTestId('internal-approvers').textContent)
      .toBe('Internal costs are approved by Christoph Demmler (never the raiser)')
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
