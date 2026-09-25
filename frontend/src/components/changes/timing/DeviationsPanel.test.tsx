import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import DeviationsPanel from './DeviationsPanel'
import type { PlanDeviation } from '../../../types/changePlan'
import { planApi } from '../../../api/changePlan'

vi.mock('../../../api/changePlan', () => ({ planApi: { lockDeviation: vi.fn(), escalateDeviation: vi.fn() } }))
vi.mock('sonner', () => ({ toast: { error: vi.fn(), success: vi.fn() } }))

const dev = (over: Partial<PlanDeviation> & { id: number; task_id: number; task_name: string }): PlanDeviation => ({
  old_start: '2026-10-05', old_end: '2026-10-10', new_start: '2026-10-07', new_end: '2026-10-12', slip_days: 2,
  finish_impact_days: 2, reason: 'late', status: 'open', ...over,
})

describe('DeviationsPanel grouped by cause (G18)', () => {
  afterEach(cleanup)
  it('lists each own move followed by the successors it pushed', () => {
    render(<QueryClientProvider client={new QueryClient()}>
      <DeviationsPanel changeId={7} canDecide={false} deviations={[
        dev({ id: 12, task_id: 5, task_name: 'Other own move' }),
        dev({ id: 11, task_id: 3, task_name: 'Sampling', caused_by_task_id: 1, caused_by_task_name: 'Tool rework' }),
        dev({ id: 10, task_id: 1, task_name: 'Tool rework' }),
        dev({ id: 13, task_id: 4, task_name: 'Orphan', caused_by_task_id: 99 }),
      ]} />
    </QueryClientProvider>)
    const rows = screen.getAllByTestId(/^deviation-\d+$/).map((r) => r.getAttribute('data-testid'))
    expect(rows).toEqual(['deviation-12', 'deviation-10', 'deviation-11', 'deviation-13'])
    expect(screen.getByTestId('deviation-11').getAttribute('data-pushed-by')).toBe('10')
    expect(screen.getByTestId('deviation-cause-11').textContent).toBe('pushed by Tool rework')
    expect(screen.queryByTestId('deviation-cause-13')).toBeNull()
  })

  const slip = () => [
    dev({ id: 22, task_id: 3, task_name: 'Sampling', caused_by_task_id: 1, caused_by_task_name: 'Tool rework' }),
    dev({ id: 21, task_id: 2, task_name: 'Measurement', caused_by_task_id: 1, caused_by_task_name: 'Tool rework' }),
    dev({ id: 20, task_id: 1, task_name: 'Tool rework' }),
  ]
  const mount = () => render(<QueryClientProvider client={new QueryClient()}>
    <DeviationsPanel changeId={7} canDecide status="in_implementation" deviations={slip()} />
  </QueryClientProvider>)

  it('one slip is one decision: the move carries Lock and Escalate, the pushed rows none', async () => {
    vi.mocked(planApi.lockDeviation).mockResolvedValue({})
    mount()
    expect(screen.queryByTestId('deviation-lock-21')).toBeNull()
    expect(screen.queryByTestId('deviation-lock-22')).toBeNull()
    expect(screen.getByTestId('deviation-lock-20').textContent).toBe('Lock all 3')
    expect(screen.getByTestId('deviation-group-20').textContent).toBe('moved 2 successors along')
    fireEvent.click(screen.getByTestId('deviation-lock-20'))
    fireEvent.click(screen.getByTestId('deviation-lock-confirm-20'))
    await waitFor(() => expect(planApi.lockDeviation).toHaveBeenCalledTimes(3))
    expect(vi.mocked(planApi.lockDeviation).mock.calls.map((c) => c[1])).toEqual([20, 21, 22])
  })

  it('escalating the move locks what it pushed with a note, and escalates once', async () => {
    vi.mocked(planApi.lockDeviation).mockReset().mockResolvedValue({})
    vi.mocked(planApi.escalateDeviation).mockResolvedValue({})
    mount()
    fireEvent.click(screen.getByTestId('deviation-escalate-20'))
    const dialog = screen.getByRole('dialog')
    fireEvent.change(within(dialog).getByRole('textbox'), { target: { value: 'SOP moves a week' } })
    fireEvent.click(within(dialog).getByText('Escalate'))
    await waitFor(() => expect(planApi.lockDeviation).toHaveBeenCalledTimes(2))
    expect(planApi.escalateDeviation).toHaveBeenCalledTimes(1)
    expect(planApi.escalateDeviation).toHaveBeenCalledWith(7, 20, 'SOP moves a week')
    expect(vi.mocked(planApi.lockDeviation).mock.calls[0][2]).toBe('Escalated to the customer with the move of Tool rework')
  })
})
