import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, cleanup, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import AssessmentSubmitForm from './AssessmentSubmitForm'

const submitAssessment = vi.fn().mockResolvedValue({})
const DEFS = [
  { key: 'cycle_time_change', label_de: 'Z', label_en: 'Cycle time change', extra: false },
  { key: 'threed_change', label_de: '3D', label_en: '3D change necessary', extra: false },
]
const assessmentChecklist = vi.fn(() => Promise.resolve(DEFS))
vi.mock('../../api/changes', () => ({
  changesApi: {
    submitAssessment: (...a: unknown[]) => submitAssessment(...a),
    assessmentChecklist: () => assessmentChecklist(),
    listConcerns: vi.fn().mockResolvedValue([]),
  },
}))

const wrap = (ui: React.ReactElement) => (
  <QueryClientProvider client={new QueryClient()}>{ui}</QueryClientProvider>
)

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
    fireEvent.click(screen.getByRole('button', { name: /submit assessment/i }))
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
    expect(screen.getByTestId('check-open-jump').textContent).toContain('1 rows unanswered')
    fireEvent.click(screen.getByTestId('check-yes-threed_change'))
    expect(submitBtn().disabled).toBe(false)
    fireEvent.click(submitBtn())
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
