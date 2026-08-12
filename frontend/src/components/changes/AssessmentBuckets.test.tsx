import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import AssessmentBuckets, { pickAssessment } from './AssessmentBuckets'
import type { Assessment } from '../../types/change'
import { changesApi } from '../../api/changes'
import { t } from '../../i18n/cmLabels'

vi.mock('../../api/changes', () => ({
  changesApi: {
    getRouting: vi.fn(),
    assessmentObjects: vi.fn(),
    submitAssessment: vi.fn().mockResolvedValue({}),
    listConcerns: vi.fn().mockResolvedValue([]),
    riskTypes: vi.fn().mockResolvedValue({ items: [] }),
    referenceActivities: vi.fn().mockResolvedValue([]),
    assessmentChecklist: vi.fn().mockResolvedValue([]),
    withdrawConcern: vi.fn(),
    raiseConcern: vi.fn(),
  },
}))
vi.mock('../../contexts/AuthContext', () => ({ useAuth: () => ({ userId: 5, isAdmin: false }) }))
vi.mock('./AttachmentDropzone', () => ({
  default: (p: { assessmentId?: number; kind?: string }) => (
    <div data-testid="dropzone" data-assessment={p.assessmentId ?? ''}
      data-kind={p.kind ?? ''} />
  ),
}))

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

describe('pickAssessment', () => {
  const row = (over: Partial<Assessment>) => assessment(over) as unknown as Assessment

  it('keeps the submitted answer in front of a not-yet-started later stage', () => {
    // Multi-stage routing pre-creates later-stage rows as `pending`. After the
    // department submits its stage-1 answer, the bucket must keep showing that
    // answer — not rebind to the dormant stage-2 row and act as if nothing
    // happened (the "my assessment went away" bug).
    const submitted = row({ id: 1, stage_order: 1, rasic_letter: 'R',
      status: 'submitted', verdict: 'feasible', submitted_at: '2026-08-11T23:57:41Z' })
    const dormant = row({ id: 2, stage_order: 2, rasic_letter: 'C',
      status: 'pending', verdict: 'pending' })
    expect(pickAssessment([submitted, dormant])?.id).toBe(1)
  })

  it('still binds to the active row over an old answer', () => {
    const answered = row({ id: 1, stage_order: 1, status: 'submitted',
      verdict: 'feasible', submitted_at: '2026-08-11T23:57:41Z' })
    const active = row({ id: 2, stage_order: 1, status: 'active', verdict: 'pending' })
    expect(pickAssessment([answered, active])?.id).toBe(2)
  })

  it('binds to the earliest pending row when nothing is active or answered', () => {
    const later = row({ id: 1, stage_order: 3, status: 'pending', verdict: 'pending' })
    const earlier = row({ id: 2, stage_order: 2, status: 'pending', verdict: 'pending' })
    expect(pickAssessment([later, earlier])?.id).toBe(2)
  })
})

