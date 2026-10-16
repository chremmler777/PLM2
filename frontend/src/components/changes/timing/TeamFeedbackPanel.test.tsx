/** A5-03: a department with no member here is confirmed by the lead or PM. */
import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, cleanup } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import TeamFeedbackPanel from './TeamFeedbackPanel'
import type { PlanFeedback } from '../../../types/changePlan'

vi.mock('../../../api/changePlan', () => ({ planApi: { postFeedback: vi.fn() } }))
vi.mock('sonner', () => ({ toast: { error: vi.fn(), success: vi.fn() } }))

const fb = (over: Partial<PlanFeedback['required'][number]> = {}): PlanFeedback => ({
  revision: 1, all_confirmed: false, validated_at: null, validated_by_name: null,
  required: [{ department_id: 3, department_name: 'Scheduling', verdict: null, note: null, by_name: null,
    at: null, stale: false, ...over }],
} as PlanFeedback)
const panel = (f: PlanFeedback, mine: number[] = []) => render(
  <QueryClientProvider client={new QueryClient()}>
    <TeamFeedbackPanel changeId={7} feedback={f} myDepartmentIds={mine} canRespond />
  </QueryClientProvider>)

afterEach(cleanup)

describe('TeamFeedbackPanel fallback', () => {
  it('the lead answers a member-less department and the row says so', () => {
    panel(fb({ no_member: true, can_answer: true, hint: 'Scheduling has no member here: Holmes coordinates' }))
    expect(screen.getByTestId('feedback-hint-3').textContent).toContain('Holmes coordinates')
    expect(screen.getByTestId('feedback-confirm-3')).toBeTruthy()
  })
  it('no button when the backend refuses, even for a member id match', () => {
    panel(fb({ can_answer: false }), [3])
    expect(screen.queryByTestId('feedback-confirm-3')).toBeNull()
  })
})
