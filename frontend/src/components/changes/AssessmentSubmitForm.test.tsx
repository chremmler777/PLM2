import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, cleanup, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import AssessmentSubmitForm, { draftKey } from './AssessmentSubmitForm'
import BucketErrorBoundary from './BucketErrorBoundary'
import { t } from '../../i18n/cmLabels'

const submitAssessment = vi.fn().mockResolvedValue({})
const saveAssessmentDraft = vi.fn().mockResolvedValue({})
const DEFS = [
  { key: 'cycle_time_change', label_de: 'Z', label_en: 'Cycle time change', extra: false },
  { key: 'threed_change', label_de: '3D', label_en: '3D change necessary', extra: false },
]
const assessmentChecklist = vi.fn(() => Promise.resolve(DEFS))
vi.mock('../../api/changes', () => ({
  changesApi: {
    submitAssessment: (...a: unknown[]) => submitAssessment(...a),
    saveAssessmentDraft: (...a: unknown[]) => saveAssessmentDraft(...a),
    uploadAttachment: vi.fn(),
    assessmentChecklist: () => assessmentChecklist(),
    listConcerns: vi.fn().mockResolvedValue([]),
  },
}))

const wrap = (ui: React.ReactElement) => (
  <QueryClientProvider client={new QueryClient()}>{ui}</QueryClientProvider>
)

// Drafts autosave to localStorage: every test starts without one.
afterEach(() => { window.localStorage.clear() })

describe('AssessmentSubmitForm', () => {
  afterEach(cleanup)

  it('requires effort hours before submitting', async () => {
    render(wrap(<AssessmentSubmitForm changeId={7} departmentId={2}
      departmentName="Quality" onDone={() => {}} />))
    fireEvent.change(screen.getByLabelText(/verdict/i), { target: { value: 'feasible' } })
    expect((screen.getByRole('button', { name: /submit assessment/i }) as HTMLButtonElement).disabled).toBeTruthy()
    fireEvent.change(screen.getByLabelText(/effort/i), { target: { value: '3.5' } })
    fireEvent.click(await screen.findByTestId('check-no-cycle_time_change'))
    fireEvent.click(screen.getByTestId('check-no-threed_change'))
    fireEvent.click(screen.getByRole('button', { name: /submit assessment/i })); fireEvent.click(screen.getByTestId('confirm-go'))
    await waitFor(() => expect(submitAssessment).toHaveBeenCalledWith(7,
      expect.objectContaining({ department_id: 2, verdict: 'feasible', effort_hours: 3.5 })))
  })
})

describe('AssessmentSubmitForm checklist gate', () => {
  afterEach(cleanup)
  const form = () => render(wrap(<AssessmentSubmitForm changeId={7} departmentId={2}
    departmentName="Quality" showEffort={false} onDone={() => {}} />))
  const submitBtn = () => screen.getByTestId('assessment-submit') as HTMLButtonElement

  it('counts answers and holds submit until every row is answered', async () => {
    form()
    fireEvent.change(screen.getByLabelText(/verdict/i), { target: { value: 'feasible' } })
    expect((await screen.findByTestId('check-progress')).textContent).toContain('0 of 2')
    expect(submitBtn().disabled).toBe(true)
    fireEvent.click(screen.getByTestId('check-no-cycle_time_change'))
    expect(screen.getByTestId('check-progress').textContent).toContain('1 of 2')
    expect(screen.getByTestId('check-open-jump').textContent).toContain('1 row unanswered')
    fireEvent.click(screen.getByTestId('check-yes-threed_change'))
    expect(submitBtn().disabled).toBe(false)
    fireEvent.click(submitBtn()); fireEvent.click(screen.getByTestId('confirm-go'))
    await waitFor(() => expect(submitAssessment).toHaveBeenLastCalledWith(7, expect.objectContaining({
      details: { impacts: expect.arrayContaining([
        { key: 'cycle_time_change', answer: 'no', impacted: false },
        expect.objectContaining({ key: 'threed_change', answer: 'yes', impacted: true }),
      ]) } })))
  })

  it('jumps to the first open row and highlights the open ones', async () => {
    const scroll = vi.fn()
    Element.prototype.scrollIntoView = scroll
    form()
    fireEvent.click(await screen.findByTestId('check-no-cycle_time_change'))
    fireEvent.click(screen.getByTestId('check-open-jump'))
    expect(scroll).toHaveBeenCalled()
    expect(document.getElementById('check-row-threed_change')?.className).toContain('border-amber-500')
  })

  it('re-opens an empty checklist gate when Packaging flips back to impacted', async () => {
    render(wrap(<AssessmentSubmitForm changeId={7} departmentId={6}
      departmentName="Packaging Engineer" showEffort={false} onDone={() => {}} />))
    fireEvent.click(await screen.findByTestId('pkg-impacted-yes'))
    fireEvent.click(await screen.findByTestId('check-no-cycle_time_change'))
    fireEvent.click(screen.getByTestId('pkg-impacted-no'))
    expect(submitBtn().disabled).toBe(false)            // not impacted is a full answer
    expect(screen.queryByTestId('check-progress')).toBeNull()
    fireEvent.click(screen.getByTestId('pkg-impacted-yes'))
    expect((await screen.findByTestId('check-progress')).textContent).toContain('0 of 2')
    fireEvent.change(screen.getByLabelText(/verdict/i), { target: { value: 'feasible' } })
    expect(submitBtn().disabled).toBe(true)
  })
})

