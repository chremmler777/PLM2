import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import AssessmentBuckets from './AssessmentBuckets'
import { changesApi } from '../../api/changes'
import { t } from '../../i18n/cmLabels'

vi.mock('../../api/changes', () => ({
  changesApi: {
    getRouting: vi.fn(),
    assessmentObjects: vi.fn(),
    submitAssessment: vi.fn().mockResolvedValue({}),
    listConcerns: vi.fn().mockResolvedValue([]),
    withdrawConcern: vi.fn(),
    raiseConcern: vi.fn(),
  },
}))
vi.mock('../../contexts/AuthContext', () => ({ useAuth: () => ({ userId: 5, isAdmin: false }) }))

const DEPTS = [
  { id: 2, name: 'Development', is_active: true },
  { id: 4, name: 'Tool Engineer', is_active: true },
  { id: 6, name: 'Packaging Engineer', is_active: true },
]

const assessment = (over: Record<string, unknown> = {}) => ({
  id: 1, department_id: 2, verdict: 'pending', stage_order: 1, rasic_letter: 'R',
  status: 'active', owner_id: null, owner_name: null, accepted_at: null,
  due_date: null, overdue: false, ...over,
})

const change = (over: Record<string, unknown> = {}) => ({
  id: 7, status: 'in_assessment', assessments: [assessment()],
  blocked_department_ids: [], ...over,
}) as never

const wrap = (ui: React.ReactElement) =>
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    {ui}
  </QueryClientProvider>)

const buckets = (props: Record<string, unknown> = {}) =>
  wrap(<AssessmentBuckets change={change()} departments={DEPTS}
    myDepartmentIds={[]} editable {...props} />)

