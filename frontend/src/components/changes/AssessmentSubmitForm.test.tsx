import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, cleanup, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import AssessmentSubmitForm from './AssessmentSubmitForm'

const submitAssessment = vi.fn().mockResolvedValue({})
vi.mock('../../api/changes', () => ({
  changesApi: { submitAssessment: (...a: unknown[]) => submitAssessment(...a) },
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
    fireEvent.click(screen.getByRole('button', { name: /submit assessment/i }))
    await waitFor(() => expect(submitAssessment).toHaveBeenCalledWith(7,
      expect.objectContaining({ department_id: 2, verdict: 'feasible', effort_hours: 3.5 })))
  })
})