describe('Packaging: only visible questions count', () => {
  afterEach(cleanup)

  it('counts the one open first question, not the hidden checklist rows', async () => {
    render(wrap(<AssessmentSubmitForm changeId={7} departmentId={6}
      departmentName="Packaging Engineer" showEffort={false} onDone={() => {}} />))
    await waitFor(() => expect(assessmentChecklist).toHaveBeenCalled())
    await screen.findByTestId('questionnaire-first')
    expect(screen.getByTestId('check-open-jump').textContent).toBe(t('check.openQuestionsOne'))
    fireEvent.click(screen.getByTestId('pkg-impacted-no'))
    expect(screen.queryByTestId('check-open-jump')).toBeNull()
  })
})

describe('AssessmentSubmitForm without a loaded checklist', () => {
  afterEach(cleanup)

  it('holds the submit when the checklist could not be loaded', async () => {
    assessmentChecklist.mockImplementationOnce(() => Promise.reject(new Error('500')))
    render(wrap(<AssessmentSubmitForm changeId={7} departmentId={2}
      departmentName="Quality" showEffort={false} onDone={() => {}} />))
    fireEvent.change(screen.getByLabelText(/verdict/i), { target: { value: 'feasible' } })
    await waitFor(() => expect(assessmentChecklist).toHaveBeenCalled())
    await new Promise((r) => setTimeout(r, 20))
    expect((screen.getByTestId('assessment-submit') as HTMLButtonElement).disabled).toBe(true)
  })
})

describe('AssessmentSubmitForm Rest → No', () => {
  afterEach(cleanup)

  it('fills only the unanswered rows with No and marks them', async () => {
    submitAssessment.mockClear()
    render(wrap(<AssessmentSubmitForm changeId={7} departmentId={2}
      departmentName="Quality" showEffort={false} onDone={() => {}} />))
    fireEvent.click(await screen.findByTestId('check-yes-threed_change'))
    fireEvent.click(screen.getByTestId('check-rest-no'))
    expect(screen.getByTestId('check-progress').textContent).toContain('2 of 2')
    expect(screen.getByTestId('check-yes-threed_change').getAttribute('aria-pressed')).toBe('true')
    expect(screen.queryByTestId('check-rest-no')).toBeNull()       // nothing left to fill
    fireEvent.change(screen.getByLabelText(/verdict/i), { target: { value: 'feasible' } })
    fireEvent.click(screen.getByTestId('assessment-submit')); fireEvent.click(screen.getByTestId('confirm-go'))
    await waitFor(() => expect(submitAssessment).toHaveBeenLastCalledWith(7, expect.objectContaining({
      details: { impacts: expect.arrayContaining([
        { key: 'cycle_time_change', answer: 'no', impacted: false, bulk: true },
        expect.objectContaining({ key: 'threed_change', answer: 'yes', impacted: true }),
      ]) } })))
    const three = submitAssessment.mock.lastCall![1].details.impacts
      .find((i: { key: string }) => i.key === 'threed_change')
    expect(three.bulk).toBeUndefined()
  })
})