describe('AssessmentBuckets dormant stages', () => {
  afterEach(cleanup)

  it('marks a not-yet-started stage as queued, not as unclaimed work', async () => {
    // PM's stage-2 row exists from routing but the stage has not started.
    // The bucket must not present PM as on the hook ("R … unclaimed, waiting").
    vi.mocked(changesApi.getRouting).mockResolvedValue({ stages: [] } as never)
    vi.mocked(changesApi.assessmentObjects).mockResolvedValue({ departments: [] } as never)
    wrap(<AssessmentBuckets departments={DEPTS} myDepartmentIds={[]} editable canSeeAll
      change={change({ assessments: [assessment({
        department_id: 2, status: 'pending', stage_order: 2 })] })} />)
    expect((await screen.findByTestId('bucket-state-2')).textContent).toBe(t('bucket.queued'))
    expect(screen.queryByText(t('tasks.unclaimed'))).toBeNull()
  })

  it('tells a member there is nothing to submit yet, not that access is denied', async () => {
    vi.mocked(changesApi.getRouting).mockResolvedValue({ stages: [] } as never)
    vi.mocked(changesApi.assessmentObjects).mockResolvedValue({ departments: [] } as never)
    wrap(<AssessmentBuckets departments={DEPTS} myDepartmentIds={[2]} editable
      change={change({ assessments: [assessment({
        department_id: 2, status: 'pending', stage_order: 2 })] })} />)
    expect((await screen.findByTestId('bucket-readonly-2')).textContent)
      .toBe(t('bucket.notOpenYet'))
  })
})

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
    buckets({ canSeeAll: true })
    expect(await screen.findByTestId('bucket-2')).toBeTruthy()
    // Routed but with no assessment row of its own — still on the board.
    expect(await screen.findByTestId('bucket-4')).toBeTruthy()
    expect(screen.getByTestId('bucket-state-2').textContent).toBe(t('bucket.waiting'))
  })

  it('says a department is on hold when a concern blocks it', async () => {
    buckets({ canSeeAll: true, change: change({ blocked_department_ids: [2] }) })
    expect((await screen.findByTestId('bucket-state-2')).textContent).toBe(t('concern.onHold'))
  })

  it('shows the verdict once submitted and keeps the answer readable', async () => {
    buckets({ canSeeAll: true, change: change({ assessments: [assessment({
      verdict: 'feasible_with_conditions', status: 'submitted',
      submitted_at: '2026-08-01T00:00:00', conditions: 'needs a new gauge' })] }) })
    expect((await screen.findByTestId('bucket-state-2')).textContent).toBe(t('bucket.submitted'))
    expect(screen.getByTestId('bucket-verdict-2')).toBeTruthy()
    fireEvent.click(screen.getByTestId('bucket-toggle-2'))
    expect(screen.getByTestId('bucket-answer-2').textContent).toContain('needs a new gauge')
  })

  it('opens a member’s own row on its objects and form, unasked', async () => {
    // A member came here to do their department's work — it should be in front
    // of them, not one click away.
    buckets({ myDepartmentIds: [2] })
    await waitFor(() => expect(screen.getByText('20-3450-001-0')).toBeTruthy())
    // Objects are grouped by kind, with the via-part reference kept.
    expect(screen.getByText(t('objtype.gauge'))).toBeTruthy()
    expect(screen.getByText(/via part #11/)).toBeTruthy()
    expect(screen.getByTestId('assessment-submit')).toBeTruthy()
  })

  it('gives an ordinary member their own bucket and one line for the rest', async () => {
    buckets({ myDepartmentIds: [4] })
    // Their own bucket, already open. Another department's work is not theirs to
    // read — it is not even on the page.
    expect(await screen.findByTestId('bucket-4')).toBeTruthy()
    expect(screen.getByTestId('bucket-readonly-4')).toBeTruthy()
    expect(screen.queryByTestId('bucket-2')).toBeNull()
    expect(screen.queryByText('20-3450-001-0')).toBeNull()
    // But they still learn whether the change is moving, and who it sits with.
    expect(screen.getByTestId('bucket-progress').textContent).toBe(
      t('bucket.progress').replace('{n}', '0').replace('{m}', '1')
        .replace('{x}', 'Development'))
  })

  it('leaves a viewer with no department the progress line alone', async () => {
    buckets({ myDepartmentIds: [] })
    expect(await screen.findByTestId('bucket-progress')).toBeTruthy()
    expect(screen.queryByTestId('bucket-2')).toBeNull()
    expect(screen.queryByTestId('bucket-4')).toBeNull()
  })

  it('keeps the whole board for PM, Sales, the lead and admin', async () => {
    buckets({ myDepartmentIds: [4], canSeeAll: true })
    expect(await screen.findByTestId('bucket-4')).toBeTruthy()
    expect(screen.getByTestId('bucket-2')).toBeTruthy()
    // The board is the summary; a progress line would only repeat it.
    expect(screen.queryByTestId('bucket-progress')).toBeNull()
  })

  it('summarises the rest as done once everyone has answered', async () => {
    buckets({ myDepartmentIds: [4], change: change({ assessments: [
      assessment({ id: 1, department_id: 2, status: 'submitted', verdict: 'feasible',
        submitted_at: '2026-08-01T00:00:00' })] }) })
    expect((await screen.findByTestId('bucket-progress')).textContent).toBe(
      t('bucket.progressDone').replace('{n}', '1').replace('{m}', '1'))
  })

  it('lets PM, Sales, the lead and admin read any bucket', async () => {
    buckets({ myDepartmentIds: [4], canSeeAll: true })
    const toggle = await screen.findByTestId('bucket-toggle-2') as HTMLButtonElement
    expect(toggle.disabled).toBe(false)
    fireEvent.click(toggle)
    await waitFor(() => expect(screen.getByText('20-3450-001-0')).toBeTruthy())
    // Read-only: the overview never becomes an edit right.
    expect(screen.queryByTestId('assessment-submit')).toBeNull()
    expect(screen.getByTestId('bucket-readonly-2').textContent).toBe(t('bucket.readOnly'))
  })

  it('says so plainly when a department has nothing linked to look at', async () => {
    buckets({ myDepartmentIds: [4] })
    expect(await screen.findByText(t('bucket.noObjects'))).toBeTruthy()
  })

  it('asks nothing about cost — that belongs to costing', async () => {
    buckets({ myDepartmentIds: [2] })
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
    await screen.findByTestId('bucket-6')
    expect(screen.getByText(t('pkg.impacted'))).toBeTruthy()
    // The detail only exists once the answer is yes.
    expect(screen.queryByTestId('pkg-detail')).toBeNull()
    fireEvent.click(screen.getByTestId('pkg-impacted-yes'))
    expect(screen.getByTestId('pkg-detail')).toBeTruthy()
    expect(screen.getByTestId('pkg-layout_change')).toBeTruthy()
  })

  it('submits a not-impacted answer in one step', async () => {
    packaging()
    await screen.findByTestId('bucket-6')
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
    await screen.findByTestId('bucket-6')
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

describe('AssessmentBuckets checklist', () => {
  // Whatever the endpoint serves is what renders — the list grows backend-side.
  const CHECKLIST = [
    { key: 'cycle_time_change', label_de: 'Zykluszeit-Änderung nötig',
      label_en: 'Cycle time change', extra: false },
    { key: 'sparepart_required', label_de: 'Ersatzteil erforderlich',
      label_en: 'Spare part required', extra: false },
    { key: 'prototyping_required', label_de: 'Prototypen/Musterbau erforderlich',
      label_en: 'Prototyping required', extra: false },
    { key: 'matching_required', label_de: 'Abmusterung/Matching erforderlich',
      label_en: 'Matching/sampling required', extra: false },
    { key: 'modification_internal', label_de: 'Interne Änderung/Umbau',
      label_en: 'Internal modification', extra: false },
    { key: 'modification_external', label_de: 'Externe Änderung/Umbau (Lieferant)',
      label_en: 'External modification (supplier)', extra: false },
    { key: 'article_design_update', label_de: 'Artikeldesign-Änderung',
      label_en: 'Article design update', extra: true,
      choices: ['internal', 'customer_given'] },
  ]

  beforeEach(() => {
    vi.mocked(changesApi.getRouting).mockResolvedValue({
      change_id: 7, template_id: 1, template_version: 1, has_deviation: false,
      deviation_status: 'none',
      stages: [{ stage_order: 1, departments: [
        { department_id: 2, rasic_letter: 'R', tier: 'blocking', status: 'active', verdict: 'pending' },
      ] }],
    } as never)
    vi.mocked(changesApi.assessmentObjects).mockResolvedValue({ departments: [] } as never)
    vi.mocked(changesApi.assessmentChecklist).mockResolvedValue(CHECKLIST as never)
    vi.mocked(changesApi.submitAssessment).mockClear()
  })
  afterEach(cleanup)

  const open2 = async () => {
    buckets({ myDepartmentIds: [2] })
    return screen.findByTestId('check-cycle_time_change')
  }

  it('asks the backend’s questions, whatever they are, and sends keyed answers', async () => {
    await open2()
    // Every served item renders — the list is the backend's business, not ours.
    CHECKLIST.forEach((i) => expect(screen.getByTestId(`check-${i.key}`)).toBeTruthy())
    expect(screen.queryByTestId('check-remark-cycle_time_change')).toBeNull()
    fireEvent.click(screen.getByTestId('check-cycle_time_change'))
    fireEvent.change(screen.getByTestId('check-remark-cycle_time_change'),
      { target: { value: '+2s per part' } })
    fireEvent.change(screen.getByLabelText(/Verdict|Bewertung/i), { target: { value: 'feasible' } })
    fireEvent.click(screen.getByTestId('assessment-submit'))
    await waitFor(() => expect(changesApi.submitAssessment).toHaveBeenCalledWith(7,
      expect.objectContaining({
        details: { impacts: [
          { key: 'cycle_time_change', impacted: true, remark: '+2s per part' },
        ] },
      })))
  })

  it('asks for the RFQ where supplier work was ticked, and files it there', async () => {
    buckets({ myDepartmentIds: [2], change: change({
      assessments: [assessment({ id: 1, department_id: 2 })], attachments: [] }) })
    await screen.findByTestId('check-modification_external')
    // Nothing asked until the box is ticked.
    expect(screen.queryByTestId('check-rfq-modification_external')).toBeNull()
    fireEvent.click(screen.getByTestId('check-modification_external'))
    const slot = screen.getByTestId('check-rfq-modification_external')
    expect(slot).toBeTruthy()
    // A hint, not a gate: a feasible verdict still submits without the RFQ.
    expect(screen.getByTestId('check-rfq-missing')).toBeTruthy()
    fireEvent.change(screen.getByLabelText(/Verdict|Bewertung/i), { target: { value: 'feasible' } })
    expect((screen.getByTestId('assessment-submit') as HTMLButtonElement).disabled).toBe(false)
    const zone = screen.getAllByTestId('dropzone')
      .find((z) => z.getAttribute('data-kind') === 'rfq')
    expect(zone?.getAttribute('data-assessment')).toBe('1')
    // Internal modification is tickable on its own and asks for nothing.
    fireEvent.click(screen.getByTestId('check-modification_internal'))
    expect(screen.queryByTestId('check-rfq-modification_internal')).toBeNull()
  })

  it('shows an RFQ already on file under its row', async () => {
    buckets({ myDepartmentIds: [2], change: change({
      assessments: [assessment({ id: 1, department_id: 2 })],
      attachments: [{ id: 60, filename: 'rfq-supplier.pdf', content_type: 'application/pdf',
        size_bytes: 10, phase: 'baseline', created_at: '2026-08-01T00:00:00',
        kind: 'rfq', responds_to_id: null, concern_id: null, assessment_id: 1 }] }) })
    fireEvent.click(await screen.findByTestId('check-modification_external'))
    expect(screen.getByTestId('check-rfq-modification_external').textContent)
      .toContain('rfq-supplier.pdf')
    expect(screen.queryByTestId('check-rfq-missing')).toBeNull()
    // It is an assessment document like any other, so the evidence list has it too.
    expect(screen.getByTestId('bucket-evidence-2').textContent).toContain('rfq-supplier.pdf')
  })

  it('makes a choice-bearing item say which kind it is', async () => {
    await open2()
    fireEvent.click(screen.getByTestId('check-article_design_update'))
    fireEvent.click(screen.getByTestId('check-choice-article_design_update-customer_given'))
    fireEvent.change(screen.getByLabelText(/Verdict|Bewertung/i), { target: { value: 'feasible' } })
    fireEvent.click(screen.getByTestId('assessment-submit'))
    await waitFor(() => expect(changesApi.submitAssessment).toHaveBeenCalledWith(7,
      expect.objectContaining({
        details: { impacts: [
          { key: 'article_design_update', impacted: true, choice: 'customer_given' },
        ] },
      })))
  })

  it('takes a free line the checklist does not cover', async () => {
    await open2()
    fireEvent.click(screen.getByTestId('check-add-item'))
    fireEvent.blur(screen.getByTestId('check-free-input-0'),
      { target: { value: 'operator training' } })
    fireEvent.change(screen.getByLabelText(/Verdict|Bewertung/i), { target: { value: 'feasible' } })
    fireEvent.click(screen.getByTestId('assessment-submit'))
    await waitFor(() => expect(changesApi.submitAssessment).toHaveBeenCalledWith(7,
      expect.objectContaining({
        details: { impacts: [{ label: 'operator training', impacted: true }] },
      })))
  })

  it('shows answers stored under the old catalog shape without offering to edit them', async () => {
    buckets({ canSeeAll: true, change: change({ assessments: [assessment({
      status: 'submitted', verdict: 'feasible', submitted_at: '2026-08-01T00:00:00',
      details: { impacts: [
        { activity_id: 31, label: 'Tool rework', impacted: true, remark: 'insert' },
      ] },
    })] }) })
    // Counted and listed, but no checkbox to change history with.
    expect((await screen.findByTestId('bucket-areas-2')).textContent)
      .toBe(t('check.impactedOne'))
    fireEvent.click(screen.getByTestId('bucket-toggle-2'))
    expect(screen.getByTestId('bucket-impacts-2').textContent).toContain('Tool rework — insert')
  })

  it('counts the impacted areas on the collapsed row once submitted', async () => {
    buckets({ canSeeAll: true, change: change({ assessments: [assessment({
      status: 'submitted', verdict: 'feasible', submitted_at: '2026-08-01T00:00:00',
      details: { impacts: [
        { key: 'cycle_time_change', impacted: true, remark: '+2s' },
        { key: 'sparepart_required', impacted: true },
        { key: 'visual_risk', impacted: false },
      ] },
    })] }) })
    expect((await screen.findByTestId('bucket-areas-2')).textContent)
      .toBe(t('check.impactedCount').replace('{n}', '2'))
  })
})

describe('AssessmentBuckets not-feasible needs its explanation', () => {
  beforeEach(() => {
    vi.mocked(changesApi.getRouting).mockResolvedValue({
      change_id: 7, template_id: 1, template_version: 1, has_deviation: false,
      deviation_status: 'none',
      stages: [{ stage_order: 1, departments: [
        { department_id: 2, rasic_letter: 'R', tier: 'blocking', status: 'active', verdict: 'pending' },
      ] }],
    } as never)
    vi.mocked(changesApi.assessmentObjects).mockResolvedValue({ departments: [] } as never)
    vi.mocked(changesApi.assessmentChecklist).mockResolvedValue([] as never)
    vi.mocked(changesApi.submitAssessment).mockClear()
  })
  afterEach(cleanup)

  const changePpt = {
    id: 50, filename: 'why-not.pptx', content_type: 'application/vnd.ms-powerpoint',
    size_bytes: 10, phase: 'baseline', created_at: '2026-08-01T00:00:00',
    kind: 'change_ppt', responds_to_id: null, concern_id: null, assessment_id: 1,
  }

  it('gates the submit until the change PPT is attached', async () => {
    buckets({ myDepartmentIds: [2], change: change({
      assessments: [assessment({ id: 1, department_id: 2 })], attachments: [] }) })
    await screen.findByTestId('bucket-2')
    fireEvent.change(screen.getByLabelText(/Verdict|Bewertung/i),
      { target: { value: 'not_feasible' } })
    // The document block says what is owed, and the submit waits for it.
    expect(screen.getByTestId('bucket-evidence-required-2').textContent)
      .toBe(t('check.changePptRequired'))
    expect(screen.getByTestId('assessment-evidence-required')).toBeTruthy()
    expect((screen.getByTestId('assessment-submit') as HTMLButtonElement).disabled).toBe(true)
  })

  it('is not satisfied by just any document on the assessment', async () => {
    // The rule is the deck, not a file count: an RFQ is not an explanation.
    buckets({ myDepartmentIds: [2], change: change({
      assessments: [assessment({ id: 1, department_id: 2 })],
      attachments: [{ ...changePpt, id: 51, filename: 'rfq.pdf', kind: 'rfq' }] }) })
    await screen.findByTestId('bucket-2')
    fireEvent.change(screen.getByLabelText(/Verdict|Bewertung/i),
      { target: { value: 'not_feasible' } })
    expect(screen.getByTestId('bucket-evidence-required-2')).toBeTruthy()
    expect((screen.getByTestId('assessment-submit') as HTMLButtonElement).disabled).toBe(true)
  })

  it('lets it through once the change PPT is on the assessment', async () => {
    buckets({ myDepartmentIds: [2], change: change({
      assessments: [assessment({ id: 1, department_id: 2 })], attachments: [changePpt] }) })
    await screen.findByTestId('bucket-2')
    fireEvent.change(screen.getByLabelText(/Verdict|Bewertung/i),
      { target: { value: 'not_feasible' } })
    expect(screen.queryByTestId('bucket-evidence-required-2')).toBeNull()
    expect((screen.getByTestId('assessment-submit') as HTMLButtonElement).disabled).toBe(false)
  })

  it('takes the backend’s word for it when the deck is not in the list', async () => {
    // The serialised row knows; the page's attachment list may not carry it.
    buckets({ myDepartmentIds: [2], change: change({
      assessments: [assessment({ id: 1, department_id: 2, has_change_ppt: true })],
      attachments: [] }) })
    await screen.findByTestId('bucket-2')
    fireEvent.change(screen.getByLabelText(/Verdict|Bewertung/i),
      { target: { value: 'not_feasible' } })
    expect(screen.queryByTestId('bucket-evidence-required-2')).toBeNull()
    expect((screen.getByTestId('assessment-submit') as HTMLButtonElement).disabled).toBe(false)
  })

  it('files the bucket’s slot as the change PPT, labelled as internal', async () => {
    buckets({ myDepartmentIds: [2], change: change({
      assessments: [assessment({ id: 1, department_id: 2 })], attachments: [] }) })
    await screen.findByTestId('bucket-2')
    expect(screen.getByText(t('bucket.changePpt'))).toBeTruthy()
    const zone = screen.getAllByTestId('dropzone')
      .find((z) => z.getAttribute('data-kind') === 'change_ppt')
    expect(zone?.getAttribute('data-assessment')).toBe('1')
  })

  it('asks nothing extra of a feasible verdict', async () => {
    buckets({ myDepartmentIds: [2], change: change({
      assessments: [assessment({ id: 1, department_id: 2 })], attachments: [] }) })
    await screen.findByTestId('bucket-2')
    fireEvent.change(screen.getByLabelText(/Verdict|Bewertung/i), { target: { value: 'feasible' } })
    expect(screen.queryByTestId('assessment-evidence-required')).toBeNull()
    expect((screen.getByTestId('assessment-submit') as HTMLButtonElement).disabled).toBe(false)
  })
})

describe('AssessmentBuckets with a re-routed history', () => {
  beforeEach(() => {
    // The department appears twice: the live row from the current template and
    // a leftover from the one it replaced.
    vi.mocked(changesApi.getRouting).mockResolvedValue({
      change_id: 7, template_id: 2, template_version: 2, has_deviation: false,
      deviation_status: 'none',
      stages: [{ stage_order: 1, departments: [
        { department_id: 4, rasic_letter: 'R', tier: 'blocking', status: 'active', verdict: 'pending' },
      ] }],
    } as never)
    vi.mocked(changesApi.assessmentObjects).mockResolvedValue({ departments: [] } as never)
  })
  afterEach(cleanup)

  const twoRows = () => change({ assessments: [
    assessment({ id: 9, department_id: 4, rasic_letter: 'C', stage_order: 2,
      status: 'pending', verdict: 'pending' }),
    assessment({ id: 8, department_id: 4, rasic_letter: 'R', stage_order: 1,
      status: 'active', verdict: 'pending' }),
  ] })

  it('gives the department one bucket, bound to the row it can actually work', async () => {
    buckets({ myDepartmentIds: [4], change: twoRows() })
    // One bucket, not two.
    expect(await screen.findByTestId('bucket-4')).toBeTruthy()
    expect(screen.getAllByTestId(/^bucket-\d+$/)).toHaveLength(1)
    // The live R row, not the stale C leftover.
    expect(screen.getByTestId('bucket-toggle-4').textContent).toContain('R')
    expect(screen.getByTestId('bucket-stale-4').textContent).toBe('+1')
    // And the member gets their entry mask.
    await waitFor(() => expect(screen.getByTestId('assessment-submit')).toBeTruthy())
  })

  it('falls back to the earliest pending row when none is active', async () => {
    buckets({ myDepartmentIds: [4], change: change({ assessments: [
      assessment({ id: 9, department_id: 4, rasic_letter: 'C', stage_order: 2,
        status: 'pending', verdict: 'pending' }),
      assessment({ id: 8, department_id: 4, rasic_letter: 'S', stage_order: 1,
        status: 'pending', verdict: 'pending' }),
    ] }) })
    expect((await screen.findByTestId('bucket-toggle-4')).textContent).toContain('S')
  })

  it('keeps a submitted answer visible when every row is done', async () => {
    buckets({ canSeeAll: true, change: change({ assessments: [
      assessment({ id: 8, department_id: 4, rasic_letter: 'R', stage_order: 1,
        status: 'submitted', verdict: 'feasible', submitted_at: '2026-08-01T00:00:00' }),
      assessment({ id: 9, department_id: 4, rasic_letter: 'C', stage_order: 2,
        status: 'waived', verdict: 'pending' }),
    ] }) })
    expect((await screen.findByTestId('bucket-state-4')).textContent).toBe(t('bucket.submitted'))
  })
})

describe('AssessmentBuckets evidence', () => {
  const evidence = (over: Record<string, unknown> = {}) => ({
    id: 50, filename: 'measurement.pdf', content_type: 'application/pdf',
    size_bytes: 10, phase: 'baseline', created_at: '2026-08-01T00:00:00',
    kind: 'general', responds_to_id: null, concern_id: null, assessment_id: 1, ...over,
  })

  beforeEach(() => {
    vi.mocked(changesApi.getRouting).mockResolvedValue({
      change_id: 7, template_id: 1, template_version: 1, has_deviation: false,
      deviation_status: 'none',
      stages: [{ stage_order: 1, departments: [
        { department_id: 2, rasic_letter: 'R', tier: 'blocking', status: 'active', verdict: 'pending' },
        { department_id: 4, rasic_letter: 'S', tier: 'optional', status: 'active', verdict: 'pending' },
      ] }],
    } as never)
    vi.mocked(changesApi.assessmentObjects).mockResolvedValue({ departments: [] } as never)
  })
  afterEach(cleanup)

  const withEvidence = () => change({
    assessments: [assessment({ id: 1, department_id: 2 }),
      assessment({ id: 2, department_id: 4 })],
    attachments: [evidence({ id: 50, assessment_id: 1 }),
      evidence({ id: 51, filename: 'other-dept.pdf', assessment_id: 2 })],
  })

  it('shows a department its own evidence and nobody else’s', async () => {
    buckets({ myDepartmentIds: [2], change: withEvidence() })
    expect((await screen.findByTestId('bucket-evidence-count-2')).textContent).toContain('1')
    const block = screen.getByTestId('bucket-evidence-2')
    expect(block.textContent).toContain('measurement.pdf')
    expect(block.textContent).not.toContain('other-dept.pdf')
    expect(screen.getByRole('link', { name: 'measurement.pdf' })).toBeTruthy()
  })

  it('files an upload against that department’s assessment', async () => {
    buckets({ myDepartmentIds: [2], change: withEvidence() })
    await screen.findByTestId('bucket-2')
    expect(screen.getByTestId('dropzone').getAttribute('data-assessment')).toBe('1')
  })

  it('lets a privileged reader see evidence without an upload slot', async () => {
    buckets({ canSeeAll: true, change: withEvidence() })
    fireEvent.click(await screen.findByTestId('bucket-toggle-2'))
    expect(screen.getByTestId('bucket-evidence-2').textContent).toContain('measurement.pdf')
    expect(screen.queryByTestId('dropzone')).toBeNull()
  })
})
