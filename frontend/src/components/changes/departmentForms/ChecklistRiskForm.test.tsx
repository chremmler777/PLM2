import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, fireEvent, cleanup, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import ChecklistRiskForm from './ChecklistRiskForm'

const raiseConcern = vi.fn().mockResolvedValue({ id: 1 })
vi.mock('../../../api/changes', () => ({
  changesApi: {
    riskTypes: vi.fn(() => Promise.resolve({ items: [
      { key: 'timing', label_en: 'Timing' }, { key: 'd4_cooling', label_en: 'Cooling' }] })),
    raiseConcern: (...a: unknown[]) => raiseConcern(...a),
  },
}))
const wrap = (ui: React.ReactElement) => (
  <QueryClientProvider client={new QueryClient()}>{ui}</QueryClientProvider>
)

describe('ChecklistRiskForm', () => {
  afterEach(cleanup)

  it('is pre-filled from the row and posts its checklist key', async () => {
    const onDone = vi.fn()
    render(wrap(<ChecklistRiskForm changeId={5} departmentId={4}
      checklistKey="threed_change" defaultNote="3D change necessary — gate moves"
      onDone={onDone} />))
    expect((screen.getByTestId('check-risk-note') as HTMLTextAreaElement).value)
      .toBe('3D change necessary — gate moves')
    const submit = screen.getByTestId('check-risk-submit') as HTMLButtonElement
    expect(submit.disabled).toBe(true)                  // type is a deliberate pick
    await screen.findByRole('option', { name: 'Cooling' })
    fireEvent.change(screen.getByTestId('check-risk-type'), { target: { value: 'd4_cooling' } })
    fireEvent.click(screen.getByTestId('check-risk-sev-3'))
    fireEvent.click(submit)
    await waitFor(() => expect(raiseConcern).toHaveBeenCalledWith(5, {
      kind: 'risk', note: '3D change necessary — gate moves', department_id: 4,
      risk_type: 'd4_cooling', severity: 3, checklist_key: 'threed_change' }))
    await waitFor(() => expect(onDone).toHaveBeenCalled())
  })

  it('shows a refusal in place and keeps the note', async () => {
    raiseConcern.mockRejectedValueOnce({ response: { data: { detail: 'nope' } } })
    render(wrap(<ChecklistRiskForm changeId={5} departmentId={4}
      checklistKey="threed_change" defaultNote="x" onDone={() => {}} />))
    await screen.findByRole('option', { name: 'Timing' })
    fireEvent.change(screen.getByTestId('check-risk-type'), { target: { value: 'timing' } })
    fireEvent.click(screen.getByTestId('check-risk-submit'))
    expect((await screen.findByRole('alert')).textContent).toContain('nope')
    expect((screen.getByTestId('check-risk-note') as HTMLTextAreaElement).value).toBe('x')
  })
})