describe('AssessmentSubmitForm drafts and confirm (spec §16)', () => {
  afterEach(cleanup)
  const form = (extra: Record<string, unknown> = {}) => render(wrap(<AssessmentSubmitForm changeId={7}
    departmentId={2} departmentName="Quality" showEffort={false} onDone={() => {}} {...extra} />))

  it('keeps every answer as a local draft and restores it on the next load', async () => {
    form()
    fireEvent.click(await screen.findByTestId('check-yes-threed_change'))
    fireEvent.change(screen.getByLabelText(/verdict/i), { target: { value: 'feasible_with_conditions' } })
    const saved = JSON.parse(window.localStorage.getItem(draftKey(7, 2))!)
    expect(saved.verdict).toBe('feasible_with_conditions')
    expect(saved.details.impacts[0]).toMatchObject({ key: 'threed_change', answer: 'yes' })
    expect(screen.getByTestId('assessment-draft-state')).toBeTruthy()
    cleanup()
    form()
    expect((await screen.findByTestId('check-yes-threed_change')).getAttribute('aria-pressed')).toBe('true')
    expect((screen.getByLabelText(/verdict/i) as HTMLSelectElement).value).toBe('feasible_with_conditions')
  })

  it('saves the draft on the server after a pause', async () => {
    saveAssessmentDraft.mockClear()
    form({ assessmentId: 31 })
    fireEvent.click(await screen.findByTestId('check-no-threed_change'))
    await waitFor(() => expect(saveAssessmentDraft).toHaveBeenCalledWith(7, 31, expect.objectContaining({
      details: { impacts: [{ key: 'threed_change', answer: 'no', impacted: false }] } })), { timeout: 2000 })
  })

  it('restores the server draft when this browser has none', async () => {
    form({ serverDraft: { draft: { data: { details: { impacts: [
      { key: 'cycle_time_change', answer: 'no', impacted: false }] }, verdict: 'feasible' } } } })
    expect((await screen.findByTestId('check-no-cycle_time_change')).getAttribute('aria-pressed')).toBe('true')
    // Says where the draft came from, not "kept in this browser".
    expect(screen.getByTestId('assessment-draft-state').textContent).toBe(t('assessment.draftRestored'))
  })

  it('names verdicts in words, asks before sending and clears the draft after', async () => {
    submitAssessment.mockClear()
    form()
    const select = screen.getByLabelText(/verdict/i) as HTMLSelectElement
    expect([...select.options].map((o) => o.text)).toEqual(
      ['Pick a verdict', 'Feasible', 'Feasible with conditions', 'Not feasible'])
    fireEvent.click(await screen.findByTestId('check-yes-threed_change'))
    fireEvent.click(screen.getByTestId('check-no-cycle_time_change'))
    fireEvent.change(select, { target: { value: 'feasible' } })
    fireEvent.click(screen.getByTestId('assessment-submit'))
    expect(submitAssessment).not.toHaveBeenCalled()
    expect(screen.getByTestId('confirm-info').textContent).toContain('Verdict: Feasible')
    expect(screen.getByTestId('confirm-info').textContent).toContain('1 area impacted')
    fireEvent.click(screen.getByTestId('confirm-go'))
    await waitFor(() => expect(submitAssessment).toHaveBeenCalled())
    await waitFor(() => expect(window.localStorage.getItem(draftKey(7, 2))).toBeNull())
  })

  it('puts the change PPT drop zone right above Submit for a not-feasible verdict', async () => {
    form({ assessmentId: 31 })
    fireEvent.change(screen.getByLabelText(/verdict/i), { target: { value: 'not_feasible' } })
    const box = await screen.findByTestId('assessment-evidence-required')
    expect(box.textContent).toContain(t('bucket.changePptSlot'))
    const submit = screen.getByTestId('assessment-submit')
    expect(box.compareDocumentPosition(submit) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  })
})

describe('BucketErrorBoundary', () => {
  afterEach(cleanup)
  it('contains a crashing bucket and offers a retry', () => {
    const spy = vi.spyOn(console, 'error').mockImplementation(() => {})
    const Boom = () => { throw new Error('bad shape') }
    render(<div><BucketErrorBoundary name="Development"><Boom /></BucketErrorBoundary><p>other bucket</p></div>)
    expect(screen.getByTestId('bucket-error').textContent).toContain('Development')
    expect(screen.getByText('other bucket')).toBeTruthy()
    expect(screen.getByTestId('bucket-error-retry')).toBeTruthy()
    spy.mockRestore()
  })
})
