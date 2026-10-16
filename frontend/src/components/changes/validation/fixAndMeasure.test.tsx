/** ECR-solid §10: computed checks, the Fix task and the concession (UI). */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, cleanup, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import type { IssueOut } from '../../../types/validationIssue'
import type { ValidationCheck } from '../../../types/change'
import { validationIssuesApi } from '../../../api/validationIssues'
import { changesApi } from '../../../api/changes'
import MeasurementForm, { measurementBody, type MeasureDraft } from './MeasurementForm'
import { ConcessionForm, FixForm, concessionBlocked, fixBlocked } from './FixConcessionForms'
import IssueCard from './IssueCard'
import CustomerDecisionForm, { customerDecisionBlocked } from './CustomerDecisionForm'

vi.mock('../../../api/validationIssues', () => ({
  validationIssuesKey: (id: number) => ['change', id, 'validation-issues'],
  validationIssuesApi: {
    list: vi.fn(), customer: vi.fn(), fix: vi.fn(), requestConcession: vi.fn(),
  },
}))
vi.mock('../../../api/changes', () => ({
  changesApi: { setValidationCheck: vi.fn() },
}))
vi.mock('../../../api/changePlan', () => ({ planApi: { get: vi.fn().mockResolvedValue({ tasks: [] }) } }))
vi.mock('sonner', () => ({ toast: { error: vi.fn(), success: vi.fn() } }))

const wrap = (ui: React.ReactElement) => render(
  <MemoryRouter>
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>{ui}</QueryClientProvider>
  </MemoryRouter>)

afterEach(cleanup)
beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(changesApi.setValidationCheck).mockResolvedValue({} as never)
  for (const fn of Object.values(validationIssuesApi)) vi.mocked(fn).mockResolvedValue({} as never)
})

const draft = (over: Partial<MeasureDraft> = {}): MeasureDraft => ({
  n: '5', min: '503', max: '509', ref: 'scale WG-0042', lot: '', lower: '495', upper: '515',
  source: 'drawing 886.197 D', kind: '', changed: '', ...over,
})
const weight = (over: Partial<ValidationCheck> = {}): ValidationCheck => ({
  check_key: 'weight', status: 'open', computed: true, unit_short: 'g', needs_lot: false,
  lower_limit: null, upper_limit: null, measurements: [], ...over,
})

describe('measurementBody', () => {
  it('the first measurement carries the limits and their source', () => {
    const { body, why } = measurementBody(weight(), draft())
    expect(why).toBeNull()
    expect(body).toMatchObject({ sample_size: 5, min_value: 503, max_value: 509,
      lower_limit: 495, upper_limit: 515, spec_source: 'drawing 886.197 D' })
  })
  it('NEGATIVE: "ok" is no measuring report, min above max is refused', () => {
    expect(measurementBody(weight(), draft({ ref: 'ok' })).body).toBeNull()
    expect(measurementBody(weight(), draft({ min: '510', max: '503' })).body).toBeNull()
    expect(measurementBody(weight(), draft({ n: '0' })).body).toBeNull()
  })
  it('limits fixed: not sent again; a retest needs what changed', () => {
    const fixed = weight({ lower_limit: 495, upper_limit: 515, status: 'failed' })
    expect(measurementBody(fixed, draft()).body).toBeNull()
    const { body } = measurementBody(fixed, draft({ kind: 'parameter', changed: 'holding pressure -5 bar' }))
    expect(body).toMatchObject({ what_changed_kind: 'parameter' })
    expect(body).not.toHaveProperty('lower_limit')
  })
  it('cycle time names its lot', () => {
    const ct = weight({ check_key: 'cycle_time', unit_short: 's', needs_lot: true })
    expect(measurementBody(ct, draft()).body).toBeNull()
    expect(measurementBody(ct, draft({ lot: 'lot 2026-41-117' })).body).toMatchObject({ lot_ref: 'lot 2026-41-117' })
  })
})

describe('MeasurementForm', () => {
  it('posts the measurement, never a status', async () => {
    wrap(<MeasurementForm changeId={7} deptId={3} check={weight()} id="3-weight" />)
    const fill = (tid: string, v: string) => fireEvent.change(screen.getByTestId(tid), { target: { value: v } })
    fill('validation-lower-3-weight', '495'); fill('validation-upper-3-weight', '515')
    fill('validation-source-3-weight', 'drawing 886.197 D')
    fill('validation-n-3-weight', '5'); fill('validation-min-3-weight', '503')
    fill('validation-max-3-weight', '516.2'); fill('validation-ref-3-weight', 'report MR-2026-118')
    fireEvent.click(screen.getByTestId('validation-measure-submit-3-weight'))
    await waitFor(() => expect(changesApi.setValidationCheck).toHaveBeenCalled())
    const body = vi.mocked(changesApi.setValidationCheck).mock.calls[0][1]
    expect(body).not.toHaveProperty('status')
    expect(body.measurement).toMatchObject({ max_value: 516.2, upper_limit: 515 })
  })
})