describe('AssessmentBuckets', () => {
  beforeEach(() => {
    vi.mocked(changesApi.getRouting).mockResolvedValue({
      change_id: 7, template_id: 1, template_version: 1, has_deviation: false,
      deviation_status: 'none',
      stages: [{ stage_order: 1, departments: [
        { department_id: 2, rasic_letter: 'R', tier: 'blocking', status: 'active', verdict: 'pending' },
        { department_id: 4, rasic_letter: 'S', tier: 'optional', status: 'pending', verdict: null },
      ] }],
    } as never)
    vi.mocked(changesApi.assessmentObjects).mockResolvedValue({ departments: [
      { department_id: 2, name: 'Development', objects: [
        { type: 'part', id: 11, number: '20-3450-001-0', name: 'Clip', via_part_id: null },
        { type: 'gauge', id: 12, number: 'G-77', name: 'Clip gauge', via_part_id: 11 },
      ] },
    ] } as never)
    vi.mocked(changesApi.submitAssessment).mockClear()
  })
  afterEach(cleanup)

  it('gives every routed department a row, whether or not it has answered', async () => {
    buckets()
    expect(await screen.findByTestId('bucket-2')).toBeTruthy()
    // Routed but with no assessment row of its own — still on the board.
    expect(await screen.findByTestId('bucket-4')).toBeTruthy()
    expect(screen.getByTestId('bucket-state-2').textContent).toBe(t('bucket.waiting'))
  })

  it('says a department is on hold when a concern blocks it', async () => {
    buckets({ change: change({ blocked_department_ids: [2] }) })
    expect((await screen.findByTestId('bucket-state-2')).textContent).toBe(t('concern.onHold'))
  })

  it('shows the verdict once submitted and keeps the answer readable', async () => {
    buckets({ change: change({ assessments: [assessment({
      verdict: 'feasible_with_conditions', status: 'submitted',
      submitted_at: '2026-08-01T00:00:00', conditions: 'needs a new gauge' })] }) })
    expect((await screen.findByTestId('bucket-state-2')).textContent).toBe(t('bucket.submitted'))
    expect(screen.getByTestId('bucket-verdict-2')).toBeTruthy()
    fireEvent.click(screen.getByTestId('bucket-toggle-2'))
    expect(screen.getByTestId('bucket-answer-2').textContent).toContain('needs a new gauge')
  })

  it('opens a member row into their objects and the form', async () => {
    buckets({ myDepartmentIds: [2] })
    fireEvent.click(await screen.findByTestId('bucket-toggle-2'))
    await waitFor(() => expect(screen.getByText('20-3450-001-0')).toBeTruthy())
    // Objects are grouped by kind, with the via-part reference kept.
    expect(screen.getByText(t('objtype.gauge'))).toBeTruthy()
    expect(screen.getByText(/via part #11/)).toBeTruthy()
    expect(screen.getByTestId('assessment-submit')).toBeTruthy()
  })

  it('leaves a non-member the objects but no form', async () => {
    buckets({ myDepartmentIds: [4] })
    fireEvent.click(await screen.findByTestId('bucket-toggle-2'))
    await waitFor(() => expect(screen.getByText('20-3450-001-0')).toBeTruthy())
    expect(screen.queryByTestId('assessment-submit')).toBeNull()
    expect(screen.getByTestId('bucket-readonly-2').textContent).toBe(t('bucket.readOnly'))
  })

  it('says so plainly when a department has nothing linked to look at', async () => {
    buckets({ myDepartmentIds: [4] })
    fireEvent.click(await screen.findByTestId('bucket-toggle-4'))
    expect(await screen.findByText(t('bucket.noObjects'))).toBeTruthy()
  })

  it('asks nothing about cost — that belongs to costing', async () => {
    buckets({ myDepartmentIds: [2] })
    fireEvent.click(await screen.findByTestId('bucket-toggle-2'))
    await waitFor(() => expect(screen.getByTestId('assessment-submit')).toBeTruthy())
    expect(screen.queryByLabelText(/effort/i)).toBeNull()
    expect(screen.queryByText(t('effort.hours'))).toBeNull()
  })
})

describe('AssessmentBuckets department questionnaires', () => {
  beforeEach(() => {
    vi.mocked(changesApi.getRouting).mockResolvedValue({
      change_id: 7, template_id: 1, template_version: 1, has_deviation: false,
      deviation_status: 'none',
      stages: [{ stage_order: 1, departments: [
        { department_id: 6, rasic_letter: 'R', tier: 'blocking', status: 'active', verdict: 'pending' },
      ] }],
    } as never)
    vi.mocked(changesApi.assessmentObjects).mockResolvedValue({ departments: [] } as never)
    vi.mocked(changesApi.submitAssessment).mockClear()
  })
  afterEach(cleanup)

  const packaging = () => buckets({
    myDepartmentIds: [6],
    change: change({ assessments: [assessment({ id: 2, department_id: 6 })] }),
  })

  it('asks packaging first whether packaging is impacted at all', async () => {
    packaging()
    fireEvent.click(await screen.findByTestId('bucket-toggle-6'))
    expect(screen.getByText(t('pkg.impacted'))).toBeTruthy()
    // The detail only exists once the answer is yes.
    expect(screen.queryByTestId('pkg-detail')).toBeNull()
    fireEvent.click(screen.getByTestId('pkg-impacted-yes'))
    expect(screen.getByTestId('pkg-detail')).toBeTruthy()
    expect(screen.getByTestId('pkg-layout_change')).toBeTruthy()
  })

  it('submits a not-impacted answer in one step', async () => {
    packaging()
    fireEvent.click(await screen.findByTestId('bucket-toggle-6'))
    fireEvent.click(screen.getByTestId('pkg-impacted-no'))
    // Nothing else to ask: no verdict picker, no notes — just record it.
    const submit = screen.getByTestId('assessment-submit') as HTMLButtonElement
    expect(submit.disabled).toBe(false)
    expect(submit.textContent).toBe(t('pkg.submitNotImpacted'))
    fireEvent.click(submit)
    await waitFor(() => expect(changesApi.submitAssessment).toHaveBeenCalledWith(7,
      expect.objectContaining({
        department_id: 6, verdict: 'feasible', details: { impacted: false },
      })))
  })

  it('carries the checked boxes into the submission', async () => {
    packaging()
    fireEvent.click(await screen.findByTestId('bucket-toggle-6'))
    fireEvent.click(screen.getByTestId('pkg-impacted-yes'))
    fireEvent.click(screen.getByTestId('pkg-layout_change'))
    fireEvent.change(screen.getByLabelText(/Verdict|Bewertung/i), { target: { value: 'feasible' } })
    fireEvent.click(screen.getByTestId('assessment-submit'))
    await waitFor(() => expect(changesApi.submitAssessment).toHaveBeenCalledWith(7,
      expect.objectContaining({
        department_id: 6, verdict: 'feasible',
        details: expect.objectContaining({ impacted: true, layout_change: true }),
      })))
  })

  it('leaves departments without a questionnaire on the generic form', async () => {
    buckets({ myDepartmentIds: [2] })
    fireEvent.click(await screen.findByTestId('bucket-toggle-2'))
    expect(screen.queryByText(t('pkg.impacted'))).toBeNull()
  })
})
