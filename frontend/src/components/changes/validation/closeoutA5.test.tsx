/**
 * Area 5 close-out on the validation issue card: HARD #3 closes need a
 * reference (A5-01), Quality's options (follow-up change, raised in error)
 * are buttons the backend accepts (A5-08), the route dialog offers the
 * viewer's routes only, and 4 eyes hold for an admin.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, cleanup, fireEvent } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import type { IssueOut } from '../../../types/validationIssue'
import { validationIssuesApi } from '../../../api/validationIssues'
import IssueCard from './IssueCard'
import { routeOptions } from './RouteDialog'
import { raiserBlocked } from './issueModel'
import { weekendRetest } from './FixConcessionForms'
import { settledIssueForCheck } from '../ValidationPanel'

vi.mock('../../../api/validationIssues', () => ({
  validationIssuesKey: (id: number) => ['change', id, 'validation-issues'],
  validationIssuesApi: {
    list: vi.fn(), create: vi.fn(), update: vi.fn(), contain: vi.fn(), rootCause: vi.fn(),
    route: vi.fn(), customer: vi.fn(), cost: vi.fn(), addAction: vi.fn(), actionDone: vi.fn(),
    close: vi.fn(), escalate: vi.fn(), deescalate: vi.fn(), fixQuoted: vi.fn(), acknowledge: vi.fn(),
  },
}))
vi.mock('../../../api/changes', () => ({
  changesApi: { uploadAttachment: vi.fn(), deleteAttachment: vi.fn(), costingContext: vi.fn() },
}))
vi.mock('sonner', () => ({ toast: { error: vi.fn(), success: vi.fn() } }))

const departments = [{ id: 4, name: 'Tool Engineer' }]
const issue = (over: Partial<IssueOut> = {}): IssueOut => ({
  id: 11, change_id: 7, number: 2, title: 'Scratch on the cover', category: 'other', severity: 1,
  department_id: 4, department_name: 'Tool Engineer', description: 'visual, 3 parts',
  status: 'revalidation', created_by: 5, created_by_name: 'Rita Raiser', created_at: '2026-09-24T08:00:00',
  actions: [], attachments: [], escalation_level: 1, escalations: [], next_acts: ['close'], extra_acts: [],
  primary_act: 'close', fix_rule: true, close_needs_ref: true, route: 'internal_rework', ...over,
})
const card = (i: IssueOut) => render(
  <MemoryRouter>
    <QueryClientProvider client={new QueryClient()}>
      <IssueCard changeId={7} changeStatus="in_validation" issue={i} viewer={{}} departments={departments} />
    </QueryClientProvider>
  </MemoryRouter>)

afterEach(cleanup)
beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(validationIssuesApi.close).mockResolvedValue({} as never)
})

describe('A5-01 the closure note of a HARD #3 issue is a reference', () => {
  it('"ok" keeps Close disabled, a report number enables it', () => {
    card(issue())
    fireEvent.click(screen.getByTestId('issue-primary-11'))
    const box = screen.getByTestId('issue-text-close-11')
    fireEvent.change(box, { target: { value: 'ok' } })
    expect(screen.getByTestId('issue-text-submit-close-11')).toHaveProperty('disabled', true)
    fireEvent.change(box, { target: { value: 'approved' } })
    expect(screen.getByTestId('issue-text-submit-close-11')).toHaveProperty('disabled', true)
    expect(screen.getByTestId('issue-text-ref-close-11')).toBeTruthy()
    fireEvent.change(box, { target: { value: 'CMM report MR-2026-311' } })
    expect(screen.getByTestId('issue-text-submit-close-11')).toHaveProperty('disabled', false)
  })

  it('switched off, any note closes (the rule before)', () => {
    card(issue({ close_needs_ref: false }))
    fireEvent.click(screen.getByTestId('issue-primary-11'))
    fireEvent.change(screen.getByTestId('issue-text-close-11'), { target: { value: 'fine' } })
    expect(screen.getByTestId('issue-text-submit-close-11')).toHaveProperty('disabled', false)
  })
})

describe('A5-08 Quality options on an open unlinked issue', () => {
  it('shows "Close: raised in error" and "Move to a follow-up change", no primary', () => {
    card(issue({
      status: 'open', route: null, primary_act: null, next_acts: ['concession_request', 'route', 'close'],
      route_options: ['follow_up_change'],
    }))
    expect(screen.queryByTestId('issue-primary-11')).toBeNull()
    const expand = screen.queryByRole('button', { name: /^Expand/ })
    if (expand) fireEvent.click(expand)
    expect(screen.getByTestId('issue-act-close-11').textContent).toBe('Close: raised in error')
    expect(screen.getByTestId('issue-act-route-11').textContent).toBe('Move to a follow-up change')
  })
})

describe('A5-01 route options and 4 eyes', () => {
  it('the dialog offers the backend list for this viewer', () => {
    expect(routeOptions(issue({ route: null, route_options: ['follow_up_change'] }))).toEqual(['follow_up_change'])
    expect(routeOptions(issue({ route: null, route_options: ['internal_rework', 'supplier_rework', 'design_change'] })))
      .not.toContain('follow_up_change')
  })
  it('an admin who raised the issue is blocked like anyone (4 eyes)', () => {
    expect(raiserBlocked(issue({ created_by: 1 }), { id: 1, isAdmin: true })).toBe(true)
  })
})

describe('A5-11 fix and concession edges', () => {
  it('a weekend retest moves to the next Monday', () => {
    expect(weekendRetest('2026-10-17')).toBe('2026-10-19')
    expect(weekendRetest('2026-10-18')).toBe('2026-10-19')
    expect(weekendRetest('2026-10-16')).toBeNull()
  })
  it('an accepted concession settles the failed check: no second Raise', () => {
    const acc = issue({ status: 'accepted', check_key: 'weight', department_id: 4, route: 'customer_concession' })
    expect(settledIssueForCheck([acc], 4, 'weight')?.status).toBe('accepted')
    expect(settledIssueForCheck([issue({ status: 'open', check_key: 'weight' })], 4, 'weight')).toBeUndefined()
  })
})