const issue = (over: Partial<IssueOut> = {}): IssueOut => ({
  id: 11, change_id: 7, number: 1, title: 'Part weight validated failed', category: 'material_weight',
  severity: 2, department_id: 4, department_name: 'Tool Engineer',
  description: 'Part weight validated 518 g vs 495-515', status: 'open', created_by: 5,
  created_at: '2026-10-15T08:00:00', actions: [], attachments: [], escalation_level: 1, escalations: [],
  check_id: 3, check_key: 'weight', fix_rule: true, ...over,
} as IssueOut)

describe('Fix task', () => {
  it('NEGATIVE: nothing is sent without an owner, a supplier for the tool, a future date', () => {
    expect(fixBlocked(null, null, '', '2099-01-01')).not.toBeNull()
    expect(fixBlocked('tool_at_supplier', null, '', '2099-01-01')).not.toBeNull()
    expect(fixBlocked('other', null, '', '2099-01-01')).not.toBeNull()
    expect(fixBlocked('process_parameters', null, '', '2000-01-01', '2026-10-15')).not.toBeNull()
    expect(fixBlocked('process_parameters', null, '', '2026-10-20', '2026-10-15')).toBeNull()
  })
  it('Quality sees "Pick who fixes" as the primary act; the form posts owner and date', async () => {
    wrap(<IssueCard changeId={7} changeStatus="in_validation" departments={[]} viewer={{ id: 9 }}
      issue={issue({ next_acts: ['fix', 'concession_request'], primary_act: 'fix' })} />)
    const primary = screen.getByTestId('issue-primary-11')
    expect(primary.textContent).toBe('Pick who fixes')
    fireEvent.click(primary)
    fireEvent.click(screen.getByTestId('fix-owner-process_parameters'))
    expect((screen.getByTestId('fix-submit') as HTMLButtonElement).disabled).toBe(true)
  })
  it('after the pick (and beside a concession) Quality may change it: a quiet re-pick', () => {
    wrap(<IssueCard changeId={7} changeStatus="in_validation" departments={[]} viewer={{ id: 9 }}
      issue={issue({ route: 'customer_concession', fix_owner_kind: 'process_parameters', fix_department_id: 4,
        retest_due: '2099-01-02', next_acts: ['refix'], primary_act: null })} />)
    expect(screen.queryByTestId('issue-primary-11')).toBeNull()
    fireEvent.click(screen.getByTestId('issue-act-refix-11'))
    expect(screen.getByTestId('issue-fix-form-11')).toBeTruthy()
    // prefilled with the current pick: only the changed field needs a touch
    expect((screen.getByTestId('fix-submit') as HTMLButtonElement).disabled).toBe(false)
  })
  it('the Fix form submits process parameters with the date', async () => {
    const { container } = wrap(<FixForm changeId={7} issue={issue({ retest_due: '2099-01-02' })} departments={[]} onDone={() => {}} />)
    fireEvent.click(screen.getByTestId('fix-owner-process_parameters'))
    fireEvent.click(screen.getByTestId('fix-submit'))
    await waitFor(() => expect(validationIssuesApi.fix).toHaveBeenCalledWith(7, 11,
      { owner: 'process_parameters', retest_due: '2099-01-02' }))
    expect(container).toBeTruthy()
  })
})

describe('concession', () => {
  it('NEGATIVE internal: not for shipment and a bound are required', () => {
    expect(concessionBlocked(true, 'trial parts', false, '200', '')).not.toBeNull()
    expect(concessionBlocked(true, 'trial parts', true, '', '')).not.toBeNull()
    expect(concessionBlocked(true, 'trial parts', true, '2.5', '')).not.toBeNull()
    expect(concessionBlocked(true, 'trial parts', true, '200', '')).toBeNull()
    expect(concessionBlocked(false, 'ask for 518 g', false, '', '')).toBeNull()
  })
  it('a customer change asks the Sales owner: note only', async () => {
    wrap(<ConcessionForm changeId={7} issue={issue()} customerRelevant onDone={() => {}} />)
    expect(screen.queryByTestId('concession-nfs')).toBeNull()
    fireEvent.change(screen.getByTestId('concession-note'), { target: { value: 'ask for 518 g max' } })
    fireEvent.click(screen.getByTestId('concession-submit'))
    await waitFor(() => expect(validationIssuesApi.requestConcession).toHaveBeenCalledWith(7, 11,
      { note: 'ask for 518 g max' }))
  })
  it("NEGATIVE: Quality's yes needs a quantity or a date under the rule", () => {
    const i = issue({ route: 'customer_concession', status: 'route_decided',
      attachments: [{ id: 1, kind: 'customer_email' } as never] })
    expect(customerDecisionBlocked(i, 'accept_deviation', 'mail 15 Oct', '')).toMatch(/quantity/)
    expect(customerDecisionBlocked(i, 'accept_deviation', 'mail 15 Oct', '', '2026-10-15', '500')).toBeNull()
  })
  it('the decision form shows the bound fields for a concession', () => {
    wrap(<CustomerDecisionForm changeId={7} issue={issue({ route: 'customer_concession',
      customer_options: ['accept_deviation'] })} />)
    fireEvent.click(screen.getByTestId('customer-decision-accept_deviation'))
    expect(screen.getByTestId('concession-qty')).toBeTruthy()
  })
})
